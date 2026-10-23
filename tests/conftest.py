import pytest

import app as web_app


@pytest.fixture(autouse=True)
def disable_security_middleware():
    """Disable CSRF and reset rate limit storage for each test."""
    web_app.app.config['WTF_CSRF_ENABLED'] = False
    web_app.limiter.reset()
    yield
    web_app.app.config['WTF_CSRF_ENABLED'] = True


@pytest.fixture(autouse=True)
def fixed_school_day(monkeypatch):
    """Tests book classes on fixed 2026 dates; the past-semester check must not age them out."""
    from datetime import date
    monkeypatch.setattr(web_app, 'school_today', lambda: date(2026, 10, 23))
