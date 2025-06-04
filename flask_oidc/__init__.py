# SPDX-FileCopyrightText: 2014-2015 Erica Ehrhardt
# SPDX-FileCopyrightText: 2016-2022 Patrick Uiterwijk <patrick@puiterwijk.org>
# SPDX-FileCopyrightText: 2023 Aurélien Bompard <aurelien@bompard.org>
#
# SPDX-License-Identifier: BSD-2-Clause

import json
import logging
import warnings
from functools import wraps
from typing import Any, Callable, Optional, cast
from urllib.parse import quote_plus

from authlib.common.errors import AuthlibBaseError
from authlib.integrations.base_client import InvalidTokenError
from authlib.integrations.flask_client import FlaskOAuth2App, OAuth
from authlib.integrations.flask_oauth2.resource_protector import ResourceProtector
from authlib.oauth2.rfc6749 import OAuth2Token
from authlib.oauth2.rfc7662 import (
    IntrospectTokenValidator as BaseIntrospectTokenValidator,
)
from flask import Flask, abort, current_app, g, redirect, request, session, url_for
from flask.typing import ResponseReturnValue
from werkzeug.utils import import_string

from .views import auth_routes, legacy_oidc_callback

__all__ = ["OpenIDConnect"]

_CONFIG_REMOVED = (
    "OIDC_GOOGLE_APPS_DOMAIN",
    "OIDC_REQUIRE_VERIFIED_EMAIL",
    "OIDC_RESOURCE_CHECK_AUD",
    "OIDC_VALID_ISSUERS",
)
_CONFIG_DEPRECATED = (
    "OIDC_ID_TOKEN_COOKIE_NAME",
    "OIDC_ID_TOKEN_COOKIE_PATH",
    "OIDC_ID_TOKEN_COOKIE_TTL",
    "OIDC_COOKIE_SECURE",
    "OIDC_OPENID_REALM",
    "OIDC_CALLBACK_ROUTE",
    "OIDC_USERINFO_URL",
)

logger = logging.getLogger(__name__)


class IntrospectTokenValidator(BaseIntrospectTokenValidator):
    """Validates a token using introspection."""

    # TODO: bug in types-authlib: this is supposed to return a token dict
    def introspect_token(self, token_string: str) -> dict[str, Any]:  # type: ignore
        """Return the token introspection result."""
        oauth = g._oidc_auth
        if not current_app.config["OIDC_ENABLED"]:
            testing_profile = current_app.config.get("OIDC_TESTING_PROFILE", {})
            return {
                "active": bool(testing_profile),
                "scope": current_app.config["OIDC_SCOPES"],
            }
        metadata = oauth.load_server_metadata()
        if "introspection_endpoint" not in metadata:
            raise RuntimeError(
                "Can't validate the token because the server does not support "
                "introspection."
            )
        with oauth._get_oauth_client(**metadata) as session:
            response = session.introspect_token(
                metadata["introspection_endpoint"], token=token_string
            )
        result: dict[str, Any] = response.json()
        # Add the token to the response
        result["access_token"] = token_string
        return result


