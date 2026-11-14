#!/usr/bin/env python3
"""Build the Reno-area nursing home ratings site from CMS's Provider Information file.

Input (in uploads/):
  * NH_ProviderInfo_*.csv   - REQUIRED. CMS "Provider Information" download from
                              data.cms.gov/provider-data/dataset/4pq5-n9py (whole country).
                              If several are present, the one with the newest
                              processing date wins, so old files can stay.
  * any CMS Health Deficiencies / Health Citations CSV - OPTIONAL. If present, the
    immediate jeopardy and actual harm counts come from it.
Also read:
  * config.json                         - radius, origin ZIP, fixed CMS thresholds.
  * supplements/serious_citations.json - immediate jeopardy / actual harm counts kept
                                          up to date from CMS-derived sources when no
                                          citations CSV is uploaded.
Output (site/): index.html, data.json, data.csv

Standard library only.
"""

import csv
import datetime as dt
import html
import io
import json
import math
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
UPLOADS = ROOT / "uploads"
CONFIG = json.loads((ROOT / "config.json").read_text())
SUPPLEMENT = ROOT / "supplements" / "serious_citations.json"


# ---------------------------------------------------------------- reading uploads

def norm(key):
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def iter_csv_sources():
    """Yield (name, text) for every CSV in uploads/, including CSVs inside .zip files."""
    for path in sorted(UPLOADS.glob("*")):
        if path.suffix.lower() == ".csv":
            yield path.name, path.read_text(encoding="utf-8-sig", errors="replace")
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                for n in zf.namelist():
                    if n.lower().endswith(".csv"):
                        yield f"{path.name}:{n}", zf.read(n).decode("utf-8-sig", "replace")


