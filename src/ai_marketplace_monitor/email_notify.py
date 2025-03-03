import smtplib
import ssl
from dataclasses import dataclass
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from logging import Logger
from pathlib import Path
from typing import List, Tuple

import inflect
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .ai import AIResponse  # type: ignore
from .listing import Listing
from .notification import NotificationConfig, NotificationStatus
from .utils import fetch_with_retry, hilight, resize_image_data, value_from_environ


@dataclass
class EmailNotificationConfig(NotificationConfig):
    email: List[str] | None = None
    smtp_server: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    def handle_email(self: "EmailNotificationConfig") -> None:
        if self.email is None:
            return
        if isinstance(self.email, str):
            self.email = [self.email]
        if not isinstance(self.email, list) or not all(
            (isinstance(x, str) and "@" in x and "." in x.split("@")[1]) for x in self.email
        ):
            raise ValueError(
                f"Item {hilight(self.name)} email must be a string or list of string."
            )

    def handle_smtp_server(self: "EmailNotificationConfig") -> None:
        if self.smtp_server is None:
            return

        if not isinstance(self.smtp_server, str):
            raise ValueError("user requires a string smtp_server.")
        self.smtp_server = self.smtp_server.strip()

    def handle_smtp_port(self: "EmailNotificationConfig") -> None:
        if self.smtp_port is None:
            return

        if not isinstance(self.smtp_port, int):
            raise ValueError("user requires an integer smtp_port.")
        if self.smtp_port < 1 or self.smtp_port > 65535:
            raise ValueError("user requires an integer smtp_port between 1 and 65535.")

    def handle_smtp_username(self: "EmailNotificationConfig") -> None:
        if self.smtp_username is None:
            return

        self.smtp_username = value_from_environ(self.smtp_username)

        # smtp_username should be a string
        if not isinstance(self.smtp_username, str) or not self.smtp_username:
            raise ValueError("A non-empty value is requires for option smtp_username.")
        self.smtp_username = self.smtp_username.strip()

    def handle_smtp_password(self: "EmailNotificationConfig") -> None:
        if self.smtp_password is None:
            return

        self.smtp_password = value_from_environ(self.smtp_password)

        # smtp_password should be a string
        if not isinstance(self.smtp_password, str) or not self.smtp_password:
            raise ValueError("A non-empty value is is required for option smtp_password.")
        self.smtp_password = self.smtp_password.strip()

    def handle_smtp_from(self: "EmailNotificationConfig") -> None:
        if self.smtp_from is None:
            return
        # smtp_from should be a string
        if not isinstance(self.smtp_from, str):
            raise ValueError("user requires a string smtp_from.")
        self.smtp_from = self.smtp_from.strip()

    def get_title(
        self: "EmailNotificationConfig",
        listings: List[Listing],
        notification_status: List[NotificationStatus],
        force: bool = False,
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
        if n_updated > 0:
            cnts.append(f"{n_updated} updated ")
        if n_expired > 0 or (force and n_notified > 0):
            cnts.append(f"{n_expired + (n_notified if force else 0)} revisitable ")
        if len(cnts) > 1:
            cnts[-1] = f"and {cnts[-1]}"
        elif len(cnts) == 0:
            # no new items
            return ""

        title += " ".join(cnts)
        title += f"{listings[0].name} {p.plural_noun('listing', len(listings)-(0 if force else n_notified))} from {listings[0].marketplace}"
        return title

    def get_text_message(
        self: "EmailNotificationConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        force: bool = False,
        logger: Logger | None = None,
    ) -> str:
        messages = []
        for listing, rating, ns in zip(listings, ratings, notification_status):
            prefix = ""
            if ns == NotificationStatus.NOTIFIED:
                if force:
                    prefix = "[NOTIFIED] "
                else:
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
        self: "EmailNotificationConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        force: bool = False,
        logger: Logger | None = None,
    ) -> Tuple[str, list[Tuple[bytes, str, str]]]:  # Return HTML and image data
        template_dir = Path(__file__).parent

        # Set up Jinja2 environment
        env = Environment(
            loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["html", "xml"])
        )

        # Add custom filter for hashing
        env.filters["hash"] = hash

        # Load template
        template = env.get_template("email.html.j2")

        # Prepare images list for attachments
        images = []
        valid_image_hashes = set()  # Track which images were successfully processed

        # Process images first
        for listing in listings:
            if listing.image:
                result = fetch_with_retry(listing.image, logger=logger)
                if result:
                    image_data, content_type = result
                    image_data = resize_image_data(image_data)
                    if image_data and len(image_data) <= 1024 * 1024:
                        image_hash = hash(listing.image)
                        images.append((image_data, content_type, f"image_{image_hash}"))
                        valid_image_hashes.add(image_hash)  # Track valid image
                    else:
                        if logger:
                            logger.debug(f"Image too large: {len(image_data)} bytes, skipped.")
                else:
                    if logger:
                        logger.debug(f"Failed to fetch image: {listing.image}")

        # Render template
        html = template.render(
            listings=zip(listings, ratings, notification_status),
            force=force,
            item_name=listings[0].name.capitalize(),
            NotificationStatus=NotificationStatus,  # Pass enum for comparison
            valid_image_hashes=valid_image_hashes,  # Pass set of valid image hashes
        )
        return html, images

    def notify(
        self: "EmailNotificationConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        force: bool = False,
        logger: Logger | None = None,
    ) -> bool:
        if not self.email:
            if logger:
                logger.debug("No recipients specified. No email sent.")
            return False

        title = self.get_title(listings, notification_status, force=force)
        if not title:
            if logger:
                logger.debug("No new listings. No email sent.")
            return False
        message = self.get_text_message(
            listings, ratings, notification_status, force, logger=logger
        )
        html_message, images = self.get_html_message(
            listings, ratings, notification_status, force, logger=logger
        )
        return self.send_email_message(title, message, html_message, images, logger=logger)

    def send_email_message(
        self: "EmailNotificationConfig",
        title: str,
        message: str,
        html: str,
        images: List[Tuple[bytes, str, str]],
        logger: Logger | None = None,
    ) -> bool:
        if not self.email:
            if logger:
                logger.debug("No recipients specified. No email sent.")
            return False

        sender = self.smtp_from or self.smtp_username or self.email[0]

        if self.smtp_server:
            smtp_server = self.smtp_server
        else:
            smtp_server = f"""smtp.{sender.split("@")[1]}"""

        # s.starttls()
        msg = MIMEMultipart("related")
        msg["Subject"] = title
        # can use the humanized version of self.name as well
        msg["From"] = formataddr(("AI Marketplace Monitor", sender))
        msg["To"] = ", ".join(self.email)

        # Create alternative part
        alt_part = MIMEMultipart("alternative")
        msg.attach(alt_part)

        alt_part.attach(MIMEText(message, "plain"))
        alt_part.attach(MIMEText(html, "html"))  # HTML part last = preferred

        # Attach images
        for image_data, _, cid in images:
            image = MIMEImage(image_data)
            image.add_header("Content-ID", f"<{cid}>")
            image.add_header("Content-Disposition", "inline")
            msg.attach(image)

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
                logger.info(
                    f"""{hilight("[Notify]", "succ")} Sent {self.name} an email with title {hilight(title)}"""
                )
            return True
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if logger:
                logger.error(f"Failed to send email: {e}")
            return False
