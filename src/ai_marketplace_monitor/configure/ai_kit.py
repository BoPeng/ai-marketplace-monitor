"""The AI toolkit: `[ai.*]` sections, configured with the help of the current AI.

It does what the `aimm configure ai` wizard does (update or fix a section, add one, make one the
default, choose a model from the provider's list) through the same probe and model listing.
The session keeps using the AI it started with; changes take effect the next time aimm runs.
"""

from __future__ import annotations

import copy
import os
import warnings
from typing import TYPE_CHECKING, Any, Dict, List, Tuple
from urllib.parse import urlparse

from ..config import supported_ai_backends
from ..config_toml import dump_config_toml
from .ai_setup import (
    PROVIDER_BY_KEY,
    PROVIDER_LABELS,
    AISection,
    ProbeResult,
    _build_ai_config,
    probe_sections,
)
from .marketplace import _plain
from .toolkits import (
    FieldGroup,
    FieldGuide,
    SectionDraft,
    Toolkit,
    is_reference,
    unset_variable_notes,
)
from .ui import SetupUI

if TYPE_CHECKING:
    from .workspace import Workspace

DEFAULT = "default"  # not written: makes the section the first [ai.*], i.e. aimm's default AI
_ENV_VARS = ", ".join(f"`{s.env_var}` ({s.label})" for s in PROVIDER_BY_KEY.values() if s.env_var)

AI_GUIDES: Tuple[FieldGuide, ...] = (
    FieldGuide(
        "provider",
        "only for a section not named after its provider (e.g. [ai.backup]); a section named "
        "unitysvc, openai, anthropic or ollama uses that provider",
        '`"unitysvc"`, `"openai"`, `"anthropic"` or `"ollama"`',
        "the section name",
    ),
    FieldGuide(
        "api_key",
        f"the provider's API key, as an environment variable: {_ENV_VARS}",
        '`"${UNITYSVC_API_KEY}"`',
        "required (not for Ollama)",
        secret=True,
    ),
    FieldGuide(
        "model",
        "a model from `available_models` of section_check; for UnitySVC also a tier "
        "(`balanced`, ...)",
        'e.g. `"balanced"`, `"gpt-4o"`, `"claude-sonnet-5-5"`',
        "the provider's default model",
    ),
    FieldGuide(
        "base_url",
        "UnitySVC: another endpoint or alias (e.g. `https://api.svcpass.com/a/myllm`); Ollama: "
        "the server; use `suggested_base_url` from section_check when there is one",
        "a URL starting with https:// or http://",
        "UnitySVC: https://api.svcpass.com/p/llm; Ollama: required",
    ),
    FieldGuide(
        "use_images",
        "`false` if the user wants to save tokens or the model cannot read images; on by "
        "default, the AI sees the listing's main photo (800 px; 400 px for Anthropic)",
        "`true` or `false`",
        "true (photo and text)",
    ),
    FieldGuide(
        "image_detail",
        "with use_images: how closely the photo is read; `high` can double the cost per listing",
        '`"low"` (about 85 tokens), `"high"`, `"auto"` or `"original"`',
        '`"low"`',
    ),
    FieldGuide("timeout", "only on request: seconds to wait for a reply", "integer", "none"),
    FieldGuide("max_retries", "only on request: attempts per request", "integer", "10"),
    FieldGuide("enabled", "only to turn this AI off without removing it", "`false`", "on"),
    FieldGuide(
        DEFAULT,
        "make this the default AI (moved before the others); a new section becomes the default "
        "unless the user wants it as a backup (`false`). Not written to the file",
        "`true` or `false`",
        "new sections: true; existing: unchanged",
    ),
)


def _provider(name: str, values: Dict[str, Any]) -> str:
    return str(values.get("provider", name)).lower()


def _section(name: str, values: Dict[str, Any]) -> AISection:
    """The draft as the wizard's AISection, so the wizard's probe can try it."""
    raw = {k: v for k, v in values.items() if k != DEFAULT}
    section = AISection(name=name, raw=raw, files=[])
    section.config, section.problem = _build_ai_config(name, raw)
    return section


def _result(result: ProbeResult) -> Dict[str, Any]:
    out: Dict[str, Any] = {"works": result.ok, "model": result.model, "message": result.message}
    if result.available:
        out["available_models"] = result.available[:40]
    if result.suggested_base_url:
        out["suggested_base_url"] = result.suggested_base_url
    return out


