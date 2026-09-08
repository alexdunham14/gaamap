#!/usr/bin/env python3
"""Match a venue written as free text to a venue id already in venues.json.

gaa.ie and camogie.ie both name a venue with the GAA's own UUID, so those two sources
look venues up. ladiesgaelic.ie does not: its rows carry the venue as prose, inside a
"Referee: X * Venue: Y * Time: Z" string, and sometimes in Irish ("Páirc an Chrócaigh").
Matching that text to a ground already on the map is the only way a ladies' football
fixture lands on the same dot as the men's game played at the same ground.

The names really do come from the same stock -- LGFA writes "BOX-IT Athletic Grounds,
Armagh" and "Glenisk O'Connor Park, Tullamore" exactly as gaa.ie does -- so the work is
normalising away the things that vary: naming-rights sponsors, the town appended after a
comma, Eircodes, and the club furniture ("GAA", "GAC", "4G Pitch").

A name is looked up under three keys, strictest first, each against its own index:

    full  the whole name, accents and punctuation folded
    head  the part before the first comma ("Austin Stack Park, Tralee" -> "austin stack park")
    bare  head with the sponsor and the club furniture gone ("Clarecastle GAA 4G Pitch" -> "clarecastle")

Three rules keep this safe rather than merely good:

  * The town after the comma is a disambiguator, not noise. "St Brigid's GAA, Kiltoom"
    and "St Brigid's GAA, Ballinacree" share a head and a bare key and are 120 km apart,
    so two names that both carry a town and disagree about it never match.
  * A match is taken only when the whole candidate set is one ground. Several venue ids
    can share a ground (venues.json marks them with "same"; see merge_venues.py), and that
    is fine. Two ids in two different places is not: "Pearse Park" is a real name in
    several counties, so an ambiguous key is left unmatched.
  * A name that does not match is not forced. It gets its own id, geocode.py places it,
    and merge_venues.py folds it into the existing ground if it lands within 150 m. A
    missed match costs one geocoding query; a wrong match puts a fixture in the wrong
    county, which nothing downstream will catch.
"""
import json
import math
import os
import re
import sys
import unicodedata

# Naming rights change every few seasons and the two sites do not change them together.
SPONSOR_RE = re.compile(
    r"^(Hastings Insurance|SuperValu|FBD|Zimmer Biomet|Cedral|Laois Hire|BOX-IT|"
    r"Glennon Brothers?'?s?|Heartland Credit Union|King & Moffatt|Kingspan|Netwatch|O'Neills|"
    r"TEG|TUS|UPMC|Azzurri|Chadwicks|DEFY|Glenisk|Grant Heating|Cappoquin Logistics|"
    r"Find Insurance|Integral|Protection & Prosperity|Manguard Plus|Cullen Auto Parts|"
    r"MW Hire|Samaritans|AirNav|ZuCar)\s+", re.I)
EIRCODE_RE = re.compile(r"\b[A-Z]{1,2}\d{2}\s?[A-Z0-9]{4}\b")
# Club furniture. Everything here is the kind of word that is present in one source's
# spelling of a ground and absent from the other's; "Park", "Stadium" and "Field" are not.
BOILER_RE = re.compile(
    r"\b(GAA|GAC|CLG|GFC|Club|Clubhouse|Grass Pitch|Main Campus Pitch|Stand Pitch|"
    r"[34]G Pitch|Pitch\s*\d*|Hurling and Camogie|Camogie|Grounds?)\b", re.I)
COUNTY_RE = re.compile(
    r"\b(Antrim|Armagh|Carlow|Cavan|Clare|Cork|Derry|Londonderry|Donegal|Down|Dublin|Fermanagh|"
    r"Galway|Kerry|Kildare|Kilkenny|Laois|Leitrim|Limerick|Longford|Louth|Mayo|Meath|Monaghan|"
    r"Offaly|Roscommon|Sligo|Tipperary|Tyrone|Waterford|Westmeath|Wexford|Wicklow)\b", re.I)
LEVELS = ("exact", "head", "bare")
NEAR_M = 150  # the radius merge_venues.py already treats as one ground


