import unittest
from argparse import Namespace
from xml.etree import ElementTree

from panel2series import chart, export_panel


def frame(fields):
    return {"schema": {"fields": [{"type": "time", "name": "Time"}] + [
        {"type": "number", "name": "rate", "labels": {"host": host},
         "config": {"unit": unit} if unit else {}} for host, unit, _ in fields]},
        "data": {"values": [[1000, 2000]] + [values for _, _, values in fields]}}


def export(frames):
    def api(path, body=None):
        if body:
            return {"results": {"T": {"frames": frames}}}
        return {"spec": {"panels": [{"id": 1, "targets": [{"refId": "T"}],
                "title": "Load", "fieldConfig": {"defaults": {"unit": "short"}}}]}}
    return export_panel(Namespace(uid="test", panel=1, start=1000, end=2000, var=[]), api)


class SingleTargetTest(unittest.TestCase):
    def test_labeled_multiframe_and_wide_frame(self):
        data = export([frame([("node-a", "Bps", [5, None]), ("node-b", None, [9, 12])]),
                       frame([("node-c", "s", [1, 3])])])
        self.assertEqual(data["schema_version"], 2)
        rows = data["results"]["T"]["series"]
        self.assertEqual([(r["labels"]["host"], r["unit"]) for r in rows],
                         [("node-a", "Bps"), ("node-b", "short"), ("node-c", "s")])
        self.assertEqual(rows[0]["points"], [(1000, 5), (2000, None)])
        svg = ElementTree.fromstring(chart({**data, **rows[2]}))
        text = " ".join(svg.itertext())
        for expected in ("rate", "node-c", "s"):
            self.assertIn(expected, text)

    def test_one_series_retains_flat_archive(self):
        data = export([frame([("node-a", None, [5, 8])])])
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["refId"], "T")
        self.assertEqual(data["unit"], "short")
        self.assertEqual(data["points"], [(1000, 5), (2000, 8)])

    def test_string_dimension_cannot_be_silently_lost(self):
        source = frame([("node-a", "ms", [1, 3])])
        source["schema"]["fields"].append({"type": "string", "name": "region"})
        source["data"]["values"].append(["east", "west"])
        with self.assertRaisesRegex(ValueError, "String dimension"):
            export([source])
