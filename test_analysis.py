"""Offline acceptance tests with a non-periodic synthetic input and known delay."""
import json
import unittest
from pathlib import Path

from analysis_core import analyze

FIXTURES = Path(__file__).resolve().parent / "example" / "analysis"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


class OfflineAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.config = load("config")
        self.exports = [load("run1"), load("run2")]

    def test_known_delay_gaps_and_stages(self):
        report = analyze(self.exports, self.config)
        for run in report["runs"]:
            lag = run["lag"]
            self.assertEqual(lag["status"], "ok")
            self.assertEqual(lag["lag_ms"], 4000)
            self.assertAlmostEqual(lag["correlation"], 1.0)
            self.assertEqual(lag["pairs"], 53)
            self.assertEqual(run["gaps"]["x"]["intervals_ms"], [[10000, 12000]])
            self.assertEqual(run["gaps"]["y"]["intervals_ms"], [[44000, 45000]])
            for name, axis, count in [("warm", "x", 28), ("load", "y", 29)]:
                stat = run["stages"][name][axis]
                self.assertEqual((stat["count"], stat["expected"]), (count, 30))
            observed = run["stages"]["load"]["x"]["mean"] - run["stages"]["warm"]["x"]["mean"]
            self.assertAlmostEqual(run["stage_changes"]["load"]["x"], observed)
        first = report["runs"][0]["stages"]
        self.assertAlmostEqual(first["warm"]["x"]["mean"], 771 / 28)
        self.assertAlmostEqual(first["load"]["x"]["mean"], 1499 / 30)
        self.assertAlmostEqual(first["warm"]["y"]["mean"], 1712 / 30)
        self.assertAlmostEqual(first["load"]["y"]["mean"], 2861 / 29)
        for stage in self.config["stages"]:
            self.assertAlmostEqual(report["run_changes"][stage]["x"], 7)
            self.assertAlmostEqual(report["run_changes"][stage]["y"], 14)

    def test_reverse_direction(self):
        self.config["x"], self.config["y"] = self.config["y"], self.config["x"]
        for run in analyze(self.exports, self.config)["runs"]:
            self.assertEqual(run["lag"]["lag_ms"], -4000)

    def test_constant_series_has_no_identifiable_delay(self):
        for export in self.exports:
            points = export["results"]["A"]["series"][0]["points"]
            for point in points:
                point[1] = 0
        for run in analyze(self.exports, self.config)["runs"]:
            self.assertIsNone(run["lag"]["lag_ms"])
            self.assertNotEqual(run["lag"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
