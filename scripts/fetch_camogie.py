#!/usr/bin/env python3
"""Prototype: pull camogie inter-county fixtures/results from camogie.ie and write
them in gaamap's fixtures.json record shape (sport: "Camogie").

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
"""
import datetime as dt
import json
import re
import sys
import time
import urllib.request

BASE = "https://camogie.ie/fixtures-results/"
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


def parse_date(s):
    s = ORDINAL_RE.sub(r"\1", s.strip())
    return dt.datetime.strptime(s, "%A %d %b %Y").date()


def parse_score(s):
    m = re.match(r"(\d+)-(\d+)", s.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


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
            comp, group, round_ = split_competition(comp_raw)
            hscore, ascore = (parse_score(hscore_s), parse_score(ascore_s)) if is_result else (None, None)
            time_s = time_s.strip() if time_s else None
            try:
                hh, mm = (int(x) for x in time_s.split(":")[:2])
                # camogie.ie times are printed in Irish local time with no zone marker;
                # treat as UTC here (a real integration needs an Europe/Dublin -> UTC
                # conversion, same problem fetch.py's gaa.ie times don't have since
                # gaa.ie already gives an ISO instant).
                iso = dt.datetime(match_date.year, match_date.month, match_date.day, hh, mm, tzinfo=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
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
    out_path = "/tmp/claude-1000/-home-alex-projects-small-project-builder/aeeeb495-2b43-4b8a-ac78-ba117cb9b943/scratchpad/camogie.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    print(f"{len(rows)} fixtures -> {out_path}")


if __name__ == "__main__":
    main()