def read_rows(text):
    return [{norm(k): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(io.StringIO(text))]


def load_inputs():
    providers, citations = [], []
    for name, text in iter_csv_sources():
        header = {norm(h) for h in next(csv.reader(io.StringIO(text)), [])}
        if "overall_rating" in header:
            rows = read_rows(text)
            processed = max((r.get("processing_date", "") for r in rows), default="")
            providers.append((to_date(processed) or dt.date.min, name, rows))
        elif "scope_severity_code" in header:
            first = next(csv.DictReader(io.StringIO(text)), {})
            first = {norm(k): v for k, v in first.items() if k}
            citations.append((to_date(first.get("processing_date")) or dt.date.min, name, text))
    if not providers:
        sys.exit("No CMS Provider Information CSV found in uploads/. Download it from "
                 "https://data.cms.gov/provider-data/dataset/4pq5-n9py and upload it there.")
    providers.sort(key=lambda p: p[0])
    date, name, rows = providers[-1]
    print(f"Using provider file {name} (processed {date}).")
    citations.sort(key=lambda c: c[0])
    newest_citations = citations[-1] if citations else None
    if newest_citations:
        print(f"Using citations file {newest_citations[1]} (processed {newest_citations[0]}).")
    return rows, name, newest_citations


# ---------------------------------------------------------------- column helpers

def pick(row, *names, contains=None):
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return v
    if contains:
        for k, v in row.items():
            if all(w in k for w in contains) and v not in (None, ""):
                return v
    return None


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
    s = str(v).strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def yes(v):
    return str(v).strip().upper() in ("Y", "YES", "TRUE", "1")


def sum_cols(row, pattern):
    rx = re.compile(pattern)
    vals = [to_int(v) for k, v in row.items() if rx.fullmatch(k)]
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


P = {
    "ccn": lambda r: pick(r, "cms_certification_number_ccn", "federal_provider_number", "ccn", contains=["certification"]),
    "name": lambda r: pick(r, "provider_name"),
    "city": lambda r: pick(r, "city_town", "citytown", "provider_city"),
    "state": lambda r: pick(r, "state", "provider_state"),
    "county": lambda r: pick(r, "county_parish", "countyparish", "provider_county_name"),
    "beds": lambda r: pick(r, "number_of_certified_beds"),
    "overall": lambda r: pick(r, "overall_rating"),
    "health": lambda r: pick(r, "health_inspection_rating"),
    "staffing": lambda r: pick(r, "staffing_rating"),
    "qm": lambda r: pick(r, "qm_rating", "quality_measure_rating"),
    "score": lambda r: pick(r, "total_weighted_health_survey_score", contains=["total", "weighted", "score"]),
    "sff": lambda r: pick(r, "special_focus_status"),
    "abuse": lambda r: pick(r, "abuse_icon"),
    "fines_usd": lambda r: pick(r, "total_amount_of_fines_in_dollars"),
    "denials": lambda r: pick(r, "number_of_payment_denials"),
    "std_date": lambda r: pick(r, "rating_cycle_1_standard_survey_health_date", contains=["cycle_1", "standard", "date"]),
    "c1_standard": lambda r: pick(r, "rating_cycle_1_number_of_standard_health_deficiencies"),
    "lat": lambda r: pick(r, "latitude"),
    "lon": lambda r: pick(r, "longitude"),
    "processed": lambda r: pick(r, "processing_date"),
}


STAFF = {
    # key: (column in the CMS file, decimals)
    "residents": ("average_number_of_residents_per_day", 1),
    "rn": ("reported_rn_staffing_hours_per_resident_per_day", 2),
    "lpn": ("reported_lpn_staffing_hours_per_resident_per_day", 2),
    "cna": ("reported_nurse_aide_staffing_hours_per_resident_per_day", 2),
    "total": ("reported_total_nurse_staffing_hours_per_resident_per_day", 2),
    "weekend_total": ("total_number_of_nurse_staff_hours_per_resident_per_day_on_the_weekend", 2),
    "weekend_rn": ("registered_nurse_hours_per_resident_per_day_on_the_weekend", 2),
    "pt": ("reported_physical_therapist_staffing_hours_per_resident_per_day", 2),
    "adj_rn": ("adjusted_rn_staffing_hours_per_resident_per_day", 2),
    "adj_lpn": ("adjusted_lpn_staffing_hours_per_resident_per_day", 2),
    "adj_cna": ("adjusted_nurse_aide_staffing_hours_per_resident_per_day", 2),
    "adj_total": ("adjusted_total_nurse_staffing_hours_per_resident_per_day", 2),
    "adj_weekend_total": ("adjusted_weekend_total_nurse_staffing_hours_per_resident_per_day", 2),
    "turnover_total": ("total_nursing_staff_turnover", 1),
    "turnover_rn": ("registered_nurse_turnover", 1),
    "admins_left": ("number_of_administrators_who_have_left_the_nursing_home", 0),
    "case_mix": ("nursing_case_mix_index", 2),
}


def staff_fields(row):
    out = {}
    for key, (col, places) in STAFF.items():
        v = to_float(row.get(col))
        out[key] = None if v is None else (int(round(v)) if places == 0 else round(v, places))
    return out


def staffing_averages(rows, state):
    """Unweighted averages of each staffing measure across facilities that report it."""
    def avg(subset):
        res = {}
        for key, (col, places) in STAFF.items():
            vals = [to_float(r.get(col)) for r in subset]
            vals = [v for v in vals if v is not None]
            res[key] = round(sum(vals) / len(vals), max(places, 1)) if vals else None
        return res
    return avg([r for r in rows if (P["state"](r) or "").upper() == state]), avg(rows)


def check_columns(rows):
    needed = ["ccn", "name", "city", "state", "overall", "health", "staffing", "qm", "score"]
    missing = [k for k in needed if all(P[k](r) is None for r in rows[:200])]
    if missing:
        sys.exit(f"Provider file is missing {missing}. Columns found: {sorted(rows[0])}")


# ---------------------------------------------------------------- selection

def miles(lat1, lon1, lat2, lon2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def select(rows):
    area = CONFIG["area"]
    o = area["origin"]
    include = set(area.get("also_include_ccns", []))
    exclude = set(area.get("exclude_ccns", []))
    have_coords = any(P["lat"](r) and P["lon"](r) for r in rows)
    if not have_coords:
        print("No latitude/longitude columns; falling back to the facility list in config.", file=sys.stderr)
    chosen = []
    for r in rows:
        ccn = str(P["ccn"](r)).zfill(6)
        lat, lon = to_float(P["lat"](r)), to_float(P["lon"](r))
        dist = miles(o["lat"], o["lon"], lat, lon) if lat is not None and lon is not None else None
        if ccn in exclude:
            continue
        if ccn in include or (have_coords and dist is not None and dist <= area["radius_miles"]) \
                or (not have_coords and ccn in set(area.get("fallback_ccns", []))):
            chosen.append((r, ccn, dist))
    return chosen


# ---------------------------------------------------------------- health inspection cut points

def percentile(sorted_vals, pct):
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, int(math.ceil(pct / 100 * len(sorted_vals))) - 1))
    return sorted_vals[k]


