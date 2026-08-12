#!/usr/bin/env python3
"""
Google Places (New) enrichment for the Unified Fencing Group map.

Two jobs:
  1. DISCOVER fencing companies the tracker missed  (Text Search over metro
     rectangles) and score them with the same buy-box model.
  2. ENRICH existing tracker companies with a street ADDRESS (for handwritten
     notes) + fresh Google rating / review count + precise lat-lng.

Uses the Places API "New": POST https://places.googleapis.com/v1/places:searchText
with an X-Goog-FieldMask header. Rating / reviews / phone / website are billed at
the Text Search *Enterprise* SKU, so every call here is Enterprise-tier — the
cost estimator below assumes that.

Cost control:
  * every API response is cached under cache/ (a repeat run bills nothing),
  * `--estimate` prints projected request count + $ and spends nothing,
  * you must pass `--go` to actually call the API.

Usage:
  python3 enrich_places.py --estimate --enrich --discover --limit 5
  python3 enrich_places.py --enrich --scope buybox --go
  python3 enrich_places.py --discover --limit 10 --go
Then re-serve; companies.json is updated in place.
"""
import argparse, hashlib, json, os, re, sys, time, urllib.request, urllib.error

import build_data as bd  # reuse geocoding + buy-box scoring

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
COMPANIES = os.path.join(HERE, "public", "companies.json")
ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.location", "places.rating", "places.userRatingCount",
    "places.nationalPhoneNumber", "places.websiteUri",
    "places.primaryType", "places.types", "places.businessStatus",
    "nextPageToken",
])
ENTERPRISE_PER_1000 = 35.0  # approx USD, Text Search Enterprise SKU
QUERIES = ["fence company", "fence contractor", "fencing installation"]

# Metro rectangles (low = SW corner, high = NE corner). South/West weighted per
# the buy box. Add more to widen coverage; each region costs ~len(QUERIES)*pages.
REGIONS = [
    ("Dallas-FortWorth,TX", (32.55, -97.55), (33.10, -96.55)),
    ("Houston,TX",          (29.45, -95.85), (30.15, -95.05)),
    ("Austin,TX",           (30.10, -98.05), (30.55, -97.55)),
    ("SanAntonio,TX",       (29.20, -98.75), (29.70, -98.25)),
    ("Phoenix,AZ",          (33.20, -112.40),(33.75, -111.75)),
    ("Atlanta,GA",          (33.55, -84.60), (34.10, -84.10)),
    ("Tampa,FL",            (27.80, -82.65), (28.20, -82.25)),
    ("Orlando,FL",          (28.35, -81.60), (28.70, -81.15)),
    ("Miami-FtLauderdale,FL",(25.70,-80.45), (26.30, -80.05)),
    ("Charlotte,NC",        (35.05, -81.05), (35.45, -80.65)),
    ("Raleigh,NC",          (35.65, -78.80), (35.95, -78.45)),
    ("Nashville,TN",        (35.95, -87.05), (36.35, -86.55)),
    ("Denver,CO",           (39.55, -105.20),(39.95, -104.75)),
    ("LasVegas,NV",         (36.00, -115.35),(36.35, -114.95)),
    ("LosAngeles,CA",       (33.70, -118.55),(34.30, -117.65)),
    ("Sacramento,CA",       (38.40, -121.65),(38.75, -121.20)),
    ("Chicago,IL",          (41.65, -88.05), (42.05, -87.55)),
    ("Minneapolis,MN",      (44.80, -93.50), (45.15, -93.05)),
    ("Columbus,OH",         (39.85, -83.20), (40.15, -82.75)),
    ("Indianapolis,IN",     (39.65, -86.35), (39.95, -85.95)),
    ("KansasCity,MO",       (38.90, -94.75), (39.25, -94.40)),
    ("StLouis,MO",          (38.50, -90.50), (38.80, -90.10)),
    ("Philadelphia,PA",     (39.85, -75.30), (40.15, -74.95)),
    ("LongIsland,NY",       (40.65, -73.65), (40.95, -72.85)),
    ("Boston,MA",           (42.25, -71.25), (42.55, -70.90)),
    ("Detroit,MI",          (42.20, -83.45), (42.60, -82.90)),
    ("Seattle,WA",          (47.40, -122.45),(47.80, -122.10)),
    ("Portland,OR",         (45.40, -122.85),(45.65, -122.45)),
    ("SaltLakeCity,UT",     (40.55, -112.10),(40.85, -111.75)),
    ("Richmond,VA",         (37.40, -77.65), (37.70, -77.30)),
]

