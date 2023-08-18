import flask
import pytest


def test_authorize_error(client):
    resp = client.get(
        "http://localhost/authorize?error=dummy_error&error_description=Dummy+Error"
    )
    assert resp.status_code == 401
    assert "<p>dummy_error: Dummy Error</p>" in resp.get_data(as_text=True)


def test_authorize_no_return_url(client, mocked_responses, dummy_token):
    mocked_responses.post("https://test/openidc/Token", json=dummy_token)
    mocked_responses.get("https://test/openidc/UserInfo", json={"nickname": "dummy"})
    with client.session_transaction() as session:
        session["_state_oidc_dummy_state"] = {"data": {}}
    resp = client.get("/authorize?state=dummy_state&code=dummy_code")
    assert resp.status_code == 302
    assert resp.location == "http://localhost/"


def test_authorize_no_user_info(test_app, client, mocked_responses, dummy_token):
    test_app.config["OIDC_USER_INFO_ENABLED"] = False
    mocked_responses.post("https://test/openidc/Token", json=dummy_token)
    with client.session_transaction() as session:
        session["_state_oidc_dummy_state"] = {"data": {}}
    resp = client.get("/authorize?state=dummy_state&code=dummy_code")
    assert resp.status_code == 302
    assert "oidc_auth_token" in flask.session
    assert "oidc_auth_profile" not in flask.session


def test_logout(client, dummy_token):
    with client.session_transaction() as session:
        session["oidc_auth_token"] = dummy_token
        session["oidc_auth_profile"] = {"nickname": "dummy"}
    resp = client.get("/logout")
    assert resp.status_code == 302
    assert resp.location == "http://localhost/"
    assert "oidc_auth_token" not in flask.session
    assert "oidc_auth_profile" not in flask.session
    flashes = flask.get_flashed_messages()
    assert len(flashes) == 1
    assert flashes[0] == "You were successfully logged out."


def test_logout_expired(client, dummy_token):
    with client.session_transaction() as session:
        session["oidc_auth_token"] = dummy_token
        session["oidc_auth_profile"] = {"nickname": "dummy"}
    client.get("/logout?reason=expired")
    flashes = flask.get_flashed_messages()
    assert len(flashes) == 1
    assert flashes[0] == "Your session expired, please reconnect."


def test_oidc_callback_route(test_app, client, dummy_token):
    with pytest.warns(DeprecationWarning):
        resp = client.get("/oidc_callback?state=dummy-state&code=dummy-code")
    assert resp.status_code == 302
    assert resp.location == "/authorize?state=dummy-state&code=dummy-code"
