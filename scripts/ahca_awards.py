#!/usr/bin/env python3
"""Look up AHCA/NCAL National Quality Award recipients among the site's facilities.

Reads AHCA's public "Active Quality Award Recipients" list (a SharePoint list on
ahcancal.org), matches recipients to the facilities on the site by name and city,
and writes supplements/quality_awards.json, which the site build displays.

Matching:
  * exact or close name match within the same state and city, or
  * a name listed under "aliases" in supplements/quality_awards.json (for facilities
    that have been renamed since they earned an award).
Entries marked "manual": true in that file are kept as-is (for awards confirmed from
press releases that AHCA's list doesn't show).

If AHCA's site can't be reached, the existing file is left unchanged and the run
reports why, so the site keeps showing the last known awards.

Standard library only (plus curl, which GitHub's runners have).
"""

import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "supplements" / "quality_awards.json"
HISTORY = ROOT / "history"

SITE = "https://www.ahcancal.org"
WEB = "/Quality/National-Quality-Award-Program"
LIST_TITLE = "Active Quality Award Recipients"
HEADERS = [
    "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language: en-US,en;q=0.9",
]
LEVELS = ("Gold", "Silver", "Bronze")


def curl(url, accept="application/json;odata=nometadata", method="GET", body=None):
    if not shutil.which("curl"):
        sys.exit("curl is required")
    cmd = ["curl", "-sS", "-L", "--compressed", "--max-time", "90", "-w", "\n%{http_code}",
           "-H", f"Accept: {accept}"]
    for h in HEADERS:
        cmd += ["-H", h]
    if method == "POST":
        cmd += ["-X", "POST", "-H", "Content-Type: application/json;odata=verbose", "--data", body or "{}"]
    p = subprocess.run(cmd + [url], capture_output=True)
    out, _, code = p.stdout.rpartition(b"\n")
    return int(code or 0), out.decode("utf-8", "replace")


def fetch_rest_items():
    """SharePoint REST: every item in the list, following paging."""
    title = urllib.parse.quote(LIST_TITLE.replace("'", "''"))
    url = f"{SITE}{WEB}/_api/web/lists/GetByTitle('{title}')/items?$top=5000"
    items = []
    while url:
        code, text = curl(url)
        if code != 200:
            raise RuntimeError(f"REST items HTTP {code}: {text[:200]!r}")
        data = json.loads(text)
        items += data.get("value") or data.get("d", {}).get("results", [])
        url = data.get("odata.nextLink") or data.get("@odata.nextLink") or data.get("d", {}).get("__next")
    return items


def fetch_view_rows():
    """SharePoint list view data (what the public list page itself loads)."""
    title = urllib.parse.quote(LIST_TITLE.replace("'", "''"))
    url = f"{SITE}{WEB}/_api/web/lists/GetByTitle('{title}')/RenderListDataAsStream"
    body = json.dumps({"parameters": {"__metadata": {"type": "SP.RenderListDataParameters"},
                                      "RenderOptions": 2, "RowLimit": 5000}})
    code, text = curl(url, accept="application/json;odata=verbose", method="POST", body=body)
    if code != 200:
        raise RuntimeError(f"RenderListDataAsStream HTTP {code}: {text[:200]!r}")
    return json.loads(text).get("Row", [])


def fetch_page_rows():
    """Last resort: public pages whose HTML embeds the list's rows as JSON (SharePoint ListData)."""
    urls = [f"{SITE}{WEB}/Lists/{urllib.parse.quote(LIST_TITLE)}/AllItems.aspx",
            f"{SITE}{WEB}/Pages/QualityAwardRecipients.aspx"]
    notes = []
    for url in urls:
        code, text = curl(url, accept="text/html")
        title = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
        notes.append(f"{url} -> HTTP {code}, {len(text)} bytes, title {title.group(1).strip()[:60] if title else '?'!r}, "
                     f"'Row' x{text.count('\"Row\"')}, ListData x{text.count('ListData')}")
        if code != 200:
            continue
        for m in re.finditer(r'ListData\s*=\s*(\{.*?\});\s*(?:var|WPQ|\n|<)', text, re.S):
            try:
                rows = json.loads(m.group(1)).get("Row", [])
            except ValueError:
                continue
            if rows:
                return rows
        m = re.search(r'"Row"\s*:\s*(\[.*?\])\s*,\s*"FirstRow"', text, re.S)
        if m:
            return json.loads(m.group(1))
        links = sorted(set(re.findall(r'href="([^"]*(?:Lists|Recipient)[^"]*)"', text)))[:15]
        notes.append(f"  list links on page: {links}")
    raise RuntimeError("rows not found in page HTML:\n" + "\n".join(notes))


# ---------------------------------------------------------------- normalizing AHCA rows

def norm_key(k):
    return re.sub(r"[^a-z0-9]+", "_", str(k).lower()).strip("_")


