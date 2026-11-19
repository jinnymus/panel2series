# Grafana authentication

## Interactive OIDC login with MFA

Install the optional dependencies and Chromium as described in [Browser export](BROWSER.md). From a desktop with access to Grafana and your identity provider:

    mkdir -p -m 700 "$HOME/.panel2series"
    python sso_login.py --url https://grafana.example.org --session "$HOME/.panel2series/viewer.json"
    python browser_export.py --url https://grafana.example.org --session "$HOME/.panel2series/viewer.json" --uid demo --panel 2 --start 1704067200000 --end 1704067320000 --out output
    python panel2series.py export --url https://grafana.example.org --session "$HOME/.panel2series/viewer.json" --uid demo --panel 1 --start 1704067200000 --end 1704067320000 --out series.json

The login command opens a visible browser at Grafana's Generic OAuth endpoint. Complete the password and MFA prompts there. The command checks the authenticated Grafana user and saves the Grafana login cookie. Use the same session file for subsequent headless exports. The numerical exporter uses a Playwright request context and needs no browser process. Supply `--channel chrome` to the login or browser export command to use installed Chrome. If Grafana uses a custom login cookie, give its name to `sso_login.py --cookie-name`.

Treat the session file as a credential. Keep it in a private directory outside exports and Git. It is written atomically with owner-only permissions. It is bound to the supplied Grafana base URL, including port and subpath. The file contains the Grafana login cookie only. After a successful export the client persists the current cookie to retain Grafana rotations. Use one writer at a time per session file.

If the browser export reports an expired or invalid session, repeat the login command with the same file. The account must have Viewer access to the dashboard and permission to query the datasource. Remote Grafana connections use HTTPS. The test harness uses HTTP on local loopback ports.

### Configure Grafana and the IdP

Register a confidential OIDC client with the exact callback URL `https://grafana.example.org/login/generic_oauth`. Enable authorization code flow, user email claims and MFA in the provider's browser authentication flow. Enable Generic OAuth on Grafana. A minimal configuration for a dedicated test integration is:

    [auth.generic_oauth]
    enabled = true
    client_id = panel
    scopes = openid profile email
    auth_url = https://idp.example.org/realms/test/protocol/openid-connect/auth
    token_url = https://idp.example.org/realms/test/protocol/openid-connect/token
    api_url = https://idp.example.org/realms/test/protocol/openid-connect/userinfo
    role_attribute_path = 'Viewer'
    role_attribute_strict = true

Supply `GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET` through the Grafana deployment's secret store. Configure the signing-key endpoint and ID-token validation according to the Grafana release and provider. Restrict which users can sign in at the IdP. The fixture uses a dedicated Keycloak realm with one user, an enrolled TOTP credential and explicit callback URLs.

## CI export with a Viewer service account

An administrator creates a Grafana service account in the target organization, assigns Viewer plus the required dashboard and datasource permissions, and issues a time-limited token. Store its value as the masked CI secret `GRAFANA_TOKEN`. Run:

    python panel2series.py export --token --url https://grafana.example.org --uid demo --panel 1 --start 1704067200000 --end 1704067320000 --out series.json

This selects bearer authentication for the numerical API export. HTTP 401 means Grafana rejected the token. Replace an expired or revoked token in the CI secret store. An HTTP 403 with an active token calls for checking organization, folder and datasource permissions.

## Reproduce the authentication tests

    python integration/oidc_matrix.py /tmp/panel2series-auth --channel chrome

Pass a version after the output directory to test one image. The suite uses Keycloak 26.2.5, temporary Grafana containers, their bundled TestData source and browser automation with synthetic credentials. A wrong second factor must leave the browser without a Grafana login. A valid TOTP must establish a Viewer session. Two separate exporter processes use the resulting file to produce CSV and PNG. The service account exports the same reference series through the API.

The configured test lifetime is two minutes for Grafana login and 25 seconds for the service-account token. The test waits for expiration, presents the last saved cookie directly to Grafana, expects HTTP 401 and checks both CLI failure paths. Allow several minutes for the default sequential matrix. Test credentials, session files and containers are disposable. The requested output directory retains the exports. The test drives the IdP form only inside the synthetic fixture. During normal interactive use, the user completes the IdP prompts.

Run `CHECK_CI_TOKEN=1 bash integration/matrix.sh /tmp/panel2series-ci` for the Prometheus and InfluxDB matrix over HTTPS. Its export containers receive a short-lived Viewer token and an empty password. The existing reference checks cover nested panels, variables, partial query failures, labels and offline charts. See [the compatibility matrix](COMPATIBILITY.md) for exact versions.