# ------------------------------------------------------------ .env + client
def load_key():
    for path in [os.path.join(HERE, ".env")]:
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return os.environ.get("GOOGLE_PLACES_API_KEY") or os.environ.get("GOOGLE_API_KEY")

def cache_path(key):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, hashlib.md5(key.encode()).hexdigest() + ".json")

def search_text(query, rect=None, api_key=None, live=False, max_pages=3):
    """Returns list of place dicts. Cached. Only calls network when live=True."""
    results, token, pages = [], None, 0
    while pages < max_pages:
        ck = json.dumps({"q": query, "r": rect, "p": pages}, sort_keys=True)
        cp = cache_path(ck)
        if os.path.exists(cp):
            with open(cp) as f:
                data = json.load(f)
        elif live:
            body = {"textQuery": query, "pageSize": 20}
            if rect:
                body["locationRestriction"] = {"rectangle": {
                    "low": {"latitude": rect[0][0], "longitude": rect[0][1]},
                    "high": {"latitude": rect[1][0], "longitude": rect[1][1]}}}
            if token:
                body["pageToken"] = token
            req = urllib.request.Request(
                ENDPOINT, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json",
                         "X-Goog-Api-Key": api_key,
                         "X-Goog-FieldMask": FIELD_MASK}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.load(r)
            except urllib.error.HTTPError as e:
                sys.stderr.write(f"  HTTP {e.code} for {query!r}: {e.read().decode()[:200]}\n")
                break
            with open(cp, "w") as f:
                json.dump(data, f)
            time.sleep(0.3)
        else:
            break  # estimate mode / no cache
        results.extend(data.get("places", []))
        token = data.get("nextPageToken")
        pages += 1
        if not token:
            break
    return results

# ------------------------------------------------------------ helpers
STOP = {"inc", "llc", "co", "company", "corp", "the", "fence", "fencing",
        "and", "of", "&", "ltd", "services", "service"}
def norm_name(s):
    toks = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()
    return set(t for t in toks if t not in STOP)

def domain_of(url):
    if not url: return None
    m = re.sub(r"^https?://(www\.)?", "", url.lower()).split("/")[0]
    return m or None

def is_fencing(place):
    name = (place.get("displayName", {}) or {}).get("text", "").lower()
    types = place.get("types", []) or []
    pt = place.get("primaryType", "") or ""
    return ("fence" in name or "fencing" in name
            or "fence_contractor" in types or pt == "fence_contractor")

# ------------------------------------------------------------ core ops
def load_companies():
    with open(COMPANIES) as f:
        return json.load(f)

def index_tracker(companies):
    by_name_city, by_domain = {}, {}
    for c in companies:
        key = (frozenset(norm_name(c["company"])), (c.get("city") or "").lower())
        by_name_city.setdefault(key, c)
        d = domain_of(c.get("domain") and f"http://{c['domain']}")
        if d: by_domain[d] = c
    return by_name_city, by_domain

