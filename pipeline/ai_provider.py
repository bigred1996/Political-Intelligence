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


class ClaudeInterpretationProvider:
    """One forced tool-call to Claude per turn. Any other provider that can
    return a JSON object matching `INTERPRETATION_TOOL`'s schema can implement
    the same `call`/`continue_call` signatures and be swapped in."""

    name = "claude"

    def __init__(self, model: str | None = None):
        if not settings.anthropic_api_key:
            raise ProviderUnavailable("ANTHROPIC_API_KEY not set")
        self.model = model or settings.claude_model

    def _extract(self, resp: Any, messages_so_far: list[dict[str, Any]]) -> ProviderTurn:
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use" and block.name == TOOL_NAME:
                assistant_message = {"role": "assistant", "content": resp.content}
                return ProviderTurn(
                    tool_input=block.input,
                    tool_use_id=block.id,
                    messages=messages_so_far + [assistant_message],
                    model=self.model,
                )
        raise ProviderError("model did not return the build_interpretation tool call")

    async def call(self, system: str, user_content: str) -> ProviderTurn:
        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            messages = [{"role": "user", "content": user_content}]
            resp = await client.messages.create(
                model=self.model, max_tokens=1400, system=system,
                tools=[INTERPRETATION_TOOL],
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=messages,
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(str(exc)) from exc
        return self._extract(resp, messages)

    async def continue_call(self, system: str, prior: ProviderTurn, correction: str) -> ProviderTurn:
        """Re-prompt with a single correction, tied to the prior tool_use via
        a tool_result block (required by the Anthropic message format)."""
        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            messages = prior.messages + [
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": prior.tool_use_id, "content": correction},
                    ],
                }
            ]
            resp = await client.messages.create(
                model=self.model, max_tokens=1400, system=system,
                tools=[INTERPRETATION_TOOL],
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=messages,
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(str(exc)) from exc
        return self._extract(resp, messages)
