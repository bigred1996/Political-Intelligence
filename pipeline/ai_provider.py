"""Modular AI provider for the Goal B2 interpretation layer.

Deliberately isolated from retrieval and from the DB: this module turns
(system prompt, conversation) into a structured tool-call result and nothing
else. It never imports `search.retrieval` or touches a session — swapping the
underlying model (or provider entirely) means editing this file alone, same
spirit as the Claude-path/template-path split in `pipeline.report_builder`.

Uses a forced tool call (`tool_choice={"type": "tool", ...}`), same pattern as
`search.planner.claude_plan` — the model cannot return free-form prose, only
the `build_interpretation` schema, which is what makes the downstream
contract validation in `pipeline.interpretation_contract` meaningful.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from api.config import settings

log = structlog.get_logger()

TOOL_NAME = "build_interpretation"

INTERPRETATION_TOOL: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": (
        "Produce a structured, citation-safe interpretation of ONE retrieved "
        "due-diligence finding. Never include a buy/sell/proceed/valuation "
        "conclusion. Never cite a record id outside ALLOWED_RECORD_IDS."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "source_fact": {
                "type": "string",
                "description": "ONLY what the record literally states. No inference, no opinion, no characterization.",
            },
            "interpretation": {
                "type": "string",
                "description": "What the fact may mean commercially. Never a buy/sell/proceed/valuation conclusion.",
            },
            "impact": {
                "type": "string",
                "description": "Potential commercial or transaction impact. Never a buy/sell/proceed/valuation conclusion.",
            },
            "recommendation": {
                "type": "string",
                "description": "ONLY a diligence question, a monitoring step, or an expert-review suggestion.",
            },
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "evidence_limitations": {
                "type": "string",
                "description": "Coverage gaps, stale data, thin sourcing. Be specific — never 'none' or 'n/a'.",
            },
            "cited_record_ids": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"table": {"type": "string"}, "pk": {"type": ["string", "integer"]}},
                    "required": ["table", "pk"],
                },
            },
            "claims": {
                "type": "array",
                "description": "Every discrete claim made above, labeled by epistemic status.",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "label": {"type": "string", "enum": ["observed", "inferred", "speculative"]},
                        "cited_record_ids": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"table": {"type": "string"}, "pk": {"type": ["string", "integer"]}},
                                "required": ["table", "pk"],
                            },
                        },
                    },
                    "required": ["text", "label"],
                },
            },
        },
        "required": [
            "source_fact", "interpretation", "impact", "recommendation",
            "confidence", "evidence_limitations", "cited_record_ids", "claims",
        ],
    },
}


class ProviderUnavailable(Exception):
    """No provider configured (no API key) — caller should degrade, not retry."""


class ProviderError(Exception):
    """The provider was called but failed (timeout, auth, malformed response)."""


@dataclass
class ProviderTurn:
    tool_input: dict[str, Any]
    tool_use_id: str
    messages: list[dict[str, Any]]  # running conversation, ending with this assistant turn
    model: str


class _ClaudeToolProvider:
    """Shared base for every forced-single-tool-call-to-Claude provider in
    Nessus. Subclasses set `tool` (the schema) and `name`; this base owns the
    one Anthropic client construction, the `tool_choice` forcing, the response
    extraction, and the `call`/`continue_call` re-prompt protocol. Adding a new
    structured AI step = a new subclass + a new tool schema, never a new copy
    of the client plumbing (same spirit as reusing one provider abstraction
    across B2 interpretation and B3 research)."""

    name = "claude"
    tool: dict[str, Any] = INTERPRETATION_TOOL
    max_tokens = 1400

    def __init__(self, model: str | None = None):
        if not settings.anthropic_api_key:
            raise ProviderUnavailable("ANTHROPIC_API_KEY not set")
        self.model = model or self._default_model()

    def _default_model(self) -> str:
        """The model this provider uses when none is passed explicitly.
        Subclasses override to run on a different tier (e.g. synthesis on Opus
        while interpretation/planner stay on the cheaper workhorse)."""
        return settings.claude_model

    @property
    def _tool_name(self) -> str:
        return self.tool["name"]

    def _extract(self, resp: Any, messages_so_far: list[dict[str, Any]]) -> ProviderTurn:
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use" and block.name == self._tool_name:
                assistant_message = {"role": "assistant", "content": resp.content}
                return ProviderTurn(
                    tool_input=block.input,
                    tool_use_id=block.id,
                    messages=messages_so_far + [assistant_message],
                    model=self.model,
                )
        raise ProviderError(f"model did not return the {self._tool_name} tool call")

    async def _create(self, system: str, messages: list[dict[str, Any]]) -> ProviderTurn:
        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            resp = await client.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=system,
                tools=[self.tool],
                tool_choice={"type": "tool", "name": self._tool_name},
                messages=messages,
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(str(exc)) from exc
        return self._extract(resp, messages)

    async def call(self, system: str, user_content: str) -> ProviderTurn:
        return await self._create(system, [{"role": "user", "content": user_content}])

    async def continue_call(self, system: str, prior: ProviderTurn, correction: str) -> ProviderTurn:
        """Re-prompt with a single correction, tied to the prior tool_use via
        a tool_result block (required by the Anthropic message format)."""
        messages = prior.messages + [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": prior.tool_use_id, "content": correction},
                ],
            }
        ]
        return await self._create(system, messages)


class ClaudeInterpretationProvider(_ClaudeToolProvider):
    """One forced `build_interpretation` tool-call per turn (Goal B2). Any
    provider returning a JSON object matching `INTERPRETATION_TOOL`'s schema can
    implement the same `call`/`continue_call` signatures and be swapped in."""

    name = "claude"
    tool = INTERPRETATION_TOOL


# --- Goal B3 — research-loop tools (planner + cross-finding synthesizer) -------
# These reuse the exact same provider plumbing (_ClaudeToolProvider,
# ProviderTurn, ProviderError, ProviderUnavailable, forced tool_choice) — only
# the tool schema changes. The B3 orchestrator owns all citation/conclusion
# validation; these tools just shape the model's output.

PLAN_TOOL_NAME = "plan_research_round"

PLAN_TOOL: dict[str, Any] = {
    "name": PLAN_TOOL_NAME,
    "description": (
        "Propose the next round of internal-records retrieval queries for a "
        "due-diligence research run. Queries must be GAP-DRIVEN — target what "
        "is still unknown given what has already been found, never repeat "
        "prior queries. Also judge whether material questions still remain."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-4 natural-language retrieval queries for the next round, gap-driven.",
            },
            "material_gaps_remain": {
                "type": "boolean",
                "description": "True if material due-diligence questions are still unanswered and another round is warranted.",
            },
            "rationale": {
                "type": "string",
                "description": "Brief reason for these queries / for stopping.",
            },
        },
        "required": ["queries", "material_gaps_remain", "rationale"],
    },
}

SYNTHESIS_TOOL_NAME = "build_synthesis"

_LABELLED_FINDING_LIST = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "label": {"type": "string", "enum": ["observed", "inferred", "speculative"]},
            "finding_ids": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"table": {"type": "string"}, "pk": {"type": ["string", "integer"]}},
                    "required": ["table", "pk"],
                },
            },
        },
        "required": ["text", "label", "finding_ids"],
    },
}

SYNTHESIS_TOOL: dict[str, Any] = {
    "name": SYNTHESIS_TOOL_NAME,
    "description": (
        "Synthesize ACROSS many interpreted due-diligence findings into a "
        "structured run result. Never include a buy/sell/proceed/valuation "
        "conclusion anywhere. Every finding_id MUST come from the run's "
        "retrieved records — never invent one. Label every risk/opportunity/"
        "theme observed, inferred, or speculative."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "themes": {
                "type": "array",
                "description": "Clusters of related findings.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "label": {"type": "string", "enum": ["observed", "inferred", "speculative"]},
                        "finding_ids": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"table": {"type": "string"}, "pk": {"type": ["string", "integer"]}},
                                "required": ["table", "pk"],
                            },
                        },
                    },
                    "required": ["title", "summary", "label", "finding_ids"],
                },
            },
            "material_risks": _LABELLED_FINDING_LIST,
            "opportunities": _LABELLED_FINDING_LIST,
            "diligence_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Open questions for an analyst to pursue. Never deal conclusions.",
            },
            "overall_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "coverage_summary": {
                "type": "string",
                "description": "What was searched, what is thin or missing. Be specific.",
            },
        },
        "required": [
            "themes", "material_risks", "opportunities",
            "diligence_questions", "overall_confidence", "coverage_summary",
        ],
    },
}


class ClaudeResearchPlanner(_ClaudeToolProvider):
    """Forced `plan_research_round` tool-call — proposes the next round's
    gap-driven retrieval queries (Goal B3)."""

    name = "claude"
    tool = PLAN_TOOL
    max_tokens = 800


class ClaudeSynthesisProvider(_ClaudeToolProvider):
    """Forced `build_synthesis` tool-call — cross-finding synthesis (Goal B3).
    Runs on the stronger `synthesis_model` (Opus by default): this is the one
    call per report that does the cross-finding reasoning, so quality matters
    most here and the per-report cost of upgrading a single call is negligible."""

    name = "claude"
    tool = SYNTHESIS_TOOL

    def _default_model(self) -> str:
        return settings.synthesis_model
    # Synthesis emits the full structure (themes + risks + opportunities +
    # diligence questions + coverage_summary), each item carrying multiple
    # citations. At 2000 the JSON tool-call truncated mid-structure and the
    # trailing required field (coverage_summary) was silently dropped, failing
    # validation and collapsing every run to the placeholder fallback. Give it
    # real headroom so the model can finish the object.
    max_tokens = 6000
