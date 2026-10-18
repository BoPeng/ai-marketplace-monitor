"""One-time migrations of a user's config files, run before they are parsed.

Each migration is a function that edits the parsed files (``tomlkit`` documents, which keep
comments and order) and returns a line for each change it made; it changes nothing in a file
that is already migrated, so the migrations run every time aimm reads its config. When one
changes a file, aimm writes the file back, after a copy of the old one (``<file>.bak``).

The migrations take all the files that are read together, because a user in one file may
receive a section of another.
"""

import copy
import shutil
from dataclasses import fields
from logging import Logger
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Tuple, cast

import tomlkit
from tomlkit.items import Comment, Null, Table, Whitespace
from tomlkit.toml_document import TOMLDocument

from .channels import channel_classes
from .email_notify import (
    EMAIL_PRESETS,
    UNITYSVC_SMTP_USERNAME,
    EmailNotificationConfig,
    email_preset,
)
from .notification import CHANNEL, COMMON, RECIPIENT, PushNotificationConfig, fields_with_role
from .utils import hilight

Docs = List[TOMLDocument]

EMAIL_KEYS = set(fields_with_role(EmailNotificationConfig, CHANNEL)) | set(
    fields_with_role(EmailNotificationConfig, RECIPIENT)
)
# the keys an [email.*] section can have
EMAIL_SECTION_KEYS = {f.name for f in fields(EmailNotificationConfig)} - {"name"}
# how each type of channel is sent (credentials, servers)
CHANNEL_KEYS: Dict[str, Tuple[str, ...]] = {
    t: fields_with_role(cls, CHANNEL) for t, cls in channel_classes().items()
}
COMMON_KEYS = set(fields_with_role(PushNotificationConfig, COMMON))


def _plain(value: Any) -> Any:
    return value.unwrap() if hasattr(value, "unwrap") else value


def _tables(docs: Docs, kind: str) -> Iterator[Tuple[TOMLDocument, str, Table]]:
    """The [kind.*] sections of all files, with their file."""
    for doc in docs:
        for name, table in list(doc.get(kind, {}).items()):
            if isinstance(table, Table):
                yield doc, name, table


def _names(docs: Docs, kind: str) -> List[str]:
    return [name for _, name, _ in _tables(docs, kind)]


def _section_keys(docs: Docs) -> List[str]:
    """Every section a user may receive, as "email.<name>" and "notification.<name>"."""
    return [f"email.{n}" for n in _names(docs, "email")] + [
        f"notification.{n}" for n in _names(docs, "notification")
    ]


def _find(docs: Docs, key: str) -> Table | None:
    kind, name = key.split(".", 1)
    return next((t for _, n, t in _tables(docs, kind) if n == name), None)


def _resolve(docs: Docs, entry: str) -> str | None:
    """The section a notify_with entry names (bare names: the one kind that has it)."""
    keys = _section_keys(docs)
    if entry in keys:
        return entry
    matches = [k for k in keys if k.split(".", 1)[1] == entry]
    return matches[0] if len(matches) == 1 else None


def _listed(value: Any) -> List[str]:
    value = _plain(value)
    return [value] if isinstance(value, str) else list(value or [])


def _received(docs: Docs, user: Table) -> List[str]:
    """The enabled sections a user receives, as "email.<name>" and "notification.<name>"."""
    if "notify_with" in user:
        keys = [_resolve(docs, e) for e in _listed(user["notify_with"])]
    else:
        keys = list(_section_keys(docs))
    return [
        k
        for k in dict.fromkeys(k for k in keys if k is not None)
        if _plain(_find(docs, k).get("enabled")) is not False  # type: ignore[union-attr]
    ]


def _make_explicit(docs: Docs) -> None:
    """Name the sections each user receives, before a section is added or copied.

    A user without notify_with receives every section, and would also receive the new one.
    """
    for _, _, user in _tables(docs, "user"):
        if "notify_with" not in user:
            user["notify_with"] = _received(docs, user)


def _new_name(docs: Docs, kind: str, wanted: List[str]) -> str:
    taken = set(_names(docs, kind))
    name = next((n for n in wanted if n not in taken), wanted[-1])
    suffix = 2
    while name in taken:
        name = f"{wanted[-1]}_{suffix}"
        suffix += 1
    return name


def _add_section(doc: TOMLDocument, kind: str, name: str, values: Dict[str, Any]) -> None:
    table = tomlkit.table()
    for key, value in values.items():
        table[key] = value
    _add_table(doc, kind, name, table)


def _add_table(doc: TOMLDocument, kind: str, name: str, table: Table) -> None:
    """Add a section after the last one of its kind, above the lines about the next one."""
    if kind not in doc:
        doc[kind] = tomlkit.table(is_super_table=True)
    siblings = [t for _, _, t in _tables([doc], kind)]
    lines = _trailing(siblings[-1]) if siblings else []
    cast(Table, doc[kind])[name] = table
    _move_lines(lines, table)


