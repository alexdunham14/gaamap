"""Where the fixtures live: one file per source per season, and an index of them.

A season is a calendar year, which is what a GAA season is: the club All-Ireland stages in
January, the league in spring, the championships through the summer. Each fetch script owns
one *source* (gaa.ie, camogie.ie, ladiesgaelic.ie) and writes one file per season it saw:

    data/seasons.json     the index the site loads first
    data/2026-gaa.json    football and hurling from gaa.ie, 2026
    data/2026-camogie.json
    data/2026-ladies.json
    data/2026-club.json   club championships from the county and provincial sites

Two properties this shape buys, both of which the single root-level fixtures.json lacked:

  * A finished season is never thrown away. gaa.ie's fixtures page only ever shows the
    season it is in, so when the 2027 fixtures replace the 2026 ones on their site, the
    2026 file here is simply not written again. It stays as the record of that season.
  * The site downloads one season, not all of them. app.js reads seasons.json, loads the
    newest season's files, and fetches an older season only if the reader asks for it.

Nothing is ever merged across seasons on disk and no script writes another script's file,
so a source being down costs that source's newest season and nothing else.
"""
import datetime as dt
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "data")
INDEX = os.path.join(DIR, "seasons.json")
# Sources in the order the site should load them; the sports each one can produce is
# written into the index so app.js can name a season's contents before fetching it.
SOURCES = {
    "gaa": {"sports": ["Football", "Hurling"], "site": "gaa.ie"},
    "camogie": {"sports": ["Camogie"], "site": "camogie.ie"},
    "ladies": {"sports": ["Ladies' Football"], "site": "ladiesgaelic.ie"},
    # Club championships, from the county boards and provincial councils whose sites can be
    # read (scripts/club_sites.json). Unlike the other three this file accumulates, because
    # no site shows more than a few weeks at a time: see fetch_club.py.
    "club": {"sports": ["Football", "Hurling", "Camogie", "Ladies' Football"], "site": "county and provincial board sites"},
}


def season_of(row):
    """The calendar year a fixture belongs to. Throw-ins are stored as UTC instants and no
    GAA match is played within an hour of midnight, so the date's own year is the season."""
    return int(row["date"][:4])


def path(year, key):
    return os.path.join(DIR, f"{year}-{key}.json")


def rel(year, key):
    return f"data/{year}-{key}.json"


def read(year, key):
    p = path(year, key)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def all_fixtures():
    """Every fixture row on disk, every season, every source. Geocoding and venue merging
    want all of them: a ground first used in 2026 still needs its coordinates in 2027."""
    rows = []
    for year, key in _files():
        rows += read(year, key)["fixtures"]
    return rows


def _files():
    if not os.path.isdir(DIR):
        return []
    out = []
    for name in sorted(os.listdir(DIR)):
        year, _, rest = name.partition("-")
        key = rest[:-5] if rest.endswith(".json") else ""
        if year.isdigit() and key in SOURCES:
            out.append((int(year), key))
    return out


def write_source(key, rows, source_url, min_rows=1, fetched=None):
    """Write one source's rows, split into a file per season, and rebuild the index.

    Only the seasons present in `rows` are written: a fetch that returns the 2027 season
    leaves the 2026 file exactly as it was. `min_rows` guards against a source that has
    changed its page format and now parses to almost nothing -- better to keep last
    week's file than to replace it with three rows."""
    assert key in SOURCES, key
    by_year = {}
    for r in rows:
        by_year.setdefault(season_of(r), []).append(r)
    os.makedirs(DIR, exist_ok=True)
    written = []
    now = fetched or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for year, rs in sorted(by_year.items()):
        if len(rs) < min_rows:
            print(f"skip {year}: only {len(rs)} rows")
            continue
        # Sorted on the id as well as the date: two rows can share a date and a
        # competition, and without a total order they swap places between runs and every
        # refresh commits a diff that changes nothing.
        rs.sort(key=lambda r: (r["date"] or "", r["competition"] or "", str(r["id"])))
        out = {"season": year, "source": source_url, "fetched": now, "fixtures": rs}
        with open(path(year, key), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=0)
        written.append((year, len(rs)))
    reindex()
    return written


def reindex():
    """Rebuild data/seasons.json from the files that are actually on disk."""
    seasons = {}
    for year, key in _files():
        d = read(year, key)
        sports = sorted({r["sport"] for r in d["fixtures"] if r.get("sport")})
        seasons.setdefault(year, []).append({
            "key": key, "file": rel(year, key), "site": SOURCES[key]["site"],
            "sports": sports, "count": len(d["fixtures"]),
            "from": min(r["date"][:10] for r in d["fixtures"]) if d["fixtures"] else None,
            "to": max(r["date"][:10] for r in d["fixtures"]) if d["fixtures"] else None,
            "fetched": d.get("fetched"), "source": d.get("source"),
        })
    order = list(SOURCES)
    for v in seasons.values():
        v.sort(key=lambda s: order.index(s["key"]))
    index = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest": max(seasons) if seasons else None,
        "seasons": [{"year": y, "sources": seasons[y]} for y in sorted(seasons, reverse=True)],
    }
    os.makedirs(DIR, exist_ok=True)
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    return index
