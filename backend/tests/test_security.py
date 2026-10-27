import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import AppError
from app.main import app
from app.security import TokenVerifier, get_verifier


@pytest.fixture
def signer(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = TokenVerifier(
        Settings(
            _env_file=None,
            environment="test",
            supabase_url="https://sana-test.supabase.co",
            supabase_publishable_key="sb_publishable_test",
        )
    )

    class SigningKey:
        pass

    signing_key = SigningKey()
    signing_key.key = key.public_key()
    monkeypatch.setattr(verifier.jwks, "get_signing_key_from_jwt", lambda token: signing_key)
    claims = {
        "sub": str(uuid.uuid4()),
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "iss": "https://sana-test.supabase.co/auth/v1",
        "aud": "authenticated",
        "role": "authenticated",
        "user_metadata": {"display_name": "Айдана"},
    }
    return key, verifier, claims


def test_valid_signature_and_identity(signer):
    key, verifier, claims = signer
    identity = verifier.verify(jwt.encode(claims, key, algorithm="RS256"))
    assert str(identity.id) == claims["sub"]
    assert identity.display_name == "Айдана"


@pytest.mark.parametrize(
    "change",
    [
        {"exp": 1},
        {"aud": "wrong"},
        {"iss": "https://attacker.example/auth/v1"},
        {"role": "service_role"},
        {"sub": "invalid"},
        {"is_anonymous": True},
        {"iat": 9999999999},
    ],
)
def test_invalid_claims_rejected(signer, change):
    key, verifier, claims = signer
    with pytest.raises(AppError, match="invalid_token"):
        verifier.verify(jwt.encode({**claims, **change}, key, algorithm="RS256"))


def test_signature_and_algorithm_confusion_rejected(signer):
    _key, verifier, claims = signer
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token in [
        jwt.encode(claims, other, algorithm="RS256"),
        jwt.encode(claims, "not-a-public-key" * 3, algorithm="HS256"),
        "nonsense",
    ]:
        with pytest.raises(AppError, match="invalid_token"):
            verifier.verify(token)


def test_anonymous_and_expired_api_access_denied(signer):
    key, verifier, claims = signer
    app.dependency_overrides[get_verifier] = lambda: verifier
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/profile").status_code == 401
            token = jwt.encode({**claims, "exp": 1}, key, algorithm="RS256")
            assert (
                client.get(
                    "/api/v1/profile", headers={"Authorization": f"Bearer {token}"}
                ).status_code
                == 401
            )
            assert (
                client.get(
                    "/api/v1/materials", headers={"Authorization": "Bearer invalid"}
                ).status_code
                == 401
            )
    finally:
        app.dependency_overrides.clear()


def test_no_secret_key_in_public_config():
    with pytest.raises(ValueError):
        Settings(_env_file=None, supabase_publishable_key="sb_secret_test")
    legacy = jwt.encode({"role": "service_role"}, "a" * 32, algorithm="HS256")
    with pytest.raises(ValueError):
        Settings(_env_file=None, supabase_publishable_key=legacy)


def test_unconfigured_auth_is_explicit():
    verifier = TokenVerifier(Settings(_env_file=None))
    with pytest.raises(AppError, match="auth_not_configured"):
        verifier.verify("some-token")


def test_legacy_auth_server_verification_is_required(signer, monkeypatch):
    import httpx

    key, original, claims = signer
    verifier = TokenVerifier(original.settings.model_copy(update={"auth_mode": "auth_server"}))
    token = jwt.encode(claims, key, algorithm="RS256")
    status, identity = 200, claims["sub"]

    def response(url, **kwargs):
        assert url == original.issuer + "/user"
        assert kwargs["headers"]["Authorization"] == "Bearer " + token
        assert kwargs["follow_redirects"] is False
        return httpx.Response(status, json={"id": identity})

    monkeypatch.setattr(httpx, "get", response)
    assert str(verifier.verify(token).id) == claims["sub"]
    identity = str(uuid.uuid4())
    with pytest.raises(AppError, match="invalid_token"):
        verifier.verify(token)
    status = 401
    with pytest.raises(AppError, match="invalid_token"):
        verifier.verify(token)
    status = 503
    with pytest.raises(AppError, match="auth_unavailable"):
        verifier.verify(token)
