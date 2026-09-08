#!/usr/bin/env python3
"""Mark venues that are the same ground under different gaa.ie stadium ids.

gaa.ie gives the one ground several ids ("Brewster Park" and "Brewster Park, Enniskillen";
"Croke Park" and "Páirc an Chrócaigh"; the hurling and football fixtures often use different
ones), so the map drew dots on top of dots. Any two geocoded venues within RADIUS_M of each
other are taken to be the same ground: the one with the most fixtures (longest name on a tie)
is the canonical one and the others get "same": <canonical id>. app.js groups by that.

An existing "same" is never changed and an existing canonical is never demoted, so a hand
edit of venues.json (a near-duplicate outside the radius, or a better choice of name) sticks;
a new id that lands in an old group simply points at the old canonical.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data  # noqa: E402

RADIUS_M = 150


def main():
    venues = json.load(open("venues.json"))
    fixtures = data.all_fixtures()
    counts = {}
    for f in fixtures:
        counts[f["venueId"]] = counts.get(f["venueId"], 0) + 1
    placed = [(vid, v) for vid, v in venues.items() if v.get("lat") is not None]

    def near(a, b):
        dy = (a["lat"] - b["lat"]) * 111_000
        dx = (a["lon"] - b["lon"]) * 111_000 * math.cos(math.radians(a["lat"]))
        return math.hypot(dx, dy) <= RADIUS_M

    # Union-find over proximity, plus every existing "same" link.
    parent = {vid: vid for vid in venues}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for vid, v in venues.items():
        if v.get("same") in venues:
            union(vid, v["same"])
    for i, (a, va) in enumerate(placed):
        for b, vb in placed[i + 1:]:
            if near(va, vb):
                union(a, b)

    groups = {}
    for vid in venues:
        groups.setdefault(find(vid), []).append(vid)
    changed = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        existing = {venues[m]["same"] for m in members if venues[m].get("same") in venues}
        if existing:
            canonical = next(iter(existing))
        else:
            canonical = max(members, key=lambda m: (counts.get(m, 0), len(venues[m].get("name") or "")))
        for m in members:
            if m == canonical:
                if venues[m].pop("same", None) is not None:
                    changed += 1
            elif venues[m].get("same") != canonical:
                venues[m]["same"] = canonical
                changed += 1
        print(f"{venues[canonical]['name']}  <-  " + "; ".join(venues[m]["name"] or "?" for m in members if m != canonical))
    json.dump(dict(sorted(venues.items(), key=lambda kv: kv[1].get("name") or "")), open("venues.json", "w"), ensure_ascii=False, indent=1)
    print(f"{sum(len(g) for g in groups.values() if len(g) > 1)} venue ids in {sum(1 for g in groups.values() if len(g) > 1)} merged grounds, {changed} entries changed")


if __name__ == "__main__":
    main()
