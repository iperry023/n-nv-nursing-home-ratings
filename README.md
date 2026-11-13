# Reno-Area Nursing Home Ratings

A public page listing CMS Care Compare star ratings, point ranges and health survey citations for every
Medicare/Medicaid-certified nursing home within 50 miles of ZIP 89509 (Reno, NV), including the
California homes in that radius.

## Monthly update (about 2 minutes)

CMS refreshes Care Compare data about once a month. After it does:

1. Download the **Provider Information** CSV from https://data.cms.gov/provider-data/dataset/4pq5-n9py.
2. Open the `uploads` folder here → **Add file → Upload files** → drop the CSV → **Commit changes**.
3. The **Build site** action rebuilds and republishes the page in about two minutes, and saves a dated copy
   of the numbers in `history/`.

CMS blocks automated downloads from GitHub's servers, which is why the file is uploaded by hand.

## Where each column comes from

- Stars, health inspection score, survey dates, tag counts, fines, Special Focus and abuse flags:
  the uploaded CMS Provider Information file.
- Immediate jeopardy / actual harm counts: `supplements/serious_citations.json`, refreshed monthly from
  sources that republish CMS deficiency data — or from a CMS health citations CSV, if one is uploaded.
- Health inspection star bands: estimated each month from every facility's score in that state, using CMS's
  percentile method (or CMS's published table, if entered in `config.json`).
- Staffing and quality point ranges: fixed CMS thresholds in `config.json`. Update them when CMS publishes
  a new Five-Star Technical Users' Guide (a quality-measure change is expected January 2027).

## Settings (`config.json`)

- `area` — origin ZIP and coordinates, radius, and CCNs to always include or exclude.
- `regions` — region labels.
- `staffing_ranges` / `qm_ranges` / `health_cut_points_official` — CMS thresholds.

Not affiliated with CMS. Confirm details on Medicare Care Compare.
