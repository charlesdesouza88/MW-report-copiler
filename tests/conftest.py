import pytest

import app as web_app


@pytest.fixture(autouse=True)
def disable_security_middleware():
    """Disable CSRF and reset rate limit storage for each test."""
    web_app.app.config['WTF_CSRF_ENABLED'] = False
    web_app.limiter.reset()
    yield
    web_app.app.config['WTF_CSRF_ENABLED'] = True
