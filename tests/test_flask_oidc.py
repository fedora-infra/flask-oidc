import time
from importlib import metadata
from unittest import mock
from urllib.parse import parse_qs, urlparse, urlsplit

import flask
import pytest
import responses
from authlib.common.urls import url_decode
from packaging.version import Version, parse as parse_version
from werkzeug.exceptions import Unauthorized

from flask_oidc import OpenIDConnect


def callback_url_for(response):
    """
    Take a redirect to the IdP and turn it into a redirect from the IdP.
    :return: The URL that the IdP would have redirected the user to.
    """
    location = urlparse(response.location)
    query = parse_qs(location.query)
    return f"{query['redirect_uri'][0]}?state={query['state'][0]}&code=mock_auth_code"


def test_signin(test_app, client, mocked_responses, dummy_token):
    """Happy path authentication test."""
    mocked_responses.post("https://test/openidc/Token", json=dummy_token)
    mocked_responses.get("https://test/openidc/UserInfo", json={"nickname": "dummy"})

    resp = client.get("/")
    assert (
        resp.status_code == 302
    ), f"Expected redirect to /login (response status was {resp.status})"
    resp = client.get(resp.location)
    assert (
        resp.status_code == 302
    ), f"Expected redirect to IdP (response status was {resp.status})"
    assert "state=" in resp.location
    state = dict(url_decode(urlparse(resp.location).query))["state"]
    assert state is not None

    # the app should now contact the IdP
    # to exchange that auth code for credentials
    resp = client.get(callback_url_for(resp))
    assert (
        resp.status_code == 302
    ), f"Expected redirect to destination (response status was {resp.status})"
    location = urlsplit(resp.location)
    assert (
        location.path == "/"
    ), f"Expected redirect to destination (unexpected path {location.path})"

    token_query = parse_qs(mocked_responses.calls[1][0].body)
    assert token_query == {
        "grant_type": ["authorization_code"],
        "redirect_uri": ["http://localhost/authorize"],
        "code": ["mock_auth_code"],
        "client_id": ["MyClient"],
        "client_secret": ["MySecret"],
    }

    # Let's get the at and rt
    resp = client.get("/at")
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "dummy_access_token"
    resp = client.get("/rt")
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "dummy_refresh_token"


def test_ext_logout(test_app, client, dummy_token):
    with test_app.test_request_context(path="/somewhere"):
        flask.session["oidc_auth_token"] = dummy_token
        flask.session["oidc_auth_profile"] = {"nickname": "dummy"}
        with pytest.warns():
            resp = test_app.oidc_ext.logout(return_to="/somewhere_else")
    expected = "/logout?next=/somewhere_else"
    if parse_version(metadata.version("werkzeug")) < Version("2.3"):
        expected = "/logout?next=%2Fsomewhere_else"
    assert resp.location == expected


def test_expired_token(client, dummy_token):
    dummy_token["expires_at"] = int(time.time())
    with client.session_transaction() as session:
        session["oidc_auth_token"] = dummy_token
        session["oidc_auth_profile"] = {"nickname": "dummy"}
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.location == "/logout?reason=expired"
    resp = client.get(resp.location)


def test_bad_token(client):
    with client.session_transaction() as session:
        session["oidc_auth_token"] = "bad_token"
        session["oidc_auth_profile"] = {"nickname": "dummy"}
    resp = client.get("/")
    assert resp.status_code == 500
    assert "oidc_auth_token" not in flask.session
    assert "oidc_auth_profile" not in flask.session
    assert "TypeError: string indices must be integers" in resp.get_data(as_text=True)


def test_user_getinfo(test_app, client, dummy_token):
    user_info = {"nickname": "dummy"}
    with test_app.test_request_context(path="/somewhere"):
        flask.session["oidc_auth_token"] = dummy_token
        flask.session["oidc_auth_profile"] = user_info
        with pytest.warns(DeprecationWarning):
            resp = test_app.oidc_ext.user_getinfo([])
    assert resp == user_info


