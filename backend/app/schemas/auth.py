from pydantic import BaseModel, EmailStr


class EmailCodeRequest(BaseModel):
    email: EmailStr


class EmailCodeVerifyRequest(BaseModel):
    email: EmailStr
    code: str


class AuthUserResponse(BaseModel):
    id: int
    email: EmailStr | None = None
    display_name: str
    avatar_url: str | None = None
    auth_method: str

