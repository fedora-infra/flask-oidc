import pytest

from . import app


@pytest.fixture
def isolate_app_globals():
    old_oidc = app.oidc
    app.oidc = None

    yield

    app.oidc = old_oidc
