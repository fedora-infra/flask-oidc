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

import warnings
from urllib.parse import quote_plus
from authlib.integrations.flask_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
import time
import logging
import json
from functools import wraps
from urllib.parse import urlparse
from flask import request, session, redirect, url_for, g, current_app, abort, flash, Blueprint


__all__ = ["OpenIDConnect"]

logger = logging.getLogger(__name__)

auth_routes = Blueprint("oidc_auth", __name__)


@auth_routes.route("/login", endpoint="login")
def login_view():
    redirect_uri = url_for("oidc_auth.authorize", _external=True)
    session["next"] = request.args.get("next", request.root_url)
    return g._oidc_auth.authorize_redirect(redirect_uri)


@auth_routes.route("/authorize", endpoint="authorize")
def authorize_view():
    try:
        token = g._oidc_auth.authorize_access_token()
    except OAuthError as e:
        abort(401, str(e))
    profile = g._oidc_auth.userinfo(token=token)
    session["token"] = token
    g.oidc_id_token = token
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
    reason = request.args.get("reason")
    if reason == "expired":
        flash("Your session expired, please reconnect.")
    else:
        flash("You were successfully logged out.")
    return_to = request.args.get("next", request.root_url)
    return redirect(return_to)


class OpenIDConnect:
    def __init__(
        self, app=None, credentials_store=None, http=None, time=None, urandom=None, prefix=None,
    ):
        for param_name in ("credentials_store", "http", "time", "urandom"):
            if locals()[param_name] is not None:
                warnings.warn(
                    f"The {param_name!r} attibute is no longer used.",
                    DeprecationWarning, stacklevel=2
                )
        self._prefix = prefix
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        secrets = self.load_secrets(app)
        self.client_secrets = list(secrets.values())[0]

        app.config.setdefault("OIDC_VALID_ISSUERS", self.client_secrets["issuer"])
        app.config.setdefault("OIDC_CLIENT_ID", self.client_secrets["client_id"])
        app.config.setdefault("OIDC_CLIENT_SECRET", self.client_secrets["client_secret"])
        app.config.setdefault("OIDC_USERINFO_URL", self.client_secrets["userinfo_uri"])
        app.config.setdefault("OIDC_INTROSPECTION_AUTH_METHOD", "client_secret_post")
        app.config.setdefault("OIDC_CALLBACK_ROUTE", "/oidc_callback")

        app.config.setdefault("OIDC_SCOPES", "openid profile email")
        if not 'openid' in app.config['OIDC_SCOPES']:
            raise ValueError('The value "openid" must be in the OIDC_SCOPES')

        #app.config.from_file(app.config["OIDC_CLIENT_SECRETS"], load=json.load)
        app.config.setdefault(
            "OIDC_SERVER_METADATA_URL",
            f"{app.config['OIDC_VALID_ISSUERS']}/.well-known/openid-configuration",
        )

        self.oauth = OAuth(app)
        self.oauth.register(
            name="oidc",
            server_metadata_url=app.config["OIDC_SERVER_METADATA_URL"],
            client_kwargs={
                "scope": app.config["OIDC_SCOPES"],
                "token_endpoint_auth_method": app.config["OIDC_INTROSPECTION_AUTH_METHOD"],
            },
        )

        app.register_blueprint(auth_routes, url_prefix=self._prefix)
        app.route(app.config["OIDC_CALLBACK_ROUTE"])(self._oidc_callback)
        app.before_request(self._before_request)
        app.after_request(self._after_request)

    def load_secrets(self, app):
        # Load client_secrets.json to pre-initialize some configuration
        content_or_filepath = app.config['OIDC_CLIENT_SECRETS']
        if isinstance(content_or_filepath, dict):
            return content_or_filepath
        else:
            with open(content_or_filepath) as f:
                return json.load(f)

    def _before_request(self):
        return self.check_token_expiry()

    def _after_request(self, response):
        return response

    def _oidc_callback(self):
        warnings.warn(
            "The {callback_url} route is deprecated, please use {authorize_url}".format(
                callback_url=current_app.config["OIDC_CALLBACK_ROUTE"],
                authorize_url=url_for("oidc_auth.authorize"),
            ),
            DeprecationWarning,
            stacklevel=2,
        )
        return redirect("{url}?{qs}".format(
            url=url_for("oidc_auth.authorize"),
            qs=urlparse(request.url).query)
        )

    def check_token_expiry(self):
        try:
            token = session.get("token")
            g.oidc_token_info = session.get("token")
            if not token:
                return
            if token["expires_at"] - 60 < int(time.time()):
                return redirect("{}?reason=expired".format(url_for("oidc_auth.logout")))
        except Exception as e:
            session.pop("token", None)
            session.pop("userinfo", None)
            abort(500, f"{e.__class__.__name__}: {e}")

    @property
    def user_loggedin(self):
        """
        Represents whether the user is currently logged in.

        Returns:
            bool: Whether the user is logged in with Flask-OIDC.

        .. versionadded:: 1.0
        """
        return session.get("token") is not None

    def _retrieve_userinfo(self, access_token=None):
        """
        Requests extra user information from the Provider's UserInfo and
        returns the result.

        :returns: The contents of the UserInfo endpoint.
        :rtype: dict
        """
        # Cache the info from this request
        token = session.get("token")
        userinfo = session.get("userinfo")
        if userinfo:
            return userinfo
        else:
            try:
                resp = self.oauth.oidc.get(
                    current_app.config["OIDC_USERINFO_URL"], token=token
                )
                userinfo = resp.json()
                session["userinfo"] = userinfo
                return userinfo
            except Exception:
                raise

    def require_login(self, view_func):
        """
        Use this to decorate view functions that require a user to be logged
        in. If the user is not already logged in, they will be sent to the
        Provider to log in, after which they will be returned.

        .. versionadded:: 1.0
           This was :func:`check` before.
        """

        @wraps(view_func)
        def decorated(*args, **kwargs):
            if not self.user_loggedin:
                redirect_uri = "{login}?next={here}".format(
                    login=url_for("oidc_auth.login"),
                    here=quote_plus(request.url),
                )
                return redirect(redirect_uri)
            return view_func(*args, **kwargs)

        return decorated

    def logout(self, return_to=None):
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
        return_to = return_to or request.root_url
        return redirect(url_for("oidc_auth.logout", next=return_to))
