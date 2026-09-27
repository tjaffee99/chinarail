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
data/network.json   lines, stations, cities (OpenStreetMap, extracted 25 Sep 2026, curated)
data/manifest.json  index into the rail tile chunks
data/tiles/*.bin    rail vector tiles (z3–12), packed into chunk files
data/glyphs/        Noto Sans label glyphs (Latin/Greek/punctuation ranges)
CNAME               chinarail.theojaffee.net
tools/              data curation and tile rebuild scripts (see below)
```

The base map (streets, buildings, water, parks, place and POI labels, worldwide,
zoom 0–14 overzoomed to 19) streams from [OpenFreeMap](https://openfreemap.org),
which is free and needs no key. Glyph ranges not bundled locally (Cyrillic, Thai,
etc.) also come from OpenFreeMap; Chinese characters use the system font.

The map position is kept in the URL (`#view=zoom/lat/lng`), so links are shareable.

## Data curation

OpenStreetMap route relations include things that are not passenger routes. `tools/curate.py`
cleans `data/network.json`, and `tools/build_tiles.py` then rewrites the rail tiles to match. It
changes only feature properties and copies the geometry byte-for-byte. Both scripts are idempotent.

- Hidden from lists, search and clicks, and drawn as thin grey "other track": depot and yard
  tracks (动车段/动车所/走行线), bridges mapped as lines (特大桥), connectors and reversing spurs
  (联络线/疏解线/直通线/立折线), freight lines (货线/货车外绕线), lines outside China, duplicate
  relations (e.g. Batong Line, now part of Line 1), and stubs with fewer than two mapped stops.
- Stop lists that OSM has out of order are re-sequenced along the shortest path.
- English names: hand-checked names for high-speed and trunk lines and named urban lines
  (`tools/names.py`); "N号线" becomes "Line N"; auto-romanised pinyin blobs are re-spelled
  word by word.

```
pip install jieba pypinyin mapbox-vector-tile protobuf
python3 tools/curate.py -v      # -v lists every hidden line and why
python3 tools/build_tiles.py
```

## Run locally

```
python3 -m http.server 8000   # then open http://localhost:8000
```

## Deploying

Served by GitHub Pages from the `main` branch (root). The `CNAME` file sets the
custom domain; DNS has a `CNAME chinarail -> tjaffee99.github.io` record.
Push to `main` and the site updates within a minute or two.
