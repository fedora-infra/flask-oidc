import json
import time
from importlib.resources import path

import pytest
import responses

from . import app


@pytest.fixture
def dummy_token():
    return {
        "token_type": "Bearer",
        "access_token": "dummy_access_token",
        "refresh_token": "dummy_refresh_token",
        "expires_in": "3600",
        "expires_at": int(time.time()) + 3600,
    }


@pytest.fixture(scope="session")
def client_secrets_path():
    with path("tests", "client_secrets.json") as filepath:
        yield filepath.as_posix()


@pytest.fixture(scope="session")
def client_secrets(client_secrets_path):
    """The parsed contents of `client_secrets.json`."""
    with open(client_secrets_path) as f:
        return json.load(f)["web"]


@pytest.fixture
def mocked_responses():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture(scope="session")
def oidc_server_metadata(client_secrets):
    """IdP server metadata used in tests."""
    base_url = client_secrets["issuer"].rstrip("/")
    return {
        "issuer": f"{base_url}/",
        "authorization_endpoint": f"{base_url}/Authorization",
        "token_endpoint": f"{base_url}/Token",
        "userinfo_endpoint": f"{base_url}/UserInfo",
        "introspection_endpoint": f"{base_url}/TokenInfo",
        # "jwks_uri": f"{base_url}/Jwks",
    }


@pytest.fixture
def make_test_app(
    oidc_server_metadata, client_secrets_path, client_secrets, mocked_responses
):
    """Make a Flask app object set up for testing."""

    def _make_test_app(config=None, oidc_overrides=None):
        _config = {
            "SECRET_KEY": "SEEEKRIT",
            "TESTING": True,
            "OIDC_CLIENT_SECRETS": client_secrets_path,
        }
        _config.update(config or {})

        test_app = app.create_app(_config, oidc_overrides or {})

        base_url = client_secrets["issuer"].rstrip("/")
        mocked_responses.get(
            f"{base_url}/.well-known/openid-configuration", json=oidc_server_metadata
        )
        return test_app

    return _make_test_app


@pytest.fixture
def test_app(make_test_app):
    """A Flask app object set up for testing."""
    return make_test_app()


@pytest.fixture
def test_client(test_app):
    """A Flask test client for the test app."""
    return test_app.test_client()


@pytest.fixture
def client(test_client):
    """A Flask test client for the test app."""
    with test_client:
        yield test_client
