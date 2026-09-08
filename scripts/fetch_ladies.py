#!/usr/bin/env python3
"""Pull ladies' football from ladiesgaelic.ie into data/<year>-ladies.json, in the same
record shape fetch.py writes for gaa.ie (sport: "Ladies' Football").

ladiesgaelic.ie is a WordPress site whose fixtures/results pages render every match row
server-side in one request -- the year/competition/team menus on the page are a filter
over rows that are already in the HTML, not an API, so there is nothing to page through
and nothing to run JavaScript for. The results page carries every season since 2016;
only the current one is taken (see --since).

Each row is a <div class="fixture"> carrying the useful parts as data- attributes:

    data-filter-year        2026
    data-filter-competition All-Ireland Senior Championship
    data-filter-division    All-Ireland Senior Championship-All-Ireland Senior Championship Group 1
    data-date               20260802

with the teams and scores in three columns, the sponsor-prefixed competition and the
round together in an <h2>, and referee, venue and throw-in time run together in a
<small> as "Referee: X * Venue: Y * Time: Z".

Two things this source makes harder than the other two:

  * **No venue ids.** gaa.ie and camogie.ie both name a venue by the GAA's own UUID;
    LGFA writes it as prose, sometimes in Irish ("Páirc an Chrócaigh" for Croke Park).
    scripts/venue_match.py matches that text to a venue already in venues.json so the
    fixture lands on the ground's existing dot; a name it cannot match safely gets an
    "lgfa-" id of its own, and geocode.py places it.
  * **The competition name is split over three fields** and none of them is the whole
    truth: the <h2> has the sponsor on the front and the round on the end, the
    competition attribute drops the division, and the division attribute repeats the
    competition. The name that goes in the file is assembled from all three, without the
    sponsor -- sponsors change every few seasons and would otherwise split one
    competition into a new menu entry every time they did.

Times print as bare Irish wall clock with no zone, so they are read in Europe/Dublin and
stored as the UTC instant gaa.ie gives for free.
"""
import datetime as dt
import gzip
import html as htmllib
import json
import os
import re
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data  # noqa: E402
import venue_match  # noqa: E402

BASE = "https://ladiesgaelic.ie"
PAGES = [("results", f"{BASE}/fixtures-results/results/"),
         ("fixtures", f"{BASE}/fixtures-results/upcoming-fixtures/")]
IRELAND = ZoneInfo("Europe/Dublin")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
THIS_YEAR = dt.datetime.now(dt.timezone.utc).year
SINCE = int(sys.argv[sys.argv.index("--since") + 1]) if "--since" in sys.argv else THIS_YEAR

COUNTIES = venue_match.COUNTY_RE
# Every <h2> ends with the round. Longest phrases first, so "Relegation Final" is not read
# as "Final" and "Preliminary Quarter-Final" is not read as "Quarter-Final".
ROUND_TAIL_RE = re.compile(
    r"(?:(Group [A-Z0-9]+)\s+)?("
    r"Round \d+[A-Z]?|Preliminary Quarter-Finals?|Relegation (?:Qualifier|Play-?off|Semi-Finals?|Finals?)|"
    r"Quarter-Finals?(?: \d)?|Semi-Finals?|Play-?offs?(?: \d)?|(?:Home |International |Shield |Plate )?Finals?"
    r")\s*$", re.I)
DIVISION_RE = re.compile(r"Division\s*(\d)", re.I)
GRADE_RE = re.compile(r"['‘’\"]([A-C])['‘’\"]")
GROUP_RE = re.compile(r"\b(Group [A-Z0-9]+)\s*$")
# The U-14 festival's four finals are one competition played at four standards; the
# standard is the only thing that tells them apart, so it goes in the round.
STANDARD_RE = re.compile(r"\b(Platinum|Gold|Silver|Bronze)\b")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=90) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")


def text(s):
    """Markup text as it should read: tags gone, entities decoded, whitespace collapsed."""
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def attr(block, name):
    m = re.search(r'data-%s="([^"]*)"' % name, block)
    return htmllib.unescape(m.group(1)) if m else None


def parse_round(title, suffix):
    """(group, round) read off the end of the <h2>, which is the only field carrying the
    round at all, and always ends with it."""
    m = ROUND_TAIL_RE.search(title or "")
    if not m:
        return (GROUP_RE.search(suffix or "") or [None, None])[1], None
    group, round_ = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
    round_ = re.sub(r"play-?off", "Play-Off", round_, flags=re.I)
    round_ = re.sub(r"\bfinals\b", "Final", round_, flags=re.I)
    round_ = re.sub(r"\b(quarter|semi)-final\b", lambda x: x.group(1).title() + "-Final", round_, flags=re.I)
    standard = STANDARD_RE.search(suffix or "")
    if standard:
        round_ = f"{standard.group(1)} {round_}"
    return group or (GROUP_RE.search(suffix or "") or [None, None])[1], round_


def competition_of(comp, suffix):
    """One name per competition, assembled from the competition and division attributes.

    The division attribute is the competition plus a suffix, so the suffix is the more
    specific of the two and is preferred where it says something: a grade ("All-Ireland
    U-16 'A' Championship") or a league division. Where it only repeats the competition
    or adds a championship group, the competition name is what goes in the file and the
    group is kept separately."""
    if DIVISION_RE.search(suffix) and re.search(r"\bNFL\b|National Football League", suffix + comp, re.I):
        # "Ladies NFL - League Division 2" and "Ladies NFL - Cup Division 2" are the group
        # stage and the knockout of one competition, and belong under one name.
        return f"National Football League Division {DIVISION_RE.search(suffix).group(1)}"
    if GRADE_RE.search(suffix):
        # "All-Ireland U-16 'A' Championship" -> "All-Ireland U-16A Championship";
        # "... Post Primary Schools Senior 'A' Championship" -> "... Senior A Championship".
        name = GRADE_RE.sub(r"\1", suffix)
        return re.sub(r"\s+", " ", re.sub(r"\b(U-\d+) ([A-C])\b", r"\1\2", name)).strip()
    return comp


