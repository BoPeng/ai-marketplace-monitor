import hashlib
import json
import os
import random
import re
import time
from dataclasses import asdict, dataclass, fields
from enum import Enum
from logging import Logger
from pathlib import Path
from typing import Any, Dict, List, Tuple, TypeVar

import parsedatetime  # type: ignore
import requests  # type: ignore
import rich
from diskcache import Cache  # type: ignore
from playwright.sync_api import ProxySettings
from pyparsing import (
    CharsNotIn,
    Keyword,
    ParserElement,
    ParseResults,
    Word,
    alphanums,
    infix_notation,
    opAssoc,
)
from requests.exceptions import RequestException, Timeout  # type: ignore
from rich.pretty import pretty_repr

try:
    from pynput import keyboard  # type: ignore

    pynput_installed = True
except ImportError:
    # some platforms are not supported
    pynput_installed = False

import io

import rich.pretty
from PIL import Image
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

# home directory for all settings and caches
amm_home = Path.home() / ".ai-marketplace-monitor"
amm_home.mkdir(parents=True, exist_ok=True)

cache = Cache(amm_home)


TConfigType = TypeVar("TConfigType", bound="BaseConfig")


class SleepStatus(Enum):
    NOT_DISRUPTED = 0
    BY_KEYBOARD = 1
    BY_FILE_CHANGE = 2


class CacheType(Enum):
    LISTING_DETAILS = "listing-details"
    AI_INQUIRY = "ai-inquiries"
    USER_NOTIFIED = "user-notifications"
    COUNTERS = "counters"


class CounterItem(Enum):
    SEARCH_PERFORMED = "Search performed"
    LISTING_EXAMINED = "Total listing examined"
    LISTING_QUERY = "New listing fetched"
    EXCLUDED_LISTING = "Listing excluded"
    NEW_VALIDATED_LISTING = "New validated listing"
    AI_QUERY = "Total AI Queries"
    NEW_AI_QUERY = "New AI Queries"
    FAILED_AI_QUERY = "Failed AI Queries)"
    NOTIFICATIONS_SENT = "Notifications sent"
    REMINDERS_SENT = "Reminders sent"


class KeyboardMonitor:
    confirm_character = "c"

    def __init__(self: "KeyboardMonitor") -> None:
        self._paused: bool = False
        self._listener: keyboard.Listener | None = None
        self._sleeping: bool = False
        self._confirmed: bool | None = None

    def start(self: "KeyboardMonitor") -> None:
        if pynput_installed:
            self._listener = keyboard.Listener(on_press=self.handle_key_press)
            self._listener.start()  # start to listen on a separate thread

    def stop(self: "KeyboardMonitor") -> None:
        if self._listener:
            self._listener.stop()  # stop the listener

    def start_sleeping(self: "KeyboardMonitor") -> None:
        self._sleeping = True

    def confirm(self: "KeyboardMonitor", msg: str | None = None) -> bool:
        self._confirmed = False
        rich.print(
            msg
            or f"Press {hilight(self.confirm_character)} to enter interactive mode in 10 seconds: ",
            end="",
            flush=True,
        )
        try:
            count = 0
            while self._confirmed is False:
                time.sleep(0.1)
                if self._confirmed:
                    return True
                count += 1
                # wait a total of 10s
                if count > 100:
                    break
            return self._confirmed
        finally:
            # whether or not confirm is successful, reset paused and confirmed flag
            self._paused = False
            self._confirmed = None

    def is_sleeping(self: "KeyboardMonitor") -> bool:
        return self._sleeping

    def is_paused(self: "KeyboardMonitor") -> bool:
        return self._paused

    def is_confirmed(self: "KeyboardMonitor") -> bool:
        return self._confirmed is True

    def set_paused(self: "KeyboardMonitor", paused: bool = True) -> None:
        self._paused = paused

    if pynput_installed:

        def handle_key_press(
            self: "KeyboardMonitor", key: keyboard.Key | keyboard.KeyCode | None
        ) -> None:
            # is sleeping, wake up
            if self._sleeping:
                if key == keyboard.Key.esc:
                    self._sleeping = False
                    return
            # if waiting for confirmation, set confirm
            if self._confirmed is False:
                if getattr(key, "char", "") == self.confirm_character:
                    self._confirmed = True
                    return
            # if being paused
            if self.is_paused():
                if key == keyboard.Key.esc:
                    print("Still searching ... will pause as soon as I am done.")
                    return
            if key == keyboard.Key.esc:
                print("Pausing search ...")
                self._paused = True


