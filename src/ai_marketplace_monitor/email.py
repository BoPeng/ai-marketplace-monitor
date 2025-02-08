import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from logging import Logger
from typing import List

from .utils import BaseConfig


@dataclass
class SMTPConfig(BaseConfig):
    smtp_server: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    def handle_smtp_server(self: "SMTPConfig") -> None:
        if self.smtp_server is None:
            return
        if not isinstance(self.smtp_server, str):
            raise ValueError("user requires a string smtp_server.")
        self.smtp_server = self.smtp_server.strip()

    def handle_smtp_port(self: "SMTPConfig") -> None:
        if self.smtp_port is None:
            return

        if not isinstance(self.smtp_port, int):
            raise ValueError("user requires an integer smtp_port.")
        if self.smtp_port < 1 or self.smtp_port > 65535:
            raise ValueError("user requires an integer smtp_port between 1 and 65535.")

    def handle_smtp_username(self: "SMTPConfig") -> None:
        if self.smtp_username is None:
            return
        # smtp_username should be a string
        if not isinstance(self.smtp_username, str):
            raise ValueError("user requires a string smtp_username.")
        self.smtp_username = self.smtp_username.strip()

    def handle_smtp_password(self: "SMTPConfig") -> None:
        if self.smtp_password is None:
            return
        # smtp_password should be a string
        if not isinstance(self.smtp_password, str):
            raise ValueError("user requires a string smtp_password.")
        self.smtp_password = self.smtp_password.strip()

    def handle_smtp_from(self: "SMTPConfig") -> None:
        if self.smtp_from is None:
            return
        # smtp_from should be a string
        if not isinstance(self.smtp_from, str):
            raise ValueError("user requires a string smtp_from.")
        self.smtp_from = self.smtp_from.strip()

    def send_email_message(
        self: "SMTPConfig",
        recipients: List[str] | None,
        title: str,
        message: str,
        logger: Logger | None = None,
    ) -> bool:
        if not recipients:
            return False

        sender = self.smtp_from or self.smtp_username or recipients[0]

        smtp_server = self.self.smtp_server
        if sender.endswith("gmail.com"):
            smtp_server = "smtp.gmail.com"
        elif sender.endswith("yahoo.com"):
            smtp_server = "smtp.mail.yahoo.com"
        elif sender.endswith("outlook.com"):
            smtp_server = "smtp-mail.outlook.com"
        elif sender.endswith("hotmail.com"):
            smtp_server = "smtp-mail.outlook.com"
        elif sender.endswith("aol.com"):
            smtp_server = "smtp.aol.com"
        elif sender.endswith("zoho.com"):
            smtp_server = "smtp.zoho.com"
        elif sender.endswith("icloud.com"):
            smtp_server = "smtp.icloud.com"
        elif sender.endswith("protonmail.com"):
            smtp_server = "smtp.protonmail.com"
        elif sender.endswith("proton.me"):
            smtp_server = "smtp.proton.me"
        elif sender.endswith("yandex.com"):
            smtp_server = "smtp.yandex.com"
        elif sender.endswith("gmx.com"):
            smtp_server = "smtp.gmx.com"
        elif sender.endswith("mail.com"):
            smtp_server = "smtp.mail.com"

        if not smtp_server:
            if logger:
                logger.warning(f"Cannot determine a smtp server for sender {sender}")

        # s.starttls()
        msg = EmailMessage()
        msg.set_content(message)

        msg["Subject"] = title
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)

        try:
            with smtplib.SMTP_SSL(smtp_server, self.smtp_port or 465) as smtp:
                smtp.set_debuglevel(1)
                if self.smtp_username and self.smtp_password:
                    smtp.login(self.smtp_username, self.smtp_password)
                    smtp.send_message(msg)
            return True
        except Exception as e:
            if logger:
                logger.error(f"Failed to send email: {e}")
            return False
