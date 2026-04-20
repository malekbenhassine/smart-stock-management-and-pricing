import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings


class EmailService:
    @staticmethod
    def send_activation_email(to_email: str, full_name: str, token: str) -> None:
        activation_link = f"{settings.FRONTEND_ACTIVATION_URL}?token={token}"

        subject = "Activation de votre compte"
        html_body = f"""
        <html>
          <body>
            <p>Bonjour {full_name},</p>
            <p>Votre compte a été créé avec succès.</p>
            <p>Veuillez cliquer sur le lien suivant pour définir votre mot de passe et activer votre compte :</p>
            <p><a href="{activation_link}">Activer mon compte</a></p>
          </body>
        </html>
        """

        EmailService._send_html_email(to_email, subject, html_body)

    @staticmethod
    def send_reset_password_email(to_email: str, full_name: str, token: str) -> None:
        reset_link = f"{settings.FRONTEND_RESET_PASSWORD_URL}?token={token}"

        subject = "Réinitialisation de votre mot de passe"
        html_body = f"""
        <html>
          <body>
            <p>Bonjour {full_name},</p>
            <p>Vous avez demandé la réinitialisation de votre mot de passe.</p>
            <p>Veuillez cliquer sur le lien suivant :</p>
            <p><a href="{reset_link}">Réinitialiser mon mot de passe</a></p>
          </body>
        </html>
        """

        EmailService._send_html_email(to_email, subject, html_body)

    @staticmethod
    def _send_html_email(to_email: str, subject: str, html_body: str) -> None:
        msg = MIMEMultipart()
        msg["From"] = settings.MAIL_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.sendmail(settings.MAIL_FROM, to_email, msg.as_string())