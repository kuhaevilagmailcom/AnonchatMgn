"""Street-block outlines derived from OSM road geometry, never drawn as ellipses.

Built lazily and cached on disk. Failure leaves icon-only zones instead of
misrepresenting guessed polygons as real streets. OSM data © contributors.
"""
import asyncio
import json
import logging
import math
import os
import time
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout

_LOG = logging.getLogger(__name__)
# Small OSM coverage rectangles on both banks. South, west, north, east.
BOUNDS = (
    (53.369, 58.945, 53.440, 59.013),
    (53.383, 59.040, 53.424, 59.081),
)
URLS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)
HIGHWAYS = "residential|tertiary|secondary|primary|unclassified|living_street|pedestrian|service"
MAX_BYTES = 12_000_000


def _bbox_query(bounds):
    s, w, n, e = bounds
    return (
        f'[out:json][timeout:18];way["highway"~"^({HIGHWAYS})$"]'
        f'({s},{w},{n},{e});out geom;'
    )


def build_shapes(ways, zones):
    """Polygonize the noded road network; return only actual road-bounded faces.

    Geometry is in [latitude, longitude] for Leaflet. Large/open road cells
    are not guessed or extrapolated. It is intentionally OK to return no face.
    """
    from shapely.geometry import LineString, Point, box
    from shapely.ops import polygonize, unary_union
    shapes = {}
    for bounds in BOUNDS:
        s, w, n, e = bounds
        area = box(w, s, e, n)
        lines = []
        for way in ways:
            points = way.get("geometry", [])
            if len(points) < 2:
                continue
            coords = [(p["lon"], p["lat"]) for p in points
                      if "lon" in p and "lat" in p]
            if len(coords) >= 2:
                geom = LineString(coords)
                if geom.intersects(area):
                    lines.append(geom.intersection(area))
        if not lines:
            continue
        # Never close a street block with the arbitrary fetch bounding box:
        # that created artificial straight edges which cross buildings/roads.
        network = unary_union(lines)
        faces = [p for p in polygonize(network)
                 if p.is_valid and not p.is_empty and p.area > 0.00000007]
        for zone_id, latitude, longitude in zones:
            point = Point(longitude, latitude)
            if not area.contains(point):
                continue
            containing = [p for p in faces if p.contains(point)]
            if containing:
                candidate = min(containing, key=lambda p: p.area)
            else:
                # Some verified entrance/POI anchors sit directly on a street.
                # Choose the closest bounded block only within ~50 metres.
                candidate = min(faces, key=lambda p: p.distance(point), default=None)
                if candidate is None:
                    continue
                metres = point.distance(candidate) * 111320
                if metres > 50:
                    continue
            # Require a reasonably bounded urban block, not huge rural space.
            approx_area_m2 = candidate.area * 111320 * 111320 * math.cos(math.radians(latitude))
            if not 500 <= approx_area_m2 <= 700_000:
                continue
            # Preserve street corners, with only small simplification.
            simple = candidate.simplify(0.000008, preserve_topology=True)
            outline = list(simple.exterior.coords)
            if not 4 <= len(outline) <= 240:
                continue
            shapes[str(zone_id)] = [[round(y, 6), round(x, 6)] for x, y in outline]
    return shapes


class RoadGeometry:
    def __init__(self, cache_path):
        self.cache_path = Path(cache_path)
        self.data = {}
        self.retry_at = 0
        self.lock = asyncio.Lock()
        try:
            cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if cached.get("version") == 1 and isinstance(cached.get("shapes"), dict):
                self.data = cached["shapes"]
        except (OSError, ValueError, TypeError):
            pass

    async def shapes(self, zones):
        if self.data:
            return self.data
        if time.monotonic() < self.retry_at:
            return {}
        async with self.lock:
            if self.data or time.monotonic() < self.retry_at:
                return self.data
            self.retry_at = time.monotonic() + 3600
            try:
                ways = []
                async with ClientSession(timeout=ClientTimeout(total=28),
                                         headers={"User-Agent": "AnonMGN-CityGame/1.0 (street blocks)"}) as session:
                    for bounds in BOUNDS:
                        result = None
                        for url in URLS:
                            try:
                                async with session.post(url, data={"data": _bbox_query(bounds)}) as response:
                                    response.raise_for_status()
                                    raw = await response.content.read(MAX_BYTES + 1)
                                    if len(raw) > MAX_BYTES:
                                        raise ValueError("Road response too large")
                                    result = json.loads(raw)
                                if not isinstance(result.get("elements"), list):
                                    raise ValueError("Invalid OSM road response")
                                break
                            except Exception as err:
                                _LOG.warning("OSM road provider failed: %s", err)
                        if result:
                            ways.extend(result["elements"])
                if ways:
                    found = await asyncio.to_thread(build_shapes, ways, zones)
                    if found:
                        self.data = found
                        try:
                            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                            tmp = self.cache_path.with_suffix(".tmp")
                            tmp.write_text(json.dumps({"version": 1, "shapes": found}, ensure_ascii=False),
                                           encoding="utf-8")
                            os.replace(tmp, self.cache_path)
                        except OSError as err:
                            _LOG.warning("Could not persist city street blocks: %s", err)
            except Exception:
                _LOG.exception("Unable to build street-aligned city blocks")
        return self.data
