import os
from dataclasses import dataclass

from dotenv import load_dotenv

# 在导入配置对象前加载 `.env`，这样模块级默认值也能正确读取环境变量。
load_dotenv()


@dataclass(frozen=True)
class Settings:
    # 使用 dataclass 统一收口项目配置，方便后续替换成更完整的配置系统。
    app_name: str = os.getenv("APP_NAME", "Makerfabs Agent")
    app_url: str = os.getenv("APP_URL", "http://127.0.0.1:8000")
    database_url: str = os.getenv("DATABASE_URL", "")
    session_cookie_name: str = os.getenv("SESSION_COOKIE_NAME", "makerfabs_session")
    session_secret: str = os.getenv("SESSION_SECRET", "change-me-in-production")
    session_ttl_hours: int = int(os.getenv("SESSION_TTL_HOURS", "168"))

    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/google/callback")

    email_provider: str = os.getenv("EMAIL_PROVIDER", "console")
    email_from: str = os.getenv("EMAIL_FROM", "no-reply@example.com")
    email_subject_prefix: str = os.getenv("EMAIL_SUBJECT_PREFIX", "[Makerfabs Agent]")
    email_debug_expose_code: bool = os.getenv("EMAIL_DEBUG_EXPOSE_CODE", "true").lower() == "true"
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_use_tls: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    phone_login_enabled: bool = os.getenv("PHONE_LOGIN_ENABLED", "false").lower() == "true"

    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.4")

    @property
    def google_auth_enabled(self) -> bool:
        # Google OAuth 依赖 client id / secret / redirect uri 三项都配置完成。
        return bool(self.google_client_id and self.google_client_secret and self.google_redirect_uri)


# 全局单例配置对象，供整个后端直接读取。
settings = Settings()
