import pytest
from pydantic import ValidationError

from app.schemas.auth import RegisterRequest


def test_register_username_normalized():
    body = RegisterRequest(username="Orbantis", email="o@agency.com")
    assert body.username == "orbantis"


def test_register_rejects_bad_username():
    with pytest.raises(ValidationError):
        RegisterRequest(username="ab", email="o@agency.com")
