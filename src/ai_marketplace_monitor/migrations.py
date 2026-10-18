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
from typing import Any, Callable, Dict, Iterable, Iterator, List, Tuple, cast

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
    """The [kind.*] sections of all files, with their file (a name may be in several)."""
    for doc in docs:
        for name, table in list(doc.get(kind, {}).items()):
            if isinstance(table, Table):
                yield doc, name, table


def _names(docs: Docs, kind: str) -> List[str]:
    """The names of the [kind.*] sections, each once."""
    return list(dict.fromkeys(name for _, name, _ in _tables(docs, kind)))


def _defs(docs: Docs, kind: str, name: str) -> List[Tuple[TOMLDocument, Table]]:
    """Where [kind.name] is defined, in reading order: later files override earlier ones."""
    return [(d, t) for d, n, t in _tables(docs, kind) if n == name]


def _merged(docs: Docs, kind: str, name: str) -> Dict[str, Any]:
    """The values of [kind.name] as aimm reads them, from all the files that define it."""
    values: Dict[str, Any] = {}
    for _, table in _defs(docs, kind, name):
        values.update({k: _plain(v) for k, v in table.items()})
    return values


def _last(docs: Docs, kind: str, name: str) -> Table:
    """The definition of [kind.name] whose values win (the one to change)."""
    return _defs(docs, kind, name)[-1][1]


def _section_keys(docs: Docs) -> List[str]:
    """Every section a user may receive, as "email.<name>" and "notification.<name>"."""
    return [f"email.{n}" for n in _names(docs, "email")] + [
        f"notification.{n}" for n in _names(docs, "notification")
    ]


def _section(docs: Docs, key: str) -> Dict[str, Any]:
    return _merged(docs, *key.split(".", 1))


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


def _received(docs: Docs, user_name: str) -> List[str]:
    """The enabled sections a user receives, as "email.<name>" and "notification.<name>"."""
    user = _merged(docs, "user", user_name)
    if "notify_with" in user:
        keys = [_resolve(docs, e) for e in _listed(user["notify_with"])]
    else:
        keys = list(_section_keys(docs))
    return [
        k
        for k in dict.fromkeys(k for k in keys if k is not None)
        if _section(docs, k).get("enabled") is not False
    ]


def _set_list(docs: Docs, user_name: str, key: str, value: List[str]) -> None:
    """Set a user's list where it is defined last (or in the last definition of the user)."""
    defs = [t for _, t in _defs(docs, "user", user_name)]
    table = next((t for t in reversed(defs) if key in t), defs[-1])
    table[key] = value


def _make_explicit(docs: Docs) -> None:
    """Name the sections each user receives, before a section is added or copied.

    A user without notify_with receives every section, and would also receive the new one.
    """
    for user_name in _names(docs, "user"):
        if "notify_with" not in _merged(docs, "user", user_name):
            _set_list(docs, user_name, "notify_with", _received(docs, user_name))


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


def _previous(doc: TOMLDocument, table: Table) -> Table | None:
    """The section just above ``table`` in the file."""
    order = [t for k in doc for _, _, t in _tables([doc], k)]
    index = next(i for i, t in enumerate(order) if t is table)
    return order[index - 1] if index else None


def _delete_section(doc: TOMLDocument, kind: str, name: str) -> None:
    """Remove a section from a file; the lines above the next one stay where they are."""
    table = cast(Table, cast(Table, doc[kind])[name])
    above = _previous(doc, table)
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
    return next((n for n in _names(docs, kind) if _merged(docs, kind, n) == values), None)


def _replace_in_lists(docs: Docs, user_name: str, old: str, new: List[str]) -> None:
    for _, user in _defs(docs, "user", user_name):
        for key in ("notify_with", "digest_with"):
            if key not in user:
                continue
            entries: List[str] = []
            for entry in _listed(user[key]):
                entries += new if _resolve(docs, entry) == old or entry == old else [entry]
            user[key] = list(dict.fromkeys(entries))


def _remove_everywhere(docs: Docs, kind: str, name: str, keys: Iterable[str]) -> None:
    for _, table in _defs(docs, kind, name):
        for key in keys:
            if key in table:
                _remove(table, key)


def _for_user(docs: Docs, key: str, user_name: str, updates: Dict[str, Any]) -> str:
    """Make ``updates`` to a section for one user; the section the user then receives.

    In place when no other user receives the section, otherwise in a copy that this user
    receives instead. The section is returned as "<kind>.<name>".
    """
    kind, name = key.split(".", 1)
    receivers = [u for u in _names(docs, "user") if key in _received(docs, u)]
    if receivers == [user_name]:
        table = _last(docs, kind, name)
        for k, v in updates.items():
            if v is None:
                _remove_everywhere(docs, kind, name, [k])
            else:
                table[k] = v
        return key
    _make_explicit(docs)
    values = _merged(docs, kind, name)
    if kind == "email":  # a copy under another name has no preset: it keeps its values
        values = {**EMAIL_PRESETS.get(name, {}), **values}
    values.update(updates)
    values = {k: v for k, v in values.items() if v is not None}
    doc = _defs(docs, kind, name)[-1][0]
    copy_name = _new_name(docs, kind, [f"{name}_{user_name}"])
    _add_section(doc, kind, copy_name, values)
    _replace_in_lists(docs, user_name, key, [f"{kind}.{copy_name}"])
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


