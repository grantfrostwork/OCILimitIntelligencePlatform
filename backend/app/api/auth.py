from __future__ import annotations

from functools import lru_cache
from urllib.parse import urljoin

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user, user_from_claims
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models import AuditLog

router = APIRouter(prefix="/api/auth", tags=["auth"])


@lru_cache(maxsize=4)
def _oauth(
    discovery_url: str,
    client_id: str,
    client_secret: str,
    scopes: str,
) -> OAuth:
    oauth = OAuth()
    oauth.register(
        name="oci",
        server_metadata_url=discovery_url,
        client_id=client_id,
        client_secret=client_secret,
        client_kwargs={"scope": scopes},
    )
    return oauth


def _client(settings: Settings):
    settings.validate_auth_configuration()
    oauth = _oauth(
        settings.auth_oidc_discovery_url or "",
        settings.auth_oidc_client_id or "",
        settings.auth_oidc_client_secret or "",
        settings.auth_oidc_scopes,
    )
    return oauth.create_client("oci")


def _safe_next(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


@router.get("/login")
async def login(
    request: Request,
    next_path: str | None = Query(default=None, alias="next"),
    settings: Settings = Depends(get_settings),
):
    if not settings.auth_enabled:
        return RedirectResponse(url="/")
    request.session["post_login_path"] = _safe_next(next_path)
    redirect_uri = urljoin(settings.auth_public_url.rstrip("/") + "/", "api/auth/callback")
    return await _client(settings).authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def callback(
    request: Request,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    try:
        token = await _client(settings).authorize_access_token(request)
    except OAuthError:
        request.session.clear()
        return RedirectResponse(url="/?auth_error=login_failed", status_code=303)

    claims = token.get("userinfo")
    if not isinstance(claims, dict):
        claims = await _client(settings).userinfo(token=token)
    user = user_from_claims(dict(claims), settings)
    if user is None:
        db.add(
            AuditLog(
                actor=str(claims.get("email") or claims.get("sub") or "unknown"),
                action="auth.denied",
                target="oci-iam",
            )
        )
        db.commit()
        request.session.clear()
        return RedirectResponse(
            url="/?auth_error=not_authorized",
            status_code=303,
        )
    next_path = _safe_next(request.session.get("post_login_path"))
    request.session.clear()
    request.session["user"] = user.to_session()
    db.add(
        AuditLog(
            actor=user.email,
            action="auth.login",
            target=user.subject,
            detail={"role": user.role},
        )
    )
    db.commit()
    return RedirectResponse(url=next_path, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/me")
def me(
    user: AuthUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    return {
        "authenticated": True,
        "enabled": settings.auth_enabled,
        "subject": user.subject,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "groups": list(user.groups),
    }


@router.get("/verify")
def verify(
    response: Response,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    response.headers["X-Auth-User"] = user.subject
    response.headers["X-Auth-Email"] = user.email
    response.headers["X-Auth-Name"] = user.display_name
    response.headers["X-Auth-Role"] = user.role
    return {"authenticated": True, "role": user.role}


@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> dict:
    db.add(
        AuditLog(
            actor=user.email,
            action="auth.logout",
            target=user.subject,
        )
    )
    db.commit()
    request.session.clear()
    return {"status": "signed_out"}
