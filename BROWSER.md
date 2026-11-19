# Browser export

For Generic OAuth/OIDC with interactive MFA, use [SSO login and session reuse](AUTH.md).

Install the optional browser dependencies in a Python virtual environment:

    pip install -r browser-requirements.txt
    python -m playwright install chromium

Set GRAFANA_PASSWORD in the environment. Use a Grafana account with Viewer and datasource query permissions. Run:

    python browser_export.py --url https://grafana.example.org --user reader --uid demo --panel 2 --start 1704067200000 --end 1704067320000 --out output

Use `--channel chrome` for an installed Chrome. Pass dashboard selections as repeated `--var name=value` arguments. The numeric time boundaries are Unix milliseconds. The exporter captures the solo time-series panel and uses the native Inspector CSV download for its selected frame. For a panel with configured transformations it checks the transformation switch. The files are `panel.png` and `panel.csv` in the output directory. The fixture uses password login, an English UI, a single frame and UTC. CSV column names and formatting come from Grafana.

## Repair a site-specific locator

1. Reproduce with the same account, panel and time window. Open the data inspector. In browser developer tools inspect the failing control's role, accessible name or stable test ID.
2. Look up the failing control in `locators.yaml`. The built-in defaults can be refined by major version under `versions` (quoted keys). For one installation create a separate YAML file containing just the keys to replace. For example, to match a localized CSV button:

       download: 'role=button[name="Скачать CSV"i]'

3. Run the same export with `--locators ./site.yaml`. The exporter reads this file on each invocation. Use a fresh output directory and check the transformed column, expected values and screenshot before using the new profile for reports. Each locator should resolve to the intended control within its view. For a switch the selector must resolve to the input itself.

For example, a timeout that mentions a panel menu on 13.3.0 points to the `menu` key in the version 13 profile. The `{menu}` and `{header}` placeholders expand to quoted test IDs using the panel title. Use a unique visible title for that workflow. A timeout on `transform` points to the control inside Data options. Test with a calculated field whose output differs from the input to distinguish a transformed CSV from a raw download.

PNG and CSV use separate page loads with the same absolute time window and variables. A mutable source can return different results between requests. Existing panel.csv and panel.png in the destination are replaced after a successful capture.

The fixture override in `integration/browser-locators.yaml` is a runnable example. To exercise it across all four Docker images:

    BROWSER_CHANNEL=chrome bash integration/browser-matrix.sh /tmp/browser-evidence

Set PYTHON to the virtual environment interpreter if it is outside PATH. The matrix creates temporary Grafana instances with a Viewer account and deterministic TestData points.

To inspect the effective profile and have Playwright parse each selector in a local blank page, run:

    python locator_doctor.py --version 13.3.0 --locators integration/browser-locators.yaml --channel chrome

Omit --locators to check the built-in profile. The doctor prints the effective key and selector and exits unsuccessfully on a profile or syntax error. Matching a real control requires a browser export against the target instance.
