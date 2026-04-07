from pydantic import BaseModel, EmailStr


class UsageDailyItem(BaseModel):
    usage_date: str
    total_tokens: int


class UserProfileResponse(BaseModel):
    id: int
    email: EmailStr | None = None
    display_name: str
    avatar_url: str | None = None
    timezone: str
    locale: str
    status: str