def state_cut_points(rows, state):
    official = CONFIG.get("health_cut_points_official", {}).get(state)
    if official and official.get("use"):
        return {s: official[str(s)] for s in (5, 4, 3, 2)}, f"CMS State-Level Cut Point Table, {official['as_of']}"
    vals = sorted(v for v in (to_float(P["score"](r)) for r in rows if (P["state"](r) or "").upper() == state)
                  if v is not None)
    if not vals:
        return None, ""
    cuts = {5: percentile(vals, 10), 4: percentile(vals, 33.33), 3: percentile(vals, 56.667), 2: percentile(vals, 80)}
    return cuts, (f"Estimated from this month's scores for all {len(vals)} rated {state} facilities "
                  "(CMS sets 5★ = best 10%, 4/3/2★ = next ~23% each, 1★ = worst 20%)")


def stars_for_score(score, cuts):
    if score is None or not cuts:
        return None
    for star in (5, 4, 3, 2):
        if score <= cuts[star]:
            return star
    return 1


def bands(cuts):
    if not cuts:
        return {}
    f = lambda x: f"{x:g}"
    return {"5": f"{f(cuts[5])} or less", "4": f"Over {f(cuts[5])} to {f(cuts[4])}",
            "3": f"Over {f(cuts[4])} to {f(cuts[3])}", "2": f"Over {f(cuts[3])} to {f(cuts[2])}",
            "1": f"Over {f(cuts[2])}"}


# ---------------------------------------------------------------- serious citations

SEVERITY = {
    # letter: (harm level as Care Compare words it, residents affected)
    "A": ("Potential for minimal harm", "Few"), "B": ("Potential for minimal harm", "Some"),
    "C": ("Potential for minimal harm", "Many"),
    "D": ("Minimal harm or potential for actual harm", "Few"), "E": ("Minimal harm or potential for actual harm", "Some"),
    "F": ("Minimal harm or potential for actual harm", "Many"),
    "G": ("Actual harm", "Few"), "H": ("Actual harm", "Some"), "I": ("Actual harm", "Many"),
    "J": ("Immediate jeopardy", "Few"), "K": ("Immediate jeopardy", "Some"), "L": ("Immediate jeopardy", "Many"),
}


