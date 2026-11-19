import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from unittest.mock import Mock

from sso_login import login_options, sign_in


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
        self.assertEqual(options.provider, "oidc")

    def test_provider_from_profile_and_cli_override(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "login.json"
            config.write_text(json.dumps({"url": "https://grafana.example.org/grafana",
                                          "session": "viewer.json", "provider": "saml"}))
            argv = ["--config", str(config)]
            self.assertEqual(login_options(argv).provider, "saml")
            self.assertEqual(login_options([*argv, "--provider", "oidc"]).provider, "oidc")

    def test_sign_in_uses_provider_path_under_grafana_subpath(self):
        for kwargs, path in [({}, "/login/generic_oauth"), ({"provider": "saml"}, "/login/saml")]:
            with self.subTest(path=path):
                browser = Mock()
                ctx = browser.new_context.return_value
                with self.assertRaises(TimeoutError):
                    sign_in(browser, "https://example.org/grafana/", Path("unused"), timeout=0, **kwargs)
                ctx.new_page.return_value.goto.assert_called_once_with(
                    "https://example.org/grafana" + path, wait_until="domcontentloaded")
                ctx.close.assert_called_once()

    def test_invalid_settings(self):
        for contents in ('{"url":"https://example.org","session":"viewer","provider":"unsupported"}',
                         '{"password":"test"}', '{"url":42}', '[]', '{',
                         '{"url":"http://example.org","session":"session.json"}'):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / "login.json"
                config.write_text(contents)
                with self.assertRaises(SystemExit), redirect_stderr(StringIO()):
                    login_options(["--config", str(config)])
