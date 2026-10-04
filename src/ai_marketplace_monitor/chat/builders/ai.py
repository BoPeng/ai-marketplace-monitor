"""Scripted builder for [ai.*] sections: no AI exists yet to drive a conversation."""

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from ...ai import AIConfig, AnthropicBackend, OllamaBackend, OpenAIBackend
from ..ai_sections import AISection, env_var_name, load_ai_sections
from ..messages import AskText, Choose, Option, Say
from ..probe import probe
from ..sections import ChatContext, FieldGuide, SectionBuilder, SectionProposal, SectionRef
from ..ui import ChatUI

KEY_PATTERN = re.compile(r"^(svcpass_|sk-ant-|sk-)\S{8,}")
UNITYSVC_TIERS = ["fast", "balanced", "coding", "premium"]
OLLAMA_URL = "http://localhost:11434/v1"


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    hint: str
    env_var: str | None
    key_url: str | None


PROVIDERS: List[ProviderSpec] = [
    ProviderSpec(
        "unitysvc",
        "UnitySVC",
        "recommended — one key for the AI and for email notifications",
        "UNITYSVC_API_KEY",
        "https://unitysvc.com",
    ),
    ProviderSpec("openai", "OpenAI", "", "OPENAI_API_KEY", "https://platform.openai.com/api-keys"),
    ProviderSpec(
        "anthropic",
        "Anthropic",
        "",
        "ANTHROPIC_API_KEY",
        "https://console.anthropic.com/settings/keys",
    ),
    ProviderSpec("ollama", "Ollama", "runs on your own machine, no key", None, None),
]
_BY_KEY = {p.key: p for p in PROVIDERS}
PROVIDER_LABELS: Dict[str, str] = {
    **{p.key: p.label for p in PROVIDERS},
    "deepseek": "DeepSeek",
    "gemini": "Gemini",
}

AI_FIELDS: Tuple[FieldGuide, ...] = (
    FieldGuide(
        "provider",
        "The service the user chose; omit it when it equals the section name.",
        ask="Which AI do you want to use?",
        inherit=False,
    ),
    FieldGuide(
        "api_key",
        "Always a ${VARIABLE} reference: keep an existing variable name, otherwise use the "
        "provider's standard one (UNITYSVC_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY). "
        "Not used by Ollama. Never a literal key.",
        inherit=False,
    ),
    FieldGuide(
        "base_url",
        "Omit it to use the provider's default. Ollama needs it, usually "
        "http://localhost:11434/v1.",
        ask="Where is Ollama running?",
        inherit=False,
    ),
    FieldGuide(
        "model",
        "For UnitySVC a tier: fast, balanced (default), coding, or premium. Otherwise a "
        "model name the provider offers; default to the provider's default model.",
        ask="Which tier or model?",
        inherit=False,
    ),
    FieldGuide("max_retries", "Keep the default (10) unless the user asks for another number."),
    FieldGuide("timeout", "Seconds to wait for an answer; omit unless the user asks."),
    FieldGuide(
        "enabled",
        "Omit (enabled). Set false only when the user wants to keep the section but not use it.",
        inherit=False,
    ),
    FieldGuide(
        "request",
        "One sentence: the provider and model, and that it rates listings and powers the chat.",
        inherit=False,
    ),
)


@dataclass
class AISetupOutcome:
    config: AIConfig | None  # set when the section works now
    retry: bool = False  # it failed its probe; offer setup again


async def _ask_text(ui: ChatUI, prompt: str, default: str) -> str:
    while True:
        answer = (await ui.ask(AskText(prompt, default=default))).strip()
        if KEY_PATTERN.match(answer):
            await ui.say(
                Say(
                    "That looks like an API key. Keys never go into aimm — you will set it "
                    "as an environment variable instead, and I will show you how.",
                    kind="warning",
                )
            )
            continue
        return answer or default