def parse_page(page, is_result, url):
    if '<div class="fixtures-table">' not in page:
        return []
    section = page[page.index('<div class="fixtures-table">'):]
    rows = []
    for block in section.split('<div class="fixture ')[1:]:
        year, date_s = attr(block, "filter-year"), attr(block, "date")
        if not (year or "").isdigit() or not (date_s or "").isdigit() or int(year) < SINCE:
            continue
        comp = attr(block, "filter-competition") or ""
        division = attr(block, "filter-division") or ""
        suffix = division[len(comp) + 1:] if comp and division.startswith(comp + "-") else division
        title = text((re.search(r"<h2>(.*?)</h2>", block, re.S) or [None, ""])[1])
        group, round_ = parse_round(title, suffix)
        teams = [text(t) for t in re.findall(r'<div class="col-lg-4(?: alignright)?">\s*(.*?)\s*</div>', block, re.S)]
        scores = [text(s) for s in re.findall(r'<span class="score">\s*(.*?)\s*</span>', block, re.S)]
        detail = text((re.search(r"<small>(.*?)</small>", block, re.S) or [None, ""])[1])
        venue = (re.search(r"Venue:\s*([^•]*)", detail) or [None, ""])[1].strip() or None
        time_s = (re.search(r"Time:\s*(\d{1,2}:\d{2})", detail) or [None, None])[1]
        d = dt.date(int(date_s[:4]), int(date_s[4:6]), int(date_s[6:8]))
        if time_s:
            hh, mm = (int(x) for x in time_s.split(":"))
            # Irish wall clock with no zone marker, as on camogie.ie. Stored as the UTC
            # instant, or every summer throw-in reads an hour out against gaa.ie's rows.
            iso = dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=IRELAND).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        else:
            iso = f"{d.isoformat()}T00:00:00+00:00"
        score = [re.match(r"(\d+)\s*:\s*(\d+)", s) for s in scores[:2]]
        have = is_result and len(score) == 2 and all(score)
        rows.append({
            "id": None,  # filled in by main(); the markup carries no match id
            "date": iso,
            "time": time_s,
            "tbc": time_s is None,
            "status": "active",
            "sport": "Ladies' Football",
            "competition": competition_of(comp, suffix),
            "competitionId": None,
            "rank": None,
            "group": group,
            "round": round_,
            "home": {"id": None, "name": teams[0] if teams else None},
            "away": {"id": None, "name": teams[1] if len(teams) > 1 else None},
            "venueId": None,   # filled in by place_venues()
            "venue": venue,
            "result": bool(have),
            "score": {"hg": int(score[0][1]), "hp": int(score[0][2]),
                      "ag": int(score[1][1]), "ap": int(score[1][2])} if have else None,
            "tickets": None,
            "tv": None,
            "url": url,
        })
    return rows


def slug(name):
    return "lgfa-" + re.sub(r"\s+", "-", venue_match._plain(name))[:60]


def place_venues(rows, venues):
    """Give every row a venue id: an existing one where the name matches a ground already
    on the map, otherwise one of its own for geocode.py to place."""
    m = venue_match.Matcher(venues)
    ids, report = {}, {}
    for r in rows:
        name = r["venue"]
        if not name:
            continue
        if name not in ids:
            home = (r["home"] or {}).get("name") or ""
            county = home.title() if COUNTIES.fullmatch(home) else None
            vid, how = m.match(name, county)
            ids[name] = vid or slug(name)
            report[name] = (how, venues[vid]["name"] if vid else None)
        r["venueId"] = ids[name]
    return report


def main():
    rows = []
    for kind, url in PAGES:
        try:
            page = fetch(url)
        except Exception as ex:  # noqa: BLE001
            print(f"{kind}: {ex}", file=sys.stderr)
            continue
        got = parse_page(page, kind == "results", url)
        print(f"{kind}: {len(got)} rows")
        rows += got
        time.sleep(1.0)
    if len(rows) < 50:
        sys.exit(f"only {len(rows)} ladies' football rows parsed; refusing to write "
                 "(ladiesgaelic.ie may have changed its page format)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    vpath = os.path.join(root, "venues.json")
    venues = json.load(open(vpath, encoding="utf-8")) if os.path.exists(vpath) else {}
    report = place_venues(rows, venues)
    matched = sum(1 for how, to in report.values() if to)
    print(f"venues: {matched} of {len(report)} names matched a ground already on the map")
    if "--venues" in sys.argv:
        for name, (how, to) in sorted(report.items()):
            print(f"  {how:34s} {name}" + (f"  ->  {to}" if to else ""))
    seen = {}
    for r in rows:
        key = "|".join(str(x) for x in (r["date"], r["competition"], r["round"], r["home"]["name"], r["away"]["name"]))
        n = seen.get(key, 0)
        seen[key] = n + 1
        r["id"] = f"lgfa:{key}" + (f"#{n}" if n else "")
    for year, n in data.write_source("ladies", rows, PAGES[0][1], min_rows=20):
        print(f"{year}: {n} ladies' football fixtures")


if __name__ == "__main__":
    main()
