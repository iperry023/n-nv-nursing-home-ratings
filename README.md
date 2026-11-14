# Reno-Area Nursing Home Ratings

A public page listing CMS Care Compare star ratings, point ranges and health survey citations for every
Medicare/Medicaid-certified nursing home within 50 miles of ZIP 89509 (Reno, NV), including the
California homes in that radius.

## Monthly update (about 2 minutes)

CMS refreshes Care Compare data about once a month. After it does:

1. Download the **Provider Information** CSV from https://data.cms.gov/provider-data/dataset/4pq5-n9py.
2. Download the **Health Deficiencies** CSV from https://data.cms.gov/provider-data/dataset/r5ix-sfxw
   (zip it first if it's over GitHub's 25 MB browser-upload limit; the build reads .zip files).
3. Open the `uploads` folder here → **Add file → Upload files** → drop both files → **Commit changes**.
4. The **Build site** action rebuilds and republishes the page in about two minutes, and saves a dated copy
   of the numbers in `history/`.

CMS blocks automated downloads from GitHub's servers, which is why the file is uploaded by hand.

**Email reminder:** on the 2nd of each month, if the newest upload isn't from that month, the
*Monthly upload reminder* action opens an issue that @mentions the owner, so GitHub sends an email with a
direct upload link. It follows up on the 16th if the file still hasn't arrived, and the issue closes itself
once the new file is built.

## Where each column comes from

- Stars, health inspection score, survey dates, tag counts, fines, Special Focus and abuse flags:
  the uploaded CMS Provider Information file.
- F-tag lists (the expandable panel per facility) and immediate jeopardy / actual harm counts: the uploaded
  CMS Health Deficiencies file. If it's missing, the counts fall back to `supplements/serious_citations.json`,
  which is refreshed monthly from sources that republish CMS deficiency data.
- Full statements of deficiencies: each facility links to its Care Compare inspection reports (CMS-2567 PDFs)
  and its ProPublica page.
- Health inspection star bands: estimated each month from every facility's score in that state, using CMS's
  percentile method (or CMS's published table, if entered in `config.json`).
- Staffing and quality point ranges: fixed CMS thresholds in `config.json`. Update them when CMS publishes
  a new Five-Star Technical Users' Guide (a quality-measure change is expected January 2027).

## Settings (`config.json`)

- `area` — origin ZIP and coordinates, radius, and CCNs to always include or exclude.
- `regions` — region labels.
- `staffing_ranges` / `qm_ranges` / `health_cut_points_official` — CMS thresholds.

Not affiliated with CMS. Confirm details on Medicare Care Compare.
