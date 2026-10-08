"""Toolkits: what aimm knows about one section type, used by the configure tools.

A toolkit declares its config class, field guides and playbook, and implements how to read
a section (``view``), check it (``validate``, ``missing``), show it (``describe``) and put it
back into the config (``apply``). The tools in ``tools.py`` expose this to the LLM; the LLM
never changes the config except through them.
"""

from __future__ import annotations

import copy
import os
import warnings
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from ..marketplace import FALLBACK, LOCATION

if TYPE_CHECKING:
    from .ui import SetupUI
    from .workspace import Workspace

# section types with a single unnamed section ([monitor]); their key is (type, type)
SINGLETONS = {"monitor"}


def section_label(section_type: str, name: str) -> str:
    """``[type.name]``, or ``[type]`` for a singleton section."""
    if section_type in SINGLETONS:
        return f"[{section_type}]"
    return f"[{section_type}.{name}]"


# dataclass fields that are never configured through a toolkit
_NOT_CONFIGURED = {"name", "request", "monitor_config", "searched_count"}
_UNSET = object()


class FieldGroup(Enum):
    OWN = "own"  # belongs to the section only
    SHARED = "shared"  # default for the section's items (option(...) fields)
    LOCATION = "location"  # shared, and part of the location group


@dataclass(frozen=True)
class FieldGuide:
    name: str
    determine: str  # how to work out the value
    format: str  # accepted values and examples
    default: str | None = None  # what happens at runtime when the field is unset
    secret: bool = False  # only ever a ${VAR} reference; never sent to the LLM
    reference: bool = False  # may also be a whole ${VAR} reference (e.g. proxy_server)


@dataclass
class SectionDraft:
    """A section being edited; nothing is written until ``save``."""

    section_type: str
    name: str
    is_new: bool
    request: str | None
    values: Dict[str, Any]  # the section as the user wrote it (merged across files)
    original: Dict[str, Any] = field(default_factory=dict)  # values when the draft was made
    original_request: str | None = None

    @property
    def key(self: "SectionDraft") -> Tuple[str, str]:
        return (self.section_type, self.name)

    @property
    def label(self: "SectionDraft") -> str:
        return section_label(self.section_type, self.name)

    def copy(self: "SectionDraft") -> "SectionDraft":
        return copy.deepcopy(self)

    def unsaved_changes(self: "SectionDraft") -> Dict[str, Any]:
        """Fields changed but not saved: {field: new value, or None if removed}."""
        keys = dict.fromkeys([*self.original, *self.values])
        return {
            k: self.values.get(k)
            for k in keys
            if self.values.get(k, _UNSET) != self.original.get(k, _UNSET)
        }

    def has_changes(self: "SectionDraft") -> bool:
        """Values changed (a new or changed ``request`` alone does not count)."""
        return bool(self.unsaved_changes())


def field_group(cls: type, name: str) -> FieldGroup:
    """Group of a config field, read from its ``option(...)`` metadata."""
    for f in fields(cls):  # type: ignore[arg-type]
        if f.name == name:
            if f.metadata.get(LOCATION):
                return FieldGroup.LOCATION
            if f.metadata.get(FALLBACK):
                return FieldGroup.SHARED
            return FieldGroup.OWN
    raise KeyError(name)


