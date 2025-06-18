# SPDX-FileCopyrightText: 2023 Aurélien Bompard <aurelien@bompard.org>
#
# SPDX-License-Identifier: BSD-2-Clause

from typing import TYPE_CHECKING, Any, Optional

from flask import current_app, session

if TYPE_CHECKING:
    from . import OpenIDConnect


class User:
    """A representation of an OIDC-based user.

    Arguments:
        ext (OpenIDConnect): the extension instance
    """

    def __init__(self, ext: "OpenIDConnect"):
        self._ext = ext

    @property
    def logged_in(self) -> bool:
        """Return ``True`` if the user is logged in, ``False`` otherwise."""
        return session.get("oidc_auth_token") is not None

    @property
    def access_token(self) -> Optional[str]:
        """The user's OIDC access token."""
        return self._ext.get_access_token()

    @property
    def refresh_token(self) -> Optional[str]:
        """The user's OIDC refresh token."""
        return self._ext.get_refresh_token()

    @property
    def profile(self) -> dict[str, Any]:
        """The user's OIDC profile, if any.

        Raises:
            RuntimeError: when ``OIDC_USER_INFO_ENABLED`` is ``False`` in the application's
                configuration.
        """
        if not current_app.config["OIDC_USER_INFO_ENABLED"]:
            raise RuntimeError(
                "User info is disabled in configuration (OIDC_USER_INFO_ENABLED)"
            )
        return session.get("oidc_auth_profile", {})

    @property
    def name(self) -> Optional[str]:
        """The user's nickname."""
        return self.profile.get("nickname")

    @property
    def email(self) -> Optional[str]:
        """The user's email."""
        return self.profile.get("email")

    @property
    def groups(self) -> list[str]:
        """The list of group names the user belongs to."""
        value: list[str] = self.profile.get("groups", [])
        return value

    @property
    def unique_id(self) -> Optional[str]:
        """The unique and immutable identifier on the Issuer side"""
        return self.profile.get("sub")
