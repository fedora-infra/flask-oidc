# SPDX-FileCopyrightText: 2014-2015 Erica Ehrhardt
# SPDX-FileCopyrightText: 2016-2022 Patrick Uiterwijk <patrick@puiterwijk.org>
# SPDX-FileCopyrightText: 2023 Aurélien Bompard <aurelien@bompard.org>
#
# SPDX-License-Identifier: BSD-2-Clause

import flask
import pytest

from .utils import set_token


def test_user_in_view(client, dummy_token):
    set_token(client, dummy_token)

    resp = client.get("/")
    assert resp.status_code == 200

    assert hasattr(flask.g, "oidc_user")
    user = flask.g.oidc_user

    assert user.logged_in
    assert user.access_token == dummy_token["access_token"]
    assert user.refresh_token == dummy_token["refresh_token"]
    assert user.profile == {"nickname": "dummy", "email": "dummy@example.com"}
    assert user.name == "dummy"
    assert user.email == "dummy@example.com"


def test_user_with_groups(client, dummy_token):
    set_token(client, dummy_token, {"groups": ["dummy_group"]})

    resp = client.get("/")
    assert resp.status_code == 200

    assert hasattr(flask.g, "oidc_user")
    user = flask.g.oidc_user
    assert user.profile == {
        "nickname": "dummy",
        "email": "dummy@example.com",
        "groups": ["dummy_group"],
    }
    assert user.groups == ["dummy_group"]


def test_user_no_user_info(client, test_app, dummy_token):
    set_token(client, dummy_token)
    test_app.config["OIDC_USER_INFO_ENABLED"] = False

    resp = client.get("/")
    assert resp.status_code == 200

    assert hasattr(flask.g, "oidc_user")
    user = flask.g.oidc_user

    with pytest.raises(RuntimeError):
        user.profile

    with pytest.raises(RuntimeError):
        user.name

    with pytest.raises(RuntimeError):
        user.groups


def test_user_no_user(make_test_app, dummy_token):
    test_app = make_test_app({"OIDC_USER_CLASS": None})
    client = test_app.test_client()
    with client:
        set_token(client, dummy_token)
        resp = client.get("/")

        assert resp.status_code == 200
        assert not hasattr(flask.g, "oidc_user")


class OtherUser:
    def __init__(self, ext):
        pass


def test_user_special_user_class(make_test_app, dummy_token):
    test_app = make_test_app({"OIDC_USER_CLASS": f"{__name__}.OtherUser"})
    client = test_app.test_client()
    with client:
        set_token(client, dummy_token)
        resp = client.get("/")

        assert resp.status_code == 200
        assert hasattr(flask.g, "oidc_user")
        assert isinstance(flask.g.oidc_user, OtherUser)
