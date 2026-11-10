import jwt
from fastapi import Header, HTTPException

from api.app.core.config import get_settings


def get_current_user_id(x_user_id: str | None = Header(default=None)) -> str:
    settings = get_settings()
    if settings.app_env in {"development", "test"} and settings.dev_user_id:
        return x_user_id or settings.dev_user_id
    raise HTTPException(
        status_code=401,
        detail="Authentication is not configured for this environment.",
    )


def get_current_user_role(
    authorization: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
) -> str:
    settings = get_settings()
    if settings.app_env in {"development", "test"}:
        return x_user_role if x_user_role in {"learner", "instructor", "admin"} else "learner"
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token is required.")
    if not settings.oidc_issuer or not settings.oidc_audience or not settings.oidc_jwks_uri:
        raise HTTPException(status_code=503, detail="Production authentication is not configured.")
    try:
        token = authorization.removeprefix("Bearer ")
        key = jwt.PyJWKClient(settings.oidc_jwks_uri).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key=key,
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            algorithms=["RS256"],
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid bearer token.") from exc
    roles = claims.get("roles", [])
    if isinstance(roles, str):
        roles = [roles]
    if "admin" in roles:
        return "admin"
    if "instructor" in roles:
        return "instructor"
    return "learner"
