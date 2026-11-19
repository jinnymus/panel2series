"""Validate an effective browser locator profile without a Grafana login."""
import argparse
from pathlib import Path

from playwright.sync_api import Error, sync_playwright
import yaml

from browser_export import selectors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Grafana version, for example 13.3.0")
    parser.add_argument("--locators", type=Path, help="Site-specific YAML overrides")
    parser.add_argument("--channel", help="Installed Chromium channel")
    args = parser.parse_args()
    try:
        profile = selectors(args.version, args.locators)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=args.channel)
            page = browser.new_page()
            for key, selector in profile.items():
                probe = selector.replace("{menu}", '"example menu"').replace("{header}", '"example header"')
                try:
                    page.locator(probe).count()
                except Error as exc:
                    raise ValueError(f"Invalid locator {key}: {selector}") from exc
                print(f"{key}: {selector}")
            browser.close()
    except (Error, ValueError, OSError, yaml.YAMLError) as exc:
        parser.exit(1, f"Locator check failed: {exc}\n")


if __name__ == "__main__":
    main()
