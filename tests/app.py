# SPDX-FileCopyrightText: 2014-2015 Erica Ehrhardt
# SPDX-FileCopyrightText: 2016-2022 Patrick Uiterwijk <patrick@puiterwijk.org>
# SPDX-FileCopyrightText: 2023 Aurélien Bompard <aurelien@bompard.org>
#
# SPDX-License-Identifier: BSD-2-Clause

"""
Flask app for testing the OpenID Connect extension.
"""

import json

from authlib.integrations.flask_oauth2 import current_token
from flask import Blueprint, Flask, g

from flask_oidc import OpenIDConnect

oidc = OpenIDConnect()
bp = Blueprint("main", __name__)


@bp.route("/")
@oidc.require_login
def index():
    return "too many secrets", 200, {"Content-Type": "text/plain; charset=utf-8"}


@bp.route("/at")
@oidc.require_login
def get_at():
    return (
        oidc.get_access_token() or "failed",
        200,
        {"Content-Type": "text/plain; charset=utf-8"},
    )


@bp.route("/rt")
@oidc.require_login
def get_rt():
    return (
        oidc.get_refresh_token() or "failed",
        200,
        {"Content-Type": "text/plain; charset=utf-8"},
    )


@bp.route("/get-profile")
@oidc.require_login
def get_profile():
    return json.dumps(g.oidc_user.profile)


@bp.route("/need-token")
@oidc.accept_token()
def need_token():
    return "OK"


@bp.route("/need-profile")
@oidc.accept_token(scopes=["profile"])
def need_profile():
    profile = g._oidc_auth.userinfo(token=current_token)
    return json.dumps(profile)


def create_app(config, oidc_overrides=None):
    oidc_overrides = oidc_overrides or {}
    app = Flask(__name__)
    app.config.update(config)
    oidc.init_app(app, **oidc_overrides)
    # useful for tests
    app.oidc_ext = oidc

    app.register_blueprint(bp)
    return app
