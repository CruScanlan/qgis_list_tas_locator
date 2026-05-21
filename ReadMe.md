# LIST Tasmania Locator

A QGIS locator plugin that searches Tasmanian place names directly from the QGIS locator bar, using the official LIST Tasmania (Land Information System Tasmania) ArcGIS REST API.

This plugin is vibe coded for a personal project so do not rely on it for anything critical.

Type `tas mount rufus` (or just `mount rufus`) into the locator bar at the bottom-left of the QGIS window. The plugin queries the LIST gazetteer, returns matching mountains, lakes, capes, creeks, etc., and zooms the canvas to whatever you pick — with a brief yellow flash to confirm the match.

The data source is `Public/SearchService/MapServer/0` (LIST Named Features), the same endpoint LISTmap's own search bar uses.

## Install

Install from a zip to qgis. https://docs.qgis.org/3.44/en/docs/training_manual/qgis_plugins/fetching_plugins.html

## Use

Open the locator with **Ctrl+K** or click the search box at the bottom-left of the QGIS window. Type at least 3 characters.

```
tas mount rufus
tas cradle
tas wineglass
tas cape pillar
tas frenchmans cap
mt anne                 (no prefix — also works, mixed with Nominatim etc)
```

Click a result. The canvas zooms to the feature and flashes it briefly in yellow.

To restrict to this filter only (suppress Nominatim and the rest), always use the `tas` prefix. To leave it mixed in with the other locators, type without the prefix.

## What gets searched

Layer 0 of LIST's SearchService MapServer: the Tasmanian Named Features (nomenclature) layer. That covers gazetted natural and cultural features — mountains, peaks, lakes, tarns, rivers, creeks, capes, points, bays, islands, beaches, falls, gorges, plains, plateaus, valleys, and similar.

Attributes shown in the dropdown: `NAME`, `TYPE`, `LOCATION`. The full feature (including geometry and all attributes) is available as `result.userData` for any extensions you build.

## Abbreviation handling

The plugin expands common Tasmanian gazetteer abbreviations in both directions. Type either form, match against the other:

| Type | Also matches |
|------|--------------|
| MT | MOUNT |
| ST | SAINT |
| PT | POINT |
| IS | ISLAND |
| L | LAKE |
| C | CAPE |
| CR / CRK | CREEK |
| RVR / R | RIVER |

Edit `ABBREVS` in `locator.py` to add or modify.

## How it works

1. User types in the locator bar; QGIS calls `fetchResults` on a worker thread.
2. The query is uppercased and run through the abbreviation expander, producing both forward (MT → MOUNT) and reverse (MOUNT → MT) variants.
3. A WHERE clause is constructed (`NAME LIKE 'MT RUFUS%' OR NAME LIKE 'MOUNT RUFUS%'`) and sent to `Public/SearchService/MapServer/0/query?f=geojson&outSR=4326`.
4. Results stream back to QGIS as locator results as soon as the response is parsed.
5. On click (`triggerResult`), the GeoJSON geometry is converted to `QgsGeometry`, reprojected to the project CRS (e.g. EPSG:7855 for Tasmania), and used to set the canvas extent. `QgsMapCanvas.flashGeometries` provides the visual confirmation and self-clears.

The plugin uses `urllib` from the standard library — no `requests` or other external deps required. QGIS's locator framework handles async dispatch and cancellation; the plugin itself is single-threaded.

## Extending

The LIST SearchService MapServer has more layers than just Named Features. To add additional search modes, duplicate `ListTasFilter` with a different prefix and layer URL:

| Layer | Contents | Suggested prefix |
|------:|----------|------------------|
| 0 | Named Features | `tas` (this plugin) |
| 7 | Address Geocodes | `tasa` |
| 8 | Cadastre (PID, Volume/Folio) | `tasp` |
| 9 | Universal Grid References | `tasg` |

Register the new filter in `ListTasPlugin.initGui` alongside the existing one.

For LISTmap-style mixed results in a single query, replace `MapServer/0/query` with `MapServer/find?layers=0,7,8&searchText=...&searchFields=NAME,ADDRESS,PROPERTY_NAME` — this returns hits from all three layers in one call.

## Caveats

- **Online only.** Every query hits LIST live. For offline scouting trips, mirror the Nomenclature layer (`Public/OpenDataWFS/MapServer/34` has the full attribute set) to a local GeoPackage or PostGIS table and point the plugin at that instead.
- **No fuzzy matching.** The server does case-insensitive prefix matching only. Typos won't match.
- **No SLA.** The LIST Web Services Terms (December 2014) reserve the right to suspend the service at any time. This pluigin is also vibe coded. Don't depend on it for anything mission-critical.

## Data attribution

Place names data: **LIST Tasmania**, © State of Tasmania, licensed under [Creative Commons Attribution 3.0 Australia](https://creativecommons.org/licenses/by/3.0/au/).

When publishing maps or other deliverables built using results from this plugin, attribute as:

> Place names © State of Tasmania (LIST)

## License

Plugin code is unencumbered — use, modify, redistribute as you wish.