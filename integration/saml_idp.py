"""Disposable loopback Keycloak SAML IdP for the Grafana Enterprise fixture."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.request import urlopen
import json
import secrets
import subprocess
import time
import xml.etree.ElementTree as ET

IMAGE = "quay.io/keycloak/keycloak:26.2.5"
REALM = "panel-saml"
METADATA_NS = "urn:oasis:names:tc:SAML:2.0:metadata"
POST = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"


def realm(grafana_url, password):
    acs = grafana_url + "/saml/acs"
    mappers = []
    for name, prop in (("login", "username"), ("email", "email")):
        mappers.append({"name": name, "protocol": "saml", "protocolMapper": "saml-user-property-mapper",
                        "config": {"user.attribute": prop, "attribute.name": name,
                                   "attribute.nameformat": "Basic"}})
    mappers.append({"name": "fixture-viewer", "protocol": "saml",
                    "protocolMapper": "saml-hardcode-attribute-mapper",
                    "config": {"attribute.name": "role", "attribute.nameformat": "Basic",
                               "attribute.value": "Viewer"}})
    return {"realm": REALM, "enabled": True, "sslRequired": "none",
            "clients": [{"clientId": grafana_url + "/saml/metadata", "enabled": True,
                         "protocol": "saml", "redirectUris": [acs], "protocolMappers": mappers,
                         "attributes": {"saml.assertion.signature": "true",
                                        "saml.signature.algorithm": "RSA_SHA256",
                                        "saml.client.signature": "false",
                                        "saml_assertion_consumer_url_post": acs}}],
            "users": [{"username": "reader", "email": "reader@example.test", "emailVerified": True,
                       "firstName": "Test", "lastName": "Reader", "enabled": True,
                       "credentials": [{"type": "password", "value": password, "temporary": False}]}]}


@dataclass
class Idp:
    idp_base: str
    password: str
    metadata: bytes


@contextmanager
def start_idp(grafana_url):
    password = secrets.token_urlsafe(24)
    with TemporaryDirectory() as tmp:
        config = Path(tmp) / "realm.json"
        config.write_text(json.dumps(realm(grafana_url.rstrip("/"), password)))
        config.chmod(0o644)  # Keycloak runs as a different UID; parent directory stays private.
        command = ["docker", "run", "--rm", "-d", "-p", "127.0.0.1::8080",
                   "-v", f"{config}:/opt/keycloak/data/import/realm.json:ro", IMAGE,
                   "start-dev", "--import-realm"]
        cid = subprocess.check_output(command, text=True).strip()
        try:
            address = subprocess.check_output(["docker", "port", cid, "8080/tcp"], text=True).strip()
            base = f"http://{address}/realms/{REALM}"
            for _ in range(90):
                try:
                    with urlopen(base + "/protocol/saml/descriptor", timeout=3) as response:
                        metadata = response.read()
                    break
                except (URLError, OSError):
                    time.sleep(1)
            else:
                raise RuntimeError("Keycloak SAML metadata was unavailable")
            doc = ET.fromstring(metadata)
            post = doc.find(f".//{{{METADATA_NS}}}SingleSignOnService[@Binding='{POST}']")
            cert = doc.find(".//{http://www.w3.org/2000/09/xmldsig#}X509Certificate")
            if doc.get("entityID") != base or post is None or cert is None or not cert.text:
                raise ValueError("Keycloak metadata lacks expected entity ID, POST endpoint or certificate")
            yield Idp(base, password, metadata)
        finally:
            subprocess.run(["docker", "stop", cid], check=True, stdout=subprocess.DEVNULL)


def verify_assertion(idp, grafana_url, channel=None):
    """Exercise IdP issuance and inspect its POST form before delivery to Grafana."""
    from base64 import b64decode, b64encode
    from datetime import datetime, timezone
    from urllib.parse import parse_qs
    from playwright.sync_api import sync_playwright

    assertion_ns = "urn:oasis:names:tc:SAML:2.0:assertion"
    protocol_ns = "urn:oasis:names:tc:SAML:2.0:protocol"
    endpoint = idp.idp_base + "/protocol/saml"
    acs = grafana_url + "/saml/acs"
    entity = grafana_url + "/saml/metadata"
    request_id = "_" + secrets.token_hex(12)
    request = ET.Element(f"{{{protocol_ns}}}AuthnRequest", ID=request_id, Version="2.0",
                         IssueInstant=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         Destination=endpoint, AssertionConsumerServiceURL=acs, ProtocolBinding=POST)
    ET.SubElement(request, f"{{{assertion_ns}}}Issuer").text = entity
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel)
        page = browser.new_page()
        page.route(acs, lambda route: route.fulfill(status=200, body="SAML fixture receiver"))
        encoded = b64encode(ET.tostring(request)).decode()
        page.set_content(f'<form method="POST" action="{endpoint}">'
                         f'<input name="SAMLRequest" value="{encoded}"></form>')
        page.locator("form").evaluate("(form) => form.submit()")
        page.locator("#username").fill("reader")
        page.locator("#password").fill(idp.password)
        with page.expect_request(lambda req: req.url == acs and req.method == "POST") as posted:
            page.locator("#kc-login").click()
        form = parse_qs(posted.value.post_data)
        browser.close()
    xml = ET.fromstring(b64decode(form["SAMLResponse"][0], validate=True))
    assertion = xml.find(f"{{{assertion_ns}}}Assertion")
    if assertion is None or xml.get("Destination") != acs or xml.get("InResponseTo") != request_id:
        raise AssertionError("Unexpected SAML response destination or request ID")
    if assertion.find("{http://www.w3.org/2000/09/xmldsig#}Signature") is None:
        raise AssertionError("Missing assertion signature element")
    if assertion.findtext(f".//{{{assertion_ns}}}Audience") != entity:
        raise AssertionError("Unexpected SAML assertion audience")
    attrs = {a.get("Name"): a.findtext(f"{{{assertion_ns}}}AttributeValue")
             for a in assertion.findall(f".//{{{assertion_ns}}}Attribute")}
    expected = {"login": "reader", "email": "reader@example.test", "role": "Viewer"}
    if any(attrs.get(k) != v for k, v in expected.items()):
        raise AssertionError("Unexpected SAML attribute mapping")
    return expected


if __name__ == "__main__":
    import argparse
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--channel")
    args = cli.parse_args()
    grafana = "http://127.0.0.1:18930"
    with start_idp(grafana) as fixture:
        verify_assertion(fixture, grafana, args.channel)
        print("PASS Keycloak SAML metadata, POST response, signature element, audience and Viewer attributes")