class Counter:

    def increment(self: "Counter", counter_key: CounterItem, item_name: str, by: int = 1) -> None:
        key = (CacheType.COUNTERS.value, counter_key.value, item_name)
        try:
            cache.incr(key, by, default=None)
        except KeyError:
            # if key does not exist, set it to by, and set tag
            cache.set(key, by, tag=CacheType.COUNTERS.value)

    def __str__(self: "Counter") -> str:
        """Return pretty form of all non-zero counters"""
        # this is super inefficient. Thankfully we are not calling this often.
        # See https://github.com/grantjenks/python-diskcache/issues/341
        # for details
        counters = {
            key: cache.get(key) for key in cache.iterkeys() if key[0] == CacheType.COUNTERS.value
        }
        item_names = {x[2] for x in counters.keys()}
        cnts = {}
        for item_name in item_names:
            # per-item statistics
            cnts[item_name] = {
                x.value: counters.get((CacheType.COUNTERS.value, x.value, item_name), 0)
                for x in CounterItem
                if counters.get((CacheType.COUNTERS.value, x.value, item_name), 0)
            }
        # total statistics
        cnts["Total"] = {
            x.value: sum(
                counters.get((CacheType.COUNTERS.value, x.value, item_name), 0)
                for item_name in item_names
            )
            for x in CounterItem
            if sum(
                counters.get((CacheType.COUNTERS.value, x.value, item_name), 0)
                for item_name in item_names
            )
        }
        return pretty_repr(cnts)


counter = Counter()


def hash_dict(obj: Dict[str, Any]) -> str:
    """Hash a dictionary to a string."""
    dict_string = json.dumps(obj).encode("utf-8")
    return hashlib.sha256(dict_string).hexdigest()


@dataclass
class BaseConfig:
    name: str
    enabled: bool | None = None

    def __post_init__(self: "BaseConfig") -> None:
        """Handle all methods that start with 'handle_' in the dataclass."""
        for f in fields(self):
            handle_method = getattr(self, f"handle_{f.name}", None)
            if handle_method:
                handle_method()

    def handle_enabled(self: "BaseConfig") -> None:
        if self.enabled is None:
            return
        if not isinstance(self.enabled, bool):
            raise ValueError(f"Item {hilight(self.name)} enabled must be a boolean.")

    @property
    def hash(self: "BaseConfig") -> str:
        return hash_dict(asdict(self))


@dataclass
class MonitorConfig(BaseConfig):
    proxy_server: List[str] | None = None
    proxy_bypass: str | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None

    def handle_proxy_server(self: "MonitorConfig") -> None:
        if self.proxy_server is None:
            return
        if isinstance(self.proxy_server, str):
            self.proxy_server = [self.proxy_server]

        if not all(isinstance(x, str) for x in self.proxy_server):
            raise ValueError(f"Item {hilight(self.name)} proxy_server must be a string.")
        if not all(x.startswith("http://") or x.startswith("https://") for x in self.proxy_server):
            raise ValueError(
                f"Item {hilight(self.name)} proxy_server must start with http:// or https://"
            )

    def handle_proxy_bypass(self: "MonitorConfig") -> None:
        if self.proxy_bypass is None:
            return
        if not isinstance(self.proxy_bypass, str):
            raise ValueError(f"Item {hilight(self.name)} proxy_bypass must be a string.")

    def handle_proxy_username(self: "MonitorConfig") -> None:
        if self.proxy_username is None:
            return

        self.proxy_username = value_from_environ(self.proxy_username)

        if not isinstance(self.proxy_username, str):
            raise ValueError(f"Item {hilight(self.name)} proxy_username must be a string.")

    def handle_proxy_password(self: "MonitorConfig") -> None:
        if self.proxy_password is None:
            return

        self.proxy_password = value_from_environ(self.proxy_password)

        if not isinstance(self.proxy_password, str):
            raise ValueError(f"Item {hilight(self.name)} proxy_password must be a string.")

    def get_proxy_options(self: "MonitorConfig") -> ProxySettings | None:
        if not self.proxy_server:
            return None
        res = ProxySettings(server=random.choice(self.proxy_server))
        if self.proxy_username and self.proxy_password:
            res["username"] = self.proxy_username
            res["password"] = self.proxy_password
        if self.proxy_bypass:
            res["bypass"] = self.proxy_bypass
        return res


def calculate_file_hash(file_paths: List[Path]) -> str:
    """Calculate the SHA-256 hash of the file content."""
    hasher = hashlib.sha256()
    # they should exist, just to make sure
    for file_path in file_paths:
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        #
        with open(file_path, "rb") as file:
            while chunk := file.read(8192):
                hasher.update(chunk)
    return hasher.hexdigest()


