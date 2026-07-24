from __future__ import annotations

import ipaddress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.tools.certificate_publish import (
    load_certificate_material,
    publish_certificate,
)


def _write_lineage(path: Path, ip: str) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ip)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=6))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    path.mkdir()
    (path / "cert.pem").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    (path / "chain.pem").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    (path / "privkey.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def test_load_certificate_material_validates_ip_and_key(tmp_path):
    lineage = tmp_path / "lineage"
    _write_lineage(lineage, "129.159.177.238")

    material = load_certificate_material(lineage, "129.159.177.238")

    assert material.not_after > datetime.now(UTC) + timedelta(days=5)
    assert len(material.fingerprint_sha256) == 64
    assert material.version_name.startswith("letsencrypt-")


def test_load_certificate_material_rejects_wrong_ip(tmp_path):
    lineage = tmp_path / "lineage"
    _write_lineage(lineage, "129.159.177.238")

    with pytest.raises(ValueError, match="expected IP SAN"):
        load_certificate_material(lineage, "129.159.177.239")


def test_load_certificate_material_rejects_mismatched_private_key(tmp_path):
    lineage = tmp_path / "lineage"
    _write_lineage(lineage, "129.159.177.238")
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (lineage / "privkey.pem").write_bytes(
        wrong_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    with pytest.raises(ValueError, match="do not match"):
        load_certificate_material(lineage, "129.159.177.238")


def test_publish_skips_oci_update_when_serial_is_current(tmp_path):
    lineage = tmp_path / "lineage"
    _write_lineage(lineage, "129.159.177.238")
    material = load_certificate_material(lineage, "129.159.177.238")
    certificate = SimpleNamespace(
        current_version=SimpleNamespace(
            serial_number=str(material.serial_number),
            version_number=3,
        )
    )

    class Client:
        def get_certificate(self, certificate_id):
            assert certificate_id == "ocid1.certificate.example"
            return SimpleNamespace(data=certificate)

        def update_certificate(self, *args, **kwargs):
            raise AssertionError("an unchanged certificate must not be updated")

    result = publish_certificate(
        Client(),
        material,
        certificate_id="ocid1.certificate.example",
        compartment_id="ocid1.compartment.example",
        certificate_name="oci-lip-ip",
        public_ip="129.159.177.238",
        verify_endpoint=False,
        verify_timeout_seconds=1,
    )

    assert result["action"] == "unchanged"
    assert result["version_number"] == 3
