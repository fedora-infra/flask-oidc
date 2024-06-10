# SPDX-FileCopyrightText: 2023 Aurélien Bompard <aurelien@bompard.org>
#
# SPDX-License-Identifier: BSD-2-Clause

"""
This module contains signals that can be connected to to hook into the login and logout process.

See the `Flask documentation on signals <https://flask.palletsprojects.com/en/2.3.x/signals/>`_
to learn how to connect to these.
"""


from blinker import Namespace

# This namespace is only for signals provided by flask-oidc.
_signals = Namespace()

before_login_redirect = _signals.signal("before-login-redirect")
"""Emitted before the user is redirected to the identity provider."""

before_authorize = _signals.signal("before-authorize")
"""Emitted when the user is redirected back from the identity provider."""

after_authorize = _signals.signal("after-authorize")
"""Emitted when the user is authenticated."""

before_logout = _signals.signal("before-logout")
"""Emitted before the user is logged out."""

after_logout = _signals.signal("after-logout")
"""Emitted after the user is logged out."""
