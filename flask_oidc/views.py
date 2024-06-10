# SPDX-FileCopyrightText: 2014-2015 Erica Ehrhardt
# SPDX-FileCopyrightText: 2016-2022 Patrick Uiterwijk <patrick@puiterwijk.org>
# SPDX-FileCopyrightText: 2023 Aurélien Bompard <aurelien@bompard.org>
#
# SPDX-License-Identifier: BSD-2-Clause

import logging
import warnings
from urllib.parse import urlparse

from authlib.integrations.base_client.errors import OAuthError
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    request,
    session,
    url_for,
)

from .signals import (
    after_authorize,
    after_logout,
    before_authorize,
    before_login_redirect,
    before_logout,
)

logger = logging.getLogger(__name__)

auth_routes = Blueprint("oidc_auth", __name__)


@auth_routes.route("/login", endpoint="login")
def login_view():
    if current_app.config["OIDC_OVERWRITE_REDIRECT_URI"]:
        redirect_uri = current_app.config["OIDC_OVERWRITE_REDIRECT_URI"]
    elif current_app.config["OIDC_CALLBACK_ROUTE"]:
        redirect_uri = (
            f"https://{request.host}{current_app.config['OIDC_CALLBACK_ROUTE']}"
        )
    else:
        redirect_uri = url_for("oidc_auth.authorize", _external=True)
    session["next"] = request.args.get("next", request.root_url)
    before_login_redirect.send(
        g._oidc_auth,
        redirect_uri=redirect_uri,
        next=session["next"],
    )
    return g._oidc_auth.authorize_redirect(redirect_uri)


@auth_routes.route("/authorize", endpoint="authorize")
def authorize_view():
    before_authorize.send(g._oidc_auth)
    try:
        token = g._oidc_auth.authorize_access_token()
    except OAuthError as e:
        logger.exception("Could not get the access token")
        abort(401, str(e))
    session["oidc_auth_token"] = token
    g.oidc_id_token = token
    if current_app.config["OIDC_USER_INFO_ENABLED"]:
        profile = g._oidc_auth.userinfo(token=token)
        session["oidc_auth_profile"] = profile
    try:
        return_to = session["next"]
        del session["next"]
    except KeyError:
        return_to = request.root_url
    after_authorize.send(g._oidc_auth, token=token, return_to=return_to)
    return redirect(return_to)


@auth_routes.route("/logout", endpoint="logout")
def logout_view():
    """
    Request the browser to please forget the cookie we set, to clear the
    current session.

    Note that as described in [1], this will not log out in the case of a
    browser that doesn't clear cookies when requested to, and the user
    could be automatically logged in when they hit any authenticated
    endpoint.

    [1]: https://github.com/puiterwijk/flask-oidc/issues/5#issuecomment-86187023

    .. versionadded:: 1.0
    """
    before_logout.send(g._oidc_auth)
    session.pop("oidc_auth_token", None)
    session.pop("oidc_auth_profile", None)
    g.oidc_id_token = None
    reason = request.args.get("reason")
    if reason == "expired":
        flash("Your session expired, please reconnect.")
    else:
        flash("You were successfully logged out.")
    return_to = request.args.get("next", request.root_url)
    after_logout.send(g._oidc_auth, reason=reason, return_to=return_to)
    return redirect(return_to)


def legacy_oidc_callback():
    warnings.warn(
        "The {callback_url} route is deprecated, please use {authorize_url}".format(
            callback_url=current_app.config["OIDC_CALLBACK_ROUTE"],
            authorize_url=url_for("oidc_auth.authorize"),
        ),
        DeprecationWarning,
        stacklevel=2,
    )
    return redirect(
        "{url}?{qs}".format(
            url=url_for("oidc_auth.authorize"), qs=urlparse(request.url).query
        )
    )