class AIToolkit(Toolkit):
    section_type = "ai"
    playbook = "ai"
    config_class = object  # sections load into their provider's config class
    guides = AI_GUIDES

    def summary(self: "AIToolkit", ws: "Workspace", values: Dict[str, Any]) -> str | None:
        model = f"model {values['model']}" if values.get("model") else "default model"
        if values.get("use_images", True):
            return f"{model}; reads listing photos (use_images = false saves tokens)"
        return f"{model}; text only (use_images = true lets it read listing photos)"

    def field_names(self: "AIToolkit") -> List[str]:
        return [g.name for g in self.guides]

    def group(self: "AIToolkit", name: str) -> FieldGroup:
        return FieldGroup.OWN  # an AI section has no item defaults

    def same_value(self: "AIToolkit", key: str, old: Any, new: Any) -> bool:
        return bool(old == new)

    def masked(self: "AIToolkit", values: Dict[str, Any]) -> Dict[str, Any]:
        key = values.get("api_key")
        if key is None or is_reference(key):
            return dict(values)
        return {**values, "api_key": "<written in the file; hidden>"}

    # --- reading -------------------------------------------------------------------------
    def view(self: "AIToolkit", ws: "Workspace", name: str) -> SectionDraft:
        section = ws.user_cfg.get("ai", {}).get(name)
        values = {k: copy.deepcopy(v) for k, v in (section or {}).items() if k != "request"}
        return SectionDraft(
            section_type="ai",
            name=name,
            is_new=section is None,
            request=(section or {}).get("request"),
            values=values,
            original=copy.deepcopy(values),
            original_request=(section or {}).get("request"),
        )

    def context(self: "AIToolkit", ws: "Workspace") -> Dict[str, List[str]]:
        names = list(ws.user_cfg.get("ai", {}))
        names += [n for t, n in ws.drafts if t == "ai" and n not in names]
        return {"ai_services": names}

    def show_extra(self: "AIToolkit", ws: "Workspace", draft: SectionDraft) -> Dict[str, Any]:
        order = list(ws.user_cfg.get("ai", {}))
        return {
            "order": order,  # aimm uses the first; the others only if it fails
            "is_default": bool(order) and order[0] == draft.name,
            "in_use_by_this_session": ws.ai_in_use == draft.name,
        }

    async def check_extra(
        self: "AIToolkit", ws: "Workspace", draft: SectionDraft
    ) -> Dict[str, Any]:
        """Try the draft as the wizard does: list the models, send a one-token request."""
        if self.missing(ws, draft) or self.validate(ws, draft):
            return {}
        [result] = await probe_sections([_section(draft.name, draft.values)])
        return {"trial": _result(result)}

    # --- checking ------------------------------------------------------------------------
    def validate(self: "AIToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        values = {k: v for k, v in draft.values.items() if k != DEFAULT}
        if DEFAULT in draft.values and not isinstance(draft.values[DEFAULT], bool):
            return ["`default` must be true or false."]
        provider = _provider(draft.name, values)
        if draft.name.lower() in supported_ai_backends and provider != draft.name.lower():
            return [
                (
                    f"[ai.{draft.name}] is named after a provider, so `provider` must be "
                    f"{draft.name.lower()!r}; use another section name for {provider!r}."
                )
            ]
        if provider not in supported_ai_backends:
            return []  # `missing` asks for the provider
        if provider not in PROVIDER_BY_KEY and values != draft.original:
            label = PROVIDER_LABELS.get(provider, provider)
            return [
                (
                    f"aimm configure can set up UnitySVC, OpenAI, Anthropic and Ollama; {label} "
                    "sections have to be edited by hand."
                )
            ]
        lists = [
            k
            for k in ("provider", "api_key", "model", "base_url")
            if k in values and not isinstance(values[k], str)
        ]
        if lists:
            return [f'`{lists[0]}` must be a single string, e.g. "balanced" (not a list).']
        url = values.get("base_url")
        if url is not None and not str(url).startswith(("https://", "http://")):
            return ["`base_url` must start with https:// or http://."]
        if url is not None and str(url).startswith("http://") and provider != "ollama":
            host = urlparse(str(url)).hostname or ""
            if host not in ("localhost", "127.0.0.1", "::1"):
                # the API key would travel unencrypted
                return ["`base_url` must use https:// (http:// only for Ollama or localhost)."]
        key = values.get("api_key")
        if isinstance(key, str) and is_reference(key) and key[2:-1] not in os.environ:
            # aimm cannot load a config whose AI key is unset (even a disabled section)
            return [
                (
                    f"`api_key` refers to {key}, which is not set, and aimm cannot start with it. "
                    f"Ask the user to run `export {key[2:-1]}=<their key>` (and add it to their "
                    "shell profile), then start aimm configure again."
                )
            ]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                supported_ai_backends[provider].get_config(name=draft.name, **values)
        except Exception as e:
            return [_plain(e)]
        return []

    def missing(self: "AIToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        provider = _provider(draft.name, draft.values)
        if provider not in supported_ai_backends:
            return ["provider: choose UnitySVC, OpenAI, Anthropic or Ollama"]
        out = []
        if provider != "ollama" and not draft.values.get("api_key"):
            out.append(f"api_key: a reference such as ${{{_env_var(provider)}}}")
        if provider == "ollama":
            out += [
                f"{f}: required for Ollama"
                for f in ("base_url", "model")
                if not draft.values.get(f)
            ]
        return out

    def write_first(self: "AIToolkit", draft: SectionDraft) -> bool:
        wanted = draft.values.get(DEFAULT)
        return wanted is True or (draft.is_new and wanted is not False)

    def _will_be_default(self: "AIToolkit", ws: "Workspace", draft: SectionDraft) -> bool:
        """Whether the section is aimm's default AI after this save."""
        if self.write_first(draft):
            return True
        moved = any(
            d.key != draft.key and d.section_type == "ai" and self.write_first(d)
            for d in ws.pending()
        )
        return not moved and next(iter(ws.user_cfg.get("ai", {})), None) == draft.name

    async def preflight(
        self: "AIToolkit", ws: "Workspace", draft: SectionDraft
    ) -> Tuple[List[str], List[str]]:
        """Try the section before saving; the default AI must work, others get a warning."""
        if draft.values.get("enabled") is False:
            return [], []
        [result] = await probe_sections([_section(draft.name, draft.values)])
        if result.ok:
            return [], []
        if self._will_be_default(ws, draft):
            return [
                (
                    f"it does not work ({result.message}), so it cannot be the default AI. Fix "
                    "it, make another section the default first, or save it as a backup with "
                    "`default: false`."
                )
            ], []
        return [], [
            (
                f"[ai.{draft.name}] does not work yet: {result.message}. aimm tries it only when the "
                "AI sections before it fail."
            )
        ]

    # --- writing -------------------------------------------------------------------------
    def apply(self: "AIToolkit", user_cfg: Dict[str, Any], draft: SectionDraft) -> Dict[str, Any]:
        written = draft.copy()
        written.values.pop(DEFAULT, None)
        return super().apply(user_cfg, written)

    def describe(self: "AIToolkit", draft: SectionDraft) -> str:
        section = {"request": draft.request} if draft.request else {}
        section.update(self.masked({k: v for k, v in draft.values.items() if k != DEFAULT}))
        note = "\n\n(becomes the default AI)" if self.write_first(draft) else ""
        return f"```toml\n{dump_config_toml({'ai': {draft.name: section}})}```{note}"

    def after_save(self: "AIToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        return [
            *unset_variable_notes(draft),
            (
                f"{draft.label} takes effect the next time aimm starts; this "
                "session keeps using its current AI."
            ),
        ]

    async def choose_target(
        self: "AIToolkit", ui: SetupUI, ws: "Workspace", name: str | None
    ) -> str | None:
        sections = ws.user_cfg.get("ai", {})
        lines = [
            (
                f"**[ai.{n}]**{' (default)' if i == 0 else ''}\n\n"
                f"```toml\n{dump_config_toml({'ai': {n: self.masked(s)}})}```"
            )
            for i, (n, s) in enumerate(sections.items())
            if isinstance(s, dict)
        ]
        await ui.say("AI services (aimm uses the first):\n\n" + "\n\n".join(lines), markdown=True)
        return name or next(iter(sections), "unitysvc")

    def companions(self: "AIToolkit", ws: "Workspace", name: str) -> List[Tuple[str, str]]:
        return [("ai", "*")]


def _env_var(provider: str) -> str:
    spec = PROVIDER_BY_KEY.get(provider)
    return spec.env_var if spec and spec.env_var else f"{provider.upper()}_API_KEY"
