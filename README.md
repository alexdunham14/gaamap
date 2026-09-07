# GAA Map

Every fixture gaa.ie lists, on a map of Ireland, filterable by date, sport, and
competition. For the traveller who wants to know what is on near them next week.

## Definition of done

- A static page: map with a point per venue sized by number of fixtures and
  coloured by sport, and a plain list by day underneath. Filters for date range
  (with presets for the coming weeks and each month of the season),
  football/hurling, level, competition, team, and whether to include played
  matches. Results show the score with the points total.
- The season's shape is visible: every competition is classified into a level
  (senior championship, national league, under-20, minor, club, schools) and,
  where the level has them, a tier (Sam Maguire down to the junior
  championship, Liam MacCarthy down to Lory Meagher, league divisions, minor
  and under-20 grades). A "what is in here" guide lists them with counts, and
  the competition menu is grouped the same way. The classification is by name
  in `app.js`, so a new competition still lands somewhere.
- Data refreshed weekly by a scheduled workflow that fetches gaa.ie, commits
  `fixtures.json`, and deploys. If gaa.ie changes its page format, the fetch
  fails loudly and the site keeps serving the last good data.
- Venues geocoded once into `venues.json`, hand-corrected where the geocoder
  guessed wrong. New venues get geocoded on the next refresh and flagged.

Out of scope: club fixtures below the All-Ireland stages (those live on county
board sites, not gaa.ie), camogie and ladies' football (separate associations
with their own sites; the page says so), historical data, results analysis.

Camogie has been scoped, though: `scripts/fetch_camogie.py` is a working
prototype against camogie.ie's paginated "load more" JSON endpoint, which
uses the same venue UUIDs as gaa.ie. Not wired in yet; it still needs a
Europe/Dublin to UTC conversion, a tier ladder for camogie's grades, and a
geocode run for the venues gaa.ie never lists. See the 2026-09-07 session
doc in the parent repo.

## How it works

- `scripts/fetch.py` pulls the fixtures page and extracts the match records
  gaa.ie embeds in it as React Server Components payload. Output: `fixtures.json`.
- `scripts/geocode.py` fills `venues.json` for any venue without coordinates,
  using Nominatim with a county hint taken from the home team. Never overwrites
  a venue that already has coordinates, so hand fixes stick.
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
./scripts/fetch.py && ./scripts/geocode.py && ./scripts/merge_venues.py
git commit -am "Refresh fixtures" && git push
```

## Hosting

Cloudflare Workers static assets (`wrangler.jsonc`). Deploy by hand with `wrangler deploy` from a checkout. The GitHub Actions deploy was removed on 2026-09-06 because the `CLOUDFLARE_API_TOKEN` secret is not set and every push failed; put it back (cloudflare/wrangler-action with the token and `CLOUDFLARE_ACCOUNT_ID`) once the token exists.
The weekly refresh workflow commits new data but does not deploy it.
