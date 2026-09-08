#!/usr/bin/env python3
"""Pull club championship fixtures and results from the county boards and provincial
councils that publish them, into data/<year>-club.json.

gaa.ie's own fixtures page stops at the All-Ireland stages of the club championship, so
from August, when the inter-county season ends, it has nothing to say about the rest of
the year. The rest of the year is the club championships: county rounds through the
autumn, the provincial series from late October, the All-Ireland stages in January. The
county boards publish those, and about half of them (scripts/club_sites.json) do it on
one shared WordPress theme, the same one camogie.ie uses, which renders the GAA's own
Foireann fixture cards and pages them through an undocumented endpoint:

    GET <site>/fixtures-results/?ajax=1&feed_type=fixtures|results&page=N&size=50&grade=senior
    -> {"ok": true, "hasMore": bool, "html": "<h3 class=fix_res_date>DATE</h3><div class=competition>...</div>..."}

The cards carry what gaa.ie's rows carry, less the ticket and television fields: the
competition with its round, the two teams, the throw-in as bare Irish wall clock (read in
Europe/Dublin and stored as a UTC instant, as fetch_camogie.py does), the score once
played, and the venue, linked by the *same* venue UUID gaa.ie uses -- Foireann is one
venue database -- so a club match at Fitzgerald Stadium lands on the dot that is already
there, and a club ground the map has never seen gets an entry for geocode.py to place.

Two things make this source different from the other three, and shape the script:

  * Each site shows what is published now: a week or three of fixtures, and the recent
    results, page by page. Nothing here is a season in one request. So this script
    accumulates: it reads the season file it wrote last time, keeps every result it ever
    saw, and replaces the unplayed fixtures with what the sites say today. A fixture that
    has vanished from its site was postponed or redrawn, and a played match that never
    reached the results feed is dropped rather than shown as still to come. A site that
    fails keeps last week's rows untouched.
  * Names are typed by hand, per county. "Garvey's SuperValu Senior Football County
    Championship", "Kerry Petroleum Senior Football Club Championship" and "LCC Group
    Senior Football Championship" are the same kind of thing with three sponsors on the
    front, so the sponsor is taken off (everything before the first grade word, when none
    of it is a place or a sport) and the county put on, and "Kerry Senior Football
    Championship" is what the competition menu shows.

Only club fixtures are taken (the county sites also list their county teams, which gaa.ie
already has), at senior and intermediate grade -- junior too for a province -- in all four
codes. A match that gaa.ie also lists (the All-Ireland stages) is left to gaa.ie.
"""
import datetime as dt
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SITES = json.load(open(os.path.join(HERE, "club_sites.json"), encoding="utf-8"))["sites"]
IRELAND = ZoneInfo("Europe/Dublin")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
PAGE_SIZE = 50
MAX_PAGES = 10          # per feed; a county's whole published horizon is one or two
RESULT_PAGES = 3        # results are only read to settle fixtures seen before; ~150 rows back
RESULT_DAYS = 14        # a result older than this that was never a fixture here is last month's league, not news
SLEEP = 1.0
TODAY = dt.datetime.now(IRELAND).date()
THIS_YEAR = TODAY.year
CUTOFF = (TODAY - dt.timedelta(days=RESULT_DAYS)).isoformat()
SOURCE_URL = "county board and provincial council websites, listed in scripts/club_sites.json"

SPORTS = {"football": "Football", "hurling": "Hurling", "camogie": "Camogie", "ladies_football": "Ladies' Football"}
GRADES = ("senior", "intermediate", "junior")
DATE_RE = re.compile(r'<h3 class="fix_res_date[^"]*"[^>]*>\s*([^<]+?)\s*</h3>')
ORDINAL_RE = re.compile(r"(\d+)(st|nd|rd|th)\b")
PATH_RE = re.compile(r"/fixtures-results/([a-z_]+)/([a-z_]+)/([a-z_]+)/")
VENUE_RE = re.compile(r"<strong>Venue:</strong>\s*(?:<a([^>]*)>\s*([^<]*?)\s*</a>|([^<]+))")
PLACEHOLDER_RE = re.compile(r"^(winner|loser|first|second|third|fourth|runner|top|bottom|best|tbc|tba|tbd|bye|team\s*\w+|[12](st|nd) (in )?group|group [a-z0-9]+ (winner|runner))|\b(winners?|losers?|runners?[- ]?up)$", re.I)
REF_RE = re.compile(r"<strong>Referee:</strong>\s*([^<]+)")


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8-sig"))  # tipperary.gaa.ie sends a byte-order mark


