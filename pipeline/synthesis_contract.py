"""Goal B3 — the cross-finding synthesis contract.

After the research loop interprets N single findings (each via B2), this is the
structured "so what, across all of them" layer: themes/clusters, material
risks, opportunities, diligence questions, an overall confidence and a coverage
summary. It is a NEW contract (the new capability B3 adds) but it INHERITS B2's
hard rules and enforces them with B2's own primitives — it never reimplements
them:

  * citation integrity reuses `pipeline.citation_registry.validate_citations`
    against the union of the run's retrieval sets;
  * the buy/sell/proceed/valuation conclusion ban reuses
    `pipeline.interpretation_contract.find_conclusion_language`;
  * observed/inferred/speculative labels are the same three B2 uses.

`validate_synthesis` is pure (no DB, no AI); the orchestrator decides what to do
with a non-ok result (one re-prompt, then a deterministic template fallback).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.citation_registry import validate_citations
from pipeline.interpretation_contract import find_conclusion_language

RecordId = tuple[str, str]
_VALID_LABELS = {"observed", "inferred", "speculative"}
_VALID_CONFIDENCE = {"high", "medium", "low"}


@dataclass
class SynthesisItem:
    """A theme / material risk / opportunity — a claim across findings."""

    text: str  # for a theme this is the summary; title carried separately
    label: str
    finding_ids: list[RecordId] = field(default_factory=list)
    title: str = ""  # themes only

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "text": self.text,
            "label": self.label,
            "finding_ids": [{"table": t, "pk": p} for t, p in self.finding_ids],
        }
        if self.title:
            d["title"] = self.title
        return d


@dataclass
class SynthesisContract:
    themes: list[SynthesisItem]
    material_risks: list[SynthesisItem]
    opportunities: list[SynthesisItem]
    diligence_questions: list[str]
    overall_confidence: str
    coverage_summary: str
    generated_by: str = "claude"

    def all_items(self) -> list[SynthesisItem]:
        return [*self.themes, *self.material_risks, *self.opportunities]

    def to_dict(self) -> dict[str, Any]:
        return {
            "themes": [t.to_dict() for t in self.themes],
            "material_risks": [r.to_dict() for r in self.material_risks],
            "opportunities": [o.to_dict() for o in self.opportunities],
            "diligence_questions": list(self.diligence_questions),
            "overall_confidence": self.overall_confidence,
            "coverage_summary": self.coverage_summary,
            "generated_by": self.generated_by,
        }


def _ids_from_raw(raw: list[dict[str, Any]] | None) -> list[RecordId]:
    return [(str(r.get("table")), str(r.get("pk"))) for r in (raw or [])]


def _items_from_raw(raw: list[dict[str, Any]] | None, *, with_title: bool) -> list[SynthesisItem]:
    items = []
    for entry in raw or []:
        items.append(
            SynthesisItem(
                text=str(entry.get("summary" if with_title else "text", "")),
                label=str(entry.get("label", "")),
                finding_ids=_ids_from_raw(entry.get("finding_ids")),
                title=str(entry.get("title", "")) if with_title else "",
            )
        )
    return items


def contract_from_tool_input(data: dict[str, Any], *, generated_by: str) -> SynthesisContract:
    """Build a contract from the model's raw tool-call input. Never trusted
    until `validate_synthesis` has run against it."""
    return SynthesisContract(
        themes=_items_from_raw(data.get("themes"), with_title=True),
        material_risks=_items_from_raw(data.get("material_risks"), with_title=False),
        opportunities=_items_from_raw(data.get("opportunities"), with_title=False),
        diligence_questions=[str(q) for q in (data.get("diligence_questions") or [])],
        overall_confidence=str(data.get("overall_confidence", "low")),
        coverage_summary=str(data.get("coverage_summary", "")),
        generated_by=generated_by,
    )


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]


def validate_synthesis(
    contract: SynthesisContract, allowed_ids: list[RecordId],
) -> ValidationResult:
    """Pure, deterministic check of every hard rule, reusing B2's primitives."""
    errors: list[str] = []

    # 1. Citation integrity — every finding_id cited anywhere must belong to
    # the union of this run's retrieval sets. One definition of "is this id in
    # the set" (validate_citations), never a second.
    all_cited = [rid for item in contract.all_items() for rid in item.finding_ids]
    citation_check = validate_citations(allowed_ids, all_cited)
    if not citation_check["all_valid"]:
        errors.append(f"citation_outside_run: {citation_check['invalid']}")

    # 2. No buy/sell/proceed/valuation conclusion anywhere in the prose.
    texts: list[tuple[str, str]] = [("coverage_summary", contract.coverage_summary)]
    for i, q in enumerate(contract.diligence_questions):
        texts.append((f"diligence_question_{i}", q))
    for kind, items in (
        ("theme", contract.themes),
        ("material_risk", contract.material_risks),
        ("opportunity", contract.opportunities),
    ):
        for i, item in enumerate(items):
            texts.append((f"{kind}_{i}_title", item.title))
            texts.append((f"{kind}_{i}_text", item.text))
    for field_name, text in texts:
        hits = find_conclusion_language(text)
        if hits:
            errors.append(f"{field_name}_contains_conclusion_language: {hits}")

    # 3. Every labeled item carries one of the three allowed epistemic labels.
    for kind, items in (
        ("theme", contract.themes),
        ("material_risk", contract.material_risks),
        ("opportunity", contract.opportunities),
    ):
        for i, item in enumerate(items):
            if item.label not in _VALID_LABELS:
                errors.append(f"{kind}_{i}_invalid_label: {item.label!r}")

    # 4. Overall confidence must be one of the allowed values.
    if contract.overall_confidence not in _VALID_CONFIDENCE:
        errors.append(f"invalid_overall_confidence: {contract.overall_confidence!r}")

    # 5. A non-empty synthesis must say something about coverage.
    if not (contract.coverage_summary or "").strip():
        errors.append("coverage_summary_empty")

    # 6. Every theme/risk/opportunity item must cite at least one finding —
    # an unsupported claim must never be presented as fact (Goal B7).
    for kind, items in (
        ("theme", contract.themes),
        ("material_risk", contract.material_risks),
        ("opportunity", contract.opportunities),
    ):
        for i, item in enumerate(items):
            if not item.finding_ids:
                errors.append(f"{kind}_{i}_has_no_finding_ids")

    return ValidationResult(ok=not errors, errors=errors)


def build_correction_message(errors: list[str]) -> str:
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "Your previous build_synthesis call violated these hard rules:\n"
        f"{lines}\n\n"
        "Call build_synthesis again, fixing ONLY these violations. Only cite "
        "finding_ids from the ALLOWED_FINDING_IDS list. Never use "
        "buy/sell/proceed/valuation conclusion language anywhere. Label every "
        "theme/risk/opportunity observed, inferred, or speculative. "
        "coverage_summary must specifically state what was searched and what is "
        "thin or missing."
    )
