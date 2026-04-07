import smtplib
from email.message import EmailMessage

from ..core.config import settings


def send_login_code_email(*, to_email: str, code: str) -> None:
    # 当前只实现两种发送模式：
    # 1. console：开发期打印到后端日志
    # 2. smtp：通过标准 SMTP 发送真实邮件
    subject = f"{settings.email_subject_prefix} 登录验证码"
    body = (
        "您好，\n\n"
        f"您的 Makerfabs Agent 登录验证码是：{code}\n"
        "验证码 10 分钟内有效。如果这不是您的操作，请忽略这封邮件。\n"
    )

    if settings.email_provider == "console":
        # 本地开发模式，不真正发邮件，便于快速联调邮箱登录流程。
        print(f"[EMAIL LOGIN CODE] to={to_email} code={code}")
        return

    if settings.email_provider == "smtp":
        if not settings.smtp_host:
            raise RuntimeError("SMTP_HOST is required when EMAIL_PROVIDER=smtp")
        # 使用标准库拼装邮件，避免引入额外依赖。
        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return

    # 其他 provider 暂未实现，后续如果接 Resend/Postmark 可在这里继续扩展。
    raise RuntimeError(f"Unsupported EMAIL_PROVIDER: {settings.email_provider}")
