# SPDX-FileCopyrightText: 2014-2015 Erica Ehrhardt
# SPDX-FileCopyrightText: 2016-2022 Patrick Uiterwijk <patrick@puiterwijk.org>
# SPDX-FileCopyrightText: 2023 Aurélien Bompard <aurelien@bompard.org>
#
# SPDX-License-Identifier: BSD-2-Clause

import time
from importlib import metadata
from unittest import mock
from urllib.parse import parse_qs, urlparse, urlsplit

import flask
import pytest
import responses
from authlib.common.urls import url_decode
from packaging.version import Version
from packaging.version import parse as parse_version
from werkzeug.exceptions import Unauthorized

from flask_oidc import OpenIDConnect

from .app import oidc as oidc_ext
from .utils import set_token


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


def test_logout_redirect_loop(make_test_app, dummy_token, mocked_responses):
    app = make_test_app({"APPLICATION_ROOT": "/subpath"})
    client = app.test_client()
    with client:
        # Set an expired token
        mocked_responses.post(
            "https://test/openidc/Token", json={"error": "dummy"}, status=401
        )
        dummy_token["expires_at"] = int(time.time())
        set_token(client, dummy_token)

        resp = client.get("/logout?reason=expired")
        assert resp.location == "http://localhost/subpath/"
        assert "oidc_auth_token" not in flask.session


def test_expired_token(client, dummy_token, mocked_responses):
    new_token = dummy_token.copy()
    new_token["access_token"] = "this-is-new"
    refresh_call = mocked_responses.post("https://test/openidc/Token", json=new_token)

    dummy_token["expires_at"] = int(time.time())
    set_token(client, dummy_token)

    resp = client.get("/")

    # Make sure we called the token url properly
    assert refresh_call.call_count == 1
    call = mocked_responses.calls[1].request
    body = parse_qs(call.body)
    assert body == {
        "grant_type": ["refresh_token"],
        "refresh_token": ["dummy_refresh_token"],
        "scope": ["openid email"],
        "client_id": ["MyClient"],
        "client_secret": ["MySecret"],
    }
    # Check that we have the new token in the session
    assert "oidc_auth_token" in flask.session
    assert flask.session["oidc_auth_token"]["access_token"] == "this-is-new"
    # Make sure we went through with the page request
    assert resp.status_code == 200


def test_expired_token_cant_renew(client, dummy_token, mocked_responses):
    refresh_call = mocked_responses.post(
        "https://test/openidc/Token", json={"error": "dummy"}, status=401
    )

    dummy_token["expires_at"] = int(time.time())
    set_token(client, dummy_token)

    resp = client.get("/")

    assert refresh_call.call_count == 1
    assert resp.status_code == 302
    assert resp.location == "/logout?reason=expired"
    resp = client.get(resp.location)
    assert resp.status_code == 302
    assert resp.location == "http://localhost/"
    assert "oidc_auth_token" not in flask.session


def test_expired_token_no_refresh_token(client, dummy_token):
    del dummy_token["refresh_token"]
    dummy_token["expires_at"] = int(time.time())
    set_token(client, dummy_token)

    resp = client.get("/")

    assert resp.status_code == 302
    assert resp.location == "/logout?reason=expired"
    resp = client.get(resp.location)
    assert resp.status_code == 302
    assert resp.location == "http://localhost/"
    assert "oidc_auth_token" not in flask.session


def test_bad_token(client):
    set_token(client, "bad_token")
    resp = client.get("/")
    assert resp.status_code == 500
    assert "Internal Server Error" in resp.get_data(as_text=True)


def test_redirect_obsolete_argument(test_app):
    with test_app.test_request_context(path="/somewhere"):
        with pytest.warns(DeprecationWarning):
            resp = test_app.oidc_ext.redirect_to_auth_server(None, "dummy")
    assert resp.status_code == 302
    assert resp.location == "/login?next=http%3A%2F%2Flocalhost%2Fsomewhere"


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


def test_scopes_as_list(make_test_app):
    with pytest.warns():
        app = make_test_app({"OIDC_SCOPES": ["openid", "profile", "email"]})
    assert app.config["OIDC_SCOPES"] == "openid profile email"


def test_bad_scopes(make_test_app):
    with pytest.raises(ValueError):
        make_test_app({"OIDC_SCOPES": "profile email"})


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


def test_obsolete_config_params(make_test_app):
    with pytest.raises(ValueError):
        make_test_app({"OIDC_GOOGLE_APPS_DOMAIN": "example.com"})
    with pytest.warns(DeprecationWarning):
        make_test_app({"OIDC_ID_TOKEN_COOKIE_PATH": "/path"})


def test_custom_callback(test_app):
    with pytest.raises(ValueError):
        oidc_ext.custom_callback(None)


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


def test_resource_server_only(make_test_app):
    app = make_test_app({"OIDC_RESOURCE_SERVER_ONLY": True})
    client = app.test_client()
    with mock.patch.object(oidc_ext, "check_token_expiry") as check_token_expiry:
        for url in ("/oidc_callback", "/login", "/logout", "/authorize"):
            resp = client.get(url)
            assert resp.status_code == 404
        check_token_expiry.assert_not_called()


def test_oidc_callback_route(make_test_app):
    with pytest.warns():
        app = make_test_app({"OIDC_CALLBACK_ROUTE": "/dummy_cb"})
    client = app.test_client()
    resp = client.get("/login")
    assert resp.status_code == 302
    assert "redirect_uri=http%3A%2F%2Flocalhost%2Fdummy_cb" in resp.location
    with pytest.warns():
        resp = client.get("/dummy_cb?dummy_arg=dummy_value")
    assert resp.status_code == 302
    assert resp.location == "/authorize?dummy_arg=dummy_value"


def test_oidc_overwrite_redirect_uri_deprecated(make_test_app):
    with pytest.warns():
        app = make_test_app({"OVERWRITE_REDIRECT_URI": "http://localhost/dummy_cb"})
    assert app.config.get("OIDC_OVERWRITE_REDIRECT_URI", "http://localhost/dummy_cb")


def test_oidc_overwrite_redirect_uri(make_test_app):
    app = make_test_app({"OIDC_OVERWRITE_REDIRECT_URI": "http://localhost/dummy_cb"})
    client = app.test_client()
    resp = client.get("/login")
    assert resp.status_code == 302
    assert "redirect_uri=http%3A%2F%2Flocalhost%2Fdummy_cb" in resp.location
