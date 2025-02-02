import hashlib
import os
import re
import time
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Dict, List, TypeVar

import parsedatetime  # type: ignore
from diskcache import Cache  # type: ignore
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

# home directory for all settings and caches
amm_home = os.path.join(os.path.expanduser("~"), ".ai-marketplace-monitor")
os.makedirs(amm_home, exist_ok=True)

cache = Cache(amm_home)

TConfigType = TypeVar("TConfigType", bound="DataClassWithHandleFunc")


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
    ITEM_DETAILS = "get_item_details"
    USER_NOTIFIED = "notify_user"


def calculate_file_hash(file_paths: List[str]) -> str:
    """Calculate the SHA-256 hash of the file content."""
    hasher = hashlib.sha256()
    # they should exist, just to make sure
    for file_path in file_paths:
        if not os.path.exists(file_path):
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


def sleep_with_watchdog(duration: int, files: List[str]) -> None:
    """Sleep for a specified duration while monitoring the change of files"""
    event_handler = ChangeHandler(files)
    observers = []
    for filename in files:
        if not os.path.exists(filename):
            raise FileNotFoundError(f"File not found: {filename}")
        observer = Observer()
        # we can only monitor a directory
        observer.schedule(event_handler, os.path.dirname(filename), recursive=False)
        observer.start()
        observers.append(observer)

    start_time = time.time()
    try:
        while time.time() - start_time < duration:
            if event_handler.changed:
                return
            time.sleep(1)
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
        "name": "bright_cyan",
        "fail": "red",
        "info": "blue",
        "succ": "green",
    }.get(style, "blue")
    return f"[{color}]{text}[/{color}]"