def load_citations(citation_file, ccns):
    """Return {ccn: [citation, ...]} for health (F-tag) citations in the uploaded CMS file."""
    if not citation_file:
        return {}
    _, name, text = citation_file
    out = {}
    for raw in csv.DictReader(io.StringIO(text)):
        r = {norm(k): (v or "").strip() for k, v in raw.items() if k}
        ccn = str(P["ccn"](r) or "").zfill(6)
        if ccn not in ccns:
            continue
        prefix = (pick(r, "deficiency_prefix") or "F").upper()
        stype = (pick(r, "survey_type") or "Health").lower()
        if prefix in ("K", "E") or "fire" in stype or "life safety" in stype:
            continue
        sev = (pick(r, "scope_severity_code") or "").upper()
        tag_no = pick(r, "deficiency_tag_number", "deficiency_tag") or ""
        tag_no = tag_no.zfill(4) if tag_no.isdigit() else tag_no
        kinds = []
        if yes(pick(r, "standard_deficiency")):
            kinds.append("Standard")
        if yes(pick(r, "complaint_deficiency")):
            kinds.append("Complaint")
        if yes(pick(r, "infection_control_inspection_deficiency")):
            kinds.append("Infection control")
        date = to_date(pick(r, "survey_date"))
        corrected = to_date(pick(r, "correction_date"))
        harm, affected = SEVERITY.get(sev, ("", ""))
        out.setdefault(ccn, []).append({
            "date": date.isoformat() if date else None,
            "tag": f"{prefix}{tag_no}",
            "title": pick(r, "deficiency_description") or "",
            "category": pick(r, "deficiency_category") or "",
            "severity": sev,
            "harm": harm,
            "affected": affected,
            "survey": " + ".join(kinds) or "Health",
            "corrected": corrected.isoformat() if corrected else None,
            "status": pick(r, "deficiency_corrected") or "",
            "idr": yes(pick(r, "citation_under_idr")) or yes(pick(r, "citation_under_iidr")),
        })
    for lst in out.values():
        lst.sort(key=lambda c: (c["date"] or "", c["tag"]), reverse=True)
    print(f"Loaded {sum(len(v) for v in out.values())} health citations for {len(out)} facilities from {name}.")
    return out


def serious_counts(cites):
    return {
        "immediate_jeopardy": sum(c["severity"] in ("J", "K", "L") for c in cites),
        "actual_harm": sum(c["severity"] in ("G", "H", "I") for c in cites),
        "source": "CMS Health Deficiencies file (uploaded)",
    }


def load_supplement():
    if not SUPPLEMENT.exists():
        return {}, None
    s = json.loads(SUPPLEMENT.read_text())
    return s.get("facilities", {}), s.get("updated")


# ---------------------------------------------------------------- names

SMALL = {"of", "and", "the", "at", "in", "on", "for", "dba"}
UPPER = {"llc", "snf", "inc", "ii", "iii", "dp", "d/p", "dp/snf", "va", "hgh"}


def nice_name(s):
    out = []
    for i, w in enumerate((s or "").lower().split()):
        core = w.strip(",.()")
        if core in UPPER:
            out.append(w.upper())
        elif i > 0 and core in SMALL:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def clean_sff(v):
    s = (v or "").strip().upper()
    if not s or s in ("N", "NO", "NONE"):
        return ""
    return "Candidate" if "CANDIDATE" in s else "Special Focus Facility"


def region_for(state, county):
    regions = CONFIG["regions"]
    return regions.get(f"{state}:{(county or '').upper()}") or regions.get(state, regions["default"])


# ---------------------------------------------------------------- build

