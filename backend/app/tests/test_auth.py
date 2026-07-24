import pytest

from app.core.auth import role_from_claims, user_from_claims
from app.core.config import Settings


def test_role_mapping_uses_highest_matching_lip_group():
    settings = Settings()
    claims = {
        "sub": "user-1",
        "email": "operator@example.com",
        "name": "OCI Operator",
        "groups": [
            {"display": "OCI-LIP-Viewers"},
            {"displayName": "OCI-LIP-Operators"},
        ],
    }

    user = user_from_claims(claims, settings)

    assert user is not None
    assert user.role == "operator"
    assert user.email == "operator@example.com"
    assert user.groups == ("OCI-LIP-Viewers", "OCI-LIP-Operators")


def test_role_mapping_rejects_unassigned_user():
    settings = Settings()

    assert role_from_claims(
        {"email": "unassigned@example.com", "groups": ["Unrelated"]},
        settings,
    ) is None


def test_bootstrap_admin_email_is_case_insensitive():
    settings = Settings(auth_bootstrap_admin_emails=["Admin@Example.com"])

    assert role_from_claims({"email": "admin@example.com"}, settings) == "admin"


def test_nested_group_claim_path_is_supported():
    settings = Settings(auth_group_claim="identity.groups")

    assert (
        role_from_claims(
            {"identity": {"groups": [{"name": "OCI-LIP-Admins"}]}},
            settings,
        )
        == "admin"
    )


def test_enabled_authentication_fails_closed_without_oidc_configuration():
    settings = Settings(
        auth_enabled=True,
        auth_public_url="https://lip.example.com",
        auth_cookie_secure=True,
        auth_session_secret="a" * 32,
    )

    with pytest.raises(RuntimeError, match="AUTH_OIDC_DISCOVERY_URL"):
        settings.validate_auth_configuration()


def test_enabled_authentication_requires_https_and_secure_cookie():
    settings = Settings(
        auth_enabled=True,
        auth_public_url="http://lip.example.com",
        auth_cookie_secure=False,
        auth_session_secret="a" * 32,
        auth_oidc_discovery_url="https://identity.example.com/.well-known/openid-configuration",
        auth_oidc_client_id="client",
        auth_oidc_client_secret="secret",
    )

    with pytest.raises(RuntimeError, match="AUTH_PUBLIC_URL"):
        settings.validate_auth_configuration()