def _move_lines(lines: List[Any], table: Table) -> None:
    """Put comment lines taken off a section (``_trailing``) at the end of another one."""
    comments = [i for i in lines if not isinstance(i, Null)]
    while comments and not isinstance(comments[0], Comment):
        comments.pop(0)
    while comments and not isinstance(comments[-1], Comment):
        comments.pop()
    if comments:
        _trailing(table)
        for item in [tomlkit.nl(), *comments]:
            table.add(item)


def _trailing(table: Table) -> List[Any]:
    """Take the comment lines and blank lines after a section's last key off its end.

    tomlkit keeps the lines above a section header at the end of the section before it, so
    these are usually about the next section.
    """
    body = table.value.body
    items: List[Any] = []
    while body and body[-1][0] is None and isinstance(body[-1][1], (Comment, Whitespace, Null)):
        items.insert(0, body.pop()[1])
    return items


def _previous(doc: TOMLDocument, kind: str, name: str) -> Table | None:
    """The section just above [kind.name] in the file."""
    order = [t for k in doc for _, _, t in _tables([doc], k)]
    target = cast(Table, doc[kind])[name]
    index = next(i for i, t in enumerate(order) if t is target)
    return order[index - 1] if index else None


def _delete_section(doc: TOMLDocument, kind: str, name: str) -> None:
    """Remove a section; the lines above the next one stay where they are."""
    table = cast(Table, cast(Table, doc[kind])[name])
    above = _previous(doc, kind, name)
    lines = _trailing(table)
    if above is not None:
        _move_lines(lines, above)
    del cast(Table, doc[kind])[name]
    if not doc[kind]:
        del doc[kind]


def _copy_section(table: Table, keep: Callable[[str], bool]) -> Table:
    """A copy of a section, with its comments, and only the keys ``keep`` accepts."""
    copied = copy.deepcopy(table)
    _trailing(copied)
    for key in [k for k in copied if not keep(k)]:
        _remove(copied, key)
    return copied


def _same_section(docs: Docs, kind: str, values: Dict[str, Any]) -> str | None:
    """An existing section of this kind with exactly these values."""
    return next(
        (n for _, n, t in _tables(docs, kind) if {k: _plain(v) for k, v in t.items()} == values),
        None,
    )


def _replace_in_lists(docs: Docs, user: Table, old: str, new: List[str]) -> None:
    for key in ("notify_with", "digest_with"):
        if key not in user:
            continue
        entries: List[str] = []
        for entry in _listed(user[key]):
            entries += new if _resolve(docs, entry) == old or entry == old else [entry]
        user[key] = list(dict.fromkeys(entries))


def _for_user(docs: Docs, key: str, user_name: str, updates: Dict[str, Any]) -> str:
    """Make ``updates`` to a section for one user; the section the user then receives.

    In place when no other user receives the section, otherwise in a copy that this user
    receives instead. The section is returned as "<kind>.<name>".
    """
    kind, name = key.split(".", 1)
    receivers = [n for _, n, u in _tables(docs, "user") if key in _received(docs, u)]
    table = _find(docs, key)
    assert table is not None
    if receivers == [user_name]:
        for k, v in updates.items():
            if v is None:
                table.pop(k, None)
            else:
                table[k] = v
        return key
    _make_explicit(docs)
    values = {k: _plain(v) for k, v in table.items()}
    values.update(updates)
    values = {k: v for k, v in values.items() if v is not None}
    doc = next(d for d, n, t in _tables(docs, kind) if n == name)
    copy_name = _new_name(docs, kind, [f"{name}_{user_name}"])
    _add_section(doc, kind, copy_name, values)
    user = next(u for _, n, u in _tables(docs, "user") if n == user_name)
    _replace_in_lists(docs, user, key, [f"{kind}.{copy_name}"])
    return f"{kind}.{copy_name}"


def _email_name(values: Dict[str, Any]) -> str | None:
    """The preset of an email section's values: by its server, or a UnitySVC key."""
    preset = email_preset(values.get("smtp_server"))
    if preset is None and "smtp_server" not in values:
        password = values.get("smtp_password")
        if isinstance(password, str) and password.startswith("svcpass_"):
            preset = "unitysvc"
    return preset


