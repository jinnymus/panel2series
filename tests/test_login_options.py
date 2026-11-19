import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from sso_login import login_options


class LoginOptionsTests(unittest.TestCase):
    def test_file_and_override(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "login.json"
            config.write_text(json.dumps({"url": "https://grafana.example.org/",
                                          "session": "viewer.json", "channel": "chrome",
                                          "cookie_name": "viewer_cookie"}))
            options = login_options(["--config", str(config), "--channel", "msedge"])
            self.assertEqual(options.url, "https://grafana.example.org")
            self.assertEqual(options.session, config.parent / "viewer.json")
            self.assertEqual(options.channel, "msedge")
            self.assertEqual(options.cookie_name, "viewer_cookie")

    def test_flags_only(self):
        options = login_options(["--url", "https://example.org", "--session", "viewer"])
        self.assertEqual(options.session, Path("viewer"))
        self.assertEqual(options.cookie_name, "grafana_session")

    def test_invalid_settings(self):
        for contents in ('{"password":"test"}', '{"url":42}', '[]', '{',
                         '{"url":"http://example.org","session":"session.json"}'):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / "login.json"
                config.write_text(contents)
                with self.assertRaises(SystemExit), redirect_stderr(StringIO()):
                    login_options(["--config", str(config)])
