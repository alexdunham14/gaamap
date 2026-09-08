#!/usr/bin/env python3
"""Pull camogie inter-county fixtures/results from camogie.ie into camogie.json,
in the same record shape fetch.py writes for gaa.ie (sport: "Camogie").

camogie.ie is a WordPress site (theme "camogie_association") whose fixtures-results
page renders match rows server-side and loads more of them via an undocumented
paginated AJAX endpoint behind its "Load more" button (found by reading the page's
inline <script>, not a documented API):

    GET https://camogie.ie/fixtures-results/?ajax=1&feed_type=results|fixtures
        &page=N&size=50&sport=camogie&level=inter_county
    -> {"ok": true, "hasMore": bool, "html": "<...match rows as HTML...>"}

The "html" value is a fragment of the same markup the page itself renders: a
<h3 class="fix_res_date">DATE</h3> heading followed by one <div class="competition">
block per match (competition name + round, home/away team + score, throw-in time,
venue name, and a venueID). This script regex-parses that fragment the same way
fetch.py regex-walks gaa.ie's React payload: no official API, so if the camogie.ie
theme changes this breaks loudly and produces nothing usable.

Notably: camogie.ie's venueID values are the *same* GAA venue UUIDs gaa.ie uses
(e.g. Croke Park is 5c72d530-e7a7-4106-a9bf-64c67109a0ad on both sites) -- the two
associations share a venue database. So venues.json can be reused as-is; no separate
camogie geocoding pass is needed except for venues gaa.ie has never listed.

Only inter-county fixtures/results (level=inter_county) from the current calendar
year are kept, matching the window gaa.ie's own fetch.py effectively captures.

Times need converting: camogie.ie prints a bare Irish wall-clock time with no zone,
so a throw-in is read in Europe/Dublin and written as the UTC instant fetch.py gets
from gaa.ie for free. Getting this wrong puts every summer match an hour out.
"""
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

BASE = "https://camogie.ie/fixtures-results/"
OUT = "camogie.json"
IRELAND = ZoneInfo("Europe/Dublin")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
PAGE_SIZE = 50
MAX_PAGES = 20  # safety cap per feed
SLEEP = 1.0

THIS_YEAR = dt.datetime.now(dt.timezone.utc).year

DATE_SPLIT_RE = re.compile(r'<h3 class="fix_res_date[^"]*"[^>]*>\s*([^<]+?)\s*</h3>')
ORDINAL_RE = re.compile(r"(\d+)(st|nd|rd|th)\b")
MATCH_RE = re.compile(
    r'<div class="competition-name[^"]*"[^>]*>\s*<a href="([^"]*)">\s*([^<]+?)\s*</a>.*?'
    r'<div class="home_team[^"]*"[^>]*>.*?<a[^>]*>\s*([^<]+?)\s*</a>.*?'
    r'<div class="home_score[^"]*"[^>]*>\s*([^<]+?)\s*</div>.*?'
    r'<div class="time[^"]*"[^>]*>\s*([^<]+?)\s*</div>.*?'
    r'<div class="away_score[^"]*"[^>]*>\s*([^<]+?)\s*</div>.*?'
    r'<div class="away_team[^"]*"[^>]*>.*?<a[^>]*>\s*([^<]+?)\s*</a>'
    r'(?:.*?<strong>Venue:</strong>\s*<a[^>]*data-parmaters="[^"]*venueID=([^&"]*)[^"]*"[^>]*>\s*([^<]+?)\s*</a>)?',
    re.S,
)


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def text(s):
    """Markup text as it should read: entities decoded, whitespace collapsed.
    camogie.ie writes apostrophes as &#039;, which geocodes badly and looks worse."""
    return re.sub(r"\s+", " ", html.unescape(s)).strip() if s else s


def parse_date(s):
    s = ORDINAL_RE.sub(r"\1", s.strip())
    return dt.datetime.strptime(s, "%A %d %b %Y").date()


