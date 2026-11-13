# Northern Nevada Nursing Home Ratings

A public page listing CMS Care Compare star ratings, point ranges and health survey citations for every
Medicare/Medicaid-certified nursing home in Nevada outside the Las Vegas metro.

## How it updates

Every Monday morning, a GitHub Action (`.github/workflows/weekly-update.yml`):

1. runs `scripts/build.py`, which downloads CMS's Provider Information and Health Deficiencies datasets
   from data.cms.gov,
2. rebuilds the page (`site/index.html`) plus `data.json` and `data.csv`,
3. saves a dated copy of the data in `history/`, and
4. publishes the page with GitHub Pages.

To update right away, open the **Actions** tab, choose **Weekly update**, and click **Run workflow**.

## Changing what's included

Edit `config.json`:

- `exclude` — which counties are left out (default: Clark County, except Mesquite).
- `regions` — the region label for each county.
- `staffing_ranges` / `qm_ranges` — CMS's fixed point thresholds. Update these when CMS publishes a new
  Five-Star Technical Users' Guide (the next QM change is expected January 2027).
- `use_official_cut_points` — Nevada's health inspection cut points change monthly. By default the build
  estimates them from that week's Nevada scores using CMS's percentile method. Set this to `true` and fill in
  `health_cut_points_official` to show CMS's published table instead.

## Data notes

- Health tags exclude fire/Life Safety Code citations.
- CMS holds a facility's health inspection stars until its score changes, so a score can fall outside this
  week's band for its stars.
- Not affiliated with CMS. Confirm details on Medicare Care Compare.