def text(s):
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse_date(s):
    return dt.datetime.strptime(ORDINAL_RE.sub(r"\1", s.strip()), "%A %d %b %Y").date()


def cell(block, cls):
    """The text of the <div class="<cls> ..."> cell: its link's text if it has one."""
    m = re.search(rf'<div class="{cls}[^"]*"[^>]*>(.*?)</div>', block, re.S)
    return text(m.group(1)) if m else ""


def parse_score(s):
    m = re.match(r"(\d+)\s*-\s*(\d+)$", s.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


# The vocabulary of a hand-typed competition title, used to sort its " - " separated parts
# into competition, group and round, and to tell a sponsor from a name.
GRADE_WORD_RE = re.compile(r"\b(Senior|Intermediate|Junior|Premier|Minor|Under|U\d+|Division|Div|Adult|Novice|S[FH]C|I[FH]C|J[FH]C|Snr|Sen|Sr|Jnr|Jun|Int|Inter)\b\.?", re.I)
COMP_WORD_RE = re.compile(r"\b(Championship|Chmapionship|League|Cup|Shield|Corn|Football|Hurling|Camogie|Ladies|LGFA|S[FH]C|I[FH]C|J[FH]C|Senior|Intermediate|Junior|Premier|Minor|Adult|Novice|Under|U\d+)\b", re.I)
ROUND_RE = re.compile(r"^(?:(?:Round|RD|R)\s*\d+\b.*|\d+|.*\bFinals?\b(?:\s*\d+|\s+[AB]|\s+Replay)?(?:\s+[A-Z]{2,4})?|(?:Cup |Shield |Relegation |Preliminary |Senior |Inter(?:mediate)? |Sr\.? [AB] |Sr\.? Cup |Intermediate |Junior |League )*(?:Q-?Final|Qtr\.? Final|S/Final|Quarter-?\s?Finals?|Semi-?\s?Finals?|Finals?|Play\s?-?Offs?|Play Off)(?:\s*\d+|\s*[AB]|\s+Replay|\s+Relegation)?|.*\bRelegation\b.*|.*\bReplay\b.*|Group Phase|Round Robin)$", re.I)
GROUP_RE = re.compile(r"^(?:(?:Cup|League|Shield|KO Cup)\s+)?(?:Group|Gr\.?|Division|Div|Section|Pool)\s+[A-Z0-9]+$|^(?:Knockout|KO|Relegation|Play-?offs?)$", re.I)
KEEP_RE = re.compile(r"\b(Football|Hurling|Camogie|Ladies|LGFA|Ulster|Munster|Leinster|Connacht|County|North|South|East|West|Mid)\b", re.I)
PLACE_RE = re.compile(r"^(Ulster|Munster|Leinster|Connacht)\b")
COUNTY_RE = venue_match.COUNTY_RE
ABBREV = [
    (r"\bS\.?F\.?C\b", "Senior Football Championship"), (r"\bI\.?F\.?C\b", "Intermediate Football Championship"),
    (r"\bJ\.?F\.?C\b", "Junior Football Championship"), (r"\bS\.?H\.?C\b", "Senior Hurling Championship"),
    (r"\bI\.?H\.?C\b", "Intermediate Hurling Championship"), (r"\bJ\.?H\.?C\b", "Junior Hurling Championship"),
    (r"\b(Snr|Sen|Sr)\.?\b", "Senior"), (r"\b(Int|Inter)\.?\b", "Intermediate"), (r"\b(Jnr|Jun)\.?\b", "Junior"),
    (r"\bChmapionship\b", "Championship"), (r"\bCh'ship\b", "Championship"), (r"\bLGFA\b", "Ladies"),
    (r"\b(Chp|Champ)\.?\b", "Championship"), (r"\bHrl\b", "Hurling"), (r"\b(Ftb|Fbl|Ftbl)\b", "Football"), (r"\bPrm\b", "Premier"),
    (r"\bGr\.\s*", "Group "), (r"\bAdult\s+", ""),
    (r"\bGAA\b", ""), (r"\(Sponsored by[^)]*\)", ""), (r"\bSponsored by .*$", ""),
]


def _title(s):
    """SHOUTED words lowered; the rest as typed."""
    return " ".join(w.capitalize() if len(w) > 4 and w.isupper() else w for w in s.split())


def _expand(s):
    for pat, rep in ABBREV:
        s = re.sub(pat, rep, s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip(" -,")


def _strip_years(s):
    return re.sub(r"\s+", " ", re.sub(r"\b(?:19|20)\d\d\b", "", s)).strip(" -")


def competition_name(raw, place, sport=None):
    """(competition, group, round) from one county's hand-typed title.

    The title is " - " separated parts, in no fixed order: "2026 - SFC - Fairyhouse Steel -
    Quarter-Final 1", "Adult Championship - Senior - CUP S/FINAL 1", "Senior Championship Kyte
    Powertech - Round 4", "Cadco IFC Group A - Round 2". Each part is sorted by its vocabulary
    -- a round, a group, a grade on its own, a sponsor (no competition word at all), or the
    competition -- then the competition is made to read like the others': the year and the
    sponsor off, abbreviations expanded, a trailing group or stage moved out, the county or
    province on the front unless a place is already there, and the words in gaa.ie's order.
    "Club" and "County" stay: Kerry runs a Senior Football County Championship and a Senior
    Football Club Championship, and they are two competitions."""
    parts = [_strip_years(_title(p)) for p in re.split(r"\s+-\s+|\s+-(?=\S)|(?<=\S)-\s+", raw.strip())]
    parts = [_expand(p) for p in parts if p]
    # A sponsor on the first part, the competition later: "FBD Insurance - Snr Hrl Chp - ..."
    if len(parts) > 1 and not COMP_WORD_RE.search(parts[0]) and any(COMP_WORD_RE.search(p) for p in parts[1:]):
        parts = parts[1:]
    comp, grade_parts, group, round_ = [], [], None, None
    for i, p in enumerate(parts):
        if i and ROUND_RE.match(p):
            round_ = p if round_ is None or i == len(parts) - 1 else round_
        elif i and GROUP_RE.match(p):
            group = p
        elif i and re.fullmatch(r"(Senior|Intermediate|Junior|Premier|Premier Intermediate)( [A-C])?", p, re.I):
            grade_parts.append(p)
        elif i and not COMP_WORD_RE.search(p):
            continue  # a sponsor on a part of its own: "Meade Farm", "Fairyhouse Steel"
        else:
            comp.append(p)
    c = " ".join(grade_parts + comp) if comp else " ".join(grade_parts + parts[:1])
    c = re.sub(r"\s+", " ", c).strip(" -,")
    # A group or stage typed into the name: "Senior Football Championship Group A",
    # "Intermediate Hurling Championship Semi Finals", "Senior Championship 2026 QTR Final".
    m = re.search(r"\s+((?:Cup |League )?(?:Group|Division|Div)\s+[A-Z0-9]+|Group Phase|Group Stages?)$", c, re.I)
    if m:
        group = group or m.group(1)
        c = c[: m.start()]
    m = re.search(r"\s+((?:Quarter|Semi|Qtr\.?)[- ]?Finals?|Finals?|Relegation(?: Play[- ]?Offs?| Finals?)?|Play[- ]?Offs?|Playoffs|KO)$", c, re.I)
    if m:
        round_ = round_ or m.group(1)
        c = c[: m.start()]
    # The sponsor at the front: everything before the first grade word, once the place's own
    # name is discounted, when none of it is a place or a sport. "TUS TUS Senior Hurling".
    m = re.search(r"\b(Ulster|Munster|Leinster|Connacht)\b", c)
    if m:
        c = c[m.start():]          # "AIB Leinster Club Senior Hurling"
    m = re.search(r"\b(Senior|Intermediate|Junior|Premier|Minor|Under|U\d+|Division|Div|Novice|Football|Hurling|Camogie|Ladies|Championship|League)\b", c, re.I)
    if m and m.start() > 0:
        prefix = re.sub(rf"\b(County\s+)?{re.escape(place)}\b", "", c[:m.start()], flags=re.I)
        # A lone letter is a tier ("C Football Championship"), not a sponsor.
        if not KEEP_RE.search(prefix) and not COUNTY_RE.search(prefix) and not re.fullmatch(r"[A-D]", prefix.strip()):
            c = c[m.start():]
    # The sponsor at the back: "Senior Championship Kyte Powertech".
    m = re.search(r"\b(Championship|League)\b(.*)$", c, re.I)
    if m and m.group(2).strip() and not COMP_WORD_RE.search(m.group(2)) and not re.search(r"\b[AB]\b|Division|Group|Cup|Shield|Reserve|Relegation|Final", m.group(2), re.I):
        c = c[: m.end(1)]
    # Word order: "Football Senior Club Championship" and "Club Senior Football Championship"
    # both become "Senior Club Football Championship", which is how gaa.ie writes it.
    c = re.sub(r"\b(Football|Hurling|Camogie)\s+(Senior|Intermediate|Junior)\s+((?:Club |County )?)(\w+)", r"\2 \3\1 \4", c)
    c = re.sub(r"\bClub\s+(Senior|Intermediate|Junior|Premier Intermediate)\b", r"\1 Club", c)
    c = re.sub(r"\s+", " ", c).strip(" -,")
    if not re.search(r"\b(Championship|League|Cup|Shield|Corn|Playoffs?)\b", c, re.I):
        # "Leinster Club Intermediate Hurling" is the championship; "Senior Ladies" with a
        # group of "League Division 2" is the league.
        # A group of "League Division 2" says league; "Cup Division 1" is a championship's
        # knockout, which the theme files as Cup and Shield.
        c += " League" if re.match(r"League\b", group or "", re.I) else " Championship"
    if sport and not re.search(r"\b(Football|Hurling|Camogie|Ladies)\b", c, re.I):
        # "Tyrone Senior Championship" is the football one, the site's path says so.
        c = re.sub(r"\b(Championship|League|Cup|Shield)\b", rf"{sport} \1", c, count=1) if re.search(r"\b(Championship|League|Cup|Shield)\b", c) else f"{c} {sport}"
    if not PLACE_RE.match(c) and not COUNTY_RE.match(c):
        c = f"{place} {c}"
    if round_:
        round_ = re.sub(r"\s+", " ", round_).strip()
        round_ = re.sub(r"\bS/Final\b", "Semi-Final", round_, flags=re.I)
        round_ = re.sub(r"\bQ-Final\b|\bQtr\.? Final\b", "Quarter-Final", round_, flags=re.I)
        round_ = re.sub(r"^(?:Round|RD|R)\s*(\d+)$", r"Round \1", round_, flags=re.I)
        round_ = re.sub(r"^(\d+)$", r"Round \1", round_)
    return c, group, round_


def parse_cards(html, site, feed):
    rows = []
    place = site.get("county") or site["province"]
    chunks = DATE_RE.split(html)
    for i in range(1, len(chunks), 2):
        try:
            d = parse_date(chunks[i])
        except ValueError:
            continue
        for block in chunks[i + 1].split('<div class="competition">')[1:]:
            comp = re.search(r'<div class="competition-name[^"]*"[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.S)
            if not comp:
                continue
            href, comp_raw = comp.group(1), text(comp.group(2))
            path = PATH_RE.search(href)
            if not path or path.group(2) != "club" or path.group(1) not in SPORTS or path.group(3) not in GRADES:
                continue
            home, away = cell(block, "home_team"), cell(block, "away_team")
            # A slot in a draw is not a fixture: "Winner v Winner", "First Group A v First
            # Group B", "TBC v TBC". One named side is kept (it is a match, waiting on a semi).
            if not home or not away or (PLACEHOLDER_RE.match(home) and PLACEHOLDER_RE.match(away)):
                continue
            time_s = cell(block, "time")
            hs, as_ = parse_score(cell(block, "home_score")), parse_score(cell(block, "away_score"))
            played = feed == "results" or bool(hs and as_ and (hs != (0, 0) or as_ != (0, 0)))
            v = VENUE_RE.search(block)
            venue_id, venue = None, None
            if v:
                venue = text(v.group(2) if v.group(2) is not None else v.group(3))
                attrs = v.group(1) or ""
                u = re.search(r"/venue/[^/]+/([0-9a-f-]{36})/", attrs) or re.search(r"venueID=([0-9a-f-]{36})", attrs)
                venue_id = u.group(1) if u else None
            if venue and (venue.lower() in ("tbc", "tba", "tbd", "n/a", "-") or venue.lower().startswith("to be ")):
                venue, venue_id = None, None
            ref = REF_RE.search(block)
            comp_name, group, round_ = competition_name(comp_raw, place, SPORTS[path.group(1)])
            try:
                hh, mm = (int(x) for x in time_s.split(":")[:2])
                local = dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=IRELAND)
                iso, tbc = local.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"), False
            except ValueError:
                iso, tbc = f"{d.isoformat()}T00:00:00+00:00", True
            rows.append({
                "id": f"club:{site['id']}:{d.isoformat()}:{venue_match._plain(home)}-v-{venue_match._plain(away)}".replace(" ", "-"),
                "date": iso, "time": None if tbc else time_s, "tbc": tbc, "status": "active",
                "sport": SPORTS[path.group(1)],
                "competition": comp_name, "competitionId": None, "rank": None, "title": comp_raw,
                "group": group, "round": round_,
                "home": {"id": None, "name": home}, "away": {"id": None, "name": away},
                "venueId": venue_id, "venue": venue,
                "result": played,
                "score": {"hg": hs[0], "hp": hs[1], "ag": as_[0], "ap": as_[1]} if played and hs and as_ else None,
                "tickets": None, "tv": None,
                "url": site["base"] + href if href.startswith("/") else href or None,
                # What the other sources' rows do not have: which club stage this is, the
                # grade the site files it under, the county whose board published it (also the
                # geocoder's hint for a ground it has not seen), the site, and the referee.
                # A county site lists its clubs' provincial games too ("Leinster Club Senior
                # Football Championship - Round 1" on kildaregaa.ie), which is how Leinster,
                # whose own site cannot be read, gets on the map.
                "club": "provincial" if "province" in site or PLACE_RE.match(comp_name) else "county",
                "grade": path.group(3), "county": site.get("county"), "site": site["id"],
                "referee": text(ref.group(1)) if ref else None,
            })
    return rows


def fetch_site(site):
    rows = []
    for grade in site["grades"]:
        for feed, pages in (("fixtures", MAX_PAGES), ("results", RESULT_PAGES)):
            for page in range(pages):
                url = f"{site['base']}/fixtures-results/?ajax=1&feed_type={feed}&page={page}&size={PAGE_SIZE}&grade={grade}"
                j = fetch_json(url)
                time.sleep(SLEEP)
                if not j.get("ok"):
                    break
                got = parse_cards(j.get("html", ""), site, feed)
                rows += got
                if not j.get("hasMore") or not got or (feed == "results" and all(r["date"][:10] < CUTOFF for r in got)):
                    break
    return rows


def match_key(r):
    return (r["date"][:10], venue_match._plain(r["home"]["name"]), venue_match._plain(r["away"]["name"]))


def rename():
    """Re-derive competition, group and round from the titles stored in the season files,
    without fetching: the way to try a naming fix against every title seen so far."""
    for year in (THIS_YEAR, THIS_YEAR + 1):
        d = data.read(year, "club")
        if not d:
            continue
        for r in d["fixtures"]:
            place = r["county"] or next(s["province"] for s in SITES if s["id"] == r["site"])
            r["competition"], r["group"], r["round"] = competition_name(r["title"], place, r["sport"])
        data.write_source("club", d["fixtures"], d["source"], min_rows=20, fetched=d["fetched"])
        print(f"{year}: {len({r['competition'] for r in d['fixtures']})} competition names over {len(d['fixtures'])} rows")


def main():
    if "--rename" in sys.argv:
        return rename()
    venues = json.load(open(os.path.join(ROOT, "venues.json"), encoding="utf-8"))
    matcher = venue_match.Matcher(venues)
    only = [a for a in sys.argv[1:] if not a.startswith("-")]   # ./fetch_club.py tipperary: one site, the rest kept
    fetched, ok_sites = [], set()
    for site in SITES:
        if only and site["id"] not in only:
            continue
        try:
            rows = fetch_site(site)
        except Exception as ex:  # noqa: BLE001
            print(f"{site['name']}: FAILED ({ex}); its rows from last time are kept", file=sys.stderr, flush=True)
            continue
        ok_sites.add(site["id"])
        n_res = sum(1 for r in rows if r["result"])
        print(f"{site['name']}: {len(rows) - n_res} fixtures, {n_res} results", flush=True)
        fetched += rows
    if not ok_sites:
        sys.exit("no site answered; writing nothing")

    # A ground named in prose (no venue link): the same matching ladies' football uses.
    for r in fetched:
        if r["venue"] and not r["venueId"]:
            vid, _how = matcher.match(r["venue"], r["county"])
            r["venueId"] = vid or ("club-" + re.sub(r"\s+", "-", venue_match._plain(r["venue"]))[:60])

    # Merge with what was written before: results are kept for good, fixtures are whatever
    # the sites say now. Rows from a site that failed today are kept as they were.
    by_year = {}
    for r in fetched:
        by_year.setdefault(data.season_of(r), []).append(r)
    out = []
    for year in (THIS_YEAR, THIS_YEAR + 1):
        # Only this season and, from December, the next: the results feeds reach back into
        # last season, which the map never had, and "12 Apr 2029" is a placeholder in a
        # draw, not a fixture.
        old = (data.read(year, "club") or {"fixtures": []})["fixtures"]
        new = {r["id"]: r for r in by_year.get(year, [])}
        keep = {}
        for r in old:
            if r.get("site") not in ok_sites or (r["result"] and r["id"] not in new):
                keep[r["id"]] = r
        known = set(keep)
        for r in by_year.get(year, []):
            if not r["result"] or r["date"][:10] >= CUTOFF or r["id"] in known:
                keep[r["id"]] = r
        # One match, one row: a county board and its province both list a provincial game,
        # and gaa.ie lists the All-Ireland stages. gaa.ie's row wins (tickets, television),
        # then whichever has a venue.
        gaa = {match_key(r) for r in (data.read(year, "gaa") or {"fixtures": []})["fixtures"]}
        seen = {}
        for r in sorted(keep.values(), key=lambda r: (r["venueId"] is None, r["id"])):
            k = match_key(r)
            if k in gaa or k in seen:
                continue
            seen[k] = r
        out += seen.values()
    if len(out) < 20:
        sys.exit(f"only {len(out)} club fixtures in all; refusing to write (site format may have changed)")
    for year, n in data.write_source("club", out, SOURCE_URL, min_rows=20):
        print(f"{year}: {n} club fixtures and results")


if __name__ == "__main__":
    main()
