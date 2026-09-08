# GAA Map

Live at https://gaamatchmap.com (gaamap.alexdunham14.workers.dev also serves it; .ie is not on Cloudflare Registrar).

Every inter-county fixture gaa.ie, camogie.ie and ladiesgaelic.ie list, on a map
of Ireland, filterable by season, date, sport, and competition. For the traveller
who wants to know what is on near them next week.

## Definition of done

- A static page: map with a point per venue sized by the level of the best match
  there and coloured by the game played, and a plain list by day underneath. Filters for date range
  (with presets for the coming weeks and each month of the season),
  football/hurling/camogie/ladies' football, level, competition, team, and whether
  to include played matches. Results show the score with the points total. A dot's
  popup lists the matches at that ground one block at a time, each with a link down
  to the same match in the day-by-day list.
- Colour is the game, not the association: camogie shares hurling's colour and
  ladies' football shares football's, so the third colour keeps meaning "more than
  one game at this ground" instead of multiplying with every code added.
- Seasons accumulate rather than replace. Each source writes one file per season it
  saw, `data/seasons.json` indexes them, and the site opens on the newest and
  downloads only that one. A finished season is never overwritten by the next.
- The season's shape is visible: every competition is classified into a level
  (senior championship, national league, under-23, under-20, under-18, minor,
  under-16, under-14, third level, club, schools) and,
  where the level has them, a tier (Sam Maguire down to the junior
  championship, Liam MacCarthy down to Lory Meagher, league divisions, and the
  lettered minor, under-20, under-23 and under-16 grades). A "what is in here" guide lists them with counts, and
  the competition menu is grouped the same way. The classification is by name
  in `app.js`, so a new competition still lands somewhere.
- Data refreshed weekly by a scheduled workflow that fetches all three sites and
  commits the season files. If a site changes its page format, that fetch fails
  loudly, writes nothing, and the site keeps serving the last good data.
- Venues geocoded once into `venues.json`, hand-corrected where the geocoder
  guessed wrong. New venues get geocoded on the next refresh and flagged.

Out of scope: club fixtures below the All-Ireland stages (those live on county
board sites, not gaa.ie), historical data, results analysis.

ladiesgaelic.ie publishes every season back to 2016 and the fetch will take them
(`--since 2016`), but only the current season is on the site: the other two sources
have no archive at all, so an earlier season would be ladies' football on its own,
and each one adds a few dozen club grounds to geocode.

## How it works

- `scripts/data.py` decides where fixtures live: one file per source per season
  (`data/2026-gaa.json`, `data/2026-camogie.json`, `data/2026-ladies.json`), plus
  `data/seasons.json` indexing them. A season is a calendar year. Each fetch writes
  only the seasons it actually saw, so when gaa.ie replaces the 2026 fixtures with
  2027 on their page, the 2026 file here is simply not written again and stays as
  the record of that season. Each script owns exactly one source, so none can
  clobber another and the site still draws if one is stale.
- `scripts/fetch.py` pulls the fixtures page and extracts the match records
  gaa.ie embeds in it as React Server Components payload. Output: `data/<year>-gaa.json`.
- `scripts/fetch_camogie.py` pulls inter-county camogie from camogie.ie, whose
  fixtures page loads match rows as HTML through an undocumented paginated
  endpoint behind its "Load more" button. Output: `data/<year>-camogie.json`. Two things it
  has to fix that gaa.ie gives for free: throw-in times print as bare Irish wall
  clock, so they are read in Europe/Dublin and stored as UTC instants, and both
  competition and round names are typed by hand and drift ("Div 1 B National
  League" beside "Div 1A National League", four spellings of semi-final), so
  they are canonicalised to one spelling each. camogie.ie uses the same venue
  UUIDs as gaa.ie — the two associations share a venue database — so
  `venues.json` is a direct lookup.
- `scripts/fetch_ladies.py` pulls ladies' football from ladiesgaelic.ie, whose
  results and fixtures pages render every row server-side in one request (the
  year/competition menus on the page filter markup that is already there, so there
  is no endpoint to page through). Output: `data/<year>-ladies.json`. Its two hard
  parts: the competition name is split across three fields and none of them is the
  whole name, and the venue is prose rather than a UUID.
- `scripts/venue_match.py` is that venue name matching. LGFA writes venues the way
  gaa.ie does — "BOX-IT Athletic Grounds, Armagh", or the Irish "Páirc an
  Chrócaigh" for Croke Park — so a name is looked up under three keys of
  decreasing strictness: the whole name, the part before the comma, and that with
  the sponsor and the club furniture ("GAA", "4G Pitch") removed. It is built to
  miss rather than to guess: a town after a comma is a disambiguator, not noise
  (St Brigid's, Kiltoom is not St Brigid's, Ballinacree), and a key that resolves
  to two grounds in two places is left unmatched. An unmatched name gets an
  `lgfa-` id of its own, geocode.py places it, and merge_venues.py folds it into
  the existing ground if it lands within 150 m — so a miss costs one geocoding
  query, where a wrong match would put a fixture in the wrong county silently.
- `scripts/geocode.py` fills `venues.json` for any venue without coordinates,
  using Nominatim with a county hint taken from the home team. Never overwrites
  a venue that already has coordinates, so hand fixes stick.
- `scripts/venue_queries.json` is the hand-written half of that: a venue name mapped
  to the queries to try first, for the grounds Nominatim answers badly (it put Mallow
  GAA in Killarney and Páirc Chiaráin in Cavan). An entry may instead be a *string*, a
  note saying no query for this ground is trustworthy and it is to be left off the map:
  Nominatim has no Glenfin in Donegal, only a street named after it 8 km away in
  Stranorlar, and a dot there would be worse than no dot. That check runs before the
  already-placed one, so writing a note also takes back an earlier bad hit.
- `scripts/venue_overrides.json` names the venue for matches gaa.ie lists with
  none, keyed by match id and applied by `fetch.py` on every refresh; the
  venue gets a hand-placed entry in `venues.json` under a `manual-` id.
- `scripts/merge_venues.py` marks the venue ids that are one ground under
  different gaa.ie names ("Croke Park" and "Páirc an Chrócaigh"; hurling and
  football often use different ids) with `"same": <canonical id>`, taking any
  two geocoded venues within 150 m to be the same ground. Existing `same`
  entries are kept, so a hand edit (a near-duplicate further apart, or a
  better choice of name) sticks. The map groups fixtures by the canonical id.
- `index.html`, `styles.css`, `app.js`: the site. Leaflet from cdnjs, tiles
  from OpenStreetMap. No build step.

## Refresh by hand

```
./scripts/fetch.py && ./scripts/fetch_camogie.py && ./scripts/fetch_ladies.py
./scripts/geocode.py && ./scripts/merge_venues.py
git commit -am "Refresh fixtures" && git push
```

The three fetches are independent: if camogie.ie is down, its season file keeps
its last good contents and the rest of the refresh proceeds (the weekly workflow
marks those steps `continue-on-error` for the same reason). `fetch_ladies.py
--venues` prints what each venue name matched, which is the thing to read after a
refresh that adds new grounds.

## Hosting

Cloudflare Workers static assets (`wrangler.jsonc`). Deploy by hand with `wrangler deploy` from a checkout. The GitHub Actions deploy was removed on 2026-09-06 because the `CLOUDFLARE_API_TOKEN` secret is not set and every push failed; put it back (cloudflare/wrangler-action with the token and `CLOUDFLARE_ACCOUNT_ID`) once the token exists.
The weekly refresh workflow commits new data but does not deploy it.
