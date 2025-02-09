import base64
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from logging import Logger
from typing import List

import inflect

from .ai import AIResponse  # type: ignore
from .listing import Listing
from .utils import BaseConfig, NotificationStatus, fetch_with_retry, hilight, resize_image_data


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

    def get_title(
        self: "SMTPConfig",
        listings: List[Listing],
        notification_status: List[NotificationStatus],
    ) -> str:
        p = inflect.engine()
        n_new = len([x for x in notification_status if x == NotificationStatus.NOT_NOTIFIED])
        n_notified = len([x for x in notification_status if x == NotificationStatus.NOTIFIED])
        n_expired = len([x for x in notification_status if x == NotificationStatus.EXPIRED])
        n_updated = len(
            [x for x in notification_status if x == NotificationStatus.LISTING_CHANGED]
        )
        title = "Found "
        cnts = []
        if n_new > 0:
            cnts.append(f"{n_new} new ")
        if n_expired > 0:
            cnts.append(f"{n_expired} expired ")
        if n_updated > 0:
            cnts.append(f"{n_updated} updated ")
        if len(cnts) > 1:
            cnts[-1] = f"and {cnts[-1]}"
        if len(cnts) > 0:
            cnts[-1] = hilight(cnts[-1])
        else:
            # no new items
            return ""

        title += " ".join(cnts)
        title += f"{p.plural_noun(listings[0].name, len(listings)-n_notified)} from {listings[0].marketplace}"
        return title

    def get_text_message(
        self: "SMTPConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        logger: Logger | None = None,
    ) -> str:
        messages = []
        for listing, rating, ns in zip(listings, ratings, notification_status):
            prefix = ""
            if ns == NotificationStatus.NOTIFIED:
                continue
            if ns == NotificationStatus.EXPIRED:
                prefix = "[REMINDER] "
            elif ns == NotificationStatus.LISTING_CHANGED:
                prefix = "[lISTING UPDATED] "

            messages.append(
                (
                    f"{prefix}{listing.title}\n{listing.price}, {listing.location}\n"
                    f"{listing.post_url.split('?')[0]}"
                )
                if rating.comment == AIResponse.NOT_EVALUATED
                else (
                    f"{prefix} [{rating.conclusion} ({rating.score})] {listing.title}\n"
                    f"{listing.price}, {listing.location}\n"
                    f"{listing.post_url.split('?')[0]}\n"
                    f"AI: {rating.comment}"
                )
            )
        message = "\n\n".join(messages)
        return message

    def get_html_message(
        self: "SMTPConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        logger: Logger | None,
    ) -> str:
        html_text = """
    <html>
        <body>
    """

        messages = []
        for listing, rating, ns in zip(listings, ratings, notification_status):
            prefix = ""
            if ns == NotificationStatus.NOTIFIED:
                continue
            if ns == NotificationStatus.EXPIRED:
                prefix = "[REMINDER] "
            elif ns == NotificationStatus.LISTING_CHANGED:
                prefix = "[lISTING UPDATED] "

            messages.append(
                (
                    f"<h3>{prefix}<b>{listing.title}</b><h3><p><b>{listing.price}</b>, {listing.location}</p>"
                    f"""<p><a href="{listing.post_url.split('?')[0]}">{listing.post_url.split('?')[0]}</a><p>"""
                )
                if rating.comment == AIResponse.NOT_EVALUATED
                else (
                    f"<h3>{prefix} [{rating.conclusion} ({rating.score})] <b>{listing.title}</b></h3>"
                    f"<p><b>{listing.price}</b>, {listing.location}</p>"
                    f"""<p><a href="{listing.post_url.split('?')[0]}">{listing.post_url.split('?')[0]}</a><p>"""
                    f"<p><b>AI</b>: {rating.comment}</p>"
                )
            )
            # attaching image
            if listing.image:
                # download the content of image with URL listing.image
                result = fetch_with_retry(listing.image, logger=logger)
                if result is None:
                    continue
                image_data, content_type = result
                # get the image data, try to resize if it is too big
                image_data = resize_image_data(image_data)
                if len(image_data) > 1024 * 1024:
                    if logger:
                        logger.warning(f"Image {listing.image} is too big, skipping.")
                    continue
                # encode the image data to base64
                encoded_image = base64.b64encode(image_data).decode("utf-8")
                # create the HTML img tag with the base64 encoded image
                img_tag = f"""<img src="data:{content_type};base64,{encoded_image}"
                    alt="Image" width="500" height="auto" style="max-width: 600px;">"""
                # add the img tag to the message
                messages[-1] += img_tag

        html_text = "\n\n".join(messages)
        html_text += """
        </body>
    </html>
    """
        return html_text

    def notify_through_email(
        self: "SMTPConfig",
        recipients: List[str] | None,
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        logger: Logger | None = None,
    ) -> bool:
        if not recipients:
            if logger:
                logger.debug("No recipients specified. No email sent.")
            return False

        title = self.get_title(listings, notification_status)
        if not title:
            if logger:
                logger.debug("No new listings. No email sent.")
            return False
        message = self.get_text_message(listings, ratings, notification_status, logger)
        html_message = self.get_html_message(listings, ratings, notification_status, logger)
        return self.send_email_message(recipients, title, message, html_message, logger=logger)

    def send_email_message(
        self: "SMTPConfig",
        recipients: List[str] | None,
        title: str,
        message: str,
        html: str,
        logger: Logger | None = None,
    ) -> bool:
        if not recipients:
            if logger:
                logger.debug("No recipients specified. No email sent.")
            return False

        sender = self.smtp_from or self.smtp_username or recipients[0]

        if self.smtp_server:
            smtp_server = self.smtp_server
        else:
            smtp_server = f"smtp.{sender.split("@")[1]}"

        # s.starttls()
        msg = MIMEMultipart()
        msg["Subject"] = title
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(message, "plain"))
        msg.attach(MIMEText(html, "html"))

        try:
            smtp_port = self.smtp_port or 587
            smtp_username = self.smtp_username or sender
            if not smtp_username:
                if logger:
                    logger.error("No smtp username.")
                return False

            smtp_password = self.smtp_password
            if not smtp_password:
                if logger:
                    logger.error("No smtp password.")
                return False

            context = ssl.create_default_context()
            with smtplib.SMTP(smtp_server, smtp_port) as smtp:
                # smtp.set_debuglevel(1)
                smtp.ehlo()  # Can be omitted
                smtp.starttls(context=context)
                smtp.ehlo()  # Can be omitted
                try:
                    smtp.login(smtp_username, smtp_password)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    if logger:
                        logger.error(
                            f"Failed to login to smtp server {smtp_server}:{smtp_port} with username {smtp_username}: {e}"
                        )
                    return False
                smtp.send_message(msg)
            if logger:
                logger.info(f"""Email with title {title} sent to {msg["To"]}""")
            return True
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if logger:
                logger.error(f"Failed to send email: {e}")
            return False