def place_to_company(p):
    name = (p.get("displayName", {}) or {}).get("text", "")
    loc = p.get("location", {}) or {}
    lat, lng = loc.get("latitude"), loc.get("longitude")
    rating = p.get("rating")
    reviews = p.get("userRatingCount")
    addr = p.get("formattedAddress")
    # pull city/state from formatted address ("..., City, ST 12345, USA")
    city = state = None
    m = re.search(r",\s*([^,]+),\s*([A-Z]{2})\s*\d{5}", addr or "")
    if m: city, state = m.group(1).strip(), m.group(2)
    # score with shared model (unknowns -> neutral)
    r_p, r_s, r_d = bd.rating_pts(rating)
    v_p, v_s, v_d = bd.reviews_pts(reviews)
    a_p, a_s, a_d = 8, "unknown", "Discovered — residential mix not yet verified"
    o_p, o_s, o_d = 8, "unknown", "Ownership not yet verified"
    e_p, e_s, e_d = 5, "unknown", "Revenue unknown (est. only)"
    m_p, m_s, m_d, vinyl, comp = bd.material_pts(name)
    fit = r_p + v_p + a_p + o_p + e_p + m_p
    criteria = [
        {"key":"rating","label":"Google rating ≥ 4.5","status":r_s,"detail":r_d},
        {"key":"reviews","label":"Review volume","status":v_s,"detail":v_d},
        {"key":"endmkt","label":"Residential end-market","status":a_s,"detail":a_d},
        {"key":"owner","label":"Independent ownership","status":o_s,"detail":o_d},
        {"key":"size","label":"Revenue $4–50M (est.)","status":e_s,"detail":e_d},
        {"key":"material","label":"Vinyl/composite exposure","status":m_s,"detail":m_d},
    ]
    if lat is None or state is None:
        return None
    dlat, dlng = bd.jitter(name)
    return {
        "id": f"places|{p.get('id')}",
        "company": name, "domain": domain_of(p.get("websiteUri")),
        "tier": "Discovered", "confidence": "Places",
        "archetype": None, "ownership": None, "parent": None,
        "description": "", "founded": None, "revenue": None, "employees": None,
        "rating": rating, "reviews": None if reviews is None else int(reviews),
        "contactName": None, "contactTitle": None,
        "phone": p.get("nationalPhoneNumber"),
        "email": None, "linkedin": None,
        "hq": f"{city}, {state}" if city else None, "city": city, "state": state,
        "lat": round(lat + dlat*0.3, 5), "lng": round(lng + dlng*0.3, 5),
        "southWest": state in bd.SOUTH_WEST,
        "vinyl": vinyl, "composite": comp,
        "fit": fit,
        # Discovered rows are review-qualified only; ownership + residential mix
        # are unverified, so we do NOT claim they meet the full buy box.
        "meetsBuyBox": False,
        "reviewQualified": bool(rating and rating >= 4.5),
        "criteria": criteria,
        "source": "discovered",
        "address": addr, "placeId": p.get("id"),
    }

def do_discover(companies, api_key, regions, live):
    by_name_city, by_domain = index_tracker(companies)
    seen_place, added, matched = set(), [], 0
    for name, low, high in regions:
        for q in QUERIES:
            for p in search_text(q, (low, high), api_key, live):
                pid = p.get("id")
                if not pid or pid in seen_place: continue
                seen_place.add(pid)
                if p.get("businessStatus") not in (None, "OPERATIONAL"): continue
                if not is_fencing(p): continue
                pname = (p.get("displayName", {}) or {}).get("text", "")
                dom = domain_of(p.get("websiteUri"))
                # dedupe vs tracker
                key = (frozenset(norm_name(pname)), _place_city(p))
                if key in by_name_city or (dom and dom in by_domain):
                    tc = by_name_city.get(key) or by_domain.get(dom)
                    if tc and not tc.get("address"):  # enrich matched tracker co
                        tc["address"] = p.get("formattedAddress")
                        tc["placeId"] = pid
                        if p.get("rating"): tc["placeRating"] = p["rating"]
                        if p.get("userRatingCount"): tc["placeReviews"] = p["userRatingCount"]
                    matched += 1
                    continue
                nc = place_to_company(p)
                if nc: added.append(nc)
    print(f"  discovery: {len(added)} new companies, {matched} matched existing")
    return added

def _place_city(p):
    m = re.search(r",\s*([^,]+),\s*[A-Z]{2}\s*\d{5}", p.get("formattedAddress") or "")
    return (m.group(1).strip().lower() if m else "")