def is_reference(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("${") and value.endswith("}")


def unset_variable_notes(draft: SectionDraft) -> List[str]:
    """A note listing the ``${VAR}`` references of a section that are not set, if any."""
    refs = [v for v in draft.values.values() if is_reference(v)]
    names = [r[2:-1] for r in dict.fromkeys(refs) if r[2:-1] not in os.environ]
    if not names:
        return []
    exports = "\n".join(f"export {n}=<value>" for n in names)
    return [
        (
            f"{draft.label} uses environment variables that are not set here: "
            f"{', '.join(names)}. Set them where you run aimm, for example in your shell "
            f"profile:\n\n```bash\n{exports}\n```"
        )
    ]


def _only_references(value: Any) -> bool:
    """Every ``${`` in the value is a whole ``${VAR}`` value (a list may mix in plain text)."""
    values = value if isinstance(value, list) else [value]
    return all(is_reference(v) or not _mentions_reference(v) for v in values)


def _mentions_reference(value: Any) -> bool:
    if isinstance(value, str):
        return "${" in value
    if isinstance(value, list):
        return any(_mentions_reference(v) for v in value)
    return False


def listed(value: Any) -> List[str]:
    """A string-or-list field as a list of strings."""
    return [str(v) for v in value] if isinstance(value, list) else [str(value)] if value else []


def location(values: Dict[str, Any]) -> str | None:
    """Where a marketplace, item or region searches, in the user's terms where possible."""
    for key in ("city_name", "search_city", "search_region"):
        if values.get(key):
            return ", ".join(listed(values[key]))
    return None


class Toolkit:
    """Base class: subclasses declare their config class, guides and playbook."""

    section_type: str = ""
    playbook: str = ""
    config_class: type = object
    guides: Tuple[FieldGuide, ...] = ()

    # --- field facts -------------------------------------------------------------------
    def field_names(self: "Toolkit") -> List[str]:
        return [f.name for f in fields(self.config_class) if f.name not in _NOT_CONFIGURED]  # type: ignore[arg-type]

    def group(self: "Toolkit", name: str) -> FieldGroup:
        return field_group(self.config_class, name)

    def guide(self: "Toolkit", name: str) -> FieldGuide:
        return next(g for g in self.guides if g.name == name)

    def guide_table(self: "Toolkit") -> str:
        """The field guides as markdown tables, one per group."""
        titles = {
            FieldGroup.OWN: "Fields of this section only",
            FieldGroup.LOCATION: "Location fields (defaults for items, set as a group)",
            FieldGroup.SHARED: "Shared fields (defaults for items; items may override)",
        }
        out = [f"## Fields of [{self.section_type}.*]\n"]
        for group, title in titles.items():
            rows = [g for g in self.guides if self.group(g.name) is group]
            if not rows:
                continue
            out.append(f"### {title}\n\n| field | how to determine | format | when unset |")
            out.append("|---|---|---|---|")
            for g in rows:
                secret = " **Secret: only a ${VAR} reference.**" if g.secret else ""
                out.append(
                    f"| `{g.name}` | {g.determine}{secret} | {g.format} | {g.default or ''} |"
                )
            out.append("")
        return "\n".join(out)

    def same_value(self: "Toolkit", key: str, old: Any, new: Any) -> bool:
        """Whether two raw values load to the same thing (e.g. ``"x"`` and ``["x"]``)."""
        if old == new:
            return True
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                loaded = [
                    getattr(self.config_class(name="_", **{key: v}), key)  # type: ignore[call-arg]
                    for v in (old, new)
                ]
        except Exception:
            return False
        return loaded[0] == loaded[1]

    def masked(self: "Toolkit", values: Dict[str, Any]) -> Dict[str, Any]:
        """Values safe to show the LLM: secret fields only as ``${VAR}`` references."""
        out = {}
        for key, value in values.items():
            secret = any(g.name == key and g.secret for g in self.guides)
            out[key] = value if not secret or is_reference(value) else "<set; hidden>"
        return out

    def change(
        self: "Toolkit",
        draft: SectionDraft,
        values: Dict[str, Any],
        unset: List[str],
        request: str | None,
    ) -> Tuple[SectionDraft, List[str]]:
        """A copy of ``draft`` with the changes applied, and the problems found.

        Unknown fields, secrets that are not ``${VAR}``, and ``${VAR}`` in other fields are
        refused (an environment reference in a normal field would be expanded and could leak
        its value). A value equal to the current one in another form keeps the user's form.
        """
        problems: List[str] = []
        new = draft.copy()
        names = set(self.field_names())
        for key, value in values.items():
            if key not in names:
                problems.append(f"`{key}` is not a field of [{self.section_type}.*].")
            elif self.guide(key).secret:
                if not is_reference(value):
                    problems.append(f"`{key}` is secret: only a ${{VAR}} reference may be set.")
                else:
                    new.values[key] = value
            elif _mentions_reference(value) and not (
                self.guide(key).reference and _only_references(value)
            ):
                problems.append(f"`{key}` may not contain a ${{VAR}} reference.")
            elif key in draft.values and self.same_value(key, draft.values[key], value):
                continue
            else:
                new.values[key] = copy.deepcopy(value)
        for key in unset:
            if key not in names:
                problems.append(f"`{key}` is not a field of [{self.section_type}.*].")
            new.values.pop(key, None)
        if request is not None and request.strip():
            new.request = request.strip()
        return new, problems

    # --- section-specific behavior --------------------------------------------------------
    def view(self: "Toolkit", ws: "Workspace", name: str) -> SectionDraft:
        """The section as saved (empty for a new one)."""
        if self.section_type in SINGLETONS:
            section = ws.user_cfg.get(self.section_type)
        else:
            section = ws.user_cfg.get(self.section_type, {}).get(name)
        values = {k: copy.deepcopy(v) for k, v in (section or {}).items() if k != "request"}
        return SectionDraft(
            section_type=self.section_type,
            name=name,
            is_new=section is None,
            request=(section or {}).get("request"),
            values=values,
            original=copy.deepcopy(values),
            original_request=(section or {}).get("request"),
        )

    def context(self: "Toolkit", ws: "Workspace") -> Dict[str, List[str]]:
        """Names the section's fields may reference; nothing else of the config."""
        raise NotImplementedError

    def validate(self: "Toolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        raise NotImplementedError

    def missing(self: "Toolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        raise NotImplementedError

    def describe(self: "Toolkit", draft: SectionDraft) -> str:
        raise NotImplementedError

    def show_extra(self: "Toolkit", ws: "Workspace", draft: SectionDraft) -> Dict[str, Any]:
        """Read-only context added to ``section_show`` (none by default)."""
        return {}

    def summary(self: "Toolkit", ws: "Workspace", values: Dict[str, Any]) -> str | None:
        """A few words on what a saved section does, for ``list_sections`` (none by default)."""
        return None

    def companions(self: "Toolkit", ws: "Workspace", name: str) -> List[Tuple[str, str]]:
        """Other sections a single-section command may also change (none by default).

        A name of ``"*"`` allows any section of that type.
        """
        return []

    def can_apply(self: "Toolkit", ws: "Workspace", draft: SectionDraft) -> bool:
        """Whether this draft is part of the config when other sections are checked.

        By default only complete drafts are: a half-filled section is not saved as it is, so
        it must not make other sections fail.
        """
        return not self.missing(ws, draft)

    def after_save(self: "Toolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        """Notes for the user once the section is written (none by default)."""
        return []

    def testable(self: "Toolkit", ws: "Workspace", draft: SectionDraft) -> bool:
        """Whether aimm offers to try the section once this draft is saved (none by default)."""
        return False

    async def send_test(self: "Toolkit", ws: "Workspace", name: str) -> Dict[str, Any]:
        """Try a saved section, e.g. send a test message through it; changes nothing."""
        return {
            "ok": False,
            "errors": [f"{section_label(self.section_type, name)} cannot be tested."],
        }

    async def check_extra(self: "Toolkit", ws: "Workspace", draft: SectionDraft) -> Dict[str, Any]:
        """Results added to ``section_check``, e.g. from trying the section (none by default)."""
        return {}

    async def preflight(
        self: "Toolkit", ws: "Workspace", draft: SectionDraft
    ) -> Tuple[List[str], List[str]]:
        """Checks run by ``save`` before asking the user: (errors that refuse, warnings)."""
        return [], []

    def write_first(self: "Toolkit", draft: SectionDraft) -> bool:
        """Whether the section is written before the others of its type."""
        return False

    def apply(self: "Toolkit", user_cfg: Dict[str, Any], draft: SectionDraft) -> Dict[str, Any]:
        """``user_cfg`` with only this section replaced (the input is not changed)."""
        cfg = copy.deepcopy(user_cfg)
        section = {"request": draft.request} if draft.request else {}
        section.update(copy.deepcopy(draft.values))
        if self.section_type in SINGLETONS:
            cfg[self.section_type] = section
        else:
            cfg.setdefault(self.section_type, {})[draft.name] = section
        return cfg

    async def choose_target(
        self: "Toolkit", ui: "SetupUI", ws: "Workspace", name: str | None
    ) -> str | None:
        """For a single-section command: the section to work on, or None to quit."""
        raise NotImplementedError
