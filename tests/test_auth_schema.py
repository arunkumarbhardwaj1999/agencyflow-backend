import pytest
from pydantic import ValidationError

from app.schemas.auth import RegisterRequest


def test_gst_optional_empty():
    body = RegisterRequest(
        company_name="Acme",
        slug="acme",
        company_email="co@acme.com",
        first_name="A",
        email="a@acme.com",
        password="password123",
        gst_number="",
    )
    assert body.gst_number is None


def test_gst_rejects_too_long():
    with pytest.raises(ValidationError):
        RegisterRequest(
            company_name="Acme",
            slug="acme",
            company_email="co@acme.com",
            first_name="A",
            email="a@acme.com",
            password="password123",
            gst_number="x" * 17,
        )
