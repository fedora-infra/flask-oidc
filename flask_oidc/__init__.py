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


from authlib.integrations.flask_client import OAuth
import time
import logging
import json
from functools import wraps
from flask import request, session, redirect, url_for, g, current_app, abort

__all__ = ["OpenIDConnect"]

logger = logging.getLogger(__name__)

def _json_loads(content):
    if not isinstance(content, str):
        content = content.decode('utf-8')
    return json.loads(content)

class OpenIDConnect:
    def __init__(
        self, app=None, credentials_store=None, http=None, time=None, urandom=None
    ):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        secrets = self.load_secrets(app)
        self.client_secrets = list(secrets.values())[0]

        app.config.setdefault("OIDC_ISSUER", self.client_secrets["issuer"])
        app.config.setdefault("OIDC_CLIENT_ID", self.client_secrets["client_id"])
        app.config.setdefault("OIDC_CLIENT_SECRET", self.client_secrets["client_secret"])
        app.config.setdefault("OIDC_USERINFO_URL", self.client_secrets["userinfo_uri"])
        app.config.setdefault("OIDC_SCOPES", "openid profile email")
        app.config.setdefault("OIDC_CLIENT_AUTH_METHOD", "client_secret_post")
        app.config.setdefault("OIDC_OPENID_CALLBACK", "/oidc_callback")

        #app.config.from_file(app.config["OIDC_CLIENT_SECRETS"], load=json.load)
        app.config.setdefault(
            "OIDC_SERVER_METADATA_URL",
            f"{app.config['OIDC_ISSUER']}/.well-known/openid-configuration",
        )

        self.oauth = OAuth(app)
        self.oauth.register(
            name="oidc",
            server_metadata_url=app.config["OIDC_SERVER_METADATA_URL"],
            client_kwargs={
                "scope": app.config["OIDC_SCOPES"],
                "token_endpoint_auth_method": app.config["OIDC_CLIENT_AUTH_METHOD"],
            },
        )

        app.route(app.config["OIDC_OPENID_CALLBACK"])(self._oidc_callback)
        app.before_request(self._before_request)
        app.after_request(self._after_request)

    def load_secrets(self, app):
        # Load client_secrets.json to pre-initialize some configuration
        content = app.config['OIDC_CLIENT_SECRETS']
        if isinstance(content, dict):
            return content
        else:
            return _json_loads(open(content, 'r').read())

    def _before_request(self):
        self.check_token_expiry()

    def _after_request(self, response):
        return response

    def _oidc_callback(self):
        try:
            session["token"] = self.oauth.oidc.authorize_access_token()
        except AttributeError:
            raise
        return redirect("/")

    def check_token_expiry(self):
        try:
            token = session.get("token")
            if token:
                if session.get("token")["expires_at"] - 60 < int(time.time()):
                    self.logout()
        except Exception:
            session.pop("token", None)
            session.pop("userinfo", None)
            raise

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
            if session.get("token") is None:
                redirect_uri = url_for(
                    "_oidc_callback", _scheme="https", _external=True
                )
                return self.oauth.oidc.authorize_redirect(redirect_uri)
            return view_func(*args, **kwargs)

        return decorated

    def logout(self):
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
        session.pop("token", None)
        session.pop("userinfo", None)
        return redirect("/")
