#!/usr/bin/env python3
"""
Builds public/companies.json for the Grand Street / Unified Fencing Group
acquisition map.

Source: "Company Tracker_vLuis.xlsx" (Tier 1/2/3 sheets = ~2,562 targets).
For each company we:
  - normalize the row,
  - geocode by "City, ST" against a local US-cities table (free), and
  - compute a transparent Buy-Box Fit score (0-100) from the Grand Street
    "Unified Fencing Group" buy box (Aug 2026).

The two criteria Grand Street flagged as MOST important — Google rating and
number of Google reviews — together carry 50% of the score.
"""
import csv, json, os, re, hashlib
import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
XLSX = os.environ.get(
    "TRACKER_XLSX",
    os.path.expanduser("~/Downloads/Company Tracker_vLuis.xlsx"),
)
SHEETS = ["Tier 1 - Targets", "Tier2 - Targets", "Tier 3 - Watch"]

# ---------------------------------------------------------------- geocoding
def load_city_index():
    idx = {}
    with open(os.path.join(HERE, "uscities.csv"), newline="") as f:
        for r in csv.DictReader(f):
            key = (r["CITY"].strip().lower(), r["STATE_CODE"].strip().upper())
            if key not in idx:
                idx[key] = (float(r["LATITUDE"]), float(r["LONGITUDE"]))
    return idx

# Rough state centroids so every US company still gets a pin.
STATE_CENTROID = {
    "AL":(32.8,-86.8),"AK":(64.2,-149.5),"AZ":(34.2,-111.7),"AR":(34.9,-92.4),
    "CA":(37.2,-119.4),"CO":(39.0,-105.5),"CT":(41.6,-72.7),"DE":(39.0,-75.5),
    "FL":(28.6,-82.4),"GA":(32.7,-83.4),"HI":(20.3,-156.4),"ID":(44.4,-114.6),
    "IL":(40.0,-89.2),"IN":(39.9,-86.3),"IA":(42.0,-93.5),"KS":(38.5,-98.4),
    "KY":(37.5,-85.3),"LA":(31.0,-92.0),"ME":(45.4,-69.2),"MD":(39.0,-76.8),
    "MA":(42.3,-71.8),"MI":(44.3,-85.4),"MN":(46.3,-94.3),"MS":(32.7,-89.7),
    "MO":(38.4,-92.5),"MT":(46.9,-110.4),"NE":(41.5,-99.8),"NV":(39.3,-116.6),
    "NH":(43.7,-71.6),"NJ":(40.1,-74.7),"NM":(34.4,-106.1),"NY":(42.9,-75.5),
    "NC":(35.6,-79.4),"ND":(47.5,-100.5),"OH":(40.3,-82.8),"OK":(35.6,-97.5),
    "OR":(44.0,-120.5),"PA":(40.9,-77.8),"RI":(41.7,-71.6),"SC":(33.9,-80.9),
    "SD":(44.4,-100.2),"TN":(35.9,-86.4),"TX":(31.5,-99.3),"UT":(39.3,-111.7),
    "VT":(44.1,-72.7),"VA":(37.5,-78.9),"WA":(47.4,-120.5),"WV":(38.6,-80.6),
    "WI":(44.6,-89.9),"WY":(43.0,-107.6),"DC":(38.9,-77.0),
}
SOUTH_WEST = {"FL","GA","SC","NC","TN","AL","MS","LA","TX","OK","AR","AZ",
              "NM","NV","CA","UT","CO"}

def jitter(seed, span=0.15):
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    a = ((h & 0xFFFF) / 0xFFFF - 0.5) * span
    b = (((h >> 16) & 0xFFFF) / 0xFFFF - 0.5) * span
    return a, b

# ---------------------------------------------------------------- helpers
def num(x):
    if x is None: return None
    try: return float(re.sub(r"[,$]", "", str(x)))
    except ValueError: return None

def parse_hq(hq):
    if not hq: return None, None
    parts = [p.strip() for p in str(hq).split(",")]
    if len(parts) >= 2 and len(parts[-1]) <= 3:
        return parts[0], parts[-1].upper()
    return (parts[0] if parts else None), None

