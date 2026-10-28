import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

import httpx
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.errors import AppError

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Identity:
    id: uuid.UUID
    display_name: str
    language: str = "ru"


class TokenVerifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.issuer = settings.supabase_url + "/auth/v1"
        self.jwks = (
            jwt.PyJWKClient(self.issuer + "/.well-known/jwks.json", lifespan=300, timeout=5)
            if settings.supabase_url
            else None
        )

    def verify(self, token: str) -> Identity:
        if not self.settings.auth_configured:
            raise AppError("auth_not_configured", 503)
        if len(token) > 16384:
            raise AppError("invalid_token", 401)
        try:
            if self.settings.auth_mode == "auth_server":
                # Supabase verifies the signature and session. Recommended for legacy HS256.
                response = httpx.get(
                    self.issuer + "/user",
                    headers={
                        "apikey": self.settings.supabase_publishable_key,
                        "Authorization": "Bearer " + token,
                    },
                    timeout=8,
                    follow_redirects=False,
                )
                claims = self.remote_claims(token, response)
            else:
                # The untrusted header selects only among explicitly allowed asymmetric keys.
                algorithm = jwt.get_unverified_header(token).get("alg")
                if algorithm not in ("ES256", "RS256"):
                    raise AppError("invalid_token", 401)
                key = self.jwks.get_signing_key_from_jwt(token)
                claims = jwt.decode(
                    token,
                    key.key,
                    algorithms=[algorithm],
                    audience=self.settings.jwt_audience,
                    issuer=self.issuer,
                    options={"require": ["exp", "iat", "sub", "aud", "iss"]},
                )
            return self.identity_from_claims(claims)
        except AppError:
            raise
        except (httpx.HTTPError, jwt.PyJWKClientConnectionError) as error:
            raise AppError("auth_unavailable", 503) from error
        except (jwt.PyJWTError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise AppError("invalid_token", 401) from error

    def remote_claims(self, token: str, response: httpx.Response) -> dict:
        if response.status_code >= 500:
            raise AppError("auth_unavailable", 503)
        if response.status_code != 200:
            raise AppError("invalid_token", 401)
        user = response.json()
        claims = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
                "require": ["exp", "iat", "sub", "aud", "iss"],
            },
            audience=self.settings.jwt_audience,
            issuer=self.issuer,
        )
        if claims["sub"] != user["id"]:
            raise AppError("invalid_token", 401)
        return claims

    def identity_from_claims(self, claims: dict) -> Identity:
        if claims.get("role") != "authenticated" or claims.get("is_anonymous"):
            raise AppError("invalid_token", 401)
        user_id = uuid.UUID(claims["sub"])
        # Metadata is only a display preference. It never controls permissions or balances.
        metadata = claims.get("user_metadata", {})
        name = metadata.get("display_name") or metadata.get("full_name") or ""
        return Identity(
            user_id, str(name).strip()[:80], "kk" if metadata.get("language") == "kk" else "ru"
        )

    async def verify_remote_async(self, token: str) -> Identity:
        if not self.settings.auth_configured:
            raise AppError("auth_not_configured", 503)
        if len(token) > 16384:
            raise AppError("invalid_token", 401)
        try:
            # Workers must yield while Supabase verifies the session over HTTP.
            async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
                response = await client.get(
                    self.issuer + "/user",
                    headers={
                        "apikey": self.settings.supabase_publishable_key,
                        "Authorization": "Bearer " + token,
                    },
                )
            return self.identity_from_claims(self.remote_claims(token, response))
        except AppError:
            raise
        except httpx.HTTPError as error:
            raise AppError("auth_unavailable", 503) from error
        except (jwt.PyJWTError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise AppError("invalid_token", 401) from error


@lru_cache
def get_verifier() -> TokenVerifier:
    return TokenVerifier(get_settings())


async def get_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
) -> Identity:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise AppError("authentication_required", 401)
    if verifier.settings.runtime == "cloudflare":
        return await verifier.verify_remote_async(credentials.credentials)
    return verifier.verify(credentials.credentials)