def _plain(s):
    """Accents folded, punctuation dropped, spaces collapsed. Both sides get the same
    treatment, so folding never merges two names that were really different. The two
    abbreviations the sources disagree on are spelt out the short way."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\bfather\b", "fr", s)
    s = re.sub(r"\b(coe|c of excel)\b", "centre of excellence", s)
    s = re.sub(r"\bsaints?\b", lambda m: "sts" if m.group(0).endswith("s") else "st", s)
    return re.sub(r"\s+", " ", s).strip()


def _clean(name):
    """The name with the things neither source spells consistently taken out."""
    n = EIRCODE_RE.sub(" ", name or "")
    return re.sub(r"\(([^)]*)\)", r" \1 ", n)   # "(3G Pitch)" is furniture, not a second name


def keys(name):
    """[full, head, bare] -- one key per index, in the same three slots every time.
    A slot is None when the name gives nothing usable for it; slots are never collapsed
    together, because a name whose head equals its full name still has to be findable
    by another name's head."""
    if not name:
        return [None, None, None]
    n = _clean(name)
    head_text = n.split(",")[0]
    bare = _plain(BOILER_RE.sub(" ", SPONSOR_RE.sub("", head_text.strip())))
    # A bare key that has come down to a county name ("Louth GAA Training Centre" -> "louth")
    # or to almost nothing is too generic to be evidence of anything.
    if len(bare) < 4 or COUNTY_RE.fullmatch(bare):
        bare = None
    return [_plain(n) or None, _plain(head_text) or None, bare]


def tail(name):
    """What follows the first comma, normalised: the town, usually. '' when there is none."""
    n = _clean(name)
    return _plain(n.split(",", 1)[1]) if "," in n else ""


def _metres(a, b):
    dy = (a["lat"] - b["lat"]) * 111_000
    dx = (a["lon"] - b["lon"]) * 111_000 * math.cos(math.radians(a["lat"]))
    return math.hypot(dx, dy)


def county_of(v):
    """The county a geocoded venue actually sits in, read back out of Nominatim's answer."""
    m = COUNTY_RE.search(v.get("matched") or "")
    if not m:
        return v.get("hint")
    c = m.group(1).title()
    return "Derry" if c == "Londonderry" else c


class Matcher:
    def __init__(self, venues):
        self.venues = venues
        self.index = [{}, {}, {}]
        self.tails = {}
        for vid, v in venues.items():
            self.tails[vid] = tail(v.get("name"))
            for level, k in enumerate(keys(v.get("name"))):
                if k:
                    self.index[level].setdefault(k, set()).add(vid)

    def canonical(self, vid):
        seen = set()
        while self.venues.get(vid, {}).get("same") and vid not in seen:
            seen.add(vid)
            vid = self.venues[vid]["same"]
        return vid

    def _towns_agree(self, want, vid):
        """Two names that each name a town have to name the same one. A name with no town
        agrees with everything: LGFA writes "Austin Stack Park" for gaa.ie's "Austin Stack
        Park, Tralee", and there is only one."""
        got = self.tails.get(vid, "")
        return not (want and got) or want == got or want in got or got in want

    def _one_ground(self, ids):
        """Do these venue ids name a single ground? Either they already point at one
        canonical id, or every placed one sits inside merge_venues.py's radius."""
        canon = {self.canonical(i) for i in ids}
        if len(canon) == 1:
            return next(iter(canon))
        placed = [(i, self.venues[i]) for i in canon if self.venues.get(i, {}).get("lat") is not None]
        if len(placed) != len(canon) or not placed:
            return None
        a = placed[0][1]
        if any(_metres(a, v) > NEAR_M for _, v in placed[1:]):
            return None
        return placed[0][0]

    def match(self, name, county=None):
        """(venue id, how) for a name already on the map, else (None, why not)."""
        want = tail(name)
        why = "unknown"
        for level, k in enumerate(keys(name)):
            if not k:
                continue
            ids = {i for i in self.index[level].get(k, ()) if self._towns_agree(want, i)}
            if not ids:
                continue
            vid = self._one_ground(ids)
            if vid:
                return vid, LEVELS[level]
            # The same name in more than one place. A county hint can only break the tie,
            # never make the match: for a neutral venue the hint is the home team's county,
            # which is often not where the ground is.
            here = {i for i in ids if county and county_of(self.venues[i]) == county}
            vid = self._one_ground(here) if here else None
            if vid:
                return vid, LEVELS[level] + "+county"
            why = f"ambiguous: {len(ids)} grounds spelt {k!r}"
        return None, why


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    m = Matcher(json.load(open(os.path.join(here, "venues.json"), encoding="utf-8")))
    for line in sys.stdin:
        name = line.strip()
        if name:
            vid, how = m.match(name)
            print(f"{how:34s} {name}  ->  {m.venues[vid]['name'] if vid else ''}")
