"""Request and response shapes for sign-up and sign-in."""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=1, max_length=150)

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be blank")
        return v


class LoginIn(BaseModel):
    # Not EmailStr on purpose: sign-in should just say "wrong email or password",
    # never reveal which emails are valid or well-formed.
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int  # seconds