def _new_name(provider: str, sections: List[AISection]) -> str:
    names = {s.name for s in sections}
    name, suffix = provider, 1
    while name in names:
        suffix += 1
        name = f"{provider}_{suffix}"
    return name


class ScriptedAIBuilder(SectionBuilder):
    section_type = "ai"
    playbook = "ai"
    uses_ai = False
    fields = AI_FIELDS

    async def converse(
        self: "ScriptedAIBuilder", ui: ChatUI, ref: SectionRef, ctx: ChatContext
    ) -> SectionProposal | None:
        sections = load_ai_sections(ctx.files)
        named = next((s for s in sections if s.name == ref.name), None) if ref.name else None
        default = named.provider if named and named.provider in _BY_KEY else "unitysvc"
        options = [Option(p.key, p.label, p.hint) for p in PROVIDERS] + [Option("quit", "Quit")]
        choice = await ui.ask(Choose("Which AI do you want to use?", options, default))
        if choice == "quit":
            return None
        spec = _BY_KEY[choice]
        target: AISection | None
        if named is not None and named.provider == choice:
            target = named
        else:
            target = next((s for s in sections if s.provider == choice), None)
        old: Dict[str, Any] = target.raw if target else {}

        values: Dict[str, Any] = {"provider": choice}
        if spec.env_var:
            var = env_var_name(old.get("api_key")) or spec.env_var
            values["api_key"] = "${" + var + "}"
        if choice == "unitysvc":
            current = old.get("model")
            tier_default = current if current in UNITYSVC_TIERS else "balanced"
            tiers = [Option(t, t) for t in UNITYSVC_TIERS]
            values["model"] = await ui.ask(Choose("Which UnitySVC tier?", tiers, tier_default))
        elif choice == "ollama":
            values["base_url"] = await _ask_text(
                ui, "Ollama URL", old.get("base_url") or OLLAMA_URL
            )
            model_default = old.get("model") or OllamaBackend.default_model
            values["model"] = await _ask_text(ui, "Model", model_default)
        else:
            backend = OpenAIBackend if choice == "openai" else AnthropicBackend
            values["model"] = await _ask_text(
                ui, "Model", old.get("model") or backend.default_model
            )

        if target is not None:
            # an updated section keeps its own shared settings
            values.update(self.template_values(target.raw))
        else:
            # a new section starts from the named section, else the first existing one
            template = named or (sections[0] if sections else None)
            if template is not None:
                values.update(self.template_values(template.raw))

        name = target.name if target else _new_name(choice, sections)
        if name == choice:
            values.pop("provider")
        return SectionProposal(
            ref=SectionRef("ai", name),
            values=values,
            request=f"Use {spec.label} ({values['model']}) to rate listings and to chat.",
            target_file=target.files[-1] if target else ctx.default_file,
        )

    async def after_commit(
        self: "ScriptedAIBuilder", ui: ChatUI, proposal: SectionProposal, ctx: ChatContext
    ) -> AISetupOutcome:
        var = env_var_name(proposal.values.get("api_key"))
        if var is None or var in os.environ:
            section = next(s for s in load_ai_sections(ctx.files) if s.name == proposal.ref.name)
            result = await asyncio.to_thread(probe, section)
            if result.ok:
                await ui.say(Say(f"{section.name} works ({result.model}).", kind="success"))
                return AISetupOutcome(section.config)
            await ui.say(Say(result.message, kind="error"))
            return AISetupOutcome(None, retry=True)
        provider = str(proposal.values.get("provider", proposal.ref.name))
        spec = _BY_KEY.get(provider)
        if spec and spec.key_url:
            await ui.say(Say(f"Get a {spec.label} API key at {spec.key_url}."))
        await ui.say(
            Say(
                f"Set it in your shell (and add the line to your shell profile to keep it):\n\n"
                f"```bash\nexport {var}=<your key>\n```",
                markdown=True,
            )
        )
        await ui.say(Say("Then run `aimm --chat` again.", markdown=True))
        return AISetupOutcome(None)
