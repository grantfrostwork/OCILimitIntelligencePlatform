from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import socket
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import oci
from cryptography import x509
from cryptography.hazmat.primitives import serialization


@dataclass(frozen=True)
class CertificateMaterial:
    certificate_pem: str
    chain_pem: str
    private_key_pem: str
    serial_number: int
    fingerprint_sha256: str
    not_before: datetime
    not_after: datetime
    version_name: str


def utcnow() -> datetime:
    return datetime.now(UTC)


def load_certificate_material(
    lineage: Path,
    expected_ip: str,
    *,
    min_remaining_hours: int = 96,
    now: datetime | None = None,
) -> CertificateMaterial:
    now = now or utcnow()
    ip = ipaddress.ip_address(expected_ip)
    certificate_pem = (lineage / "cert.pem").read_text()
    chain_pem = (lineage / "chain.pem").read_text()
    private_key_pem = (lineage / "privkey.pem").read_text()

    certificate = x509.load_pem_x509_certificate(certificate_pem.encode())
    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    cert_public_key = certificate.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_public_key = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if cert_public_key != key_public_key:
        raise ValueError("certificate and private key do not match")

    try:
        ip_addresses = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value.get_values_for_type(x509.IPAddress)
    except x509.ExtensionNotFound as exc:
        raise ValueError("certificate does not contain a subject alternative name") from exc
    if ip not in ip_addresses:
        raise ValueError(f"certificate does not contain the expected IP SAN {expected_ip}")

    not_before = certificate.not_valid_before_utc
    not_after = certificate.not_valid_after_utc
    if not_before > now + timedelta(minutes=5):
        raise ValueError("certificate is not valid yet")
    if not_after <= now + timedelta(hours=min_remaining_hours):
        raise ValueError(
            f"certificate has less than {min_remaining_hours} hours of validity remaining"
        )

    fingerprint = certificate.fingerprint(certificate.signature_hash_algorithm).hex()
    sha256_fingerprint = hashlib.sha256(
        certificate.public_bytes(serialization.Encoding.DER)
    ).hexdigest()
    return CertificateMaterial(
        certificate_pem=certificate_pem,
        chain_pem=chain_pem,
        private_key_pem=private_key_pem,
        serial_number=certificate.serial_number,
        fingerprint_sha256=sha256_fingerprint,
        not_before=not_before,
        not_after=not_after,
        version_name=f"letsencrypt-{fingerprint[:20]}",
    )


def _client(region: str, auth_mode: str) -> Any:
    config: dict[str, Any] = {"region": region}
    kwargs: dict[str, Any] = {
        "retry_strategy": oci.retry.DEFAULT_RETRY_STRATEGY,
        "timeout": (10, 60),
    }
    if auth_mode == "instance_principal":
        kwargs["signer"] = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    elif auth_mode == "profile":
        config = oci.config.from_file(
            file_location=os.getenv("OCI_CONFIG_FILE", "~/.oci/config"),
            profile_name=os.getenv("OCI_PROFILE", "DEFAULT"),
        )
        config["region"] = region
    else:
        raise ValueError(f"unsupported OCI auth mode: {auth_mode}")
    return oci.load_balancer.LoadBalancerClient(config, **kwargs)


def _wait_for_work_request(
    client: Any,
    response: Any,
    *,
    timeout_seconds: int = 600,
) -> None:
    work_request_id = response.headers.get("opc-work-request-id")
    if not work_request_id:
        raise RuntimeError("OCI Load Balancer response did not include a work request ID")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        work_request = client.get_work_request(work_request_id).data
        if work_request.lifecycle_state == "SUCCEEDED":
            return
        if work_request.lifecycle_state == "FAILED":
            errors = getattr(work_request, "error_details", None) or []
            raise RuntimeError(f"OCI Load Balancer work request failed: {errors}")
        time.sleep(5)
    raise TimeoutError("timed out waiting for the OCI Load Balancer work request")


def _certificate_name(material: CertificateMaterial, prefix: str) -> str:
    clean_prefix = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_" for character in prefix
    ).strip("_")
    if not clean_prefix:
        raise ValueError("load balancer certificate prefix must contain a valid character")
    return f"{clean_prefix}_{material.fingerprint_sha256[:24]}"


