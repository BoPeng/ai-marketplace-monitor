import time
from dataclasses import dataclass
from logging import Logger

from pushbullet import Pushbullet  # type: ignore

from .utils import BaseConfig, hilight


@dataclass
class PushbulletConfig(BaseConfig):
    pushbullet_token: str | None = None

    def send_pushbullet_message(
        self: "PushbulletConfig",
        title: str,
        message: str,
        max_retries: int = 6,
        delay: int = 10,
        logger: Logger | None = None,
    ) -> bool:
        if not self.pushbullet_token:
            return False

        pb = Pushbullet(self.pushbullet_token)

        for attempt in range(max_retries):
            try:
                pb.push_note(title, message)
                return True
            except Exception as e:
                if logger:
                    logger.debug(
                        f"""{hilight("[Notify]", "fail")} Attempt {attempt + 1} failed: {e}"""
                    )
                if attempt < max_retries - 1:
                    if logger:
                        logger.debug(
                            f"""{hilight("[Notify]", "fail")} Retrying in {delay} seconds..."""
                        )
                    time.sleep(delay)
                else:
                    if logger:
                        logger.error(
                            f"""{hilight("[Notify]", "fail")} Max retries reached. Failed to push note to {self.name}."""
                        )
                    return False
        return False
