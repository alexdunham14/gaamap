# GAA Map

Every fixture gaa.ie lists, on a map of Ireland, filterable by date, sport, and
competition. For the traveller who wants to know what is on near them next week.

## Definition of done

- A static page: map with a point per venue sized by number of fixtures, and a
  plain list by day underneath. Filters for date range, football/hurling,
  competition, and whether to include played matches.
- Data refreshed weekly by a scheduled workflow that fetches gaa.ie, commits
  `fixtures.json`, and deploys. If gaa.ie changes its page format, the fetch
  fails loudly and the site keeps serving the last good data.
- Venues geocoded once into `venues.json`, hand-corrected where the geocoder
  guessed wrong. New venues get geocoded on the next refresh and flagged.

Out of scope: club fixtures below the All-Ireland stages (those live on county
board sites, not gaa.ie), historical data, results analysis.

## How it works

- `scripts/fetch.py` pulls the fixtures page and extracts the match records
  gaa.ie embeds in it as React Server Components payload. Output: `fixtures.json`.
- `scripts/geocode.py` fills `venues.json` for any venue without coordinates,
  using Nominatim with a county hint taken from the home team. Never overwrites
  a venue that already has coordinates, so hand fixes stick.
- `index.html`, `styles.css`, `app.js`: the site. Leaflet from cdnjs, tiles
  from OpenStreetMap. No build step.

## Refresh by hand

```
./scripts/fetch.py && ./scripts/geocode.py
git commit -am "Refresh fixtures" && git push
```

## Hosting

Cloudflare Workers static assets (`wrangler.jsonc`). Deploy by hand with `wrangler deploy` from a checkout. The GitHub Actions deploy was removed on 2026-09-06 because the `CLOUDFLARE_API_TOKEN` secret is not set and every push failed; put it back (cloudflare/wrangler-action with the token and `CLOUDFLARE_ACCOUNT_ID`) once the token exists.
The weekly refresh workflow commits new data but does not deploy it.