def _without_preset(name: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """Values of an [email.<name>] section, without those its preset already has."""
    preset = EMAIL_PRESETS.get(name, {})
    return {
        k: v
        for k, v in values.items()
        if not (k in preset and str(v).strip().lower() == str(preset[k]).lower())
    }


def migrate_email_from_notification_to_email_section(docs: Docs) -> List[str]:
    """[notification.*] sections that send email become [email.*] sections.

    The name follows the server: [email.unitysvc] for UnitySVC, [email.gmail] for Gmail
    (without the values their preset has), otherwise the section's own name. Settings for
    other channels in the same section stay in [notification.*]. Users' notify_with and
    digest_with name the new section.
    """
    changes = []
    for doc, name, table in list(_tables(docs, "notification")):
        values = {k: _plain(v) for k, v in table.items()}
        if not any(k in EMAIL_KEYS for k in values):
            continue
        push_keys = {k for t, keys in CHANNEL_KEYS.items() if t != "email" for k in keys} | {
            f for cls in channel_classes().values() for f in fields_with_role(cls, RECIPIENT)
        }
        push_keys -= EMAIL_KEYS
        shared = {"enabled", "request"} | COMMON_KEYS
        email = {k: v for k, v in values.items() if k in EMAIL_SECTION_KEYS}
        push = {k: v for k, v in values.items() if k in push_keys}
        if push:
            push.update({k: v for k, v in values.items() if k in shared})
        preset = _email_name(email)
        email = _without_preset(preset, email) if preset else email
        if preset == "unitysvc":
            email.setdefault("smtp_username", UNITYSVC_SMTP_USERNAME)
        existing = _same_section(docs, "email", email)
        new = existing or _new_name(
            docs, "email", [n for n in (preset, name, f"{name}_email") if n]
        )
        # the users' lists first, while their entries still name the old section
        old_key = f"notification.{name}"
        refs = [f"email.{new}"] + ([old_key] if push else [])
        for _, _, user in _tables(docs, "user"):
            _replace_in_lists(docs, user, old_key, refs)
        if existing is None:
            moved = _copy_section(table, set(email).__contains__)
            if preset == "unitysvc" and "smtp_username" not in moved:
                moved["smtp_username"] = UNITYSVC_SMTP_USERNAME  # what it used without one
            _add_table(doc, "email", new, moved)
        if push:
            for k in list(table):
                if k not in push:
                    del table[k]
        else:
            _delete_section(doc, "notification", name)
        changes.append(
            f"[notification.{name}] sends email: it is now [email.{new}]"
            + (f", and [notification.{name}] keeps its other channels" if push else "")
        )
    return changes


def migrate_channels_from_user_to_sections(docs: Docs) -> List[str]:
    """Channels set up in [user.*] (smtp_*, pushbullet_token, ...) move into sections.

    A user's values for a type of channel that no section the user receives sets up become
    a section of their own, which the user receives. Values under a section of that type
    the user receives (which used them where it did not set them) go into the section, or
    into a copy for this user if others receive it too. [user.*] keeps who receives.
    """
    changes = []
    for _, user_name, user in list(_tables(docs, "user")):
        for channel_type, keys in CHANNEL_KEYS.items():
            values = {k: _plain(user[k]) for k in keys if k in user}
            if not values:
                continue
            kind = "email" if channel_type == "email" else "notification"
            covering = [
                key
                for key in _received(docs, user)
                if key.startswith(f"{kind}.")
                and (kind == "email" or any(k in _find(docs, key) for k in keys))  # type: ignore[operator]
            ]
            for k in values:
                _remove(user, k)
            if covering:
                moved = False
                for key in covering:
                    table = _find(docs, key)
                    assert table is not None
                    missing = {k: v for k, v in values.items() if k not in table}
                    if missing:
                        new = _for_user(docs, key, user_name, missing)
                        changes.append(
                            f"[user.{user_name}] {', '.join(missing)}: moved to [{new}]"
                        )
                        moved = True
                if not moved:
                    changes.append(
                        f"[user.{user_name}] {', '.join(values)}: removed, as "
                        f"{', '.join(f'[{k}]' for k in covering)} sets its own"
                    )
                continue
            if kind == "email":
                preset = _email_name(values)
                values = _without_preset(preset, values) if preset else values
                if preset == "unitysvc":
                    values.setdefault("smtp_username", UNITYSVC_SMTP_USERNAME)
                wanted = [n for n in (preset, "email") if n] + [f"email_{user_name}"]
            else:
                wanted = [channel_type, f"{channel_type}_{user_name}"]
            name = _same_section(docs, kind, values)
            if name is None:
                name = _new_name(docs, kind, wanted)
                _make_explicit(docs)
                doc = next(d for d, n, _ in _tables(docs, "user") if n == user_name)
                _add_section(doc, kind, name, values)
            else:
                _make_explicit(docs)
            user["notify_with"] = list(
                dict.fromkeys([*_listed(user["notify_with"]), f"{kind}.{name}"])
            )
            changes.append(f"[user.{user_name}] {', '.join(values)}: moved to [{kind}.{name}]")
    return changes


def migrate_digest_from_user_to_notification_and_email(docs: Docs) -> List[str]:
    """A user's digest_at (and digest_with) moves onto the sections that send the digest.

    Each section the user received the digest from gets the user's digest_at. Users who
    receive the same section but differ in their digest get a copy of the section each.
    """
    wants: Dict[str, Dict[str, Any]] = {}  # section: {user: digest_at or None}
    users = [(n, u) for _, n, u in _tables(docs, "user")]
    if not any("digest_at" in u or "digest_with" in u for _, u in users):
        return []
    for user_name, user in users:
        digest_at = _plain(user.get("digest_at"))
        digest_with = (
            None
            if "digest_with" not in user
            else [_resolve(docs, e) for e in _listed(user["digest_with"])]
        )
        for key in _received(docs, user):
            chosen = digest_at if digest_with is None or key in digest_with else None
            wants.setdefault(key, {})[user_name] = chosen or None
    changes = []
    for key, by_user in wants.items():
        table = _find(docs, key)
        assert table is not None
        # most users keep the section; the others get a copy with their digest
        values = list(by_user.values())
        kept = max(set(values), key=lambda v: (values.count(v), v is not None))
        for user_name, digest_at in by_user.items():
            if digest_at != kept:
                new = _for_user(docs, key, user_name, {"digest_at": digest_at})
                changes.append(
                    f"[user.{user_name}] gets the digest of [{key}] "
                    + (f"at {digest_at}" if digest_at else "not at all")
                    + f": through its own copy [{new}]"
                )
        if kept is not None and _plain(table.get("digest_at")) != kept:
            table["digest_at"] = kept
            changes.append(f"[{key}] sends the digest at {kept}")
    for user_name, user in users:
        moved = [k for k in ("digest_at", "digest_with") if k in user]
        for k in moved:
            _remove(user, k)
        if moved:
            changes.append(f"[user.{user_name}] {', '.join(moved)}: now on its sections")
    return changes


MIGRATIONS: List[Callable[[Docs], List[str]]] = [
    migrate_email_from_notification_to_email_section,
    migrate_channels_from_user_to_sections,
    migrate_digest_from_user_to_notification_and_email,
]


def migrate_documents(docs: Docs) -> List[str]:
    """Run every migration on the documents in place; the changes made, in order."""
    changes: List[str] = []
    for migration in MIGRATIONS:
        changes += migration(docs)
    if changes:
        _tidy(docs)
    return changes


def _tidy(docs: Docs) -> None:
    """One blank line at the end of each section.

    So that the next section does not follow the last line of a migrated one directly.
    """
    for doc in docs:
        for kind in ("user", "notification", "email"):
            for _, _, table in _tables([doc], kind):
                body = table.value.body
                while body and body[-1][0] is None and isinstance(body[-1][1], (Whitespace, Null)):
                    body.pop()
                table.add(tomlkit.nl())


def _remove(table: Table, key: str) -> None:
    """Remove a key, and the comment lines just above it, which were about it."""
    body = table.value.body
    index = next(i for i, (k, _) in enumerate(body) if k is not None and k.key == key)
    start = index
    while start > 0 and body[start - 1][0] is None and isinstance(body[start - 1][1], Comment):
        start -= 1
    del table[key]
    # blanked, not deleted: tomlkit finds the keys after them by their position
    for i in range(start, index):
        body[i] = (None, Null())


def migrate_config_files(
    paths: List[Path], logger: Logger | None = None, *, write: bool = True
) -> Dict[Path, str]:
    """Migrate config files read together; the text of each, migrated.

    A file that changes is written back (unless ``write`` is false), after a copy of the old
    one in ``<file>.bak``. A file that cannot be written is still read migrated, and the log
    says so.
    """
    texts = {path: path.read_text(encoding="utf-8") for path in paths}
    docs = {path: tomlkit.parse(text) for path, text in texts.items()}
    changes = migrate_documents(list(docs.values()))
    if not changes:
        return texts
    out = {}
    for path, doc in docs.items():
        text = tomlkit.dumps(doc)
        out[path] = text
        if text == texts[path] or not write:
            continue
        try:
            shutil.copyfile(path, path.with_name(path.name + ".bak"))
            path.write_text(text, encoding="utf-8")
            if logger:
                logger.info(
                    f"""{hilight("[Config]", "succ")} Updated {hilight(str(path))} to the current format (the old file is {path.name}.bak):"""
                )
        except OSError as e:
            if logger:
                logger.warning(
                    f"""{hilight("[Config]", "fail")} {path} uses an old format and cannot be updated ({e}); aimm reads it as if it were updated:"""
                )
    if logger:
        for change in changes:
            logger.info(f"""{hilight("[Config]", "info")}   {change}""")
    return out


def migrate_config_dict(cfg: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """A parsed user config, migrated (as ``migrate_documents``), and the changes made."""
    doc = tomlkit.parse(tomlkit.dumps(cfg))
    changes = migrate_documents([doc])
    return (doc.unwrap() if changes else cfg), changes