def parse_score(s):
    m = re.match(r"(\d+)-(\d+)", s.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


# camogie.ie's competition names are typed by hand and drift: "Div 1 B National League"
# beside "Div 1A National League", a trailing full stop on 20 of the 22 U16C rows, a round
# ("Finals", "Quarter Final") pasted onto the end of the name, "Under 23A" for "U23A", and
# "All-Ireland" present or absent. Left alone they split one competition across several
# entries in the site's competition menu and its guide. Canonicalise to one spelling each.
ROUND_SUFFIX_RE = re.compile(r"\s+((?:Quarter|Semi)[- ]?Finals?|Finals?)$", re.I)


def canonical_competition(comp, round_):
    """One spelling per competition. Returns (competition, round), moving a round that was
    pasted onto the name into the round field when the row has none of its own."""
    c = comp.strip().rstrip(".").strip()
    m = ROUND_SUFFIX_RE.search(c)
    if m:
        c = c[: m.start()].strip()
        if not round_:
            r = m.group(1).title().replace("-", " ")
            round_ = "Final" if r in ("Final", "Finals") else r.replace("Final", " Final").replace("  ", " ")
    c = re.sub(r"\bAll-Ireland\s+", "", c)              # every row here is the All-Ireland series
    c = re.sub(r"\bUnder\s*(\d+)", r"U\1", c, flags=re.I)  # "Under 23A" -> "U23A"
    c = re.sub(r"\b(U\d+)\s+([A-C])\b", r"\1\2", c)      # "U16 A" -> "U16A"
    c = re.sub(r"\bDiv\s*(\d)\s*([AB])\b", r"Div \1\2", c)  # "Div 1 B" -> "Div 1B"
    if not re.search(r"\b(Championship|League|Cup|Shield)\b", c, re.I):
        c += " Championship"                              # "U23A" -> "U23A Championship"
    return re.sub(r"\s+", " ", c).strip(), round_


# Rounds are typed by hand too: "R1" beside "Round 1", four spellings of semi-final,
# "FINAL", and the grade repeated ("'A' Championship Final") when the competition already
# says it. One spelling each, so the fixture lines read consistently.
ROUND_FIXES = [
    (r"^R\s*(\d+)$", r"Round \1"),
    (r"[\u2018\u2019'\"]([ABC])[\u2018\u2019'\"]\s+Championship\s+", ""),
    (r"^Final\s*\((Cup|Shield)\)$", r"\1 Final"),
    (r"\bfinal\b", "Final"),
    (r"\bquarter[\s-]?Final\b", "Quarter-final"),
    (r"\bsemi[\s-]?Final\b", "Semi-final"),
    (r"\bplay\s*-?\s*off\b", "play-off"),
]


def normalize_round(r):
    if not r:
        return r
    r = re.sub(r"\s+", " ", r.strip())
    for pat, rep in ROUND_FIXES:
        r = re.sub(pat, rep, r, flags=re.I)
    return r[:1].upper() + r[1:]


def split_competition(raw):
    """'Comp - Group 1 - Round 3' -> (comp, group, round); 'Comp - Final' -> (comp, None, round)."""
    parts = [p.strip() for p in re.split(r"\s+-\s+", raw.strip()) if p.strip()]
    if not parts:
        return raw.strip(), None, None
    comp = parts[0]
    if len(parts) == 1:
        return comp, None, None
    if len(parts) == 2:
        return comp, None, parts[1]
    return comp, parts[1], parts[-1]


def competition_id_from_href(href):
    # .../camogie/inter_county/senior/glen-dimplex-senior-championship/<uuid>/
    if not href:
        return None
    segs = [s for s in href.split("/") if s]
    return segs[-1] if segs else None


def parse_fragment(html, is_result):
    rows = []
    parts = DATE_SPLIT_RE.split(html)
    # parts[0] is any preamble before the first date heading (ignored)
    for i in range(1, len(parts), 2):
        date_str, content = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        try:
            match_date = parse_date(date_str)
        except ValueError:
            continue
        for block in content.split('<div class="competition">')[1:]:
            m = MATCH_RE.search(block)
            if not m:
                continue
            href, comp_raw, home, hscore_s, time_s, ascore_s, away, venue_id, venue = m.groups()
            href, comp_raw, home, away, venue = (text(x) for x in (href, comp_raw, home, away, venue))
            comp, group, round_ = split_competition(comp_raw)
            comp, round_ = canonical_competition(comp, round_)
            round_ = normalize_round(round_)
            hscore, ascore = (parse_score(hscore_s), parse_score(ascore_s)) if is_result else (None, None)
            time_s = time_s.strip() if time_s else None
            try:
                hh, mm = (int(x) for x in time_s.split(":")[:2])
                # The printed time is Irish wall clock with no zone marker. Read it in
                # Europe/Dublin and store the UTC instant, so summer throw-ins are not an
                # hour out against gaa.ie's rows, which already arrive as instants.
                local = dt.datetime(match_date.year, match_date.month, match_date.day, hh, mm, tzinfo=IRELAND)
                iso = local.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
            except (ValueError, AttributeError):
                iso = f"{match_date.isoformat()}T00:00:00+00:00"
            rows.append(
                {
                    "id": None,  # filled in by caller once we know the whole set (no stable id in the markup)
                    "date": iso,
                    "time": time_s,
                    "tbc": time_s is None,
                    "status": "active",
                    "sport": "Camogie",
                    "competition": comp,
                    "competitionId": competition_id_from_href(href),
                    "rank": None,
                    "group": group,
                    "round": round_,
                    "home": {"id": None, "name": home.strip() if home else None},
                    "away": {"id": None, "name": away.strip() if away else None},
                    "venueId": venue_id or None,
                    "venue": venue.strip() if venue else None,
                    "result": bool(is_result),
                    "score": {"hg": hscore[0], "hp": hscore[1], "ag": ascore[0], "ap": ascore[1]} if (hscore and ascore) else None,
                    "tickets": None,
                    "tv": None,
                    "url": f"https://camogie.ie{href}" if href else None,
                }
            )
    return rows


def fetch_feed(feed_type):
    is_result = feed_type == "results"
    out = []
    page = 0
    stale_pages = 0
    while page < MAX_PAGES:
        url = f"{BASE}?ajax=1&feed_type={feed_type}&page={page}&size={PAGE_SIZE}&sport=camogie&level=inter_county"
        data = fetch_json(url)
        if not data.get("ok"):
            break
        rows = parse_fragment(data.get("html", ""), is_result)
        current_year_rows = [r for r in rows if r["date"][:4] == str(THIS_YEAR)]
        out.extend(current_year_rows)
        if not current_year_rows:
            stale_pages += 1
        else:
            stale_pages = 0
        if not data.get("hasMore") or stale_pages >= 2:
            break
        page += 1
        time.sleep(SLEEP)
    return out


def main():
    rows = fetch_feed("results")
    time.sleep(SLEEP)
    rows += fetch_feed("fixtures")
    if len(rows) < 20:
        sys.exit(f"only {len(rows)} camogie fixtures parsed; refusing to write output (site format may have changed)")
    # synthesize a stable-ish id since the markup carries none
    seen = {}
    for r in rows:
        key = "|".join(
            str(x) for x in (r["date"], r["competition"], r["round"], r["home"]["name"], r["away"]["name"])
        )
        n = seen.get(key, 0)
        seen[key] = n + 1
        r["id"] = f"camogie:{key}" + (f"#{n}" if n else "")
    rows.sort(key=lambda r: (r["date"] or "", r["competition"] or ""))
    out = {
        "fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": BASE,
        "fixtures": rows,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    print(f"{len(rows)} camogie fixtures, {rows[0]['date'][:10]} to {rows[-1]['date'][:10]}")


if __name__ == "__main__":
    main()