def build():
    rows, provider_file, citation_file = load_inputs()
    check_columns(rows)
    chosen = select(rows)
    if not chosen:
        sys.exit("No facilities matched the area settings in config.json.")

    states = sorted({(P["state"](r) or "").upper() for r, _, _ in chosen})
    cut_info = {s: state_cut_points(rows, s) for s in states}

    ccns = {c for _, c, _ in chosen}
    citations = load_citations(citation_file, ccns)
    serious_csv = {c: serious_counts(v) for c, v in citations.items()}
    if citation_file:
        for c in ccns - set(citations):  # in the file but no health tags on record
            serious_csv[c] = {"immediate_jeopardy": 0, "actual_harm": 0, "source": "CMS Health Deficiencies file (uploaded)"}
    serious_sup, sup_updated = load_supplement()

    out = []
    for r, ccn, dist in chosen:
        state = (P["state"](r) or "").upper()
        cuts, _ = cut_info[state]
        health = to_int(P["health"](r))
        staffing = to_int(P["staffing"](r))
        qm = to_int(P["qm"](r))
        score = to_float(P["score"](r))
        std_date = to_date(P["std_date"](r))
        serious = serious_csv.get(ccn) or serious_sup.get(ccn) or {}
        out.append({
            "name": nice_name(P["name"](r)),
            "ccn": ccn,
            "city": (P["city"](r) or "").title(),
            "state": state,
            "county": (P["county"](r) or "").title(),
            "region": region_for(state, P["county"](r)),
            "miles": round(dist, 1) if dist is not None else None,
            "beds": to_int(P["beds"](r)),
            "overall": to_int(P["overall"](r)),
            "health": health,
            "staffing": staffing,
            "qm": qm,
            "health_score": score,
            "health_score_stars_today": stars_for_score(score, cuts),
            "health_range": bands(cuts).get(str(health)),
            "staffing_range": CONFIG["staffing_ranges"].get(str(staffing)),
            "qm_range": CONFIG["qm_ranges"]["overall"].get(str(qm)),
            "last_standard_survey": std_date.isoformat() if std_date else None,
            "tags_last_standard": to_int(P["c1_standard"](r)),
            "health_tags_on_record": sum_cols(r, r"rating_cycle_[0-9_]+_total_number_of_health_deficiencies"),
            "complaint_tags": sum_cols(r, r"rating_cycle_[0-9_]+_number_of_complaint_health_deficiencies"),
            "immediate_jeopardy": serious.get("immediate_jeopardy"),
            "actual_harm": serious.get("actual_harm"),
            "serious_source": serious.get("source"),
            "serious_as_of": serious.get("as_of"),
            "fines_usd": to_int(P["fines_usd"](r)) or 0,
            "payment_denials": to_int(P["denials"](r)) or 0,
            "special_focus": clean_sff(P["sff"](r)),
            "abuse_icon": yes(P["abuse"](r)),
            "care_compare_url": f"https://www.medicare.gov/care-compare/details/nursing-home/{ccn}?state={state}",
            **staff_fields(r),
            "citations": citations.get(ccn, []) if citation_file else None,
            "inspections_url": f"https://www.medicare.gov/care-compare/inspections/nursing-home/{ccn}/health",
            "propublica_url": f"https://projects.propublica.org/nursing-homes/homes/h-{ccn}",
        })

    out.sort(key=lambda x: (x["miles"] if x["miles"] is not None else 999, x["name"]))
    processed = max((to_date(P["processed"](r)) for r, _, _ in chosen if to_date(P["processed"](r))), default=None)
    area = CONFIG["area"]
    nv_avg, us_avg = staffing_averages(rows, "NV")
    area_avg = {}
    for key, (_, places) in STAFF.items():
        vals = [f[key] for f in out if f.get(key) is not None]
        area_avg[key] = round(sum(vals) / len(vals), max(places, 1)) if vals else None
    meta = {
        "staffing_averages": {"area": area_avg, "NV": nv_avg, "US": us_avg},
        "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "cms_processing_date": processed.isoformat() if processed else None,
        "provider_file": provider_file,
        "facility_count": len(out),
        "area": f"within {area['radius_miles']:g} miles of ZIP {area['origin']['zip']}",
        "health_bands": {s: bands(c) for s, (c, _) in cut_info.items()},
        "health_cut_source": {s: src for s, (_, src) in cut_info.items()},
        "staffing_ranges": {k: v for k, v in CONFIG["staffing_ranges"].items() if not k.startswith("_")},
        "staffing_source": CONFIG["staffing_ranges"]["_source"],
        "qm_ranges": {k: v for k, v in CONFIG["qm_ranges"].items() if not k.startswith("_")},
        "qm_source": CONFIG["qm_ranges"]["_source"],
        "citations_file": citation_file[1] if citation_file else None,
        "citations_processed": citation_file[0].isoformat() if citation_file and citation_file[0] != dt.date.min else None,
        "serious_note": ("Immediate jeopardy / actual harm counts and F-tag lists come from CMS's Health Deficiencies file."
                         if serious_csv else
                         f"Immediate jeopardy / actual harm counts are kept up to date separately from "
                         f"CMS-derived inspection records (last checked {sup_updated or 'n/a'})."),
    }
    return out, meta