class OpenIDConnect:
    accept_token = ResourceProtector()

    def __init__(
        self,
        app: Optional[Flask] = None,
        credentials_store: Optional[Any] = None,
        http: Optional[Any] = None,
        time: Optional[Any] = None,
        urandom: Optional[Any] = None,
        prefix: Optional[str] = None,
    ):
        for param_name in ("credentials_store", "http", "time", "urandom"):
            if locals()[param_name] is not None:
                warnings.warn(
                    f"The {param_name!r} attibute is no longer used.",
                    DeprecationWarning,
                    stacklevel=2,
                )
        self.accept_token.register_token_validator(IntrospectTokenValidator())
        if app is not None:
            self.init_app(app, prefix=prefix)

    def init_app(self, app: Flask, prefix: Optional[str] = None) -> None:
        # Removed features, die if still there
        for param in _CONFIG_REMOVED:
            if param in app.config:
                raise ValueError(
                    f"The {param!r} configuration value is no longer enforced."
                )
        # Deprecated config values, harmless if still there
        for param in _CONFIG_DEPRECATED:
            if param in app.config:
                warnings.warn(
                    f"The {param!r} configuration value is deprecated and ignored.",
                    DeprecationWarning,
                    stacklevel=2,
                )

        app.config.setdefault("OIDC_ENABLED", True)

        secrets = self.load_secrets(app)
        self.client_secrets = list(secrets.values())[0]

        app.config.setdefault("OIDC_CLIENT_ID", self.client_secrets["client_id"])
        app.config.setdefault(
            "OIDC_CLIENT_SECRET", self.client_secrets["client_secret"]
        )
        app.config.setdefault("OIDC_USER_INFO_ENABLED", True)
        app.config.setdefault("OIDC_INTROSPECTION_AUTH_METHOD", "client_secret_post")
        app.config.setdefault("OIDC_CLOCK_SKEW", 60)
        app.config.setdefault("OIDC_RESOURCE_SERVER_ONLY", False)
        app.config.setdefault("OIDC_CALLBACK_ROUTE", None)
        app.config.setdefault("OIDC_PRESERVE_NEXT_ON_ERROR", False)

        if "OVERWRITE_REDIRECT_URI" in app.config:
            warnings.warn(
                "The 'OVERWRITE_REDIRECT_URI' configuration value has been replaced by "
                "'OIDC_OVERWRITE_REDIRECT_URI', please update your configuration.",
                DeprecationWarning,
                stacklevel=2,
            )
            app.config.setdefault(
                "OIDC_OVERWRITE_REDIRECT_URI", app.config["OVERWRITE_REDIRECT_URI"]
            )
        app.config.setdefault("OIDC_OVERWRITE_REDIRECT_URI", None)

        app.config.setdefault("OIDC_SCOPES", "openid email")
        if "openid" not in app.config["OIDC_SCOPES"]:
            raise ValueError('The value "openid" must be in the OIDC_SCOPES')
        if isinstance(app.config["OIDC_SCOPES"], (list, tuple)):
            warnings.warn(
                "The OIDC_SCOPES configuration value should now be a string",
                DeprecationWarning,
                stacklevel=2,
            )
            app.config["OIDC_SCOPES"] = " ".join(app.config["OIDC_SCOPES"])

        provider_url = self.client_secrets["issuer"].rstrip("/")
        app.config.setdefault(
            "OIDC_SERVER_METADATA_URL",
            f"{provider_url}/.well-known/openid-configuration",
        )

        # TODO: bug in types-authlib: no typing for authlib.integrations.flask_client.
        self.oauth = OAuth(app)  # type: ignore
        self.oauth.register(  # type: ignore
            name="oidc",
            server_metadata_url=app.config["OIDC_SERVER_METADATA_URL"],
            client_kwargs={
                "scope": app.config["OIDC_SCOPES"],
                "token_endpoint_auth_method": app.config[
                    "OIDC_INTROSPECTION_AUTH_METHOD"
                ],
            },
            update_token=self._update_token,
        )

        if not app.config["OIDC_RESOURCE_SERVER_ONLY"]:
            app.register_blueprint(auth_routes, url_prefix=prefix)
            app.route("/oidc_callback")(legacy_oidc_callback)
            if app.config["OIDC_CALLBACK_ROUTE"]:
                app.route(app.config["OIDC_CALLBACK_ROUTE"])(legacy_oidc_callback)

        # User model
        app.config.setdefault("OIDC_USER_CLASS", "flask_oidc.model.User")
        if app.config["OIDC_USER_CLASS"]:
            app.extensions["_oidc_user_class"] = import_string(
                app.config["OIDC_USER_CLASS"]
            )

        # Flask hooks
        app.before_request(self._before_request)

    def load_secrets(self, app: Flask) -> dict[str, Any]:
        # Load client_secrets.json to pre-initialize some configuration
        if app.config["OIDC_ENABLED"]:
            content_or_filepath = app.config["OIDC_CLIENT_SECRETS"]
        else:
            content_or_filepath = {
                "web": {
                    "client_id": "testing-client-id",
                    "client_secret": "testing-client-secret",
                    "issuer": "https://oidc.example.com",
                }
            }
        if isinstance(content_or_filepath, dict):
            return content_or_filepath
        else:
            with open(content_or_filepath) as f:
                content: dict[str, Any] = json.load(f)
                return content

    def _before_request(self) -> Optional[ResponseReturnValue]:
        g._oidc_auth = self.oauth.oidc
        User = current_app.extensions.get("_oidc_user_class")
        if User:
            g.oidc_user = User(self)
        if not current_app.config["OIDC_ENABLED"]:
            # Setup a testing user token and profile
            testing_profile = current_app.config.get("OIDC_TESTING_PROFILE", {})
            if testing_profile:
                self._update_token(
                    # TODO: bug in types-authlib: OAuth2Token.from_dict is not typed correctly
                    token=OAuth2Token.from_dict(  # type: ignore
                        {
                            "access_token": "testing-access-token",
                        }
                    ),
                )
                session["oidc_auth_profile"] = testing_profile
            return None  # Don't validate/introspect the token
        if current_app.config["OIDC_RESOURCE_SERVER_ONLY"]:
            return None
        return self.check_token_expiry()

    def check_token_expiry(self) -> Optional[ResponseReturnValue]:
        try:
            token: Optional[OAuth2Token] = session.get("oidc_auth_token")
            if not token:
                return None
            if f"{request.script_root}{request.path}" == url_for("oidc_auth.logout"):
                return None  # Avoid redirect loop
            # TODO: bug in types-authlib: OAuth2Token.from_dict is not typed correctly
            token_obj = OAuth2Token.from_dict(token)  # type: ignore
            try:
                self.ensure_active_token(token_obj)
            except AuthlibBaseError as e:
                logger.info(f"Could not refresh token {token_obj!r}: {e}")
                redirect_url = "{}?reason=expired".format(url_for("oidc_auth.logout"))
                next_url = request.args.get("next", None)
                if current_app.config["OIDC_PRESERVE_NEXT_ON_ERROR"] and next_url:
                    redirect_url = f"{redirect_url}&next={next_url}"
                return redirect(redirect_url)
        except Exception as e:
            logger.exception("Could not check token expiration")
            abort(500, f"{e.__class__.__name__}: {e}")
        return None

    def ensure_active_token(self, token: OAuth2Token) -> bool:
        client = cast(FlaskOAuth2App, self.oauth.oidc)
        metadata = client.load_server_metadata()
        # TODO: bug in types-oauth: _get_oauth_client() is not typed (because it's private?)
        with client._get_oauth_client(  # pyright: ignore[reportAttributeAccessIssue]
            **metadata
        ) as session:
            result: Optional[bool] = session.ensure_active_token(token)
            if result is None:
                # See the ensure_active_token method in
                # authlib.integrations.requests_client.oauth2_session:OAuth2Auth
                raise InvalidTokenError()
            return result

    def _update_token(
        self,
        token: OAuth2Token,
        refresh_token: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> None:
        session["oidc_auth_token"] = g.oidc_id_token = token

    @property
    def user_loggedin(self) -> bool:
        """
        Represents whether the user is currently logged in.

        Returns:
            bool: Whether the user is logged in with Flask-OIDC.

        .. versionadded:: 1.0
        """
        return session.get("oidc_auth_token") is not None

    def user_getinfo(
        self, fields: list[str], access_token: Optional[str] = None
    ) -> dict[str, Any]:
        if not current_app.config["OIDC_USER_INFO_ENABLED"]:
            raise RuntimeError(
                "User info is disabled in configuration (OIDC_USER_INFO_ENABLED)"
            )
        profile: dict[str, Any]
        if access_token is not None:
            warnings.warn(
                "Calling user_getinfo with a token is deprecated, please use "
                "g._oidc_auth.userinfo(token=token)",
                DeprecationWarning,
                stacklevel=2,
            )
            profile = cast(FlaskOAuth2App, self.oauth.oidc).userinfo(token=access_token)
            return profile
        warnings.warn(
            "The user_getinfo method is deprecated, please use "
            "session['oidc_auth_profile']",
            DeprecationWarning,
            stacklevel=2,
        )
        if not self.user_loggedin:
            abort(401, "User was not authenticated")
        profile = session.get("oidc_auth_profile", {})
        return profile

    def user_getfield(self, field: str, access_token: Optional[str] = None) -> Any:
        """
        Request a single field of information about the user.

        :param field: The name of the field requested.
        :type field: str
        :returns: The value of the field. Depending on the type, this may be
            a string, list, dict, or something else.
        :rtype: object

        .. versionadded:: 1.0
        """
        warnings.warn(
            "The user_getfield method is deprecated, all the user info is in "
            "session['oidc_auth_profile']",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.user_getinfo([field]).get(field)

    def get_access_token(self) -> Optional[str]:
        """Method to return the current requests' access_token.

        :returns: Access token or None
        :rtype: str

        .. versionadded:: 1.2
        """
        value: Optional[str] = session.get("oidc_auth_token", {}).get("access_token")
        return value

    def get_refresh_token(self) -> Optional[str]:
        """Method to return the current requests' refresh_token.

        :returns: Access token or None
        :rtype: str

        .. versionadded:: 1.2
        """
        value: Optional[str] = session.get("oidc_auth_token", {}).get("refresh_token")
        return value

    def require_login(
        self, view_func: Callable[..., ResponseReturnValue]
    ) -> Callable[..., ResponseReturnValue]:
        """
        Use this to decorate view functions that require a user to be logged
        in. If the user is not already logged in, they will be sent to the
        Provider to log in, after which they will be returned.

        .. versionadded:: 1.0
           This was :func:`check` before.
        """

        @wraps(view_func)
        def decorated(*args: Any, **kwargs: Any) -> ResponseReturnValue:
            if not self.user_loggedin:
                return self.redirect_to_auth_server()
            return view_func(*args, **kwargs)

        return decorated

    def redirect_to_auth_server(
        self, destination: Optional[str] = None, customstate: Optional[Any] = None
    ) -> ResponseReturnValue:
        """
        Redirect to the IdP.

        :param destination: The page that the user was going to,
            before we noticed they weren't logged in.
        :type destination: Url to return the client to if a custom handler is
            not used. Not available with custom callback.
        :param customstate: Ignored, left here for compatibility.
        :returns: A redirect response to start the login process.
        """
        if customstate is not None:
            warnings.warn(
                "The customstate argument of redirect_to_auth_server is ignored.",
                DeprecationWarning,
                stacklevel=2,
            )
        redirect_uri = "{login}?next={here}".format(
            login=url_for("oidc_auth.login"),
            here=quote_plus(destination or request.url),
        )
        return redirect(redirect_uri)

    def logout(self, return_to: Optional[str] = None) -> ResponseReturnValue:
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
        return_to = return_to or request.url_root
        warnings.warn(
            "The logout method is deprecated, just redirect to {}".format(
                url_for("oidc_auth.logout", next=return_to)
            ),
            DeprecationWarning,
            stacklevel=2,
        )
        return redirect(url_for("oidc_auth.logout", next=return_to))

    def custom_callback(self, *args: Any, **kwargs: Any) -> None:
        raise ValueError("This feature has been dropped")
