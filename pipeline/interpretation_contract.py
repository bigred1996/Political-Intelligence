"""The Goal B2 interpretation contract — the structured schema for "what does
this ONE retrieved finding mean" plus the hard rules that enforce the
fact/inference separation and no-conclusion policy IN CODE, not just in the
system prompt. `validate_contract` is what `pipeline.interpretation` calls
before any AI-produced contract is persisted or returned to a caller; a
violation triggers a single re-prompt there, never a silent pass-through.

Citation integrity reuses `pipeline.citation_registry.validate_citations`
directly rather than reimplementing it — there must be exactly one definition
of "is this id actually in the retrieval set."
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pipeline.citation_registry import validate_citations

RecordId = tuple[str, str]
ClaimLabel = Literal["observed", "inferred", "speculative"]
_VALID_LABELS = {"observed", "inferred", "speculative"}


@dataclass
class Claim:
    text: str
    label: str
    cited_record_ids: list[RecordId] = field(default_factory=list)


@dataclass
class InterpretationContract:
    source_fact: str
    interpretation: str
    impact: str
    recommendation: str
    confidence: str  # high | medium | low
    evidence_limitations: str
    cited_record_ids: list[RecordId]
    claims: list[Claim]
    generated_by: str = "claude"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_fact": self.source_fact,
            "interpretation": self.interpretation,
            "impact": self.impact,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "evidence_limitations": self.evidence_limitations,
            "cited_record_ids": [{"table": t, "pk": p} for t, p in self.cited_record_ids],
            "claims": [
                {
                    "text": c.text,
                    "label": c.label,
                    "cited_record_ids": [{"table": t, "pk": p} for t, p in c.cited_record_ids],
                }
                for c in self.claims
            ],
            "generated_by": self.generated_by,
        }


def _ids_from_raw(raw: list[dict[str, Any]] | None) -> list[RecordId]:
    return [(str(r.get("table")), str(r.get("pk"))) for r in (raw or [])]


def contract_from_tool_input(data: dict[str, Any], *, generated_by: str) -> InterpretationContract:
    """Build a contract from the model's raw tool-call input. Never trusted
    until `validate_contract` has run against it."""
    claims = [
        Claim(
            text=str(c.get("text", "")),
            label=str(c.get("label", "")),
            cited_record_ids=_ids_from_raw(c.get("cited_record_ids")),
        )
        for c in (data.get("claims") or [])
    ]
    return InterpretationContract(
        source_fact=str(data.get("source_fact", "")),
        interpretation=str(data.get("interpretation", "")),
        impact=str(data.get("impact", "")),
        recommendation=str(data.get("recommendation", "")),
        confidence=str(data.get("confidence", "low")),
        evidence_limitations=str(data.get("evidence_limitations", "")),
        cited_record_ids=_ids_from_raw(data.get("cited_record_ids")),
        claims=claims,
        generated_by=generated_by,
    )


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]


# Phrases that signal the writer has slipped from stating a fact into
# characterizing what it means — exactly what `source_fact` must never do.
_INFERENCE_MARKERS = [
    "suggests", "suggesting", "indicates", "indicating", "likely", "implies", "implying",
    "could mean", "may mean", "appears to", "seems to", "points to", "raises concern",
    "raises questions", "may signal", "potentially reveals", "this means", "could indicate",
    "is indicative of", "may reflect", "consistent with a pattern", "signals a",
]
_INFERENCE_RE = re.compile(r"\b(" + "|".join(re.escape(m) for m in _INFERENCE_MARKERS) + r")\b", re.IGNORECASE)

# Buy/sell/proceed/valuation conclusion language — banned from interpretation,
# impact, and recommendation. recommendation may only be a diligence
# question, a monitoring step, or an expert-review suggestion.
_CONCLUSION_PATTERNS = [
    r"\bbuy(?:ing|er)?\b", r"\bsell(?:ing|er)?\b", r"\bproceed(?:ing)?\b",
    r"\bvaluat(?:ion|e|ed|ing)\b", r"\bgo[- ]ahead\b", r"\bgood investment\b",
    r"\bwalk away\b", r"\brecommend(?:s|ed)? (?:the )?(?:acquisition|deal|transaction)\b",
]
_CONCLUSION_RE = re.compile("|".join(_CONCLUSION_PATTERNS), re.IGNORECASE)

_DISMISSIVE_LIMITATION_RE = re.compile(
    r"^\s*(none\.?|n/?a\.?|no limitations?\.?|no known limitations?\.?)\s*$", re.IGNORECASE
)


def find_inference_markers(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in _INFERENCE_RE.finditer(text or "")})


def find_conclusion_language(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in _CONCLUSION_RE.finditer(text or "")})


def validate_contract(
    contract: InterpretationContract,
    allowed_ids: list[RecordId],
    *,
    evidence_thin: bool = False,
) -> ValidationResult:
    """Pure, deterministic check of every hard rule. No DB, no AI — callers
    decide what to do with a non-ok result (re-prompt, then fall back)."""
    errors: list[str] = []

    # 1. Citation integrity — every id cited, top-level or per-claim, must be
    # a member of the retrieval set this finding came from.
    all_cited = list(contract.cited_record_ids) + [
        rid for c in contract.claims for rid in c.cited_record_ids
    ]
    citation_check = validate_citations(allowed_ids, all_cited)
    if not citation_check["all_valid"]:
        errors.append(f"citation_outside_retrieval_set: {citation_check['invalid']}")

    # 2. Fact/inference separation.
    markers = find_inference_markers(contract.source_fact)
    if markers:
        errors.append(f"source_fact_contains_inference: {markers}")

    # 3. No-conclusion rule.
    for field_name, text in (
        ("interpretation", contract.interpretation),
        ("impact", contract.impact),
        ("recommendation", contract.recommendation),
    ):
        hits = find_conclusion_language(text)
        if hits:
            errors.append(f"{field_name}_contains_conclusion_language: {hits}")

    # 4. Every claim must carry one of the three allowed labels.
    for i, c in enumerate(contract.claims):
        if c.label not in _VALID_LABELS:
            errors.append(f"claim_{i}_invalid_label: {c.label!r}")

    # 5. Low confidence / thin evidence must never be hidden behind a
    # dismissive or empty limitations field.
    if contract.confidence == "low" or evidence_thin:
        limitation = (contract.evidence_limitations or "").strip()
        if not limitation or _DISMISSIVE_LIMITATION_RE.match(limitation):
            errors.append("evidence_limitations_missing_or_dismissive_for_low_confidence")

    return ValidationResult(ok=not errors, errors=errors)


def build_correction_message(errors: list[str]) -> str:
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "Your previous build_interpretation call violated these hard rules:\n"
        f"{lines}\n\n"
        "Call build_interpretation again, fixing ONLY these violations. Keep "
        "source_fact strictly literal — no inferential language at all. Never "
        "use buy/sell/proceed/valuation conclusion language anywhere in "
        "interpretation, impact, or recommendation. Only cite record ids from "
        "ALLOWED_RECORD_IDS. If confidence is low or evidence is thin, "
        "evidence_limitations must say specifically why — never 'none' or 'n/a'."
    )
