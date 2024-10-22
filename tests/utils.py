# SPDX-FileCopyrightText: 2023 Aurélien Bompard <aurelien@bompard.org>
#
# SPDX-License-Identifier: BSD-2-Clause


def set_token(client, token, profile=None):
    _profile = {"nickname": "dummy", "email": "dummy@example.com"}
    _profile.update(profile or {})
    with client.session_transaction() as session:
        session["oidc_auth_token"] = token
        session["oidc_auth_profile"] = _profile