def test_user_getinfo_anon(test_app, client, dummy_token):
    with test_app.test_request_context(path="/somewhere"):
        # User is not authenticated
        with pytest.warns(DeprecationWarning):
            with pytest.raises(Unauthorized):
                test_app.oidc_ext.user_getinfo([])


def test_user_getinfo_token(test_app, client, mocked_responses):
    token = {"access_token": "other-access-token"}
    mocked_responses.get(
        "https://test/openidc/UserInfo",
        json={"nickname": "dummy"},
        match=[
            responses.matchers.header_matcher(
                {"Authorization": "Bearer other-access-token"}
            )
        ],
    )
    with test_app.test_request_context(path="/somewhere"):
        with pytest.warns(DeprecationWarning):
            resp = test_app.oidc_ext.user_getinfo([], access_token=token)
    assert resp == {"nickname": "dummy"}


def test_user_getinfo_disabled(test_app, client, dummy_token):
    test_app.config["OIDC_USER_INFO_ENABLED"] = False
    with test_app.test_request_context(path="/somewhere"):
        with pytest.raises(RuntimeError):
            test_app.oidc_ext.user_getinfo([])


def test_user_getfield(test_app, client, dummy_token):
    user_info = {"nickname": "dummy"}
    with test_app.test_request_context(path="/somewhere"):
        flask.session["oidc_auth_token"] = dummy_token
        flask.session["oidc_auth_profile"] = user_info
        with pytest.warns(DeprecationWarning):
            resp = test_app.oidc_ext.user_getfield("nickname")
    assert resp == "dummy"


def test_init_app():
    app = flask.Flask("dummy")
    with mock.patch.object(OpenIDConnect, "init_app") as init_app:
        OpenIDConnect(app)
    init_app.assert_called_once_with(app, prefix=None)


def test_scopes_as_list(client_secrets_path):
    app = flask.Flask("dummy")
    app.config["OIDC_CLIENT_SECRETS"] = client_secrets_path
    app.config["OIDC_SCOPES"] = ["openid", "profile", "email"]
    with pytest.warns():
        OpenIDConnect(app)
    assert app.config["OIDC_SCOPES"] == "openid profile email"


def test_bad_scopes(client_secrets_path):
    app = flask.Flask("dummy")
    app.config["OIDC_CLIENT_SECRETS"] = client_secrets_path
    app.config["OIDC_SCOPES"] = "profile email"
    with pytest.raises(ValueError):
        OpenIDConnect(app)


def test_inline_client_secrets(client_secrets):
    app = flask.Flask("dummy")
    app.config["OIDC_CLIENT_SECRETS"] = {"web": client_secrets}
    OpenIDConnect(app)
    assert app.config["OIDC_CLIENT_ID"] == "MyClient"


def test_deprecated_class_params(client_secrets_path):
    for param_name in ("credentials_store", "http", "time", "urandom"):
        app = flask.Flask("dummy")
        app.config["OIDC_CLIENT_SECRETS"] = client_secrets_path
        with pytest.warns(DeprecationWarning):
            OpenIDConnect(app, **{param_name: "dummy"})


def test_obsolete_config_params(client_secrets_path):
    app = flask.Flask("dummy")
    app.config["OIDC_CLIENT_SECRETS"] = client_secrets_path
    with mock.patch.dict(app.config, {"OIDC_GOOGLE_APPS_DOMAIN": "example.com"}):
        with pytest.raises(ValueError):
            OpenIDConnect(app)
    with mock.patch.dict(app.config, {"OIDC_ID_TOKEN_COOKIE_PATH": "/path"}):
        with pytest.warns(DeprecationWarning):
            OpenIDConnect(app)


def test_custom_callback(client_secrets_path):
    app = flask.Flask("dummy")
    app.config["OIDC_CLIENT_SECRETS"] = client_secrets_path
    ext = OpenIDConnect(app)
    with pytest.raises(ValueError):
        ext.custom_callback(None)


