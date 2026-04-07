import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from itsdangerous import URLSafeSerializer

from .config import settings


def utcnow() -> datetime:
    # 统一使用带时区的 UTC 时间，避免登录过期时间计算混乱。
    return datetime.now(timezone.utc)


def future_time(*, hours: int = 0, minutes: int = 0) -> datetime:
    # 常用于生成 session 过期时间、验证码过期时间。
    return utcnow() + timedelta(hours=hours, minutes=minutes)


def hash_text(value: str) -> str:
    # 所有敏感随机值只保存 hash，不把原始 token/code 落库。
    return hashlib.sha256(f"{settings.session_secret}:{value}".encode("utf-8")).hexdigest()


def generate_session_token() -> str:
    # 浏览器 cookie 中使用的原始 session token。
    return secrets.token_urlsafe(32)


def generate_email_code() -> str:
    # 邮箱验证码固定 6 位，便于用户输入。
    return f"{secrets.randbelow(1_000_000):06d}"


def serializer(namespace: str) -> URLSafeSerializer:
    # 不同用途的签名数据走不同 salt，防止串用。
    return URLSafeSerializer(settings.session_secret, salt=f"makerfabs:{namespace}")


def sign_value(namespace: str, payload: dict) -> str:
    # 例如 Google OAuth state 就通过它做签名，防止被篡改。
    return serializer(namespace).dumps(payload)


def unsign_value(namespace: str, value: str) -> dict:
    # 对应 sign_value 的反向校验。
    return serializer(namespace).loads(value)