def do_enrich(companies, api_key, scope, live):
    targets = [c for c in companies if c["source"] == "tracker"]
    if scope == "buybox":
        targets = [c for c in targets if c["meetsBuyBox"]]
    elif scope.startswith("state:"):
        st = scope.split(":", 1)[1].upper()
        targets = [c for c in targets if c.get("state") == st]
    elif scope.startswith("top:"):
        targets = sorted(targets, key=lambda c: c["fit"], reverse=True)[:int(scope.split(":")[1])]
    n = 0
    for c in targets:
        if c.get("address"): continue
        q = " ".join(x for x in [c["company"], c.get("city"), c.get("state")] if x)
        places = search_text(q, None, api_key, live, max_pages=1)
        if not places: continue
        best, score = None, 0
        want = norm_name(c["company"])
        for p in places:
            pn = norm_name((p.get("displayName", {}) or {}).get("text", ""))
            ov = len(want & pn)
            if ov > score: best, score = p, ov
        if best and score >= 1:
            c["address"] = best.get("formattedAddress")
            c["placeId"] = best.get("id")
            if best.get("rating"): c["placeRating"] = best["rating"]
            if best.get("userRatingCount"): c["placeReviews"] = best["userRatingCount"]
            loc = best.get("location", {})
            if loc.get("latitude"):  # upgrade to precise coords
                c["lat"], c["lng"] = round(loc["latitude"], 5), round(loc["longitude"], 5)
            n += 1
    print(f"  enrichment: {n}/{len(targets)} tracker companies got a street address")
    return targets

# ------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--enrich", action="store_true")
    ap.add_argument("--scope", default="buybox",
                    help="enrich scope: buybox | all | state:TX | top:200")
    ap.add_argument("--limit", type=int, default=len(REGIONS),
                    help="number of discovery regions to use")
    ap.add_argument("--estimate", action="store_true", help="print cost, spend nothing")
    ap.add_argument("--go", action="store_true", help="actually call the API")
    args = ap.parse_args()

    data = load_companies()
    companies = data["companies"]
    regions = REGIONS[:args.limit]

    # cost estimate
    disc_req = len(regions) * len(QUERIES) * 3 if args.discover else 0
    enr_targets = do_enrich_count(companies, args.scope) if args.enrich else 0
    total_req = disc_req + enr_targets
    est = total_req / 1000 * ENTERPRISE_PER_1000
    print(f"Planned (worst-case) requests: discovery≈{disc_req} + enrichment≈{enr_targets} "
          f"= {total_req}  →  ~${est:.2f} (Enterprise SKU; cache makes re-runs free)")
    if args.estimate:
        return

    api_key = load_key()
    if not api_key:
        sys.exit("No API key. Put GOOGLE_PLACES_API_KEY=... in fencing-acquisition-map/.env")
    live = args.go
    if not live:
        print("Dry run (no --go): using cache only, no API calls.")

    if args.enrich:
        do_enrich(companies, api_key, args.scope, live)
    if args.discover:
        companies += do_discover(companies, api_key, regions, live)

    # de-dup by id (safety so repeated discovery runs never stack rows)
    seen, uniq = set(), []
    for c in companies:
        if c["id"] in seen: continue
        seen.add(c["id"]); uniq.append(c)
    companies = uniq

    companies.sort(key=lambda c: (c["fit"], c["reviews"] or 0), reverse=True)
    data["companies"] = companies
    data["count"] = len(companies)
    data["discovered"] = sum(1 for c in companies if c["source"] == "discovered")
    data["withAddress"] = sum(1 for c in companies if c.get("address"))
    with open(COMPANIES, "w") as f:
        json.dump(data, f)
    print(f"Saved {len(companies)} companies "
          f"({data['discovered']} discovered, {data['withAddress']} with street address).")

def do_enrich_count(companies, scope):
    t = [c for c in companies if c["source"] == "tracker" and not c.get("address")]
    if scope == "buybox": t = [c for c in t if c["meetsBuyBox"]]
    elif scope.startswith("state:"):
        st = scope.split(":", 1)[1].upper(); t = [c for c in t if c.get("state") == st]
    elif scope.startswith("top:"):
        t = t[:int(scope.split(":")[1])]
    return len(t)

if __name__ == "__main__":
    main()
