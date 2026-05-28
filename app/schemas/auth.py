import re

from pydantic import BaseModel, EmailStr, Field, field_validator

_GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


class RegisterRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    company_email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = None
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = None
    address: str | None = None
    gst_number: str | None = Field(default=None, max_length=15)

    @field_validator("gst_number")
    @classmethod
    def normalize_gst(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        gst = str(value).strip().upper()
        if len(gst) != 15:
            raise ValueError("GSTIN must be exactly 15 characters (e.g. 22AAAAA0000A1Z5)")
        if not _GSTIN_PATTERN.match(gst):
            raise ValueError("Invalid GSTIN format")
        return gst


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    reset_token: str | None = None
    email: str | None = None


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("token")
    @classmethod
    def strip_token(cls, value: str) -> str:
        return value.strip()
