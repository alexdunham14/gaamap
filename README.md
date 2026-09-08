# GAA Map

Live at https://gaamatchmap.com (gaamap.alexdunham14.workers.dev also serves it; .ie is not on Cloudflare Registrar).

Every inter-county fixture gaa.ie and camogie.ie list, on a map of Ireland,
filterable by date, sport, and competition. For the traveller who wants to know
what is on near them next week.

## Definition of done

- A static page: map with a point per venue sized by the level of the best match
  there and coloured by the game played, and a plain list by day underneath. Filters for date range
  (with presets for the coming weeks and each month of the season),
  football/hurling/camogie, level, competition, team, and whether to include
  played matches. Results show the score with the points total.
- Colour is the game, not the association: camogie shares hurling's colour, so
  the third colour keeps meaning "more than one game at this ground" instead of
  multiplying with every code added.
- The season's shape is visible: every competition is classified into a level
  (senior championship, national league, under-23, under-20, minor, under-16,
  club, schools) and,
  where the level has them, a tier (Sam Maguire down to the junior
  championship, Liam MacCarthy down to Lory Meagher, league divisions, and the
  lettered minor, under-20, under-23 and under-16 grades). A "what is in here" guide lists them with counts, and
  the competition menu is grouped the same way. The classification is by name
  in `app.js`, so a new competition still lands somewhere.
- Data refreshed weekly by a scheduled workflow that fetches gaa.ie, commits
  `fixtures.json`, and deploys. If gaa.ie changes its page format, the fetch
  fails loudly and the site keeps serving the last good data.
- Venues geocoded once into `venues.json`, hand-corrected where the geocoder
  guessed wrong. New venues get geocoded on the next refresh and flagged.

Out of scope: club fixtures below the All-Ireland stages (those live on county
board sites, not gaa.ie), historical data, results analysis.

Ladies' football is not here yet. It is a third association with a third site,
ladiesgaelic.ie, whose results page renders every season since 2016 server-side
in one request — so a seed is tractable, but its rows carry venues only as text
(sometimes in Irish: "Páirc an Chrócaigh" for Croke Park), with none of the
venue UUIDs that made camogie a straight lookup against `venues.json`. Matching
those names is the work. The page says the sport is to be added ahead of the
2027 season; see the 2026-09-08 session doc in the parent repo.

## How it works

- `scripts/fetch.py` pulls the fixtures page and extracts the match records
  gaa.ie embeds in it as React Server Components payload. Output: `fixtures.json`.
- `scripts/fetch_camogie.py` pulls inter-county camogie from camogie.ie, whose
  fixtures page loads match rows as HTML through an undocumented paginated
  endpoint behind its "Load more" button. Output: `camogie.json`. Two things it
  has to fix that gaa.ie gives for free: throw-in times print as bare Irish wall
  clock, so they are read in Europe/Dublin and stored as UTC instants, and both
  competition and round names are typed by hand and drift ("Div 1 B National
  League" beside "Div 1A National League", four spellings of semi-final), so
  they are canonicalised to one spelling each. camogie.ie uses the same venue
  UUIDs as gaa.ie — the two associations share a venue database — so
  `venues.json` is a direct lookup.
- `scripts/data.py` is the union of both fixture files. Each fetch script owns
  exactly one output file, so neither can clobber the other and the site still
  draws if one source is stale; everything downstream reads the union.
- `scripts/geocode.py` fills `venues.json` for any venue without coordinates,
  using Nominatim with a county hint taken from the home team. Never overwrites
  a venue that already has coordinates, so hand fixes stick.
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
./scripts/fetch.py && ./scripts/fetch_camogie.py
./scripts/geocode.py && ./scripts/merge_venues.py
git commit -am "Refresh fixtures" && git push
```

The two fetches are independent: if camogie.ie is down, `camogie.json` keeps its
last good contents and the rest of the refresh proceeds (the weekly workflow
marks that step `continue-on-error` for the same reason).

## Hosting

Cloudflare Workers static assets (`wrangler.jsonc`). Deploy by hand with `wrangler deploy` from a checkout. The GitHub Actions deploy was removed on 2026-09-06 because the `CLOUDFLARE_API_TOKEN` secret is not set and every push failed; put it back (cloudflare/wrangler-action with the token and `CLOUDFLARE_ACCOUNT_ID`) once the token exists.
The weekly refresh workflow commits new data but does not deploy it.
