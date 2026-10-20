"""Offline street block tests: no network or third-party API needed."""
import json
import tempfile
import unittest
from pathlib import Path

from anonchat.city_roads import RoadGeometry, build_shapes


class StreetGeometryTests(unittest.TestCase):
    def test_true_closed_osm_road_block(self):
        # A block surrounded by four connected road ways.
        box = [(58.975,53.378), (58.978,53.378),
               (58.978,53.380), (58.975,53.380)]
        lines = []
        for i in range(4):
            x1,y1 = box[i]
            x2,y2 = box[(i+1)%4]
            lines.append({"geometry":[{"lon":x1,"lat":y1},{"lon":x2,"lat":y2}]})
        shapes = build_shapes(lines,[(6,53.379,58.976)])
        self.assertIn("6",shapes)
        self.assertGreaterEqual(len(shapes["6"]),5)
        self.assertAlmostEqual(shapes["6"][0][0], 53.378, delta=.005)

    def test_three_sides_never_close_using_query_box_border(self):
        # A network missing one street may not become a filled sector just
        # because its open endpoints touch the Overpass download rectangle.
        points = [(58.975, 53.378), (58.978, 53.378),
                  (58.978, 53.380), (58.975, 53.380)]
        roads = [
            {"geometry": [
                {"lon": x1, "lat": y1}, {"lon": x2, "lat": y2}
            ]}
            for (x1, y1), (x2, y2) in zip(points, points[1:])
        ]
        self.assertEqual(build_shapes(roads, [(6, 53.379, 58.976)]), {})

    def test_no_roads_means_no_fake_polygons(self):
        self.assertEqual(build_shapes([],[(15,53.415252,59.054228)]),{})

    def test_cached_blocks_are_loaded_without_network(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/"roads.json"
            f.write_text(json.dumps({"version":2,"shapes":{"13":[[53.39,59.06]]}}))
            cache=RoadGeometry(f)
            self.assertIn("13",cache.data)


if __name__=="__main__":
    unittest.main()
