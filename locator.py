import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsLocatorFilter,
    QgsLocatorResult,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
)
from qgis.PyQt.QtGui import QColor

# ArcGIS REST query endpoint used by LIST Tasmania's named feature search.
LIST_URL = (
    "https://services.thelist.tas.gov.au/arcgis/rest/services/"
    "Public/SearchService/MapServer/0/query"
)

# Bidirectional abbreviation expansion. LISTmap's JS does this client-side,
# so we replicate it. Each entry is (abbrev_regex, full_form).
ABBREVS = [
    (r"\bMT\b",  "MOUNT"),
    (r"\bST\b",  "SAINT"),
    (r"\bPT\b",  "POINT"),
    (r"\bIS\b",  "ISLAND"),
    (r"\bL\b",   "LAKE"),
    (r"\bC\b",   "CAPE"),
    (r"\bCR\b",  "CREEK"),
    (r"\bCRK\b", "CREEK"),
    (r"\bRVR\b", "RIVER"),
    (r"\bR\b",   "RIVER"),
]


def expand(query: str):
    """Generate all reasonable variants of the query (forward + reverse)."""
    q = query.upper().strip()
    variants = {q}
    for pat, full in ABBREVS:
        # Expand user-entered abbreviations so "MT WELLINGTON" can match
        # services that store the name as "MOUNT WELLINGTON".
        for v in list(variants):
            fwd = re.sub(pat, full, v)
            if fwd != v:
                variants.add(fwd)

        # Also try the inverse because LIST data is mixed: users may type the
        # long form while the service stores an abbreviated label.
        rev_pat = r"\b" + re.escape(full) + r"\b"
        abbrev = pat.replace(r"\b", "")
        for v in list(variants):
            rev = re.sub(rev_pat, abbrev, v)
            if rev != v:
                variants.add(rev)
    return list(variants)


def geojson_to_qgsgeom(geom: dict) -> QgsGeometry:
    """Translate the GeoJSON geometry returned by LIST into a QGIS geometry."""
    if not geom:
        return QgsGeometry()
    t = geom.get("type")
    c = geom.get("coordinates")
    if t == "Point":
        return QgsGeometry.fromPointXY(QgsPointXY(c[0], c[1]))
    if t == "LineString":
        return QgsGeometry.fromPolylineXY([QgsPointXY(p[0], p[1]) for p in c])
    if t == "Polygon":
        rings = [[QgsPointXY(p[0], p[1]) for p in ring] for ring in c]
        return QgsGeometry.fromPolygonXY(rings)
    if t == "MultiPolygon":
        polys = [
            [[QgsPointXY(p[0], p[1]) for p in ring] for ring in poly]
            for poly in c
        ]
        return QgsGeometry.fromMultiPolygonXY(polys)
    return QgsGeometry()


class ListTasFilter(QgsLocatorFilter):
    """Locator filter that proxies QGIS searches to the LIST Tasmania API."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface

    def name(self):
        return "list_tas_named_features"

    def displayName(self):
        return "LIST Tasmania – Named Features"

    def prefix(self):
        return "tas"

    def clone(self):
        return ListTasFilter(self.iface)

    def priority(self):
        return QgsLocatorFilter.Priority.High

    def fetchResults(self, query, context, feedback):
        # Keep the filter quiet for very short inputs so we do not spam the
        # remote service with broad prefix queries.
        query = (query or "").strip()
        if len(query) < 3:
            return

        variants = expand(query)
        # The ArcGIS layer exposes SQL-like prefix searching via the `where`
        # parameter, so we OR together every expanded variant.
        where = " OR ".join(
            "NAME LIKE '{}%'".format(v.replace("'", "''")) for v in variants
        )

        params = {
            "where": where,
            "outFields": "NAME,TYPE,LOCATION,NOM_REG_NO",
            "returnGeometry": "true",
            "outSR": "4326",
            "orderByFields": "NAME",
            "resultRecordCount": "25",
            "f": "geojson",
        }
        url = LIST_URL + "?" + urlencode(params)

        try:
            # A user agent makes the request easier to identify in server logs
            # and avoids looking like a completely anonymous script.
            req = Request(url, headers={"User-Agent": "QGIS-LIST-Locator/0.1"})
            with urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            self.logMessage(f"LIST query failed: {e}")
            return

        for feat in data.get("features", []):
            if feedback.isCanceled():
                return
            props = feat.get("properties") or {}
            name = props.get("NAME") or "Unknown"
            ftype = props.get("TYPE") or ""
            loc = props.get("LOCATION") or ""

            res = QgsLocatorResult()
            res.filter = self
            res.displayString = name
            # Show the feature type and locality in the secondary text without
            # repeating the main label when LIST duplicates the name there.
            desc = " — ".join(p for p in (ftype, loc) if p and p != name)
            res.description = desc
            # Keep the full feature payload so triggerResult can zoom/flash the
            # original geometry without issuing a second network request.
            res.userData = feat
            self.resultFetched.emit(res)

    def triggerResult(self, result):
        feat = result.userData or {}
        qgeom = geojson_to_qgsgeom(feat.get("geometry"))
        if qgeom.isEmpty():
            return

        # The service returns WGS84 coordinates. Reproject to the current
        # project CRS before setting the map extent or flashing geometry.
        src = QgsCoordinateReferenceSystem("EPSG:4326")
        dst = QgsProject.instance().crs()
        if src != dst:
            xform = QgsCoordinateTransform(src, dst, QgsProject.instance())
            qgeom.transform(xform)

        canvas = self.iface.mapCanvas()
        bbox = qgeom.boundingBox()
        if bbox.width() < 1 and bbox.height() < 1:
            # Point or near-point feature: give it a sensible viewing window
            bbox.grow(500)  # metres in projected CRS (EPSG:7855)
        else:
            # Larger features get a little padding so they are not hard against
            # the canvas edges when the locator jumps to them.
            bbox.scale(1.25)
        canvas.setExtent(bbox)
        canvas.refresh()

        # Flash the feature briefly so the user can see exactly what matched.
        canvas.flashGeometries(
            [qgeom],
            QgsProject.instance().crs(),
            QColor(255, 220, 0, 255),   # start: bright yellow
            QColor(255, 220, 0, 0),     # end: transparent
            flashes=2,
            duration=400,
        )


class ListTasPlugin:
    """Minimal plugin wrapper that registers/unregisters the locator filter."""

    def __init__(self, iface):
        self.iface = iface
        self.filter = None

    def initGui(self):
        self.filter = ListTasFilter(self.iface)
        self.iface.registerLocatorFilter(self.filter)

    def unload(self):
        if self.filter is not None:
            self.iface.deregisterLocatorFilter(self.filter)
            self.filter = None