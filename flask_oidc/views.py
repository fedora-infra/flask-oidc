# Copyright (c) 2014-2015, Erica Ehrhardt
# Copyright (c) 2016, Patrick Uiterwijk <patrick@puiterwijk.org>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

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
    return g._oidc_auth.authorize_redirect(redirect_uri)


@auth_routes.route("/authorize", endpoint="authorize")
def authorize_view():
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
    session.pop("oidc_auth_token", None)
    session.pop("oidc_auth_profile", None)
    g.oidc_id_token = None
    reason = request.args.get("reason")
    if reason == "expired":
        flash("Your session expired, please reconnect.")
    else:
        flash("You were successfully logged out.")
    return_to = request.args.get("next", request.root_url)
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
