#!/usr/bin/env python3
"""
Pushes public/companies.json into the Supabase `companies` table (upsert on id).
Runs locally with the service_role key (bypasses RLS). Re-run any time the data
refreshes; existing rows are updated, new ones inserted.

Env (from .env): SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
Usage: python3 push_to_supabase.py
"""
import json, os, sys, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
COMPANIES = os.path.join(HERE, "public", "companies.json")

def load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# camelCase JSON field  ->  snake_case DB column
FIELD_MAP = {
    "id":"id","company":"company","domain":"domain","tier":"tier",
    "confidence":"confidence","archetype":"archetype","ownership":"ownership",
    "parent":"parent","description":"description","founded":"founded",
    "revenue":"revenue","employees":"employees","rating":"rating","reviews":"reviews",
    "contactName":"contact_name","contactTitle":"contact_title","phone":"phone",
    "email":"email","linkedin":"linkedin","hq":"hq","city":"city","state":"state",
    "lat":"lat","lng":"lng","southWest":"south_west","vinyl":"vinyl",
    "composite":"composite","fit":"fit","meetsBuyBox":"meets_buy_box",
    "criteria":"criteria","source":"source","address":"address","placeId":"place_id",
    "placeRating":"place_rating","placeReviews":"place_reviews",
    "reviewQualified":"review_qualified",
}

def row_for(c):
    return {col: c.get(js) for js, col in FIELD_MAP.items()}

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def main():
    load_env()
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in .env")

    data = json.load(open(COMPANIES))
    rows = [row_for(c) for c in data["companies"]]
    endpoint = f"{url.rstrip('/')}/rest/v1/companies?on_conflict=id"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    total = 0
    for batch in chunks(rows, 500):
        req = urllib.request.Request(
            endpoint, data=json.dumps(batch).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                r.read()
            total += len(batch)
            print(f"  upserted {total}/{len(rows)}")
        except urllib.error.HTTPError as e:
            sys.exit(f"HTTP {e.code}: {e.read().decode()[:400]}")
    print(f"Done — {total} companies upserted into Supabase.")

if __name__ == "__main__":
    main()
