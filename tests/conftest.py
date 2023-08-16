import json
import time
from unittest import mock

import pytest
import responses
from pkg_resources import resource_filename

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
    return resource_filename(__name__, "client_secrets.json")


@pytest.fixture(scope="session")
def client_secrets(client_secrets_path):
    """The parsed contents of `client_secrets.json`."""
    with open(client_secrets_path) as f:
        return json.load(f)["web"]


@pytest.fixture(scope="session")
def oidc_server_metadata(client_secrets):
    """IdP server metadata used in tests."""
    base_url = client_secrets["issuer"].rstrip("/")
    return {
        "issuer": f"{base_url}/",
        "authorization_endpoint": f"{base_url}/Authorization",
        "token_endpoint": f"{base_url}/Token",
        "userinfo_endpoint": f"{base_url}/UserInfo",
        # "jwks_uri": f"{base_url}/Jwks",
    }


@pytest.fixture
def test_app(oidc_server_metadata, client_secrets_path):
    """A Flask app object set up for testing."""
    test_app = app.create_app(
        {
            "SECRET_KEY": "SEEEKRIT",
            "TESTING": True,
            "OIDC_CLIENT_SECRETS": client_secrets_path,
        },
        {},
    )

    with mock.patch.object(
        app.oidc.oauth.oidc, "load_server_metadata"
    ) as load_server_metadata:
        load_server_metadata.return_value = oidc_server_metadata
        yield test_app


@pytest.fixture
def mocked_responses():
    with responses.RequestsMock() as rsps:
        yield rsps


@pytest.fixture
def test_client(test_app):
    """A Flask test client for the test app."""
    return test_app.test_client()


@pytest.fixture
def client(test_client):
    """A Flask test client for the test app."""
    with test_client:
        yield test_client