def _ssl_details(current: Any, certificate_name: str | None = None) -> Any:
    return oci.load_balancer.models.SSLConfigurationDetails(
        verify_depth=current.verify_depth,
        verify_peer_certificate=current.verify_peer_certificate,
        has_session_resumption=current.has_session_resumption,
        trusted_certificate_authority_ids=list(current.trusted_certificate_authority_ids or []),
        certificate_ids=(list(current.certificate_ids or []) if certificate_name is None else None),
        certificate_name=certificate_name or current.certificate_name,
        protocols=list(current.protocols or []),
        cipher_suite_name=current.cipher_suite_name,
        server_order_preference=current.server_order_preference,
    )


def _listener_update_details(listener: Any, ssl_configuration: Any) -> Any:
    return oci.load_balancer.models.UpdateListenerDetails(
        default_backend_set_name=listener.default_backend_set_name,
        port=listener.port,
        protocol=listener.protocol,
        hostname_names=list(listener.hostname_names or []),
        path_route_set_name=listener.path_route_set_name,
        routing_policy_name=listener.routing_policy_name,
        ssl_configuration=ssl_configuration,
        connection_configuration=listener.connection_configuration,
        rule_set_names=list(listener.rule_set_names or []),
    )


def _create_load_balancer_certificate(
    client: Any,
    load_balancer_id: str,
    name: str,
    material: CertificateMaterial,
) -> None:
    details = oci.load_balancer.models.CreateCertificateDetails(
        certificate_name=name,
        public_certificate=material.certificate_pem,
        ca_certificate=material.chain_pem,
        private_key=material.private_key_pem,
    )
    _wait_for_work_request(
        client,
        client.create_certificate(details, load_balancer_id),
    )


def _update_listener_certificate(
    client: Any,
    load_balancer_id: str,
    listener_name: str,
    listener: Any,
    ssl_configuration: Any,
) -> None:
    _wait_for_work_request(
        client,
        client.update_listener(
            _listener_update_details(listener, ssl_configuration),
            load_balancer_id,
            listener_name,
        ),
    )


def _delete_load_balancer_certificate(
    client: Any,
    load_balancer_id: str,
    name: str,
) -> None:
    _wait_for_work_request(
        client,
        client.delete_certificate(load_balancer_id, name),
    )


def _delete_stale_certificates(
    client: Any,
    load_balancer_id: str,
    certificates: dict[str, Any],
    *,
    certificate_prefix: str,
    current_name: str,
) -> None:
    managed_prefix = f"{certificate_prefix}_"
    for name in certificates:
        if name != current_name and name.startswith(managed_prefix):
            _delete_load_balancer_certificate(client, load_balancer_id, name)


def publish_certificate(
    client: Any,
    material: CertificateMaterial,
    *,
    load_balancer_id: str,
    listener_name: str,
    certificate_prefix: str,
    public_ip: str,
    verify_endpoint: bool,
    verify_timeout_seconds: int,
) -> dict[str, Any]:
    load_balancer = client.get_load_balancer(load_balancer_id).data
    name = _certificate_name(material, certificate_prefix)
    listener = load_balancer.listeners.get(listener_name)
    if listener is None:
        if name not in load_balancer.certificates:
            _create_load_balancer_certificate(
                client,
                load_balancer_id,
                name,
                material,
            )
        return {
            "action": "created_unattached",
            "load_balancer_id": load_balancer_id,
            "certificate_name": name,
            "endpoint_verified": False,
        }
    if listener.ssl_configuration is None:
        raise ValueError(f"load balancer listener {listener_name} does not use TLS")

    current_name = listener.ssl_configuration.certificate_name
    if current_name == name:
        endpoint_verified = (
            verify_public_endpoint(
                public_ip,
                material.fingerprint_sha256,
                timeout_seconds=verify_timeout_seconds,
            )
            if verify_endpoint
            else False
        )
        _delete_stale_certificates(
            client,
            load_balancer_id,
            load_balancer.certificates,
            certificate_prefix=certificate_prefix,
            current_name=name,
        )
        return {
            "action": "unchanged",
            "load_balancer_id": load_balancer_id,
            "certificate_name": name,
            "endpoint_verified": endpoint_verified,
        }

    if name not in load_balancer.certificates:
        _create_load_balancer_certificate(
            client,
            load_balancer_id,
            name,
            material,
        )

    previous_ssl = _ssl_details(listener.ssl_configuration)
    _update_listener_certificate(
        client,
        load_balancer_id,
        listener_name,
        listener,
        _ssl_details(listener.ssl_configuration, certificate_name=name),
    )

    endpoint_verified = False
    try:
        if verify_endpoint:
            endpoint_verified = verify_public_endpoint(
                public_ip,
                material.fingerprint_sha256,
                timeout_seconds=verify_timeout_seconds,
            )
    except Exception:
        _update_listener_certificate(
            client,
            load_balancer_id,
            listener_name,
            listener,
            previous_ssl,
        )
        _delete_load_balancer_certificate(client, load_balancer_id, name)
        raise

    _delete_stale_certificates(
        client,
        load_balancer_id,
        load_balancer.certificates,
        certificate_prefix=certificate_prefix,
        current_name=name,
    )

    return {
        "action": "updated",
        "load_balancer_id": load_balancer_id,
        "certificate_name": name,
        "endpoint_verified": endpoint_verified,
    }