def merge_dicts(dicts: list) -> dict:
    """Merge a list of dictionaries into a single dictionary, including nested dictionaries.

    :param dicts: A list of dictionaries to merge.
    :return: A single merged dictionary.
    """

    def merge(d1: dict, d2: dict) -> dict:
        for key, value in d2.items():
            if key in d1:
                if isinstance(d1[key], dict) and isinstance(value, dict):
                    d1[key] = merge(d1[key], value)
                elif isinstance(d1[key], list) and isinstance(value, list):
                    d1[key].extend(value)
                else:
                    d1[key] = value
            else:
                d1[key] = value
        return d1

    result: Dict[str, Any] = {}
    for dictionary in dicts:
        result = merge(result, dictionary)
    return result


def normalize_string(string: str) -> str:
    """Normalize a string by replacing multiple spaces (including space, tab, and newline) with a single space."""
    return re.sub(r"\s+", " ", string).lower()


ParserElement.enable_packrat()
double_quoted_string = ('"' + CharsNotIn('"').leaveWhitespace() + '"').setParseAction(
    lambda t: t[1]
)  # removes quotes, keeps only the content
single_quoted_string = ("'" + CharsNotIn("'").leaveWhitespace() + "'").setParseAction(
    lambda t: t[1]
)  # removes quotes, keeps only the content

special_chars = "!@#$%^&*-_=+[]{}|;:'\",.<>?/\\`~"
unquoted_string = Word(alphanums + special_chars)

operand = double_quoted_string | single_quoted_string | unquoted_string
and_op = Keyword("AND")
or_op = Keyword("OR")
not_op = Keyword("NOT")

# Define the grammar for parsing
expr = infix_notation(
    operand,
    [
        (not_op, 1, opAssoc.RIGHT),
        (and_op, 2, opAssoc.LEFT),
        (or_op, 2, opAssoc.LEFT),
    ],
)


def is_substring(
    var1: str | List[str], var2: str | List[str], logger: Logger | None = None
) -> bool:
    """Check if var1 is a substring of var2, after normalizing both strings. One of them can be a list of strings.

    var1: can be a single string, or a list of string, for which a condition of OR is assumed.
          this program will parse var11 for "AND", "OR" and "NOT", and return the results of the
          logical expression.

    var2: one or more strings for testing if strings in  "var1" is a substring.
    """
    if isinstance(var1, list):
        return any(is_substring(x, var2, logger) for x in var1)

    # parse the expression
    parsed = ""
    try:
        parsed = expr.parseString(var1, parseAll=True)[0]
    except Exception:
        # treat var1 as literal string for searching.
        if any(x in var1 for x in (" AND ", " OR ", " NOT ", "(NOT ")) or var1.startswith("NOT "):
            if logger:
                logger.warning(
                    f"Failed to parse {var1} as a logical expression. Treating it as literal string."
                )
        if isinstance(var2, str):
            return normalize_string(var1) in normalize_string(var2)
        return any(normalize_string(var1) in normalize_string(s2) for s2 in var2)

    def evaluate_expression(parsed_expression: str | ParseResults) -> bool:
        if isinstance(parsed_expression, str):
            if isinstance(var2, str):
                return normalize_string(parsed_expression) in normalize_string(var2)
            return any(normalize_string(parsed_expression) in normalize_string(s) for s in var2)

        if len(parsed_expression) == 1:
            return evaluate_expression(parsed_expression[0])

        if parsed_expression[0] == "NOT":
            return not evaluate_expression(parsed_expression[1])

        if parsed_expression[-2] == "AND":
            return evaluate_expression(parsed_expression[:-2]) and evaluate_expression(
                parsed_expression[-1]
            )

        if parsed_expression[-2] == "OR":
            return evaluate_expression(parsed_expression[:-2]) or evaluate_expression(
                parsed_expression[-1]
            )
        if logger:
            logger.error(f"Invalid expression: {parsed_expression}")
        return False

    return evaluate_expression(parsed)


class ChangeHandler(FileSystemEventHandler):
    def __init__(self: "ChangeHandler", files: List[str]) -> None:
        self.changed = False
        self.files = files

    def on_modified(self: "ChangeHandler", event: FileSystemEvent) -> None:
        if not event.is_directory and event.src_path in self.files:
            self.changed = True


