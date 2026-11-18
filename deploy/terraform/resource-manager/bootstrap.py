#!/usr/bin/env python3
"""Fetch OIDC configuration directly from Vault; never print secret content."""
import base64
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from urllib.parse import urlparse


def environment(config, oidc, previous=None):
    if previous is not None:
        required = ("postgres_password", "grafana_password", "session_secret")
        if any(not isinstance(previous.get(k), str) or not previous[k] for k in required):
            raise ValueError("Generated secret backup is incomplete; refusing credential rotation")
    previous = previous or {}
    for key in ("discovery_url", "client_id", "client_secret"):
        if not isinstance(oidc.get(key), str) or not oidc[key].strip():
            raise ValueError("Vault JSON requires nonempty " + key)
    discovery = urlparse(oidc["discovery_url"])
    if discovery.scheme != "https" or not discovery.netloc or discovery.username:
        raise ValueError("OIDC discovery_url must be an HTTPS URL")
    admins = oidc.get("admin_emails")
    if not isinstance(admins, list) or not admins or not all(isinstance(e, str) and "@" in e for e in admins):
        raise ValueError("Vault JSON requires a nonempty admin_emails array")
    db_password = previous.get("postgres_password") or secrets.token_hex(24)
    generated = {
        "postgres_password": db_password,
        "grafana_password": previous.get("grafana_password") or secrets.token_hex(24),
        "session_secret": previous.get("session_secret") or secrets.token_hex(48),
    }
    values = {
        "ENVIRONMENT": "production",
        "POSTGRES_PASSWORD": db_password,
        "DATABASE_URL": f"postgresql+psycopg://lip:{db_password}@postgres:5432/lip",
        "CORS_ORIGINS": json.dumps([config["public_url"]]),
        "AUTH_ENABLED": "true", "AUTH_COOKIE_SECURE": "true",
        "AUTH_PUBLIC_URL": config["public_url"],
        "AUTH_SESSION_SECRET": generated["session_secret"],
        "AUTH_OIDC_DISCOVERY_URL": oidc["discovery_url"],
        "AUTH_OIDC_CLIENT_ID": oidc["client_id"],
        "AUTH_OIDC_CLIENT_SECRET": oidc["client_secret"],
        "AUTH_BOOTSTRAP_ADMIN_EMAILS": json.dumps(admins),
        "AUTH_VIEWER_GROUPS": json.dumps(oidc.get("viewer_groups", ["OCI-LIP-Viewers"])),
        "AUTH_OPERATOR_GROUPS": json.dumps(oidc.get("operator_groups", ["OCI-LIP-Operators"])),
        "AUTH_ADMIN_GROUPS": json.dumps(oidc.get("admin_groups", ["OCI-LIP-Admins"])),
        "OCI_AUTH_MODE": "instance_principal",
        "OCI_TENANCY_OCID": config["tenancy"], "OCI_DEFAULT_REGION": config["region"],
        "OCI_SCAN_ALL_REGIONS": str(config["scan_all_regions"]).lower(),
        "WARNING_THRESHOLD_PERCENT": str(config["warning"]),
        "CRITICAL_THRESHOLD_PERCENT": str(config["critical"]),
        "LIP_ENABLE_NOTIFICATIONS": "false",
        "LIP_NOTIFICATION_EMAILS": "[]",
        "LIP_NOTIFICATION_TOPIC_NAME": config["topic"],
        "LIP_NOTIFICATION_COMPARTMENT_OCID": config["notification_compartment"],
        "LIP_SCAN_INTERVAL_MINUTES": "240",
        "GRAFANA_ROOT_URL": config["public_url"] + "/grafana/",
        "GRAFANA_ADMIN_PASSWORD": generated["grafana_password"],
    }
    # Compose double-quoted syntax; escape interpolation as well as quotes/newlines.
    content = "".join(f"{key}={json.dumps(value).replace('$', '$$')}\n" for key, value in values.items())
    return content, generated


def atomic_write(path, content):
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    import oci
    os.umask(0o077)
    config = json.loads(Path("/etc/oci-lip/config.json").read_text())
    # Dynamic-group membership can take time to propagate. No SDK response is logged.
    oidc = None
    for attempt in range(60):
        try:
            signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
            client = oci.secrets.SecretsClient({"region": config["secret_region"]}, signer=signer)
            bundle = client.get_secret_bundle(config["secret"], stage="CURRENT").data
            oidc = json.loads(base64.b64decode(bundle.secret_bundle_content.content, validate=True))
            break
        except (oci.exceptions.ServiceError, oci.exceptions.RequestException):
            if attempt == 59:
                raise RuntimeError("Vault secret unavailable after 30 minutes; check IAM, region, secret OCID and network") from None
            time.sleep(30)
    state_path = Path("/etc/oci-lip/generated-secrets.json")
    env_path = Path("/opt/oci-lip/.env")
    if env_path.exists() and not state_path.exists():
        raise RuntimeError("Existing .env has no generated secret backup; refusing to rotate database credentials")
    previous = json.loads(state_path.read_text()) if state_path.exists() else None
    content, generated = environment(config, oidc, previous)
    atomic_write(state_path, json.dumps(generated))
    atomic_write(env_path, content)
    print("SSO configuration installed; secret values were not logged.")


if __name__ == "__main__":
    main()
