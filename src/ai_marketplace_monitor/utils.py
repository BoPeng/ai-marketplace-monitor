import hashlib
import re
import time
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, TypeVar

import parsedatetime  # type: ignore
import rich
from diskcache import Cache  # type: ignore
from rich.pretty import pretty_repr

try:
    from pynput import keyboard  # type: ignore

    pynput_installed = True
except ImportError:
    # some platforms are not supported
    pynput_installed = False

import rich.pretty
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

# home directory for all settings and caches
amm_home = Path.home() / ".ai-marketplace-monitor"
amm_home.mkdir(parents=True, exist_ok=True)

cache = Cache(amm_home)


TConfigType = TypeVar("TConfigType", bound="DataClassWithHandleFunc")


class SleepStatus(Enum):
    NOT_DISRUPTED = 0
    BY_KEYBOARD = 1
    BY_FILE_CHANGE = 2


class NotificationStatus(Enum):
    NOT_NOTIFIED = 0
    EXPIRED = 1
    NOTIFIED = 2


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


class CounterItem(Enum):
    SEARCH = "Search performed"
    LISTING_EXAMINED = "Total listing examined"
    LISTING_QUERY = "Listing details fetched (not cached)"
    EXCLUDED_LISTING = "Listing excluded"
    NEW_LISTING = "New listing"
    AI_QUERY = "AI Queries"
    NEW_AI_QUERY = "AI Queies (not cached)"
    FAILED_AI_QUERY = "Failed AI Queries)"
    NOTIFICATIONS = "Notifications sent"
    REMINDERS = "Reminders sent"


class Counter:

    def __init__(self: "Counter") -> None:
        self.counters: Dict[str, int] = {}

    def increment(self: "Counter", key: CounterItem, by: int = 1) -> None:
        if key not in CounterItem:
            raise ValueError(f"Invalid cunter key: {key}")

        self.counters[key.value] = self.counters.get(key.value, 0) + by

    def __str__(self: "Counter") -> str:
        """Return pretty form of all non-zero counters"""
        cnt = {
            x.value: self.counters.get(x.value, 0)
            for x in CounterItem
            if self.counters.get(x.value, 0)
        }
        return pretty_repr(cnt)


counter = Counter()


@dataclass
class DataClassWithHandleFunc:
    name: str

    def __post_init__(self: "DataClassWithHandleFunc") -> None:
        """Handle all methods that start with 'handle_' in the dataclass."""
        for f in fields(self):
            handle_method = getattr(self, f"handle_{f.name}", None)
            if handle_method:
                handle_method()


class CacheType(Enum):
    LISTING_DETAILS = "listing-details"
    AI_INQUIRY = "ai-inquiries"
    USER_NOTIFIED = "user-notifications"


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


def is_substring(var1: str | List[str], var2: str | List[str]) -> bool:
    """Check if var1 is a substring of var2, after normalizing both strings. One of them can be a list of strings."""
    if isinstance(var1, str):
        if isinstance(var2, str):
            return normalize_string(var1) in normalize_string(var2)
        return any(normalize_string(var1) in normalize_string(s) for s in var2)
    # var1 is a list, var2 must be a string
    assert isinstance(var2, str)
    return any(normalize_string(s1) in normalize_string(var2) for s1 in var1)


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
    if price.count("$") > 1:
        match = re.search(r"\$\d+(?:\.\d{2})?", price)
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