def verify_public_endpoint(
    public_ip: str,
    expected_fingerprint_sha256: str,
    *,
    timeout_seconds: int = 600,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    context = ssl.create_default_context()
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with (
                socket.create_connection((public_ip, 443), timeout=10) as raw_socket,
                context.wrap_socket(raw_socket, server_hostname=public_ip) as tls_socket,
            ):
                served = tls_socket.getpeercert(binary_form=True)
                if hashlib.sha256(served).hexdigest() == expected_fingerprint_sha256:
                    return True
        except (OSError, ssl.SSLError) as exc:
            last_error = exc
        time.sleep(10)
    detail = f": {last_error}" if last_error else ""
    raise TimeoutError(f"load balancer did not serve the renewed certificate{detail}")


def _read_status(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_status(path: Path, status: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _lineage_from_args(value: str | None) -> Path:
    lineage = value or os.getenv("RENEWED_LINEAGE")
    if not lineage:
        raise ValueError("--lineage or RENEWED_LINEAGE is required")
    return Path(lineage)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish a renewed IP certificate to an OCI Load Balancer listener."
    )
    parser.add_argument("--lineage")
    args = parser.parse_args()

    status_path = Path(
        os.getenv(
            "LIP_CERTIFICATE_STATUS_PATH",
            "/var/lib/oci-lip/certificate/status.json",
        )
    )
    status = _read_status(status_path)
    now = utcnow()
    try:
        public_ip = os.environ["LIP_CERTIFICATE_IP"]
        material = load_certificate_material(
            _lineage_from_args(args.lineage),
            public_ip,
            min_remaining_hours=int(os.getenv("LIP_CERTIFICATE_MIN_REMAINING_HOURS", "96")),
            now=now,
        )
        result = publish_certificate(
            _client(
                os.getenv("OCI_DEFAULT_REGION", "us-ashburn-1"),
                os.getenv("OCI_AUTH_MODE", "instance_principal"),
            ),
            material,
            load_balancer_id=os.environ["LIP_LOAD_BALANCER_ID"],
            listener_name=os.getenv("LIP_LOAD_BALANCER_LISTENER_NAME", "https"),
            certificate_prefix=os.getenv(
                "LIP_LOAD_BALANCER_CERTIFICATE_PREFIX",
                "oci_lip_ip",
            ),
            public_ip=public_ip,
            verify_endpoint=os.getenv("LIP_CERTIFICATE_VERIFY_ENDPOINT", "true").lower()
            in {"1", "true", "yes", "on"},
            verify_timeout_seconds=int(os.getenv("LIP_CERTIFICATE_VERIFY_TIMEOUT_SECONDS", "600")),
        )
        status.update(
            {
                **result,
                "fingerprint_sha256": material.fingerprint_sha256,
                "not_before": material.not_before.isoformat(),
                "not_after": material.not_after.isoformat(),
                "last_success_timestamp": now.isoformat(),
                "last_error": None,
                "failure_count": int(status.get("failure_count", 0)),
            }
        )
        _write_status(status_path, status)
        print(json.dumps(status, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - record all deploy-hook failures before exit.
        status.update(
            {
                "last_failure_timestamp": now.isoformat(),
                "last_error": str(exc),
                "failure_count": int(status.get("failure_count", 0)) + 1,
            }
        )
        _write_status(status_path, status)
        print(f"certificate publication failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