# ---------------------------------------------------------------- scoring
def rating_pts(r):
    if r is None: return 0, "unknown", "No Google rating on file"
    if r >= 4.7: return 25, "pass", f"{r} ★ (excellent)"
    if r >= 4.5: return 22, "pass", f"{r} ★ (meets 4.5+ buy box)"
    if r >= 4.3: return 14, "partial", f"{r} ★ (just below 4.5)"
    if r >= 4.0: return 8, "fail", f"{r} ★"
    return 0, "fail", f"{r} ★ (low)"

def reviews_pts(n):
    # Reviews are the single most important signal (per buy box + Jack call), so
    # they carry the most weight — 30 of 100.
    if n is None: return 0, "unknown", "No review count"
    if n >= 250: return 30, "pass", f"{int(n)} reviews (high volume)"
    if n >= 100: return 24, "pass", f"{int(n)} reviews (strong)"
    if n >= 50:  return 17, "partial", f"{int(n)} reviews (moderate)"
    if n >= 20:  return 10, "partial", f"{int(n)} reviews (light)"
    return 4, "fail", f"{int(n)} reviews (thin)"

ARCHETYPE_PTS = {
    "Pure-Play Residential": (15, "pass"),
    "Resi/Comm Mix — Light": (13, "pass"),
    "Resi/Comm Mix — Med": (8, "partial"),
    "Materials Specialist": (8, "partial"),
    "Service-Line Specialist (Gates)": (6, "partial"),
    "Resi/Comm Mix — Heavy": (4, "fail"),
    "Product-Adjacent (Outdoor Living)": (4, "fail"),
}
def archetype_pts(a):
    pts, status = ARCHETYPE_PTS.get(a, (6, "partial"))
    return pts, status, a or "unknown"

def ownership_pts(o):
    o = (o or "").strip()
    ol = o.lower()
    if "equity" in ol or "subsid" in ol or ol == "private sub" or "venture" in ol:
        return 0, "fail", f"{o} (already institutionally owned)"
    if ol == "bootstrapped": return 15, "pass", "Bootstrapped (independent)"
    if ol == "private": return 13, "pass", "Private / independent"
    if "investor" in ol: return 5, "partial", o
    return 8, "partial", o or "unknown"

def revenue_pts(rev):
    # NOTE: tracker revenue is an UNRELIABLE headcount-proxy estimate (confirmed
    # by Jack — "it's a formula on the backend, not real"). So it carries low
    # weight (10 of 100) and is always labeled "est.".
    if rev is None: return 5, "unknown", "Revenue unknown (est. only)"
    m = rev / 1e6
    if 8 <= m <= 50:  return 10, "pass", f"~${m:.1f}M est. (in band)"
    if 4 <= m < 8:    return 9, "pass", f"~${m:.1f}M est. (in band)"
    if 2.5 <= m < 4:  return 6, "partial", f"~${m:.1f}M est. (tuck-in / margin case)"
    if 1 <= m < 2.5:  return 3, "fail", f"~${m:.1f}M est. (below band)"
    if m > 50:        return 4, "partial", f"~${m:.1f}M est. (above band)"
    return 1, "fail", f"~${m:.2f}M est. (small)"

def material_pts(text):
    t = (text or "").lower()
    vinyl = bool(re.search(r"vinyl|pvc", t))
    comp = "composite" in t
    if vinyl or comp:
        kinds = ", ".join(k for k, v in [("vinyl", vinyl), ("composite", comp)] if v)
        return 5, "pass", f"Mentions {kinds}", vinyl, comp
    return 0, "unknown", "Vinyl/composite not detected in text (verify)", False, False

