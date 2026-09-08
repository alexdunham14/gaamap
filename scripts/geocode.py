#!/usr/bin/env python3
"""Geocode every venue in the fixture files once, into venues.json. Hand-fix venues.json afterwards;
this script never overwrites an entry that already has coordinates unless --force.

Uses Nominatim (OpenStreetMap), one request per second as its policy requires. The county
hint comes from the home team when the home team is a county, which is most inter-county
fixtures and resolves the many duplicate ground names (two Cusack Parks, several Pearse Parks).
"""
import collections
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data  # noqa: E402

UA = "gaamap/1.0 (github.com/alexdunham14/gaamap)"
COUNTIES = {
    "Antrim", "Armagh", "Carlow", "Cavan", "Clare", "Cork", "Derry", "Donegal", "Down", "Dublin", "Fermanagh",
    "Galway", "Kerry", "Kildare", "Kilkenny", "Laois", "Leitrim", "Limerick", "Longford", "Louth", "Mayo", "Meath",
    "Monaghan", "Offaly", "Roscommon", "Sligo", "Tipperary", "Tyrone", "Waterford", "Westmeath", "Wexford", "Wicklow",
}
ABROAD = {"London": "London, UK", "Lancashire": "Lancashire, UK", "New York": "New York, USA", "Warwickshire": "Warwickshire, UK"}
IRELAND = {"south": 51.3, "north": 55.5, "west": -10.8, "east": -5.3}
# The one county with two names in common use, and the one Nominatim answers to.
ALIASES = {"Derry": ("Derry", "Londonderry")}
# Eircodes ("A82 Y942", "W91WN82") ride along in camogie.ie's venue names. Nominatim cannot
# match them and they poison every query they appear in, so they come out before searching.
EIRCODE_RE = re.compile(r"\b[A-Z]\d{2}\s?[A-Z0-9]{4}\b")
# Club grounds are mostly a place name wrapped in boilerplate: "Ballinamere GAA Club",
# "Edendork St. Malachy's GAC", "Fethard Town Park (Grass Pitch)", "Hawkfield Kildare C of
# Excel". Nominatim knows the places, not the boilerplate, so the stripped name is tried too.
BOILER_RE = re.compile(
    r"\b(GAA|GAC|CLG|GFC|Club|Centre of Excellence|C of Excel|CoE|Grass Pitch|Main Campus Pitch|"
    r"Stand Pitch|[34]G Pitch|Pitch\s*\d*|Hurling and Camogie|Camogie|Grounds?)\b", re.I)


def county_matches(hit, county):
    """Does this result actually sit in the county we expected? Nominatim will happily
    answer "Crinkill GAA, Offaly" with a ground in Galway, and a dot in the wrong county is
    worse than no dot: a miss gets printed and hand-fixed, a wrong hit looks right."""
    where = hit.get("display_name", "")
    return any(re.search(rf"\b{re.escape(n)}\b", where, re.I) for n in ALIASES.get(county, (county,)))


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
    fixtures = data.all_fixtures()
    venues = json.load(open("venues.json")) if os.path.exists("venues.json") else {}
    mpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venue_queries.json")
    manual = json.load(open(mpath)) if os.path.exists(mpath) else {}
    hints = {}
    for f in fixtures:
        vid, home = f["venueId"], (f["home"] or {}).get("name", "")
        # ladiesgaelic.ie leaves the venue out of some rows altogether. A fixture with no
        # venue has nothing to geocode and must not become a "null" entry in venues.json.
        if not vid:
            continue
        hints.setdefault(vid, {"name": f["venue"], "counties": collections.Counter(), "abroad": set()})
        if home in COUNTIES:
            hints[vid]["counties"][home] += 1
        if home in ABROAD:
            hints[vid]["abroad"].add(ABROAD[home])
    for vid, h in hints.items():
        v = venues.setdefault(vid, {"name": h["name"]})
        name = h["name"]
        if not name:
            print("skip venue with no name", vid, flush=True)
            continue
        # A venue_queries.json entry can be a string instead of a list of queries: a note
        # saying no query for this ground is trustworthy, so leave it off the map. Some
        # grounds are in villages Nominatim has never heard of, and its nearest answer is
        # a street somewhere else named after the same place. Checked before the
        # already-placed test, so writing the note also takes back a bad earlier hit.
        note = manual.get(name) if isinstance(manual.get(name), str) else None
        if note:
            if v.get("lat") is not None or "why" not in v:
                v.update({"lat": None, "lon": None, "hint": None, "why": note})
                print("SKIP", name, "--", note[:60], flush=True)
            continue
        if v.get("lat") is not None and not force:
            continue
        region = next(iter(h["abroad"]), None)
        # The county a ground most often hosts, not only the unanimous case: a club ground
        # that took one neutral fixture still belongs to its own county.
        county = h["counties"].most_common(1)[0][0] if h["counties"] else None
        # Variants of the name: as given, with sponsor words dropped from the front, the part after a
        # comma, the part inside parentheses.
        listed = name  # as the source spells it, which is how venue_queries.json is keyed
        name = EIRCODE_RE.sub("", name).replace(" ,", ",").strip(" ,.")
        words = name.split()
        variants = [name] + [" ".join(words[k:]) for k in range(1, min(4, len(words) - 1))]
        stripped = re.sub(r"[\s,]+", " ", BOILER_RE.sub(" ", name)).strip(" ,-")
        if stripped and stripped != name:
            variants.insert(1, stripped)
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
        trusted = manual.get(listed) or manual.get(name, [])
        queries = trusted + [q for q in queries if q not in trusted][:8]
        hit, used = None, None
        for q in queries:
            try:
                hit = nominatim(q)
            except Exception as ex:  # noqa: BLE001
                print("error", q, ex, file=sys.stderr)
                continue
            if hit and (q in trusted or region or (in_ireland(hit) and (not county or county_matches(hit, county)))):
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
