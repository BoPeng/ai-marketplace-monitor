import smtplib
import ssl
from dataclasses import dataclass
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from logging import Logger
from typing import List, Tuple

import inflect

from .ai import AIResponse  # type: ignore
from .listing import Listing
from .utils import BaseConfig, NotificationStatus, fetch_with_retry, resize_image_data


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
        if n_expired > 0:
            cnts.append(f"{n_expired} expired ")
        if n_updated > 0:
            cnts.append(f"{n_updated} updated ")
        if force and n_notified > 0:
            cnts.append(f"{n_notified} notified ")
        if len(cnts) > 1:
            cnts[-1] = f"and {cnts[-1]}"
        elif len(cnts) == 0:
            # no new items
            return ""

        title += " ".join(cnts)
        title += f"{p.plural_noun(listings[0].name, len(listings)-(0 if force else n_notified))} from {listings[0].marketplace}"
        return title

    def get_text_message(
        self: "SMTPConfig",
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
        self: "SMTPConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        force: bool = False,
        logger: Logger | None = None,
    ) -> Tuple[str, list[Tuple[bytes, str, str]]]:  # Return HTML and image data
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
            <style type="text/css">
                /* Base */
                body {
                    margin: 0;
                    padding: 0;
                    min-width: 100%;
                    font-family: Arial, sans-serif;
                    font-size: 16px;
                    line-height: 1.5;
                    background-color: #FAFAFA;
                    color: #222222;
                }

                /* Layout */
                .wrapper {
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }

                .header {
                    background-color: #2C5364;
                    padding: 20px;
                    text-align: center;
                }

                .content {
                    background-color: #FFFFFF;
                    padding: 20px;
                }

                .footer {
                    background-color: #F5F5F5;
                    padding: 20px;
                    text-align: center;
                    font-size: 12px;
                    color: #666666;
                }

                /* Tables */
                .listing-table {
                    width: 100%;
                    border-collapse: collapse;
                    margin: 20px 0;
                }

                .listing-table td {
                    padding: 12px;
                    border-bottom: 1px solid #EEEEEE;
                }

                /* Typography */
                h1 {
                    color: #FFFFFF;
                    font-size: 24px;
                    margin: 0;
                }

                h2 {
                    color: #2C5364;
                    font-size: 20px;
                    margin: 0 0 20px 0;
                }

                /* Images */
                .listing-image {
                    max-width: 100%;
                    height: auto;
                    margin: 10px 0;
                }

                /* Status Tags */
                .status-tag {
                    display: inline-block;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-size: 12px;
                    font-weight: bold;
                }

                /* Description styling */
                .description {
                    color: #444444;
                    margin: 12px 0;
                    line-height: 1.6;
                    font-size: 14px;
                    white-space: pre-line;  /* Preserves line breaks */
                }

                .status-new { background-color: #4CAF50; color: white; }
                .status-updated { background-color: #2196F3; color: white; }
                .status-expired { background-color: #F44336; color: white; }
                .status-sent { background-color: #9E9E9E; color: white; }
            </style>
        </head>
        <body>
            <div class="wrapper">
                <!-- Header -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                        <td class="header">
                            <h1>AI Marketplace Monitor</h1>
                        </td>
                    </tr>
                </table>

                <!-- Content -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                        <td class="content">
                            <h2>Latest Listings</h2>
                            <table class="listing-table" cellpadding="0" cellspacing="0" border="0">
        """
        images = []  # Will store (image_data, content_type, cid) tuples

        # Add listings
        for listing, rating, ns in zip(listings, ratings, notification_status):
            status_class = ""
            status_text = ""

            if ns == NotificationStatus.NOT_NOTIFIED:
                status_class = "status-new"
                status_text = "NEW"
            elif ns == NotificationStatus.LISTING_CHANGED:
                status_class = "status-updated"
                status_text = "UPDATED"
            elif ns == NotificationStatus.EXPIRED:
                status_class = "status-expired"
                status_text = "EXPIRED"
            elif ns == NotificationStatus.NOTIFIED and force:
                status_class = "status-sent"
                status_text = "NOTIFIED"

            html += f"""
                <tr>
                  <td style="padding: 20px;">
                    <!-- Title with integrated status tag -->
                    <div style="margin-bottom: 15px;">
                        <h3 style="color: #2C5364; font-size: 18px; font-weight: bold; margin: 0; display: inline;">
                            {listing.title}
                        </h3>
                        <span class="status-tag {status_class}"
                              style="display: inline-block; padding: 3px 8px; border-radius: 3px;
                                     font-size: 12px; font-weight: bold; margin-left: 10px;
                                     vertical-align: middle;">
                            {status_text}
                        </span>
                    </div>

                    <!-- Info rows -->
                    <div style="color: #666666; margin-bottom: 10px;">
                        <span style="font-weight: bold; color: #333333;">Price:</span> {listing.price}
                    </div>
                    <div style="color: #666666; margin-bottom: 15px;">
                        <span style="font-weight: bold; color: #333333;">Location:</span> {listing.location}
                    </div>

                    <!-- Description -->
                    <div style="color: #444444; margin: 12px 0; line-height: 1.6; font-size: 14px;
                                white-space: pre-line; background-color: #FFFFFF; padding: 0;">
                        {listing.description if listing.description else ''}
                    </div>
            """

            # Add AI rating if available
            if rating.comment != AIResponse.NOT_EVALUATED:
                html += f"""
                        <p style="margin: 0 0 10px 0;">
                            <strong>AI Rating:</strong> {rating.conclusion} ({rating.score})<br>
                            <em>{rating.comment}</em>
                        </p>
                """
            # Add image if available
            if listing.image:
                result = fetch_with_retry(listing.image, logger=logger)
                if result:
                    original_image_data, ct = result
                    image_data = resize_image_data(original_image_data)
                    if image_data and len(image_data) <= 1024 * 1024:
                        cid = f"image_{hash(listing.image)}"
                        images.append((image_data, ct, cid))

                        # Reference image using cid: URL
                        html += f"""
                            <img src="cid:{cid}"
                                 alt="img:{listing.title}"
                                class="listing-image">
                        """

                        # import os

                        # debug_dir = "debug_images"
                        # os.makedirs(debug_dir, exist_ok=True)

                        # # Create a safe filename from the listing title
                        # safe_filename = "".join(
                        #     c for c in listing.title if c.isalnum() or c in (" ", "-", "_")
                        # ).rstrip()
                        # safe_filename = safe_filename[:50]  # Limit length

                        # # Write original image
                        # original_path = os.path.join(debug_dir, f"{safe_filename}_original.jpg")
                        # with open(original_path, "wb") as f:
                        #     f.write(original_image_data)

                        # resized_path = os.path.join(debug_dir, f"{safe_filename}_resized.jpg")
                        # with open(resized_path, "wb") as f:
                        #     f.write(image_data)
                    else:
                        if logger:
                            logger.debug(f"Image too large: {len(image_data)} bytes, skipped.")

                elif logger:
                    logger.debug(f"Failed to fetch image: {listing.image}")

            # Add view listing button
            html += f"""
                        <p style="margin: 10px 0;">
                            <a href="{listing.post_url.split('?')[0]}"
                                style="background-color: #2C5364; color: white; padding: 10px 20px;
                                        text-decoration: none; border-radius: 4px; display: inline-block;">
                                View Listing
                            </a>
                        </p>
                    </td>
                </tr>
            """

        # Close content and add footer
        html += """
                            </table>
                        </td>
                    </tr>
                </table>

                <!-- Footer -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                        <td class="footer">
                            <p>This is an automated message from AI Marketplace Monitor</p>
                            <p>
                                Check How it Works: <a href="https://github.com/BoPeng/ai-marketplace-monitor">https://github.com/BoPeng/ai-marketplace-monitor</a><br>
                                To stop this email, contact the sender
                            </p>
                        </td>
                    </tr>
                </table>
            </div>
        </body>
        </html>
        """

        return html, images

    def notify_through_email(
        self: "SMTPConfig",
        recipients: List[str] | None,
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        force: bool = False,
        logger: Logger | None = None,
    ) -> bool:
        if not recipients:
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
        return self.send_email_message(
            recipients, title, message, html_message, images, logger=logger
        )

    def send_email_message(
        self: "SMTPConfig",
        recipients: List[str] | None,
        title: str,
        message: str,
        html: str,
        images: List[Tuple[bytes, str, str]],
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
        msg = MIMEMultipart("related")
        msg["Subject"] = title
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)

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
                logger.info(f"""Email with title {title} sent to {msg["To"]}""")
            return True
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if logger:
                logger.error(f"Failed to send email: {e}")
            return False
