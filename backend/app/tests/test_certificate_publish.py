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

from app.tools import certificate_publish
from app.tools.certificate_publish import (
    _certificate_name,
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


def test_publish_skips_load_balancer_update_when_bundle_is_current(tmp_path):
    lineage = tmp_path / "lineage"
    _write_lineage(lineage, "129.159.177.238")
    material = load_certificate_material(lineage, "129.159.177.238")
    certificate_name = _certificate_name(material, "oci_lip_ip")
    ssl_configuration = SimpleNamespace(
        certificate_name=certificate_name,
        certificate_ids=[],
        verify_depth=5,
        verify_peer_certificate=False,
        has_session_resumption=False,
        trusted_certificate_authority_ids=[],
        protocols=["TLSv1.2", "TLSv1.3"],
        cipher_suite_name="oci-default-ssl-cipher-suite-v1",
        server_order_preference="ENABLED",
    )
    load_balancer = SimpleNamespace(
        listeners={
            "https": SimpleNamespace(
                ssl_configuration=ssl_configuration,
            )
        },
        certificates={certificate_name: SimpleNamespace()},
    )

    class Client:
        def get_load_balancer(self, load_balancer_id):
            assert load_balancer_id == "ocid1.loadbalancer.example"
            return SimpleNamespace(data=load_balancer)

        def create_certificate(self, *args, **kwargs):
            raise AssertionError("an unchanged certificate must not be created")

        def update_listener(self, *args, **kwargs):
            raise AssertionError("an unchanged listener must not be updated")

        def delete_certificate(self, *args, **kwargs):
            raise AssertionError("an unchanged certificate must not be deleted")

    result = publish_certificate(
        Client(),
        material,
        load_balancer_id="ocid1.loadbalancer.example",
        listener_name="https",
        certificate_prefix="oci_lip_ip",
        public_ip="129.159.177.238",
        verify_endpoint=False,
        verify_timeout_seconds=1,
    )

    assert result["action"] == "unchanged"
    assert result["certificate_name"] == certificate_name


def _listener(certificate_name: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        default_backend_set_name="oci-lip-backends",
        port=443,
        protocol="HTTP",
        hostname_names=[],
        path_route_set_name=None,
        routing_policy_name=None,
        connection_configuration=SimpleNamespace(idle_timeout=60),
        rule_set_names=[],
        ssl_configuration=SimpleNamespace(
            certificate_name=certificate_name,
            certificate_ids=[] if certificate_name else ["ocid1.certificate.example"],
            verify_depth=5,
            verify_peer_certificate=False,
            has_session_resumption=False,
            trusted_certificate_authority_ids=[],
            protocols=["TLSv1.2", "TLSv1.3"],
            cipher_suite_name="oci-default-ssl-cipher-suite-v1",
            server_order_preference="ENABLED",
        ),
    )


class _LoadBalancerClient:
    def __init__(
        self,
        listener: SimpleNamespace | None,
        certificates: dict[str, SimpleNamespace] | None = None,
    ) -> None:
        self.load_balancer = SimpleNamespace(
            listeners={"https": listener} if listener else {},
            certificates=certificates or {},
        )
        self.created: list[str] = []
        self.updated: list[object] = []
        self.deleted: list[str] = []

    @staticmethod
    def _response() -> SimpleNamespace:
        return SimpleNamespace(headers={"opc-work-request-id": "work-request"})

    def get_load_balancer(self, load_balancer_id):
        assert load_balancer_id == "ocid1.loadbalancer.example"
        return SimpleNamespace(data=self.load_balancer)

    def get_work_request(self, work_request_id):
        assert work_request_id == "work-request"
        return SimpleNamespace(data=SimpleNamespace(lifecycle_state="SUCCEEDED"))

    def create_certificate(self, details, load_balancer_id):
        assert load_balancer_id == "ocid1.loadbalancer.example"
        self.created.append(details.certificate_name)
        return self._response()

    def update_listener(self, details, load_balancer_id, listener_name):
        assert load_balancer_id == "ocid1.loadbalancer.example"
        assert listener_name == "https"
        self.updated.append(details.ssl_configuration)
        return self._response()

    def delete_certificate(self, load_balancer_id, certificate_name):
        assert load_balancer_id == "ocid1.loadbalancer.example"
        self.deleted.append(certificate_name)
        return self._response()


def _publish(client, material):
    return publish_certificate(
        client,
        material,
        load_balancer_id="ocid1.loadbalancer.example",
        listener_name="https",
        certificate_prefix="oci_lip_ip",
        public_ip="129.159.177.238",
        verify_endpoint=True,
        verify_timeout_seconds=1,
    )


def test_publish_creates_unattached_bundle_when_https_listener_is_absent(tmp_path, monkeypatch):
    lineage = tmp_path / "lineage"
    _write_lineage(lineage, "129.159.177.238")
    material = load_certificate_material(lineage, "129.159.177.238")
    client = _LoadBalancerClient(None)
    monkeypatch.setattr(certificate_publish, "verify_public_endpoint", lambda *a, **k: True)

    result = _publish(client, material)

    assert result["action"] == "created_unattached"
    assert client.created == [result["certificate_name"]]
    assert client.updated == []


def test_publish_rotates_listener_and_removes_prior_managed_bundle(tmp_path, monkeypatch):
    lineage = tmp_path / "lineage"
    _write_lineage(lineage, "129.159.177.238")
    material = load_certificate_material(lineage, "129.159.177.238")
    old_name = "oci_lip_ip_old"
    client = _LoadBalancerClient(
        _listener(old_name),
        {old_name: SimpleNamespace()},
    )
    monkeypatch.setattr(certificate_publish, "verify_public_endpoint", lambda *a, **k: True)

    result = _publish(client, material)

    assert result["action"] == "updated"
    assert client.created == [result["certificate_name"]]
    assert client.updated[0].certificate_name == result["certificate_name"]
    assert client.updated[0].certificate_ids is None
    assert client.deleted == [old_name]


def test_publish_restores_listener_and_deletes_new_bundle_on_verification_failure(
    tmp_path, monkeypatch
):
    lineage = tmp_path / "lineage"
    _write_lineage(lineage, "129.159.177.238")
    material = load_certificate_material(lineage, "129.159.177.238")
    client = _LoadBalancerClient(_listener())

    def fail_verification(*args, **kwargs):
        raise TimeoutError("certificate did not become active")

    monkeypatch.setattr(
        certificate_publish,
        "verify_public_endpoint",
        fail_verification,
    )

    with pytest.raises(TimeoutError, match="did not become active"):
        _publish(client, material)

    assert len(client.updated) == 2
    assert client.updated[0].certificate_name is not None
    assert client.updated[1].certificate_ids == ["ocid1.certificate.example"]
    assert client.updated[1].certificate_name is None
    assert client.deleted == [client.created[0]]
