# maps4agent — Google Maps from the shell

One command, four subcommands — chain them in the shell. Requires a Google
Maps API key in `~/.env` (`GOOGLE_MAPS_API_KEY=…`) or the environment.

## `maps places QUERY`

Google Places Text Search — name, address, rating, coords, open/closed.

```console
$ maps places "ramen restaurant Düsseldorf" --limit 5
$ maps places "Japantag Burgplatz" --location 51.2277,6.7735
```

Options: `--location LAT,LNG` (bias), `--radius M` (default 5000),
`--limit N` (default 10), `--json` (raw JSON).

## `maps parking LOCATION`

Parking lots near a location, with rating, review count, and haversine
distance from the center. Geocodes addresses automatically.

```console
$ maps parking "Burgplatz Düsseldorf" --radius 3000
$ maps parking 51.2227,6.7765 --sort-by rating
```

Options: `--radius M` (default 3000), `--sort-by distance|rating` (default
distance), `--json`.

## `maps directions ORIGIN DEST`

Turn-by-turn directions. Supports driving / transit / walking / bicycling,
alternative routes, waypoints, and departure/arrival times.

```console
$ maps directions "Düsseldorf Hbf" "Burgplatz Düsseldorf" --mode transit --steps
$ maps directions "Aachen" "Köln" --mode driving --alternatives --departure 08:00
```

Options: `--mode`, `--alternatives` (driving/transit), `--waypoints` (comma-
separated), `--departure TIME`, `--arrival TIME` (transit only), `--steps`
(print instructions), `--json`. Times accept ISO (`2026-06-10T08:00:00`) or
`HH:MM` (today).

## `maps pr ORIGIN DEST`

Park + Ride: finds parking near the destination, then routes drive → parking
and transit → destination for each candidate, sorted by total time. Prints a
drive/transit ratio bar and writes a standalone Leaflet HTML map per option
(`Karte: /tmp/maps_*.html`).

```console
$ maps pr "Aachen West" "Burgplatz Düsseldorf" --pnr-only
$ maps pr "Köln" "Düsseldorf Messe" --avoid-highways --max-results 8
```

Options: `--radius M` (default 2000), `--max-results N` (default 5),
`--avoid-highways`, `--pnr-only`, `--no-map`, `--json`.

## Install

```console
pip install maps4agent
```

Python >= 3.10, no dependencies (stdlib only).

## License

MIT — see [LICENSE](LICENSE).
