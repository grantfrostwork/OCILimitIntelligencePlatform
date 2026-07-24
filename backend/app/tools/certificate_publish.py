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
    return oci.certificates_management.CertificatesManagementClient(config, **kwargs)


def _wait_for_active(client: Any, certificate_id: str, timeout_seconds: int = 300) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        certificate = client.get_certificate(certificate_id).data
        if certificate.lifecycle_state == "ACTIVE":
            return certificate
        if certificate.lifecycle_state == "FAILED":
            raise RuntimeError(
                f"OCI certificate entered FAILED state: {certificate.lifecycle_details}"
            )
        time.sleep(5)
    raise TimeoutError("timed out waiting for the OCI certificate to become ACTIVE")


def _find_version(client: Any, certificate_id: str, version_name: str) -> int:
    response = oci.pagination.list_call_get_all_results(
        client.list_certificate_versions,
        certificate_id,
    )
    for version in response.data:
        if version.version_name == version_name:
            return int(version.version_number)
    raise RuntimeError(f"OCI certificate version {version_name} was not found")


def _create_certificate(
    client: Any,
    material: CertificateMaterial,
    compartment_id: str,
    name: str,
) -> str:
    details = oci.certificates_management.models.CreateCertificateDetails(
        name=name,
        description="Let's Encrypt short-lived IP certificate managed by OCI LIP",
        compartment_id=compartment_id,
        certificate_config=oci.certificates_management.models.CreateCertificateByImportingConfigDetails(
            version_name=material.version_name,
            certificate_pem=material.certificate_pem,
            cert_chain_pem=material.chain_pem,
            private_key_pem=material.private_key_pem,
        ),
        freeform_tags={
            "Application": "OCI-LIP",
            "ManagedBy": "OCI-LIP-Certificate-Renewer",
        },
    )
    response = client.create_certificate(details)
    certificate_id = response.data.id
    _wait_for_active(client, certificate_id)
    return certificate_id


def _find_certificate_by_name(
    client: Any,
    compartment_id: str,
    name: str,
) -> str | None:
    response = oci.pagination.list_call_get_all_results(
        client.list_certificates,
        compartment_id=compartment_id,
        name=name,
    )
    active = [
        certificate
        for certificate in response.data
        if certificate.name == name
        and certificate.lifecycle_state not in {"DELETED", "PENDING_DELETION"}
    ]
    if len(active) > 1:
        raise RuntimeError(f"multiple active OCI certificates are named {name}")
    return active[0].id if active else None


def _current_serial(certificate: Any) -> int | None:
    current = getattr(certificate, "current_version", None)
    serial = getattr(current, "serial_number", None)
    return int(serial) if serial is not None else None


def publish_certificate(
    client: Any,
    material: CertificateMaterial,
    *,
    certificate_id: str | None,
    compartment_id: str,
    certificate_name: str,
    public_ip: str,
    verify_endpoint: bool,
    verify_timeout_seconds: int,
) -> dict[str, Any]:
    if not certificate_id:
        certificate_id = _find_certificate_by_name(
            client,
            compartment_id,
            certificate_name,
        )
    created = not certificate_id
    previous_version: int | None = None
    if created:
        certificate_id = _create_certificate(
            client,
            material,
            compartment_id,
            certificate_name,
        )
        certificate = client.get_certificate(certificate_id).data
        version_number = int(certificate.current_version.version_number)
    else:
        certificate = client.get_certificate(certificate_id).data
        if _current_serial(certificate) == material.serial_number:
            return {
                "action": "unchanged",
                "certificate_id": certificate_id,
                "version_number": int(certificate.current_version.version_number),
                "endpoint_verified": verify_public_endpoint(
                    public_ip,
                    material.fingerprint_sha256,
                    timeout_seconds=verify_timeout_seconds,
                )
                if verify_endpoint
                else False,
            }

        previous_version = int(certificate.current_version.version_number)
        update_config = (
            oci.certificates_management.models.UpdateCertificateByImportingConfigDetails(
                version_name=material.version_name,
                stage="PENDING",
                certificate_pem=material.certificate_pem,
                cert_chain_pem=material.chain_pem,
                private_key_pem=material.private_key_pem,
            )
        )
        client.update_certificate(
            certificate_id,
            oci.certificates_management.models.UpdateCertificateDetails(
                certificate_config=update_config
            ),
        )
        _wait_for_active(client, certificate_id)
        version_number = _find_version(client, certificate_id, material.version_name)
        client.update_certificate(
            certificate_id,
            oci.certificates_management.models.UpdateCertificateDetails(
                current_version_number=version_number
            ),
        )
        certificate = _wait_for_active(client, certificate_id)
        if _current_serial(certificate) != material.serial_number:
            raise RuntimeError("OCI did not promote the renewed certificate version")

    endpoint_verified = False
    if verify_endpoint and not created:
        try:
            endpoint_verified = verify_public_endpoint(
                public_ip,
                material.fingerprint_sha256,
                timeout_seconds=verify_timeout_seconds,
            )
        except Exception:
            if previous_version is not None:
                client.update_certificate(
                    certificate_id,
                    oci.certificates_management.models.UpdateCertificateDetails(
                        current_version_number=previous_version
                    ),
                )
                _wait_for_active(client, certificate_id)
            raise

    return {
        "action": "created" if created else "updated",
        "certificate_id": certificate_id,
        "version_number": version_number,
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
        description="Publish a renewed Let's Encrypt IP certificate to OCI Certificates."
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
        certificate_id = os.getenv("LIP_CERTIFICATE_ID") or status.get("certificate_id") or None
        result = publish_certificate(
            _client(
                os.getenv("OCI_DEFAULT_REGION", "us-ashburn-1"),
                os.getenv("OCI_AUTH_MODE", "instance_principal"),
            ),
            material,
            certificate_id=certificate_id,
            compartment_id=os.getenv("LIP_CERTIFICATE_COMPARTMENT_OCID")
            or os.environ["OCI_TENANCY_OCID"],
            certificate_name=os.getenv(
                "LIP_CERTIFICATE_NAME",
                f"oci-lip-ip-{public_ip.replace('.', '-')}",
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
