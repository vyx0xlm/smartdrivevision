"""Send transactional email (password reset) via SMTP."""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def mail_configured() -> bool:
    return bool(
        os.environ.get('MAIL_SERVER')
        and os.environ.get('MAIL_USERNAME')
        and os.environ.get('MAIL_PASSWORD')
    )


def send_email(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    if not mail_configured():
        raise RuntimeError(
            'Email is not configured. Set MAIL_SERVER, MAIL_USERNAME, and MAIL_PASSWORD in .env'
        )

    sender = os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_USERNAME')
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = to_email
    msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
    if html_body:
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    server = os.environ.get('MAIL_SERVER')
    port = int(os.environ.get('MAIL_PORT', '587'))
    use_tls = os.environ.get('MAIL_USE_TLS', '1').lower() in ('1', 'true', 'yes')

    with smtplib.SMTP(server, port, timeout=30) as smtp:
        if use_tls:
            smtp.starttls()
        smtp.login(os.environ['MAIL_USERNAME'], os.environ['MAIL_PASSWORD'])
        smtp.sendmail(sender, [to_email], msg.as_string())


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    subject = 'SmartDrive — reset your password'
    text_body = (
        'You requested a password reset for your SmartDrive account.\n\n'
        f'Open this link to choose a new password (valid for 1 hour):\n{reset_url}\n\n'
        'If you did not request this, you can ignore this email.\n'
    )
    html_body = f"""
    <p>You requested a password reset for your SmartDrive account.</p>
    <p><a href="{reset_url}">Reset your password</a></p>
    <p>This link expires in 1 hour. If you did not request this, ignore this email.</p>
    """
    send_email(to_email, subject, text_body, html_body)
