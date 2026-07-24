from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings

Role = Literal["viewer", "operator", "admin"]
ROLE_LEVEL: dict[Role, int] = {"viewer": 10, "operator": 20, "admin": 30}


@dataclass(frozen=True)
class AuthUser:
    subject: str
    email: str
    display_name: str
    role: Role
    groups: tuple[str, ...]

    def to_session(self) -> dict[str, Any]:
        value = asdict(self)
        value["groups"] = list(self.groups)
        return value

    @classmethod
    def from_session(cls, value: dict[str, Any]) -> "AuthUser":
        role = value.get("role")
        if role not in ROLE_LEVEL:
            raise ValueError("Invalid role in session")
        return cls(
            subject=str(value.get("subject") or ""),
            email=str(value.get("email") or ""),
            display_name=str(value.get("display_name") or ""),
            role=role,
            groups=tuple(str(group) for group in value.get("groups") or []),
        )


def _claim_value(claims: dict[str, Any], path: str) -> Any:
    value: Any = claims
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _group_names(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    entries = value if isinstance(value, list) else [value]
    groups: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            name = entry
        elif isinstance(entry, dict):
            name = next(
                (
                    str(entry[key])
                    for key in ("display", "displayName", "name", "value")
                    if entry.get(key)
                ),
                "",
            )
        else:
            name = ""
        if name and name not in groups:
            groups.append(name)
    return tuple(groups)


def role_from_claims(claims: dict[str, Any], settings: Settings) -> Role | None:
    email = str(claims.get("email") or claims.get("preferred_username") or "").casefold()
    if email and email in {
        item.casefold() for item in settings.auth_bootstrap_admin_emails
    }:
        return "admin"

    groups = {
        group.casefold()
        for group in _group_names(_claim_value(claims, settings.auth_group_claim))
    }
    if groups.intersection(item.casefold() for item in settings.auth_admin_groups):
        return "admin"
    if groups.intersection(item.casefold() for item in settings.auth_operator_groups):
        return "operator"
    if groups.intersection(item.casefold() for item in settings.auth_viewer_groups):
        return "viewer"
    return None


def user_from_claims(claims: dict[str, Any], settings: Settings) -> AuthUser | None:
    role = role_from_claims(claims, settings)
    if role is None:
        return None
    email = str(claims.get("email") or claims.get("preferred_username") or "")
    subject = str(claims.get("sub") or email)
    display_name = str(claims.get("name") or claims.get("displayName") or email)
    groups = _group_names(_claim_value(claims, settings.auth_group_claim))
    return AuthUser(
        subject=subject,
        email=email,
        display_name=display_name,
        role=role,
        groups=groups,
    )


def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> AuthUser:
    if not settings.auth_enabled:
        return AuthUser(
            subject="local-development",
            email="local@oci-lip.invalid",
            display_name="Local administrator",
            role="admin",
            groups=("local-development",),
        )
    value = request.session.get("user")
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    try:
        return AuthUser.from_session(value)
    except ValueError as exc:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication session is invalid",
        ) from exc


def require_role(required: Role) -> Callable[..., AuthUser]:
    def dependency(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if ROLE_LEVEL[user.role] < ROLE_LEVEL[required]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"The {required} role is required",
            )
        return user

    return dependency


require_viewer = require_role("viewer")
require_operator = require_role("operator")
require_admin = require_role("admin")
