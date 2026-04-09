from pydantic import BaseModel, EmailStr


class EmailCodeRequest(BaseModel):
    email: EmailStr


class EmailCodeVerifyRequest(BaseModel):
    email: EmailStr
    code: str
    invite_code: str | None = None


class AuthUserResponse(BaseModel):
    id: int
    email: EmailStr | None = None
    display_name: str
    avatar_url: str | None = None
    role: str
    quota_tier_code: str | None = None
    daily_token_limit: int | None = None
    is_unlimited: bool = False