# ---------------------------------------------------------------- build
def build():
    cityidx = load_city_index()
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    companies, unresolved = [], 0

    for sheet in SHEETS:
        ws = wb[sheet]
        rows = list(ws.iter_rows(values_only=True))
        hdr = [(str(h).strip() if h else f"col{i}") for i, h in enumerate(rows[0])]
        H = {h: i for i, h in enumerate(hdr)}
        def g(row, *names):
            for n in names:
                if n in H and row[H[n]] is not None:
                    return row[H[n]]
            return None

        for row in rows[1:]:
            if not any(row): continue
            name = g(row, "Company")
            if not name: continue
            hq = g(row, "HQ")
            city, state = parse_hq(hq)
            desc = g(row, "Description") or ""
            specialties = g(row, "Specialties (SS)") or ""
            endmarkets = g(row, "End Markets (SS)") or ""
            rating = num(g(row, "Google Rating"))
            reviews = num(g(row, "# Reviews"))
            revenue = num(g(row, "Est. Revenue ($)", "Revenue ($)"))
            archetype = g(row, "Archetype")
            ownership = g(row, "Ownership")

            # geocode
            latlng = None
            if city and state:
                cl = city.lower()
                latlng = cityidx.get((cl, state))
                if not latlng:  # normalize "St." -> "Saint", "Ste." -> "Sainte"
                    norm = re.sub(r"\bst\.\s*", "saint ", cl)
                    norm = re.sub(r"\bste\.\s*", "sainte ", norm)
                    latlng = cityidx.get((norm.strip(), state))
            if not latlng and state in STATE_CENTROID:
                latlng = STATE_CENTROID[state]
            if not latlng:
                unresolved += 1
                continue
            dlat, dlng = jitter(str(name))
            lat, lng = latlng[0] + dlat, latlng[1] + dlng

            # score
            r_p, r_s, r_d = rating_pts(rating)
            v_p, v_s, v_d = reviews_pts(reviews)
            a_p, a_s, a_d = archetype_pts(archetype)
            o_p, o_s, o_d = ownership_pts(ownership)
            e_p, e_s, e_d = revenue_pts(revenue)
            m_p, m_s, m_d, vinyl, comp = material_pts(
                f"{desc} {specialties} {endmarkets}")
            score = r_p + v_p + a_p + o_p + e_p + m_p

            meets = (rating is not None and rating >= 4.5
                     and o_s == "pass"
                     and a_s in ("pass", "partial")
                     and (revenue is None or revenue >= 2.5e6))

            criteria = [
                {"key": "rating",   "label": "Google rating ≥ 4.5", "status": r_s, "detail": r_d},
                {"key": "reviews",  "label": "Review volume",       "status": v_s, "detail": v_d},
                {"key": "endmkt",   "label": "Residential end-market", "status": a_s, "detail": a_d},
                {"key": "owner",    "label": "Independent ownership","status": o_s, "detail": o_d},
                {"key": "size",     "label": "Revenue $4–50M (est.)","status": e_s, "detail": e_d},
                {"key": "material", "label": "Vinyl/composite exposure","status": m_s,"detail": m_d},
            ]

            companies.append({
                "id": f"{name}|{city}|{state}",
                "company": name,
                "domain": g(row, "Domain"),
                "tier": g(row, "Tier"),
                "confidence": g(row, "Data Confidence"),
                "archetype": archetype,
                "ownership": ownership,
                "parent": g(row, "Parent"),
                "description": (str(desc)[:280]),
                "founded": g(row, "Founded"),
                "revenue": revenue,
                "employees": num(g(row, "Employees")),
                "rating": rating,
                "reviews": None if reviews is None else int(reviews),
                "contactName": " ".join(x for x in [g(row,"Contact First"), g(row,"Contact Last")] if x) or None,
                "contactTitle": g(row, "Contact Title"),
                "phone": g(row, "Phone"),
                "email": g(row, "Contact Email"),
                "linkedin": g(row, "Contact LinkedIn"),
                "hq": hq, "city": city, "state": state,
                "lat": round(lat, 5), "lng": round(lng, 5),
                "southWest": state in SOUTH_WEST,
                "vinyl": vinyl, "composite": comp,
                "fit": score,
                "meetsBuyBox": meets,
                "criteria": criteria,
                "source": "tracker",
                "address": None,      # street address (filled by Places enrichment)
                "placeId": None,
            })

    companies.sort(key=lambda c: (c["fit"], c["reviews"] or 0), reverse=True)
    out = {
        "generatedFrom": os.path.basename(XLSX),
        "count": len(companies),
        "unresolved": unresolved,
        "meetsBuyBox": sum(1 for c in companies if c["meetsBuyBox"]),
        "companies": companies,
    }
    dest = os.path.join(HERE, "public", "companies.json")
    with open(dest, "w") as f:
        json.dump(out, f)
    print(f"Wrote {len(companies)} companies "
          f"({out['meetsBuyBox']} meet buy box, {unresolved} unresolved) -> {dest}")

if __name__ == "__main__":
    build()
