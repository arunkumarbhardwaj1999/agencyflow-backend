import re

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

_GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_USERNAME_PATTERN = re.compile(r"^[a-z0-9_]+$")


class RegisterRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=128)


class RegisterResponse(BaseModel):
    """Legacy — use GoogleRegisterPendingResponse for new signup flow."""
    message: str
    email: str
    username: str
    generated_password: str | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str) -> str:
        return value.strip()


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=20)


class GoogleRegisterRequest(BaseModel):
    credential: str = Field(min_length=20)


class GoogleRegisterPendingResponse(BaseModel):
    registration_id: UUID
    email: str
    first_name: str
    next_step: str = "email"
    email_sent: bool = False
    email_error: str | None = None
    confirm_link: str | None = None


class SendOtpRequest(BaseModel):
    registration_id: UUID
    phone: str = Field(min_length=10, max_length=20)


class SendOtpResponse(BaseModel):
    message: str
    dev_otp: str | None = None


class VerifyOtpRequest(BaseModel):
    registration_id: UUID
    phone: str = Field(min_length=10, max_length=20)
    code: str = Field(min_length=4, max_length=8)


class VerifyOtpResponse(BaseModel):
    message: str
    email: str


class ConfirmAccountPreview(BaseModel):
    email: str
    first_name: str
    already_confirmed: bool


class ConfirmAccountRequest(BaseModel):
    token: str = Field(min_length=16)


class InvitePreviewResponse(BaseModel):
    workspace: str
    invited_email: str
    inviter_name: str
    inviter_email: str | None = None
    role: str
    first_name: str
    last_name: str | None = None


class InviteRejectRequest(BaseModel):
    token: str = Field(min_length=16)


class InviteSetupRequest(BaseModel):
    token: str = Field(min_length=16)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    password: str = Field(min_length=8, max_length=128)


class InviteSetupResponse(BaseModel):
    message: str
    email: str
    dev_otp: str | None = None


class InviteVerifyEmailRequest(BaseModel):
    token: str = Field(min_length=16)
    code: str = Field(min_length=4, max_length=8)


class AcceptInviteGoogleRequest(BaseModel):
    token: str = Field(min_length=16)
    credential: str = Field(min_length=20)


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


class AcceptInviteRequest(ResetPasswordRequest):
    """Same shape as password reset — token + new password."""
