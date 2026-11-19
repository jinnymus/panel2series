"""Verify the portable report a downstream consumer receives."""
from html.parser import HTMLParser
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "example/reporting/report_builder.py"


class ReportPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.links = []
        self.words = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "img":
            self.images.append(attrs["src"])
        elif tag == "a":
            self.links.append(attrs["href"])

    def handle_data(self, data):
        self.words.append(data.strip())


class PortableReportTest(unittest.TestCase):
    def test_downloaded_bundle_rebuilds_offline_with_local_links_and_query_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "report"
            shutil.copytree(ROOT / "example/reporting/verified", bundle)
            (bundle / "index.html").unlink()
            subprocess.run([sys.executable, BUILDER, bundle], check=True)
            page = ReportPage()
            page.feed((bundle / "index.html").read_text())
            self.assertEqual(page.images, ["x.svg", "y.svg", "lag.svg"])
            self.assertCountEqual(page.links, ["analysis.json", "run1.json", "run2.json"])
            for target in page.images + page.links:
                self.assertTrue((bundle / target).is_file(), target)
            self.assertIn("B", page.words)
            self.assertIn("error", page.words)

    def test_missing_chart_fails_before_html_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "report"
            shutil.copytree(ROOT / "example/analysis/report", bundle)
            (bundle / "lag.svg").unlink()
            result = subprocess.run([sys.executable, BUILDER, bundle], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Missing chart lag.svg", result.stderr)
            self.assertFalse((bundle / "index.html").exists())
