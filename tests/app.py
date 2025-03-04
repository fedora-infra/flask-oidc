# SPDX-FileCopyrightText: 2014-2015 Erica Ehrhardt
# SPDX-FileCopyrightText: 2016-2022 Patrick Uiterwijk <patrick@puiterwijk.org>
# SPDX-FileCopyrightText: 2023 Aurélien Bompard <aurelien@bompard.org>
#
# SPDX-License-Identifier: BSD-2-Clause

"""
Flask app for testing the OpenID Connect extension.
"""

import json

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
    return oidc.get_access_token(), 200, {"Content-Type": "text/plain; charset=utf-8"}


@bp.route("/rt")
@oidc.require_login
def get_rt():
    return oidc.get_refresh_token(), 200, {"Content-Type": "text/plain; charset=utf-8"}


@bp.route("/get-profile")
@oidc.require_login
def get_profile():
    return json.dumps(g.oidc_user.profile)


@oidc.require_login
def raw_api():
    return {"token": g.oidc_token_info}


@bp.route("/api", methods=["GET", "POST"])
@oidc.require_login
def api():
    return json.dumps(raw_api())


@bp.route("/need-token")
@oidc.accept_token()
def need_token():
    return "OK"


@bp.route("/need-profile")
@oidc.accept_token(scopes=["profile"])
def need_profile():
    return "OK"


def create_app(config, oidc_overrides=None):
    oidc_overrides = oidc_overrides or {}
    app = Flask(__name__)
    app.config.update(config)
    oidc.init_app(app, **oidc_overrides)
    # useful for tests
    app.oidc_ext = oidc

    app.register_blueprint(bp)
    # Check combination with an external API renderer like Flask-RESTful

    def externally_rendered_api(*args, **kwds):
        inner_response = raw_api(*args, **kwds)
        if isinstance(inner_response, tuple):
            raw_response, response_code, headers = inner_response
            rendered_response = json.dumps(raw_response), response_code, headers
        else:
            rendered_response = json.dumps(inner_response)
        return rendered_response

    app.add_url_rule(
        "/external_api", view_func=externally_rendered_api, methods=["GET", "POST"]
    )

    return app