def field(row, *words, exclude=()):
    """Value of the first column whose name contains all of `words`."""
    for k, v in row.items():
        if all(w in k for w in words) and not any(x in k for x in exclude) and v not in (None, ""):
            return v if not isinstance(v, dict) else (v.get("Label") or v.get("Title") or v.get("Description") or "")
    return ""


def to_recipient(raw):
    r = {norm_key(k): v for k, v in raw.items()}
    name = field(r, "facility") or field(r, "organization") or field(r, "provider") or field(r, "title", exclude=("job",))
    level = field(r, "level") or field(r, "award")
    year = field(r, "year")
    text = " ".join(str(v) for v in r.values() if isinstance(v, (str, int)))
    lvl = next((L for L in LEVELS if L.lower() in str(level).lower()), None) or \
        next((L for L in LEVELS if re.search(rf"\b{L}\b", text, re.I)), None)
    yr = re.search(r"(19|20)\d{2}", str(year)) or None
    return {
        "name": str(name).strip(),
        "city": str(field(r, "city")).strip(),
        "state": str(field(r, "state", exclude=("statement",))).strip().upper()[:2],
        "level": lvl,
        "year": int(yr.group(0)) if yr else None,
    }


STOP = {"the", "of", "and", "at", "llc", "inc", "dba", "center", "centre", "rehabilitation", "rehab",
        "health", "healthcare", "care", "nursing", "skilled", "facility", "snf", "dp", "d", "p", "post", "acute"}


def tokens(name):
    return {t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if t not in STOP}


def similar(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ---------------------------------------------------------------- facilities on the site

def site_facilities():
    """CCN, name, city, state for the facilities in the newest history snapshot."""
    import csv
    snaps = sorted(HISTORY.glob("cms-*.csv"))
    if not snaps:
        sys.exit("No history/cms-*.csv yet; run the site build first.")
    with open(snaps[-1], newline="") as fh:
        return [{"ccn": r["CCN"].zfill(6), "name": r["Facility"], "city": r["City"], "state": r["State"]}
                for r in csv.DictReader(fh)]


def match(recipients, facilities, aliases):
    found = {}
    for f in facilities:
        names = [f["name"]] + aliases.get(f["ccn"], [])
        best = None
        for rec in recipients:
            if rec["state"] and rec["state"] != f["state"]:
                continue
            same_city = not rec["city"] or rec["city"].lower() == f["city"].lower()
            score = max(similar(n, rec["name"]) for n in names)
            exact = any(re.sub(r"\W+", "", n.lower()) == re.sub(r"\W+", "", rec["name"].lower()) for n in names)
            if exact or (same_city and score >= 0.6):
                rank = (LEVELS[::-1].index(rec["level"]) if rec["level"] in LEVELS else -1, rec["year"] or 0)
                if best is None or rank > best[0]:
                    best = (rank, rec)
        if best:
            rec = best[1]
            found[f["ccn"]] = {"facility": f["name"], "level": rec["level"], "year": rec["year"],
                               "ahca_name": rec["name"], "source": "AHCA/NCAL Active Quality Award Recipients list"}
    return found


def main():
    existing = json.loads(OUT.read_text()) if OUT.exists() else {}
    aliases = existing.get("aliases", {})
    facilities = site_facilities()

    rows, errors = None, []
    for fn in (fetch_rest_items, fetch_view_rows, fetch_page_rows):
        try:
            rows = fn()
            print(f"{fn.__name__}: {len(rows)} rows")
            if rows:
                break
        except Exception as exc:  # try the next method
            errors.append(f"{fn.__name__}: {exc}")
            print(errors[-1], file=sys.stderr)
    if not rows:
        print("Could not read AHCA's recipient list; leaving supplements/quality_awards.json unchanged.")
        print("\n".join(errors))
        return 0

    recipients = [to_recipient(r) for r in rows]
    print("Sample columns:", sorted(norm_key(k) for k in rows[0])[:40])
    in_area = [r for r in recipients if r["state"] in {f["state"] for f in facilities}]
    print(f"{len(in_area)} recipients in {sorted({f['state'] for f in facilities})}")

    found = match(recipients, facilities, aliases)
    manual = {k: v for k, v in existing.get("facilities", {}).items() if v.get("manual")}
    result = {
        "_about": existing.get("_about", "AHCA/NCAL National Quality Award recipients among the site's facilities. "
                                         "Written by scripts/ahca_awards.py; entries with manual=true are kept as-is."),
        "checked": dt.date.today().isoformat(),
        "source_url": f"{SITE}{WEB}/Pages/QualityAwardRecipients.aspx",
        "aliases": aliases,
        "facilities": {**found, **manual},
        "nearby_recipients_not_matched": sorted(
            {f"{r['name']} ({r['city']}, {r['state']}) - {r['level'] or '?'} {r['year'] or ''}".strip()
             for r in in_area if r["state"] == "NV" and not any(v.get("ahca_name") == r["name"] for v in found.values())}),
    }
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    for ccn, a in result["facilities"].items():
        print(f"  {ccn} {a['facility']}: {a['level']} {a['year'] or ''}{' (manual)' if a.get('manual') else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
