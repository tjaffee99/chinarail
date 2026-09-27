# China Rail Atlas

Interactive map of China's high-speed, conventional, metro, light rail and tram
networks. Intended to be served at <https://chinarail.theojaffee.net>.

A fully static site: no build step, no API keys.

```
index.html          page shell
style.css           UI styles (light + dark)
app.js              map style, search, line/station panels
favicon.svg
vendor/             MapLibre GL JS 5.24.0 (self-hosted)
data/network.json   lines, stations, cities (OpenStreetMap, extracted 25 Sep 2026)
data/manifest.json  index into the rail tile chunks
data/tiles/*.bin    rail vector tiles (z3–12), packed into chunk files
data/glyphs/        Noto Sans label glyphs (Latin/Greek/punctuation ranges)
CNAME               chinarail.theojaffee.net
```

The base map (streets, buildings, water, parks, place and POI labels, worldwide,
zoom 0–14 overzoomed to 19) streams from [OpenFreeMap](https://openfreemap.org),
which is free and needs no key. Glyph ranges not bundled locally (Cyrillic, Thai,
etc.) also come from OpenFreeMap; Chinese characters use the system font.

The map position is kept in the URL (`#view=zoom/lat/lng`), so links are shareable.

## Run locally

```
python3 -m http.server 8000   # then open http://localhost:8000
```

## Deploying

Served by GitHub Pages from the `main` branch (root). The `CNAME` file sets the
custom domain; DNS has a `CNAME chinarail -> tjaffee99.github.io` record.
Push to `main` and the site updates within a minute or two.
