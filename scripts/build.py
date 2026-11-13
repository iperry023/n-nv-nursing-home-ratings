#!/usr/bin/env python3
"""Weekly build for the Northern Nevada nursing home ratings site.

Pulls two CMS Provider Data Catalog datasets (the data behind Medicare Care Compare):
  * Provider Information  (4pq5-n9py) - star ratings, scores, fines, flags
  * Health Deficiencies   (r5ix-sfxw) - every cited survey tag
filters them to Nevada outside the Las Vegas metro, and writes:
  site/index.html   the public page
  site/data.json    the same numbers as JSON
  site/data.csv     the same numbers as a spreadsheet download

Standard library only, so the GitHub Action needs no installs.

For local testing without network access, set FIXTURE_DIR to a folder holding
provider.json and deficiencies.json (lists of row objects).
"""

import csv
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
CONFIG = json.loads((ROOT / "config.json").read_text())

API = "https://data.cms.gov/provider-data/api/1/datastore/query/{dataset}/0"
PROVIDER_DATASET = "4pq5-n9py"
DEFICIENCY_DATASET = "r5ix-sfxw"
PAGE = 500


# ---------------------------------------------------------------- fetching

def fetch_dataset(dataset, value, prop="state"):
    """Return every row of a CMS dataset where prop == value, following pagination."""
    fixture = os.environ.get("FIXTURE_DIR")
    if fixture:
        name = "provider.json" if dataset == PROVIDER_DATASET else "deficiencies.json"
        return json.loads((Path(fixture) / name).read_text())

    rows, offset = [], 0
    while True:
        params = {
            "conditions[0][property]": prop,
            "conditions[0][value]": value,
            "conditions[0][operator]": "=",
            "limit": PAGE,
            "offset": offset,
        }
        url = API.format(dataset=dataset) + "?" + urllib.parse.urlencode(params)
        batch = get_json(url).get("results", [])
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        offset += PAGE