CSV_COLS = [
    ("Facility", "name"), ("City", "city"), ("State", "state"), ("Region", "region"), ("Miles from origin", "miles"),
    ("CCN", "ccn"), ("Certified beds", "beds"), ("Overall stars", "overall"), ("Health inspection stars", "health"),
    ("Staffing stars", "staffing"), ("Quality stars", "qm"), ("Health inspection score (lower is better)", "health_score"),
    ("Stars that score earns this month", "health_score_stars_today"), ("Health inspection star range", "health_range"),
    ("Staffing star range (points of 380)", "staffing_range"), ("Quality star range (points of 2,300)", "qm_range"),
    ("Last standard survey", "last_standard_survey"), ("Tags on last standard survey", "tags_last_standard"),
    ("Health tags, last 3 rating cycles", "health_tags_on_record"), ("Complaint tags, last 3 rating cycles", "complaint_tags"),
    ("Immediate jeopardy tags", "immediate_jeopardy"), ("Actual harm tags", "actual_harm"),
    ("Fines (3 yrs, $)", "fines_usd"), ("Payment denials", "payment_denials"), ("Special Focus", "special_focus"),
    ("CMS abuse icon", "abuse_icon"),
    ("Avg residents per day", "residents"), ("Nursing case-mix index", "case_mix"),
    ("RN hrs/resident/day (reported)", "rn"), ("LPN hrs/resident/day (reported)", "lpn"),
    ("CNA hrs/resident/day (reported)", "cna"), ("Total nurse hrs/resident/day (reported)", "total"),
    ("Weekend total nurse hrs/resident/day", "weekend_total"), ("Weekend RN hrs/resident/day", "weekend_rn"),
    ("PT hrs/resident/day", "pt"),
    ("RN hrs (case-mix adjusted)", "adj_rn"), ("LPN hrs (case-mix adjusted)", "adj_lpn"),
    ("CNA hrs (case-mix adjusted)", "adj_cna"), ("Total nurse hrs (case-mix adjusted)", "adj_total"),
    ("Weekend total nurse hrs (case-mix adjusted)", "adj_weekend_total"),
    ("Total nursing staff turnover %", "turnover_total"), ("RN turnover %", "turnover_rn"),
    ("Administrators who left", "admins_left"),
    ("Care Compare link", "care_compare_url"),
]


def write_outputs(rows, meta):
    SITE.mkdir(exist_ok=True)
    payload = {"meta": meta, "facilities": rows}
    (SITE / "data.json").write_text(json.dumps(payload, indent=1))
    with open(SITE / "data.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([c for c, _ in CSV_COLS])
        for r in rows:
            w.writerow(["Yes" if r[k] is True else "" if r[k] is False or r[k] is None else r[k] for _, k in CSV_COLS])
    page = ((ROOT / "scripts" / "template.html").read_text()
            .replace("/*DATA*/null", json.dumps(payload).replace("</", "<\\/"))
            .replace("{{BUILT}}", html.escape(meta["built"]))
            .replace("{{PROCESSED}}", html.escape(meta["cms_processing_date"] or "unknown"))
            .replace("{{AREA}}", html.escape(meta["area"]))
            .replace("{{SERIOUS}}", html.escape(meta["serious_note"])))
    (SITE / "index.html").write_text(page)
    (SITE / ".nojekyll").write_text("")


if __name__ == "__main__":
    facilities, meta = build()
    write_outputs(facilities, meta)
    print(f"Built {len(facilities)} facilities (CMS data processed {meta['cms_processing_date']}):")
    for f in facilities:
        print(f"  {f['miles']!s:>5} mi  {f['ccn']}  {f['name']} ({f['city']}, {f['state']})")
