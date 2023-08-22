=========
Changelog
=========

UNRELEASED
==========

Fixed
-----

- Don't crash if the ``client_secrets`` don't contain a ``userinfo_uri`` key.


2.0.0 (2023-08-21)
==================

This is a major release that rebases the Flask OIDC API on `Authlib`_

.. _Authlib: https://authlib.org/


Removed
-------

- Custom callback with the :meth:`~flask_oidc.OpenIDConnect.custom_callback`
  decorator
- Registration has been moved to the If the `oidc-register package`_
- Configuration option ``OIDC_GOOGLE_APPS_DOMAIN``
- Configuration option ``OIDC_VALID_ISSUERS``
- Configuration option ``OIDC_REQUIRE_VERIFIED_EMAIL``
- Configuration option ``OIDC_RESOURCE_CHECK_AUD``
- The following parameters of the :class:`~flask_oidc.OpenIDConnect` constructor have been removed:
  - ``credentials_store``
  - ``http``
  - ``time``
  - ``urandom``

.. _oidc-register package: https://pypi.org/project/oidc-register/


Deprecated
----------

- Configuration option ``OIDC_OPENID_REALM``
- Configuration option ``OIDC_CALLBACK_ROUTE``
- Configuration option ``OVERWRITE_REDIRECT_URI``
- The following configuration options have been removed because the
  functionality is now handled by Authlib:
  - ``OIDC_ID_TOKEN_COOKIE_NAME``
  - ``OIDC_ID_TOKEN_COOKIE_PATH``
  - ``OIDC_ID_TOKEN_COOKIE_TTL``
  - ``OIDC_COOKIE_SECURE``
- The :meth:`~flask_oidc.OpenIDConnect.user_getinfo` and
  :meth:`~flask_oidc.OpenIDConnect.user_getfield` methods are deprecated,
  you'll find all the user information in the session:
  ``session["oidc_auth_profile"]``.
  If you need to get the user information using a specific token, you can
  do so by calling ``g._oidc_auth.userinfo(token=token)``.
- The :meth:`~flask_oidc.OpenIDConnect.logout` method is deprecated, just
  redirect to the ``/logout`` view.


Changed
-------

The callback route (aka "redirect URL") is not configurable with
``OIDC_CALLBACK_ROUTE`` anymore. It is always ``/authorize``, but a prefix can
be configured when instanciating the :class:`~flask_oidc.OpenIDConnect`
extension (or calling its :meth:`~flask_oidc.OpenIDConnect.init_app` method::

    app = Flask(__name__)
    openid = OpenIDConnect(app, prefix="/oidc")
    # The OIDC redirect URL will be /oidc/authorize

This will also give you ``/login`` and ``/logout`` views, prefixed identically.

The ``OIDC_SCOPES`` configuration value should now be a string, where the
scopes are separated with spaces.

The minimum Python version is ``3.8``.


Added
-----

The :meth:`~flask_oidc.OpenIDConnect.accept_token` decorator now accepts a
``scopes`` parameter, which is a list of scopes that the provided token must
include for the view to be authorized. It is an Authlib `ResourceProtector`_.

.. _ResourceProtector: https://docs.authlib.org/en/latest/flask/2/resource-server.html

The Authlib app is available in the ``g._oidc_auth`` variable. This means that
there cannot be more than one :meth:`~flask_oidc.OpenIDConnect` extension on a
given Flask application. If you need more, we advise you to use
Authlib directly.


Development
-----------

- A `pre-commit`_ config has been added, please enable it with
  ``pre-commit install``
- Unit tests are run by `Tox`_
- A coverage report is produced, and the coverage must be 100%
- The git submodule for documentation themes has been dropped
- The code is formatted using `Black`_
- The code is linted using `Ruff`_
- The package metadata is managed by `Poetry`_
- CI is run using Github Actions, Travis config has been dropped
- Dependencies are updated using `Renovate`_

.. _pre-commit: https://pre-commit.com/
.. _Tox: https://tox.readthedocs.io/
.. _Black: https://black.readthedocs.io/
.. _Ruff: https://ruff.rs
.. _Poetry: https://python-poetry.org/
.. _Renovate: https://docs.renovatebot.com/