def get_json(url, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nv-nursing-home-ratings"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except Exception as exc:  # network hiccups on CMS's side are common
            if attempt == tries - 1:
                raise
            print(f"retrying after error: {exc}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))


# ---------------------------------------------------------------- column helpers

def norm(key):
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def normalize_rows(rows):
    return [{norm(k): v for k, v in r.items()} for r in rows]


def pick(row, *names, contains=None):
    """First non-empty value among candidate column names (or a column whose name contains all words)."""
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return v
    if contains:
        for k, v in row.items():
            if all(w in k for w in contains) and v not in (None, ""):
                return v
    return None


def require_columns(rows, label, checks):
    """Stop with a clear message if CMS renamed a column we rely on."""
    if not rows:
        sys.exit(f"{label}: CMS returned no rows for {CONFIG['state']}.")
    sample = rows[0]
    missing = [desc for desc, fn in checks.items() if all(fn(r) is None for r in rows[:50])]
    if missing:
        sys.exit(f"{label}: could not find {missing}. Columns available: {sorted(sample)}")


def to_int(v):
    try:
        return int(float(str(v).replace(",", "").replace("$", "")))
    except (TypeError, ValueError):
        return None


def to_float(v):
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def to_date(v):
    if not v:
        return None
    s = str(v)[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def yes(v):
    return str(v).strip().upper() in ("Y", "YES", "TRUE", "1")


# column accessors -----------------------------------------------------------

P = {
    "ccn": lambda r: pick(r, "cms_certification_number_ccn", "federal_provider_number", "ccn", contains=["certification"]),
    "name": lambda r: pick(r, "provider_name"),
    "city": lambda r: pick(r, "citytown", "city_town", "provider_city", "city"),
    "county": lambda r: pick(r, "countyparish", "county_parish", "provider_county_name", contains=["county"]),
    "beds": lambda r: pick(r, "number_of_certified_beds"),
    "overall": lambda r: pick(r, "overall_rating"),
    "health": lambda r: pick(r, "health_inspection_rating"),
    "staffing": lambda r: pick(r, "staffing_rating"),
    "qm": lambda r: pick(r, "qm_rating", "quality_measure_rating"),
    "ls_qm": lambda r: pick(r, "long_stay_qm_rating"),
    "ss_qm": lambda r: pick(r, "short_stay_qm_rating"),
    "score": lambda r: pick(r, "total_weighted_health_survey_score", contains=["total", "weighted", "score"]),
    "sff": lambda r: pick(r, "special_focus_status", contains=["special_focus"]),
    "abuse": lambda r: pick(r, "abuse_icon", contains=["abuse"]),
    "fines_n": lambda r: pick(r, "number_of_fines"),
    "fines_usd": lambda r: pick(r, "total_amount_of_fines_in_dollars", contains=["amount", "fines"]),
    "denials": lambda r: pick(r, "number_of_payment_denials"),
    "std_date": lambda r: pick(r, "rating_cycle_1_standard_survey_health_date", contains=["cycle_1", "standard", "date"]),
    "processed": lambda r: pick(r, "processing_date"),
}

D = {
    "ccn": P["ccn"],
    "date": lambda r: pick(r, "survey_date"),
    "type": lambda r: pick(r, "survey_type"),
    "prefix": lambda r: pick(r, "deficiency_prefix"),
    "tag": lambda r: pick(r, "deficiency_tag_number", "deficiency_tag"),
    "severity": lambda r: pick(r, "scope_severity_code", contains=["scope"]),
    "standard": lambda r: pick(r, "standard_deficiency"),
    "complaint": lambda r: pick(r, "complaint_deficiency"),
}


# ---------------------------------------------------------------- build

def region_for(county):
    regions = CONFIG["regions"]
    return regions.get((county or "").upper(), regions["default"])


def included(city, county):
    ex = CONFIG["exclude"]
    if (county or "").upper() in [c.upper() for c in ex["counties"]]:
        return (city or "").upper() in [c.upper() for c in ex["keep_cities"]]
    return True


def percentile(sorted_vals, pct):
    """Nearest-rank percentile."""
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, int(round(pct / 100 * len(sorted_vals) + 0.5)) - 1))
    return sorted_vals[k]


def health_cut_points(all_state_scores):
    if CONFIG.get("use_official_cut_points"):
        off = CONFIG["health_cut_points_official"]
        return {s: off[str(s)] for s in (5, 4, 3, 2)}, f"CMS State-Level Cut Point Table, {off['as_of']}"
    vals = sorted(v for v in all_state_scores if v is not None)
    cuts = {5: percentile(vals, 10), 4: percentile(vals, 33.33), 3: percentile(vals, 56.667), 2: percentile(vals, 80)}
    return cuts, f"Estimated from this week's scores for all {len(vals)} rated Nevada facilities (CMS uses the 10th/33rd/57th/80th percentiles)"


def stars_for_score(score, cuts):
    if score is None:
        return None
    for star in (5, 4, 3, 2):
        if score <= cuts[star]:
            return star
    return 1


def fmt_band(cuts):
    def f(x):
        return f"{x:g}"
    return {
        "5": f"{f(cuts[5])} or less",
        "4": f"Over {f(cuts[5])} to {f(cuts[4])}",
        "3": f"Over {f(cuts[4])} to {f(cuts[3])}",
        "2": f"Over {f(cuts[3])} to {f(cuts[2])}",
        "1": f"Over {f(cuts[2])}",
    }


def build():
    state = CONFIG["state"]
    providers = normalize_rows(fetch_dataset(PROVIDER_DATASET, state))
    require_columns(providers, "Provider Information", {
        k: P[k] for k in ("ccn", "name", "city", "county", "overall", "health", "staffing", "qm")
    })
    deficiencies = fetch_deficiencies(providers, state)
    if deficiencies:
        require_columns(deficiencies, "Health Deficiencies", {k: D[k] for k in ("ccn", "date", "severity")})

    cuts, cut_source = health_cut_points([to_float(P["score"](r)) for r in providers])
    bands = fmt_band(cuts)

    by_ccn = {}
    for r in deficiencies:
        t = (D["type"](r) or "Health").lower()
        prefix = (D["prefix"](r) or "F").upper()
        if "fire" in t or "life safety" in t or prefix in ("K", "E"):
            continue  # Life Safety Code / emergency prep tags are not part of the health rating
        by_ccn.setdefault(str(D["ccn"](r)).zfill(6), []).append(r)

    out = []
    for r in providers:
        city, county = (P["city"](r) or "").title(), (P["county"](r) or "").title()
        if not included(city, county):
            continue
        ccn = str(P["ccn"](r)).zfill(6)
        defs = by_ccn.get(ccn, [])

        std_date = to_date(P["std_date"](r))
        std_dates = [to_date(D["date"](d)) for d in defs if yes(D["standard"](d))]
        if std_date is None and std_dates:
            std_date = max(x for x in std_dates if x)
        tags_on_std = sum(1 for d in defs if yes(D["standard"](d)) and to_date(D["date"](d)) == std_date)

        sev = [(D["severity"](d) or "").upper() for d in defs]
        ij = sum(1 for s in sev if s in ("J", "K", "L"))
        harm = sum(1 for s in sev if s in ("G", "H", "I"))
        last_survey_any = max((to_date(D["date"](d)) for d in defs if to_date(D["date"](d))), default=None)

        rating = {k: to_int(P[k](r)) for k in ("overall", "health", "staffing", "qm", "ls_qm", "ss_qm")}
        score = to_float(P["score"](r))
        out.append({
            "name": nice_name(P["name"](r)),
            "ccn": ccn,
            "city": city,
            "county": county,
            "region": region_for(county),
            "beds": to_int(P["beds"](r)),
            **rating,
            "health_score": score,
            "health_score_stars_today": stars_for_score(score, cuts),
            "health_range": bands.get(str(rating["health"])),
            "staffing_range": CONFIG["staffing_ranges"].get(str(rating["staffing"])),
            "qm_range": CONFIG["qm_ranges"]["overall"].get(str(rating["qm"])),
            "last_standard_survey": std_date.isoformat() if std_date else None,
            "tags_last_standard": tags_on_std if std_date else None,
            "health_tags_on_record": len(defs),
            "complaint_tags": sum(1 for d in defs if yes(D["complaint"](d))),
            "immediate_jeopardy": ij,
            "actual_harm": harm,
            "latest_any_survey": last_survey_any.isoformat() if last_survey_any else None,
            "fines_usd": to_int(P["fines_usd"](r)) or 0,
            "fines_count": to_int(P["fines_n"](r)) or 0,
            "payment_denials": to_int(P["denials"](r)) or 0,
            "special_focus": clean_sff(P["sff"](r)),
            "abuse_icon": yes(P["abuse"](r)),
            "care_compare_url": f"https://www.medicare.gov/care-compare/details/nursing-home/{ccn}?state={state}",
        })

    out.sort(key=lambda x: (x["region"] != "Reno/Sparks", x["region"], x["name"]))
    processed = max((str(P["processed"](r))[:10] for r in providers if P["processed"](r)), default=None)
    meta = {
        "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "cms_processing_date": processed,
        "facility_count": len(out),
        "state_facility_count": len(providers),
        "health_cut_points": {str(k): v for k, v in cuts.items()},
        "health_bands": bands,
        "health_cut_source": cut_source,
        "staffing_ranges": {k: v for k, v in CONFIG["staffing_ranges"].items() if not k.startswith("_")},
        "qm_ranges": {k: v for k, v in CONFIG["qm_ranges"].items() if not k.startswith("_")},
        "qm_source": CONFIG["qm_ranges"]["_source"],
        "staffing_source": CONFIG["staffing_ranges"]["_source"],
    }
    return out, meta


def fetch_deficiencies(providers, state):
    """By state if CMS allows it, otherwise one query per included facility."""
    try:
        rows = normalize_rows(fetch_dataset(DEFICIENCY_DATASET, state))
        if rows:
            return rows
    except Exception as exc:
        print(f"State query for deficiencies failed ({exc}); querying by facility.", file=sys.stderr)
    rows = []
    for r in providers:
        if included((P["city"](r) or ""), (P["county"](r) or "")):
            ccn = str(P["ccn"](r)).zfill(6)
            rows.extend(normalize_rows(fetch_dataset(DEFICIENCY_DATASET, ccn, prop="cms_certification_number_ccn")))
    return rows


SMALL_WORDS = {"of", "and", "the", "at", "in", "on", "for", "dba"}
UPPER_WORDS = {"llc", "snf", "inc", "ii", "iii", "dp", "va", "hgh"}


def nice_name(s):
    words = (s or "").lower().split()
    out = []
    for i, w in enumerate(words):
        core = w.strip(",.()")
        if core in UPPER_WORDS:
            out.append(w.upper())
        elif i > 0 and core in SMALL_WORDS:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def clean_sff(v):
    s = (v or "").strip()
    if not s or s.upper() in ("N", "NO", "NONE"):
        return ""
    return "Candidate" if "CANDIDATE" in s.upper() else "Special Focus Facility"


# ---------------------------------------------------------------- output

CSV_COLS = [
    ("Facility", "name"), ("City", "city"), ("County", "county"), ("Region", "region"), ("CCN", "ccn"),
    ("Certified beds", "beds"), ("Overall stars", "overall"), ("Health inspection stars", "health"),
    ("Staffing stars", "staffing"), ("Quality stars", "qm"), ("Health inspection score (lower is better)", "health_score"),
    ("Stars that score earns today", "health_score_stars_today"), ("Health inspection star range", "health_range"),
    ("Staffing star range (points of 380)", "staffing_range"), ("Quality star range (points of 2,300)", "qm_range"),
    ("Last standard survey", "last_standard_survey"), ("Tags on last standard survey", "tags_last_standard"),
    ("Health tags on record (~3 yrs)", "health_tags_on_record"), ("Complaint tags", "complaint_tags"),
    ("Immediate jeopardy tags", "immediate_jeopardy"), ("Actual harm tags", "actual_harm"),
    ("Fines (3 yrs, $)", "fines_usd"), ("Payment denials", "payment_denials"), ("Special Focus", "special_focus"),
    ("CMS abuse icon", "abuse_icon"), ("Care Compare link", "care_compare_url"),
]


def write_outputs(rows, meta):
    SITE.mkdir(exist_ok=True)
    (SITE / "data.json").write_text(json.dumps({"meta": meta, "facilities": rows}, indent=1))
    with open(SITE / "data.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([c for c, _ in CSV_COLS])
        for r in rows:
            w.writerow(["Yes" if r[k] is True else "" if r[k] is False else r[k] for _, k in CSV_COLS])
    template = (ROOT / "scripts" / "template.html").read_text()
    page = (template
            .replace("/*DATA*/null", json.dumps({"meta": meta, "facilities": rows}).replace("</", "<\\/"))
            .replace("{{BUILT}}", html.escape(meta["built"]))
            .replace("{{PROCESSED}}", html.escape(meta["cms_processing_date"] or "unknown")))
    (SITE / "index.html").write_text(page)
    (SITE / ".nojekyll").write_text("")


if __name__ == "__main__":
    facilities, meta = build()
    if not facilities:
        sys.exit("No facilities matched the filters; refusing to publish an empty page.")
    write_outputs(facilities, meta)
    print(f"Built {len(facilities)} facilities (CMS data processed {meta['cms_processing_date']}).")
