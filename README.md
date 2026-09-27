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

This is a passenger rail atlas. `tools/curate.py` cleans `data/network.json`, then
`tools/build_tiles.py` rebuilds the rail tiles from the original tiles in git history
(commit `23a0e31`), so both scripts can be re-run at any time.

- **Removed:** freight-only railways (list in `tools/names.py`, from news and Wikipedia
  research; the low-confidence ones are marked), port, mine and coal branches, depot and
  yard tracks (动车段/动车所/走行线), bridges mapped as lines (特大桥), connectors and reversing
  spurs (联络线/疏解线/直通线/立折线), lines outside China, duplicate relations (e.g. Batong Line,
  now part of Line 1), and stubs with fewer than two mapped stops. Their track is not drawn.
- **Line ends:** track that runs past a line's terminal stop (tail tracks, unopened
  extensions) is cut at the stop. It is cut only where the track dead-ends within 3 km (urban)
  or 5 km (intercity). Track that keeps going is left alone, because it usually means OSM is
  missing a stop.
- **Stop order:** lists that OSM has out of order are re-sequenced, and intercity lines are
  listed in the order their name reads (Beijing–Shanghai starts at Beijing).
- **Station complexes:** a railway station and the metro stations built into it (OSM
  transfers, or metro within 400 m) are one place, with one label, one panel and all lines.
- **English names:** hand-checked names for high-speed, trunk and named urban lines
  (`tools/names.py`); "N号线" becomes "Line N"; auto-romanised pinyin is re-spelled word by
  word.

```
pip install jieba pypinyin mapbox-vector-tile protobuf
python3 tools/curate.py -v      # -v lists every removed line and why
python3 tools/build_tiles.py
```

## Operator logos

`data/logos.json` maps each operator to its logo on Wikimedia Commons / Wikipedia. The page
loads the logos straight from `upload.wikimedia.org`. The file names come from Wikimedia
search results; any logo that fails to load is simply left out. China Railway's logo is
used as the rail station icon on the map, with a drawn train icon as the fallback.

## Run locally

```
python3 -m http.server 8000   # then open http://localhost:8000
```

## Deploying

Served by GitHub Pages from the `main` branch (root). The `CNAME` file sets the
custom domain; DNS has a `CNAME chinarail -> tjaffee99.github.io` record.
Push to `main` and the site updates within a minute or two.