def test_accept_token(client, mocked_responses):
    mocked_responses.post(
        "https://test/openidc/TokenInfo",
        json={
            "active": True,
            "scope": "openid",
        },
    )
    resp = client.get("/need-token", headers={"Authorization": "Bearer dummy-token"})
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "OK"


def test_accept_token_no_token(client, mocked_responses):
    resp = client.get("/need-token")
    assert resp.status_code == 401
    assert resp.json == {
        "error": "missing_authorization",
        "error_description": 'Missing "Authorization" in headers.',
    }


def test_accept_token_invalid(client, mocked_responses):
    mocked_responses.post(
        "https://test/openidc/TokenInfo",
        json={
            "active": False,
            "scope": "openid",
        },
    )
    resp = client.get("/need-token", headers={"Authorization": "Bearer dummy-token"})
    assert resp.status_code == 401
    assert resp.json == {
        "error": "invalid_token",
        "error_description": (
            "The access token provided is expired, revoked, malformed, or invalid "
            "for other reasons."
        ),
    }


def test_accept_token_profile(client, mocked_responses):
    mocked_responses.post(
        "https://test/openidc/TokenInfo",
        json={
            "active": True,
            "scope": "openid profile",
        },
    )
    resp = client.get("/need-profile", headers={"Authorization": "Bearer dummy-token"})
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "OK"


def test_accept_token_absent_scope(client, mocked_responses):
    mocked_responses.post(
        "https://test/openidc/TokenInfo",
        json={
            "active": True,
            "scope": "openid",
        },
    )
    resp = client.get("/need-profile", headers={"Authorization": "Bearer dummy-token"})
    assert resp.status_code == 403
    assert resp.json == {
        "error": "insufficient_scope",
        "error_description": (
            "The request requires higher privileges than provided by the access token."
        ),
    }


def test_introspection_unsupported(client, mocked_responses, oidc_server_metadata):
    metadata_without_introspection = oidc_server_metadata.copy()
    del metadata_without_introspection["introspection_endpoint"]
    mocked_responses.replace(
        responses.GET,
        "https://test/openidc/.well-known/openid-configuration",
        json=metadata_without_introspection,
    )
    with pytest.raises(RuntimeError):
        client.get("/need-token", headers={"Authorization": "Bearer dummy-token"})


def test_resource_server_only(client_secrets_path):
    app = flask.Flask("dummy")
    app.config["OIDC_CLIENT_SECRETS"] = client_secrets_path
    app.config["OIDC_RESOURCE_SERVER_ONLY"] = True
    client = app.test_client()
    ext = OpenIDConnect(app)
    with mock.patch.object(ext, "check_token_expiry") as check_token_expiry:
        for url in ("/oidc_callback", "/login", "/logout", "/authorize"):
            resp = client.get(url)
            assert resp.status_code == 404
        check_token_expiry.assert_not_called()


def test_no_userinfo_url(client_secrets, caplog):
    app = flask.Flask("dummy")
    client_secrets = client_secrets.copy()
    del client_secrets["userinfo_uri"]
    app.config["OIDC_CLIENT_SECRETS"] = {"web": client_secrets}
    OpenIDConnect(app)
    assert app.config["OIDC_USER_INFO_ENABLED"] is False
    assert len(caplog.messages) == 0


def test_no_userinfo_url_when_enabled(client_secrets, caplog):
    app = flask.Flask("dummy")
    client_secrets = client_secrets.copy()
    del client_secrets["userinfo_uri"]
    app.config["OIDC_USER_INFO_ENABLED"] = True
    app.config["OIDC_CLIENT_SECRETS"] = {"web": client_secrets}
    OpenIDConnect(app)
    assert app.config["OIDC_USER_INFO_ENABLED"] is False
    assert caplog.messages == [
        'No "userinfo_uri" entry was found in the client_secrets, retrieving user '
        "information is disabled."
    ]