def doze(
    duration: int, files: List[Path] | None = None, keyboard_monitor: KeyboardMonitor | None = None
) -> SleepStatus:
    """Sleep for a specified duration while monitoring the change of files.

    Return:
        0: if doze was done naturally.
        1: if doze was disrupted by keyboard
        2: if doze was disrupted by file change
    """
    event_handler = ChangeHandler([str(x) for x in (files or [])])
    observers = []
    if keyboard_monitor:
        keyboard_monitor.start_sleeping()

    for filename in files or []:
        if not filename.exists():
            raise FileNotFoundError(f"File not found: {filename}")
        observer = Observer()
        # we can only monitor a directory
        observer.schedule(event_handler, str(filename.parent), recursive=False)
        observer.start()
        observers.append(observer)

    start_time = time.time()
    try:
        while time.time() - start_time < duration:
            if event_handler.changed:
                return SleepStatus.BY_FILE_CHANGE
            time.sleep(1)
            if keyboard_monitor and not keyboard_monitor.is_sleeping():
                return SleepStatus.BY_KEYBOARD
        return SleepStatus.NOT_DISRUPTED
    finally:
        for observer in observers:
            observer.stop()
            observer.join()


def extract_price(price: str) -> str:
    currencies = [
        x for x in ("$", "€", "£", "¥", "₹", "¥", "$", "$", "CHF", "₩") if price.startswith(x)
    ]
    currency = "$" if not currencies else currencies[0]

    if price.count(currency) > 1:
        match = re.search(currency + r"\d+(?:\.\d{2})?", price)
        price = match.group(0) if match else price
    if "\xa0" in price:
        price = price.split("\xa0")[0]
    return price


def convert_to_seconds(time_str: str) -> int:
    cal = parsedatetime.Calendar(version=parsedatetime.VERSION_CONTEXT_STYLE)
    time_struct, _ = cal.parse(time_str)
    return int(time.mktime(time_struct) - time.mktime(time.localtime()))


def hilight(text: str, style: str = "name") -> str:
    """Highlight the keywords in the text with the specified color."""
    color = {
        "name": "cyan",
        "fail": "red",
        "info": "blue",
        "succ": "green",
    }.get(style, "blue")
    return f"[{color}]{text}[/{color}]"


def fetch_with_retry(
    url: str,
    timeout: int = 10,
    max_retries: int = 3,
    backoff_factor: float = 1.5,
    logger: Logger | None = None,
) -> Tuple[bytes, str] | None:
    """Fetch URL content with retry logic

    Args:
        url: URL to fetch
        timeout: Timeout in seconds
        max_retries: Maximum number of retry attempts
        backoff_factor: Multiplier for exponential backoff
        logger: logger object

    Returns:
        Tuple of (content, content_type) if successful, None if failed
    """
    if logger:
        logger.debug(f"Fetching {url} with timeout {timeout}s")
    for attempt in range(max_retries):
        try:
            response = requests.get(
                url, timeout=timeout, stream=True  # Good practice for downloading files
            )
            response.raise_for_status()  # Raises exception for 4XX/5XX status codes

            return response.content, response.headers["Content-Type"]

        except Timeout:
            wait_time = backoff_factor**attempt
            if logger:
                logger.warning(
                    f"Timeout fetching {url} (attempt {attempt + 1}/{max_retries}). "
                    f"Waiting {wait_time:.1f}s before retry"
                )

            if attempt < max_retries - 1:
                time.sleep(wait_time)

        except RequestException as e:
            if logger:
                logger.error(f"Error fetching {url}: {e!s}")
            return None

    if logger:
        logger.error(f"Failed to fetch {url} after {max_retries} attempts")
    return None


def resize_image_data(image_data: bytes, max_width: int = 800, max_height: int = 600) -> bytes:
    # Create image object from binary data
    try:
        image = Image.open(io.BytesIO(image_data))
        if image.format == "GIF":
            return image_data
    except Exception:
        # if unacceptable file format, just return
        return image_data

    # Calculate new dimensions maintaining aspect ratio
    width, height = image.size
    ratio = min(max_width / width, max_height / height)
    if ratio >= 1:
        return image_data

    new_width = int(width * ratio)
    new_height = int(height * ratio)

    # Resize image
    resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # Convert back to bytes
    buffer = io.BytesIO()
    resized_image.save(buffer, format=image.format)
    return buffer.getvalue()


def value_from_environ(key: str) -> str:
    """Replace key with value from an environment variable if it has a format of ${KEY}"""
    if not isinstance(key, str) or not key.startswith("${") or not key.endswith("}"):
        return key
    if key[2:-1] not in os.environ:
        raise ValueError(f"Environment variable {key[2:-1]} not set")
    return os.environ[key[2:-1]]
