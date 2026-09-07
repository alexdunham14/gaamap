#!/usr/bin/env python3
"""Pull the fixture list gaa.ie embeds in its fixtures page and write fixtures.json.

gaa.ie is a Next.js app; the fixtures-results page ships the whole season's match
records inline as React Server Components payload (self.__next_f.push chunks), as
JSON-in-a-string. No API needed. If the page format changes this script breaks and the
site simply keeps serving the last good fixtures.json.
"""
import datetime as dt
import gzip
import json
import os
import re
import sys
import urllib.request

URL = "https://www.gaa.ie/fixtures-results"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")


def rsc_strings(page):
    """Yield the decoded string payloads pushed via self.__next_f.push([1, "..."])."""
    for m in re.finditer(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', page):
        yield json.loads('"' + m.group(1) + '"')


def find_matches(obj, out):
    """Walk any JSON structure and collect dicts that look like match records."""
    if isinstance(obj, dict):
        if "matchId" in obj and "homeTeam" in obj and "matchStartDate" in obj:
            out.append(obj)
        else:
            for v in obj.values():
                find_matches(v, out)
    elif isinstance(obj, list):
        for v in obj:
            find_matches(v, out)


def parse_payload(text):
    """RSC payload lines look like `id:json`. Parse every JSON value we can."""
    found = []
    for line in text.split("\n"):
        i = line.find(":")
        if i < 0:
            continue
        body = line[i + 1:]
        if not body or body[0] not in "[{":
            continue
        try:
            find_matches(json.loads(body), found)
        except json.JSONDecodeError:
            continue
    return found


def slim(m):
    team = lambda t: {"id": t.get("id"), "name": t.get("name")} if isinstance(t, dict) else None
    comp, st, sc, tv = (m.get("competition") or {}), (m.get("stadium") or {}), (m.get("score") or {}), (m.get("tvProvider") or {})
    return {
        "id": m.get("matchId"),
        "date": m.get("matchStartDate"),
        "time": m.get("matchStartTime"),
        "tbc": bool(m.get("isTbc")),
        "status": m.get("status"),
        "sport": (m.get("sport") or {}).get("name"),
        "competition": comp.get("cupName"),
        "competitionId": comp.get("cupId"),
        "rank": comp.get("rank"),
        "group": m.get("groupName"),
        "round": m.get("roundName"),
        "home": team(m.get("homeTeam")),
        "away": team(m.get("awayTeam")),
        "venueId": st.get("stadiumId"),
        "venue": st.get("stadiumName"),
        "result": bool(m.get("isResult")),
        "score": {"hg": sc.get("homeGoals"), "hp": sc.get("homePoints"), "ag": sc.get("awayGoals"), "ap": sc.get("awayPoints")} if m.get("isResult") else None,
        "tickets": m.get("ticketUrl") or None,
        "tv": tv.get("name") or None,
        "url": m.get("url"),
    }


def main():
    page = fetch(URL)
    text = "".join(rsc_strings(page))
    matches = parse_payload(text)
    by_id = {}
    for m in matches:
        by_id.setdefault(m["matchId"], m)
    rows = [slim(m) for m in by_id.values()]
    # Venues gaa.ie leaves blank, found by hand: scripts/venue_overrides.json, keyed by match id.
    opath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venue_overrides.json")
    overrides = json.load(open(opath)) if os.path.exists(opath) else {}
    for r in rows:
        o = overrides.get(r["id"])
        if o:
            r["venueId"], r["venue"] = o["venueId"], o["venue"]
    rows.sort(key=lambda r: (r["date"] or "", r["competition"] or ""))
    if len(rows) < 50:
        sys.exit(f"only {len(rows)} fixtures parsed; refusing to overwrite fixtures.json")
    out = {"fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "source": URL, "fixtures": rows}
    with open("fixtures.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    print(f"{len(rows)} fixtures, {rows[0]['date'][:10]} to {rows[-1]['date'][:10]}")


if __name__ == "__main__":
    main()
