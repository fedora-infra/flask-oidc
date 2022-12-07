import codecs
import json
import time
from pkg_resources import resource_filename, resource_stream
from unittest import mock
from urllib.parse import parse_qs, urlencode, urlparse, urlsplit

import pytest
from authlib.common.urls import url_decode
from flask import session

from . import app
from .authlib_utils import get_bearer_token, mock_send_value

last_request = None


@pytest.fixture(scope="session")
def client_secrets():
    """The parsed contents of `client_secrets.json`."""
    with resource_stream(__name__, "client_secrets.json") as f:
        return json.load(codecs.getreader("utf-8")(f))["web"]


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
def test_app(isolate_app_globals, oidc_server_metadata):
    """A Flask app object set up for testing."""
    test_app = app.create_app(
        {
            "SECRET_KEY": "SEEEKRIT",
            "TESTING": True,
            "OIDC_CLIENT_SECRETS": resource_filename(__name__, "client_secrets.json"),
        },
        {},
    )

    with mock.patch.object(
        app.oidc.oauth.oidc, "load_server_metadata"
    ) as load_server_metadata:
        load_server_metadata.return_value = oidc_server_metadata
        yield test_app


@pytest.fixture
def test_client(test_app):
    """A Flask test client for the test app."""
    return test_app.test_client()


def callback_url_for(response):
    """
    Take a redirect to the IdP and turn it into a redirect from the IdP.
    :return: The URL that the IdP would have redirected the user to.
    """
    location = urlsplit(response.headers["Location"])
    query = parse_qs(location.query)
    state = query["state"][0]
    callback_url = "/oidc_callback?" + urlencode(
        {"state": state, "code": "mock_auth_code"}
    )
    return callback_url


@mock.patch("time.time", mock.Mock(return_value=time.time()))
def test_signin(test_app, test_client):
    """
    Happy path authentication test.
    """
    with test_app.test_request_context():
        # make an unauthenticated request,
        # which should result in a redirect to the IdP
        r1 = test_client.get("/")
        assert r1.status_code == 302, (
            "Expected redirect to IdP "
            "(response status was {response.status})".format(response=r1)
        )
        url = r1.headers.get("Location")
        assert "state=" in url
        state = dict(url_decode(urlparse(url).query))["state"]
        assert state is not None
        #data = session[f"_state_oidc_{state}"]
        data = session

    with test_app.test_request_context(path=f"/?code=a&state={state}"), mock.patch(
        "requests.sessions.Session.send"
    ) as send:
        # session is cleared after exiting test context
        session[f"_state_oidc_{state}"] = data

        send.return_value = mock_send_value(get_bearer_token())

        # the app should now contact the IdP
        # to exchange that auth code for credentials
        r2 = test_client.get(callback_url_for(r1))
        assert r2.status_code == 302, (
            "Expected redirect to destination "
            "(response status was {response.status})".format(response=r2)
        )
        r2location = urlsplit(r2.headers["Location"])
        assert r2location.path == "/", (
            "Expected redirect to destination "
            "(unexpected path {location.path})".format(location=r2location)
        )

       # # Let's get the at and rt
       # r3 = test_client.get("/at")
       # assert r3.status_code == 200, "Expected access token to succeed"
       # page_text = "".join(codecs.iterdecode(r3.response, "utf-8"))
       # assert page_text == "mock_access_token", "Access token expected"
       # r4 = test_client.get("/rt")
       # assert r4.status_code == 200, "Expected refresh token to succeed"
       # page_text = "".join(codecs.iterdecode(r4.response, "utf-8"))
       # assert page_text == "mock_refresh_token", "Refresh token expected"


## @mock.patch('httplib2.Http', MockHttp)
#def test_refresh(test_client):
#    """
#    Test token expiration and refresh.
#    """
#    with mock.patch("time.time", mock.Mock(return_value=time.time())) as time_1:
#        # authenticate and get an ID token cookie
#        auth_redirect = test_client.get("/")
#        callback_redirect = test_client.get(callback_url_for(auth_redirect))
#        actual_page = test_client.get(callback_redirect.headers["Location"])
#        page_text = "".join(codecs.iterdecode(actual_page.response, "utf-8"))
#        assert page_text == "too many secrets", "Authentication failed"
#
#    # app should now try to use the refresh token
#    with mock.patch("time.time", mock.Mock(return_value=time.time() + 10)) as time_2:
#        test_client.get("/")
#        body = parse_qs(last_request["body"])
#        assert body.get("refresh_token") == [
#            "mock_refresh_token"
#        ], "App should have tried to refresh credentials"


#def _check_api_token_handling(test_client, api_path):
#    """
#    Test API token acceptance.
#    """
#    # Test without a token
#    resp = test_client.get(api_path)
#    assert resp.status_code == 401, "Token should be required"
#    resp = json.loads(resp.get_data().decode("utf-8"))
#    assert resp["error"] == "invalid_token", "Token should be requested"
#
#    # Test with invalid token
#    resp = test_client.get(api_path + "?access_token=invalid_token")
#    assert resp.status_code == 401, "Token should be rejected"
#
#    # Test with query token
#    resp = test_client.get(api_path + "?access_token=query_token")
#    assert resp.status_code == 200, "Token should be accepted"
#    resp = json.loads(resp.get_data().decode("utf-8"))
#    assert resp["token"]["sub"] == "valid_sub"
#
#    # Test with post token
#    resp = test_client.post(api_path, data={"access_token": "post_token"})
#    assert resp.status_code == 200, "Token should be accepted"
#
#    # Test with insufficient token
#    resp = test_client.post(api_path + "?access_token=insufficient_token")
#    assert resp.status_code == 401, "Token should be refused"
#    resp = json.loads(resp.get_data().decode("utf-8"))
#    assert resp["error"] == "invalid_token"
#
#    # Test with multiple audiences
#    resp = test_client.get(api_path + "?access_token=multi_aud_token")
#    assert resp.status_code == 200, "Token should be accepted"
#
#    # Test with token for another audience
#    resp = test_client.get(api_path + "?access_token=some_elses_token")
#    assert resp.status_code == 200, "Token should be accepted"
#    test_client.application.config["OIDC_RESOURCE_CHECK_AUD"] = True
#    resp = test_client.get(api_path + "?access_token=some_elses_token")
#    assert resp.status_code == 401, "Token should be refused"
#
#
## @mock.patch('httplib2.Http', MockHttp)
#def test_api_token(test_client):
#    _check_api_token_handling(test_client, "/api")
#
#
## @mock.patch('httplib2.Http', MockHttp)
#def test_api_token_with_external_rendering(test_client):
#    _check_api_token_handling(test_client, "/external_api")
