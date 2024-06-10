# SPDX-FileCopyrightText: 2014-2015 Erica Ehrhardt
# SPDX-FileCopyrightText: 2016-2022 Patrick Uiterwijk <patrick@puiterwijk.org>
# SPDX-FileCopyrightText: 2023 Aurélien Bompard <aurelien@bompard.org>
#
# SPDX-License-Identifier: BSD-2-Clause

import sys
import time
from collections import defaultdict

import flask
import pytest

from flask_oidc.signals import (
    after_authorize,
    after_logout,
    before_authorize,
    before_logout,
)

HAS_MULTIPLE_CONTEXT_MANAGERS = sys.hexversion >= 0x030900F0  # 3.9.0


@pytest.fixture()
def sent_signals():
    if not HAS_MULTIPLE_CONTEXT_MANAGERS:
        yield {}
        return

    sent = defaultdict(list)

    def record_signal(signal):
        def record(sender, **kwargs):
            sent[signal].append(kwargs)

        return signal.connected_to(record)

    with (
        record_signal(before_authorize),
        record_signal(after_authorize),
        record_signal(before_logout),
        record_signal(after_logout),
    ):
        yield sent


def test_authorize_error(client, sent_signals):
    resp = client.get(
        "http://localhost/authorize?error=dummy_error&error_description=Dummy+Error"
    )
    assert resp.status_code == 401
    assert "<p>dummy_error: Dummy Error</p>" in resp.get_data(as_text=True)
    # Model
    assert flask.g.oidc_user.logged_in is False
    # Signals
    if HAS_MULTIPLE_CONTEXT_MANAGERS:
        assert len(sent_signals[before_authorize]) == 1
        assert len(sent_signals[after_authorize]) == 0


def test_authorize_no_return_url(client, mocked_responses, dummy_token, sent_signals):
    mocked_responses.post("https://test/openidc/Token", json=dummy_token)
    mocked_responses.get("https://test/openidc/UserInfo", json={"nickname": "dummy"})
    with client.session_transaction() as session:
        session["_state_oidc_dummy_state"] = {"data": {}}
    resp = client.get("/authorize?state=dummy_state&code=dummy_code")
    assert resp.status_code == 302
    assert resp.location == "http://localhost/"
    # Signals
    if HAS_MULTIPLE_CONTEXT_MANAGERS:
        assert len(sent_signals[before_authorize]) == 1
        assert len(sent_signals[after_authorize]) == 1
        assert sent_signals[after_authorize][0]["token"] == dummy_token


def test_authorize_no_user_info(
    test_app, client, mocked_responses, dummy_token, sent_signals
):
    test_app.config["OIDC_USER_INFO_ENABLED"] = False
    mocked_responses.post("https://test/openidc/Token", json=dummy_token)
    with client.session_transaction() as session:
        session["_state_oidc_dummy_state"] = {"data": {}}
    resp = client.get("/authorize?state=dummy_state&code=dummy_code")
    assert resp.status_code == 302
    assert "oidc_auth_token" in flask.session
    assert "oidc_auth_profile" not in flask.session
    # Signals
    if HAS_MULTIPLE_CONTEXT_MANAGERS:
        assert len(sent_signals[before_authorize]) == 1
        assert len(sent_signals[after_authorize]) == 1
        assert sent_signals[after_authorize][0]["token"] == dummy_token


def test_logout(client, dummy_token, sent_signals):
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
    # Signals
    if HAS_MULTIPLE_CONTEXT_MANAGERS:
        assert len(sent_signals[before_logout]) == 1
        assert len(sent_signals[after_logout]) == 1


def test_logout_expired(client, dummy_token, sent_signals):
    dummy_token["expires_at"] = int(time.time())
    with client.session_transaction() as session:
        session["oidc_auth_token"] = dummy_token
        session["oidc_auth_profile"] = {"nickname": "dummy"}
    response = client.get("/logout?reason=expired")
    assert response.status_code == 302
    # This should not redirect forever to the logout page
    assert response.location == "http://localhost/"
    flashes = flask.get_flashed_messages()
    assert len(flashes) == 1
    assert flashes[0] == "Your session expired, please reconnect."
    # Signals
    if HAS_MULTIPLE_CONTEXT_MANAGERS:
        assert len(sent_signals[before_logout]) == 1
        assert len(sent_signals[after_logout]) == 1


def test_oidc_callback_route(test_app, client, dummy_token):
    with pytest.warns(DeprecationWarning):
        resp = client.get("/oidc_callback?state=dummy-state&code=dummy-code")
    assert resp.status_code == 302
    assert resp.location == "/authorize?state=dummy-state&code=dummy-code"