def _email_names(preset: str | None, name: str) -> List[str]:
    """Names for the email section of [notification.<name>]: a preset's only if it is one."""
    own = name if name not in EMAIL_PRESETS or name == preset else None
    return [n for n in (preset, own, f"{name}_email") if n]


PUSH_KEYS = (
    {k for t, keys in CHANNEL_KEYS.items() if t != "email" for k in keys}
    | {f for cls in channel_classes().values() for f in fields_with_role(cls, RECIPIENT)}
) - EMAIL_KEYS
SHARED_KEYS = {"enabled", "request"} | COMMON_KEYS


def migrate_email_from_notification_to_email_section(docs: Docs) -> List[str]:
    """[notification.*] sections that send email become [email.*] sections.

    The name follows the server: [email.unitysvc] for UnitySVC, [email.gmail] for Gmail
    (without the values their preset has), otherwise the section's own name. Settings for
    other channels in the same section stay in [notification.*]. Users' notify_with and
    digest_with name the new section. A section defined in several files (later ones
    overriding earlier ones) becomes one email section, defined in the same files.
    """
    changes = []
    for name in _names(docs, "notification"):
        values = _merged(docs, "notification", name)
        if not any(k in EMAIL_KEYS for k in values):
            continue
        defs = _defs(docs, "notification", name)
        layered = len(defs) > 1
        email = {k: v for k, v in values.items() if k in EMAIL_SECTION_KEYS}
        push = any(k in PUSH_KEYS for k in values)
        preset = _email_name(email)
        # in layered files, a value equal to the preset may override an earlier one: kept
        strip = (
            set() if layered or not preset else set(email) - set(_without_preset(preset, email))
        )
        email = {k: v for k, v in email.items() if k not in strip}
        username = preset == "unitysvc" and "smtp_username" not in email
        if username:
            email["smtp_username"] = UNITYSVC_SMTP_USERNAME  # what it used without one
        existing = None if layered else _same_section(docs, "email", email)
        new = existing or _new_name(docs, "email", _email_names(preset, name))
        # the users' lists first, while their entries still name the old section
        old_key = f"notification.{name}"
        refs = [f"email.{new}"] + ([old_key] if push else [])
        for user_name in _names(docs, "user"):
            _replace_in_lists(docs, user_name, old_key, refs)
        kept = EMAIL_SECTION_KEYS - strip
        for index, (doc, table) in enumerate(defs):
            if existing is None:
                moved = _copy_section(table, kept.__contains__)
                if username and index == 0:
                    moved["smtp_username"] = UNITYSVC_SMTP_USERNAME
                _add_table(doc, "email", new, moved)
            if push:
                for k in [k for k in table if k not in PUSH_KEYS | SHARED_KEYS]:
                    _remove(table, k)
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
    for user_name in _names(docs, "user"):
        user = _merged(docs, "user", user_name)
        for channel_type, keys in CHANNEL_KEYS.items():
            values = {k: user[k] for k in keys if k in user}
            if not values:
                continue
            kind = "email" if channel_type == "email" else "notification"
            covering = [
                key
                for key in _received(docs, user_name)
                if key.startswith(f"{kind}.")
                and (kind == "email" or any(k in _section(docs, key) for k in keys))
            ]
            _remove_everywhere(docs, "user", user_name, values)
            if covering:
                moved = False
                for key in covering:
                    missing = {k: v for k, v in values.items() if k not in _section(docs, key)}
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
            _make_explicit(docs)
            if name is None:
                name = _new_name(docs, kind, wanted)
                _add_section(_defs(docs, "user", user_name)[0][0], kind, name, values)
            received = _listed(_merged(docs, "user", user_name)["notify_with"])
            _set_list(
                docs, user_name, "notify_with", list(dict.fromkeys([*received, f"{kind}.{name}"]))
            )
            changes.append(f"[user.{user_name}] {', '.join(values)}: moved to [{kind}.{name}]")
    return changes


def migrate_digest_from_user_to_notification_and_email(docs: Docs) -> List[str]:
    """A user's digest_at (and digest_with) moves onto the sections that send the digest.

    Each section the user received the digest from gets the user's digest_at. Users who
    receive the same section but differ in their digest get a copy of the section each.
    """
    users = _names(docs, "user")
    merged = {u: _merged(docs, "user", u) for u in users}
    if not any("digest_at" in m or "digest_with" in m for m in merged.values()):
        return []
    wants: Dict[str, Dict[str, Any]] = {}  # section: {user: digest_at or None}
    for user_name in users:
        digest_at = merged[user_name].get("digest_at")
        digest_with = (
            None
            if "digest_with" not in merged[user_name]
            else [_resolve(docs, e) for e in _listed(merged[user_name]["digest_with"])]
        )
        for key in _received(docs, user_name):
            chosen = digest_at if digest_with is None or key in digest_with else None
            wants.setdefault(key, {})[user_name] = chosen or None
    changes = []
    for key, by_user in wants.items():
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
        if kept is not None and _section(docs, key).get("digest_at") != kept:
            _last(docs, *key.split(".", 1))["digest_at"] = kept
            changes.append(f"[{key}] sends the digest at {kept}")
    for user_name in users:
        moved = [k for k in ("digest_at", "digest_with") if k in merged[user_name]]
        _remove_everywhere(docs, "user", user_name, moved)
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
