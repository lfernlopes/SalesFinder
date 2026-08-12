# Unified Fencing Group — Acquisition Map (Grand Street Partners)

A US map of residential-fencing acquisition targets, scored against the Grand
Street "Unified Fencing Group" **buy box** (Aug 2026). Built from the
`Company Tracker_vLuis.xlsx` (Tier 1/2/3 = ~2,562 companies). The two criteria
Grand Street flagged as most important — **Google rating** and **# of Google
reviews** — together drive 50% of the fit score.

## Run

```bash
npm install
npm run build     # reads the xlsx, geocodes, scores -> public/companies.json
npm start         # http://localhost:4800
```

`build` reads the tracker from `~/Downloads/Company Tracker_vLuis.xlsx` (override
with `TRACKER_XLSX=/path/to/file.xlsx npm run build`).

## What the map shows

- **Pins** colored by buy-box fit (green ≥70 strong, blue 55–69, amber 40–54,
  grey <40) and **sized by number of Google reviews**.
- **Filters**: meets-buy-box, independent-owners-only (excludes PE/VC-owned),
  min Google rating (default 4.5), min # reviews, revenue band, archetype, tier,
  free-text search. Sort by fit / reviews / rating / revenue.
- **Click a pin** → full buy-box checklist (pass/partial/fail/unknown per
  criterion), owner contact, click-to-call, website, "Copy for note" (formats
  contact + company + city/state for a handwritten-note mail-merge), and an
  outreach-status tracker (Not started → Note sent → Called → Meeting → Interested
  → Pass) saved in the browser.

## Buy-box fit score (0–100)

Computed in `build_data.py` from the tracker columns. Transparent per-criterion:

| Criterion | Weight | Source |
|---|---|---|
| Google rating ≥ 4.5 | 25 | `Google Rating` |
| Review volume | 25 | `# Reviews` |
| Residential end-market | 15 | `Archetype` |
| Independent ownership (roll-able) | 15 | `Ownership` |
| Revenue $4–50M | 15 | `Est. Revenue ($)` |
| Vinyl/composite exposure | 5 | keyword scan of Description + Specialties + End Markets |

"Meets buy box" badge = rating ≥ 4.5 **and** independent owner **and**
residential-ish archetype **and** revenue ≥ $2.5M.

Criteria the tracker can't tell us (shown as "diligence" in each popup): DTC vs
new-construction split, W-2 vs 1099 labor, owner equity-roll intent, valuation.

## PE terms baked in (from the buy box)

- **Buy box** — a PE firm's codified acquisition criteria (sector, size,
  geography, margin, quality) used to filter targets. UFG's: 75%+ residential,
  DTC, $750k–$5M+ EBITDA (~$4–50M revenue), 4.5+ Google stars, vinyl/composite
  exposure, independent owner willing to roll ~30% equity, 3–6x.
- **Platform / add-on / tuck-in** — UFG is a *platform* (family of fencing
  brands); most targets here would be *add-ons*. A *tuck-in* folds into an
  existing brand (why a retiring owner is only OK near an existing brand).
- **Rollover equity** — owner keeps ~30% in the combined entity instead of all
  cash; aligns incentives, why "independent owner" is scored highly.

## Google Places enrichment (`enrich_places.py`)

Uses the **Places API (New)** `places:searchText`. Two jobs:

- **Discover** fencing companies the tracker missed — Text Search ("fence
  company/contractor/installation") over ~30 metro rectangles, deduped against
  the tracker, scored with the same buy-box model (rating + reviews known;
  revenue/ownership/archetype marked "needs diligence").
- **Enrich** existing tracker companies with a **street address** (for
  handwritten notes) + fresh Google rating/reviews + precise coordinates.

Setup: `cp .env.example .env` and put a `GOOGLE_PLACES_API_KEY` in it (a key with
"Places API (New)" enabled, on a billing-enabled project — ideally a **dedicated**
key so spend stays off Beija's billing).

```bash
# See projected cost, spend nothing:
python3 enrich_places.py --discover --enrich --scope buybox --estimate

# Cheap validation run (5 metros + 50 companies ≈ $3):
python3 enrich_places.py --discover --enrich --scope top:50 --limit 5 --go

# Full run (~$27): all 30 metros + street addresses for the 515 buy-box cos:
python3 enrich_places.py --discover --enrich --scope buybox --go
```

Cost control: rating/reviews/phone are the Places **Enterprise** SKU (~$35/1,000);
every response is **cached** under `cache/` so re-runs bill nothing; `--go` is
required to actually spend. `--scope` = `buybox | all | state:TX | top:200`.
The map then shows discovered targets (purple "Discovered" badge), a **Source**
filter, and 📮 street addresses in the popup + "Copy for note".

## Known gaps → enrichment roadmap

1. **Comprehensiveness** (their #1 ask — companies not in the list). Requires a
   discovery pass: Google Places **Text Search** ("fence company") across metros,
   then dedupe against the tracker and score identically. Needs a Google Places
   API key + budget (~$32 / 1,000 searches + details).
2. **Street addresses for handwritten notes.** The tracker has city/state only.
   Google Places **Details** (or website scraping via the `Domain` column) returns
   `formatted_address`. Same API key as above.
3. **Fresh Google ratings/reviews.** Tracker values are a snapshot; Places Details
   refreshes rating + review count on demand.
4. **176 companies unmapped** — 138 have no HQ in the tracker, ~36 are
   non-US/unknown-state. Recoverable via the same Places enrichment.

## Files

- `build_data.py` — xlsx → geocode → buy-box score → `public/companies.json`
- `server.js` — static server on :4800
- `public/index.html` — Leaflet map + filters + scoring UI
- `uscities.csv` — free US city→lat/lng table (kelvins/US-Cities-Database)
