#!/usr/bin/env python3
"""Geocode every venue in fixtures.json once, into venues.json. Hand-fix venues.json afterwards;
this script never overwrites an entry that already has coordinates unless --force.

Uses Nominatim (OpenStreetMap), one request per second as its policy requires. The county
hint comes from the home team when the home team is a county, which is most inter-county
fixtures and resolves the many duplicate ground names (two Cusack Parks, several Pearse Parks).
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

UA = "gaamap/1.0 (github.com/alexdunham14/gaamap)"
COUNTIES = {
    "Antrim", "Armagh", "Carlow", "Cavan", "Clare", "Cork", "Derry", "Donegal", "Down", "Dublin", "Fermanagh",
    "Galway", "Kerry", "Kildare", "Kilkenny", "Laois", "Leitrim", "Limerick", "Longford", "Louth", "Mayo", "Meath",
    "Monaghan", "Offaly", "Roscommon", "Sligo", "Tipperary", "Tyrone", "Waterford", "Westmeath", "Wexford", "Wicklow",
}
ABROAD = {"London": "London, UK", "Lancashire": "Lancashire, UK", "New York": "New York, USA", "Warwickshire": "Warwickshire, UK"}
IRELAND = {"south": 51.3, "north": 55.5, "west": -10.8, "east": -5.3}


def nominatim(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q, "format": "jsonv2", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    time.sleep(1.1)
    return res[0] if res else None


def in_ireland(hit):
    lat, lon = float(hit["lat"]), float(hit["lon"])
    return IRELAND["south"] <= lat <= IRELAND["north"] and IRELAND["west"] <= lon <= IRELAND["east"]


def main():
    force = "--force" in sys.argv
    fixtures = json.load(open("fixtures.json"))["fixtures"]
    venues = json.load(open("venues.json")) if os.path.exists("venues.json") else {}
    mpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venue_queries.json")
    manual = json.load(open(mpath)) if os.path.exists(mpath) else {}
    hints = {}
    for f in fixtures:
        vid, home = f["venueId"], (f["home"] or {}).get("name", "")
        hints.setdefault(vid, {"name": f["venue"], "counties": set(), "abroad": set()})
        if home in COUNTIES:
            hints[vid]["counties"].add(home)
        if home in ABROAD:
            hints[vid]["abroad"].add(ABROAD[home])
    for vid, h in hints.items():
        v = venues.setdefault(vid, {"name": h["name"]})
        if v.get("lat") is not None and not force:
            continue
        name = h["name"]
        if not name:
            print("skip venue with no name", vid, flush=True)
            continue
        region = next(iter(h["abroad"]), None)
        county = next(iter(h["counties"]), None) if len(h["counties"]) == 1 else None
        # Variants of the name: as given, with sponsor words dropped from the front, the part after a
        # comma, the part inside parentheses.
        words = name.split()
        variants = [name] + [" ".join(words[k:]) for k in range(1, min(4, len(words) - 1))]
        if "," in name:
            variants.append(name.split(",", 1)[1].strip())
        if "(" in name and ")" in name:
            variants.append(name[name.index("(") + 1:name.index(")")].strip())
            variants.append(name[:name.index("(")].strip())
        variants = [x for i, x in enumerate(variants) if x and x not in variants[:i]]
        queries = []
        for var in variants:
            if region:
                queries.append(f"{var}, {region}")
            elif county:
                queries.append(f"{var}, County {county}, Ireland")
            else:
                queries.append(f"{var} GAA, Ireland")
        queries += [f"{var}, Ireland" for var in variants]
        trusted = manual.get(name, [])
        queries = trusted + [q for q in queries if q not in trusted][:8]
        hit, used = None, None
        for q in queries:
            try:
                hit = nominatim(q)
            except Exception as ex:  # noqa: BLE001
                print("error", q, ex, file=sys.stderr)
                continue
            if hit and (q in trusted or region or in_ireland(hit)):
                used = q
                break
            hit = None
        if hit:
            v.update({"lat": round(float(hit["lat"]), 5), "lon": round(float(hit["lon"]), 5),
                      "query": used, "matched": hit.get("display_name", "")[:120], "hint": county or region})
            print("ok  ", name, "->", hit.get("display_name", "")[:80], flush=True)
        else:
            v.update({"lat": None, "lon": None, "hint": county or region})
            print("MISS", name, flush=True)
        json.dump(dict(sorted(venues.items(), key=lambda kv: kv[1].get("name") or "")), open("venues.json", "w"), ensure_ascii=False, indent=1)
    json.dump(dict(sorted(venues.items(), key=lambda kv: kv[1].get("name") or "")), open("venues.json", "w"), ensure_ascii=False, indent=1)
    missing = [v["name"] for v in venues.values() if v.get("lat") is None]
    print(f"{len(venues)} venues, {len(missing)} missing: {missing}")


if __name__ == "__main__":
    main()
