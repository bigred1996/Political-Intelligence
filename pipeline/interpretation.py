"""Goal B2 — AI interpretation layer for a single retrieved finding.

Sits strictly downstream of B1 (`search.retrieval` + `pipeline.citation_registry`):
every call names a `retrieval_set_id` from a real, previously persisted
retrieval, and the `(table, pk)` finding under interpretation MUST be a
member of that exact set — interpreting something that was never actually
retrieved is refused before any AI call is made, the same "never cite a
record you didn't retrieve" rule B1 enforces for citations, applied here to
the finding's own identity.

This module is the only caller of `pipeline.ai_provider`; retrieval code
never imports it, and the provider never imports retrieval — see
`tests/test_retrieval.py::test_no_ai_provider_imports_in_retrieval_module`.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.interpretation import Interpretation
from api.routes.records import _ALIASES, _spec_for
from pipeline.ai_provider import ClaudeInterpretationProvider, ProviderError, ProviderTurn, ProviderUnavailable
from pipeline.citation_registry import get_retrieval_set, validate_citations
from pipeline.interpretation_contract import (
    InterpretationContract,
    Claim,
    build_correction_message,
    contract_from_tool_input,
    validate_contract,
)
from search.retrieval import internal_url
from search.sql_search import _g, _import_model

log = structlog.get_logger()

CONTRACT_VERSION = "b2-v1"
MAX_CONTEXT_RECORDS = 12


class UnknownRetrievalSetError(ValueError):
    """The named retrieval_set_id has no persisted record."""


class FindingNotRetrievedError(ValueError):
    """The (table, pk) finding is not a member of the named retrieval set,
    or could not be resolved to an evidentiary record at all."""


def _normalize_table(table: str) -> str:
    return _ALIASES.get(table, table)


def _cache_key(retrieval_set_id: str, table: str, pk: str) -> str:
    raw = f"{CONTRACT_VERSION}|{retrieval_set_id}|{table}|{pk}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _load_literal_record(session: AsyncSession, table: str, pk: str) -> dict[str, Any] | None:
    """Deterministically load a record's literal content — title, snippet,
    date, amount — straight from the DB. This is the only source of truth
    `source_fact` may ever be grounded in; the model never sees anything we
    didn't put in front of it here."""
    spec, key = _spec_for(table)
    if not spec:
        return None
    model = _import_model(spec.model_path)
    pk_value: Any = int(pk) if isinstance(pk, str) and pk.lstrip("-").isdigit() else pk
    row = (await session.execute(select(model).where(model.id == pk_value))).scalar_one_or_none()
    if row is None:
        return None

    title = spec.title_fn(row)
    snippet = spec.snippet_fn(row)
    date = _g(row, spec.date_col) if spec.date_col else None
    amount = getattr(row, spec.amount_col, None) if spec.amount_col else None
    literal_fact = title.strip()
    if snippet:
        literal_fact += f" — {snippet}"
    if date:
        literal_fact += f" (dated {date})"

    return {
        "table": key, "pk": str(row.id), "title": title, "snippet": snippet,
        "date": date, "amount": amount, "record_type": spec.record_type,
        "literal_fact": literal_fact,
    }


def _build_prompt(finding: dict[str, Any], context: list[dict[str, Any]], allowed_ids_shown: list[tuple[str, str]]) -> tuple[str, str]:
    system = (
        "You are the interpretation layer for Nessus, a Canadian political "
        "due-diligence platform. You analyze exactly ONE retrieved finding at "
        "a time. Hard rules — violations are rejected in code and you will be "
        "asked to correct them:\n"
        "1. source_fact must be 100% literal — only what the record states. "
        "No adjectives implying meaning, no inference, no opinion.\n"
        "2. interpretation, impact, and recommendation must NEVER contain a "
        "buy, sell, proceed, or valuation conclusion. recommendation may only "
        "be a diligence question, a monitoring step, or an expert-review "
        "suggestion — never a deal conclusion.\n"
        "3. Every id in cited_record_ids (top-level and per-claim) MUST come "
        "from the ALLOWED_RECORD_IDS list below. Never invent or guess one.\n"
        "4. Every entry in claims must be labeled observed, inferred, or "
        "speculative, matching how certain that specific claim actually is.\n"
        "5. If confidence is not high, or the evidence is thin, state exactly "
        "why in evidence_limitations — never 'none' or 'n/a'.\n"
        "Call build_interpretation with your answer."
    )
    allowed_str = ", ".join(f"{t}:{p}" for t, p in allowed_ids_shown)
    user = (
        f"FINDING (table={finding['table']}, pk={finding['pk']}):\n"
        f"{json.dumps({k: v for k, v in finding.items() if k != 'literal_fact'}, default=str)}\n"
        f"Literal record content: {finding['literal_fact']}\n\n"
        f"ALLOWED_RECORD_IDS (cite ONLY ids from this list, exactly as written): {allowed_str}\n\n"
        "OTHER RECORDS RETRIEVED IN THE SAME QUERY (context only — the finding "
        "above is what you are interpreting):\n"
        f"{json.dumps(context, default=str)[:8000]}\n\n"
        "Produce the structured interpretation for the FINDING above by calling build_interpretation."
    )
    return system, user


def _fallback_contract(finding: dict[str, Any], reason: str) -> InterpretationContract:
    fid = (finding["table"], str(finding["pk"]))
    fact = finding["literal_fact"] or f"{finding['table']} record {finding['pk']}."
    return InterpretationContract(
        source_fact=fact,
        interpretation="AI interpretation unavailable for this finding.",
        impact="Not assessed automatically — review this record directly before drawing any conclusion.",
        recommendation="Escalate this record to an analyst for manual review.",
        confidence="low",
        evidence_limitations=(
            f"Automated interpretation could not be produced ({reason}); this is a "
            "deterministic placeholder, not an analysis."
        ),
        cited_record_ids=[fid],
        claims=[Claim(text=fact, label="observed", cited_record_ids=[fid])],
        generated_by="template_fallback",
    )


async def _resolve_cited_records(session: AsyncSession, cited: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve each cited (table, pk) to a title + internal link, computed
    fresh on every response so a link is never stale even for a cached result."""
    out = []
    for ref in cited:
        table, pk = str(ref["table"]), str(ref["pk"])
        rec = await _load_literal_record(session, table, pk)
        out.append({
            "table": table, "pk": pk,
            "title": rec["title"] if rec else f"{table}:{pk}",
            "internal_url": internal_url(table, pk),
        })
    return out


async def get_interpretation(session: AsyncSession, interpretation_id: str) -> Interpretation | None:
    return (
        await session.execute(select(Interpretation).where(Interpretation.id == interpretation_id))
    ).scalar_one_or_none()


async def get_interpretation_response(session: AsyncSession, interpretation_id: str) -> dict[str, Any] | None:
    """The reproducibility lookup: re-derive the full response shape for a
    previously stored interpretation by id, without re-calling the model."""
    row = await get_interpretation(session, interpretation_id)
    if row is None:
        return None
    return await _to_response(session, row, from_cache=False)


async def _to_response(session: AsyncSession, row: Interpretation, *, from_cache: bool) -> dict[str, Any]:
    output = dict(row.output)
    output["cited_records"] = await _resolve_cited_records(session, output.get("cited_record_ids", []))
    return {
        "id": row.id,
        "retrieval_set_id": row.retrieval_set_id,
        "table": row.table,
        "pk": row.pk,
        "status": row.status,
        "rejection_reason": row.rejection_reason,
        "model": row.model,
        "provider": row.provider,
        "contract_version": row.contract_version,
        "created_at": row.created_at.isoformat(),
        "from_cache": from_cache,
        **output,
    }


async def _run_with_provider(
    provider: ClaudeInterpretationProvider, system: str, user: str,
    allowed_ids: list[tuple[str, str]], evidence_thin: bool,
) -> tuple[InterpretationContract | None, str, str | None, list[ProviderTurn]]:
    try:
        turn = await provider.call(system, user)
    except ProviderError as exc:
        return None, "degraded", f"provider_error: {exc}", []

    contract = contract_from_tool_input(turn.tool_input, generated_by=provider.name)
    result = validate_contract(contract, allowed_ids, evidence_thin=evidence_thin)
    if result.ok:
        return contract, "ok", None, [turn]

    log.warning("interpretation_validation_failed", errors=result.errors)
    correction = build_correction_message(result.errors)
    try:
        turn2 = await provider.continue_call(system, turn, correction)
    except ProviderError as exc:
        return None, "rejected", f"reprompt_failed after [{'; '.join(result.errors)}]: {exc}", [turn]

    contract2 = contract_from_tool_input(turn2.tool_input, generated_by=provider.name)
    result2 = validate_contract(contract2, allowed_ids, evidence_thin=evidence_thin)
    if result2.ok:
        return contract2, "ok", None, [turn, turn2]

    log.warning("interpretation_validation_failed_after_reprompt", errors=result2.errors)
    return None, "rejected", "validation_failed_after_reprompt: " + "; ".join(result2.errors), [turn, turn2]


async def interpret_finding(
    session: AsyncSession, retrieval_set_id: str, table: str, pk: Any, *, force_refresh: bool = False,
) -> dict[str, Any]:
    retrieval_set_row = await get_retrieval_set(session, retrieval_set_id)
    if retrieval_set_row is None:
        raise UnknownRetrievalSetError(retrieval_set_id)

    allowed_ids = [(_normalize_table(str(t)), str(p)) for t, p in retrieval_set_row.record_ids]
    target = (_normalize_table(table), str(pk))
    membership = validate_citations(allowed_ids, [target])
    if not membership["all_valid"]:
        raise FindingNotRetrievedError(f"{table}:{pk} is not a member of retrieval set {retrieval_set_id}")

    cache_key = _cache_key(retrieval_set_id, target[0], target[1])
    if not force_refresh:
        # Only a successful ("ok") interpretation is cached. A transient
        # provider failure (network blip, rate limit, bad key) is often
        # fixable on the next call — caching it would otherwise lock a
        # finding into a permanent placeholder until someone notices and
        # passes force_refresh.
        cached = (
            await session.execute(
                select(Interpretation)
                .where(Interpretation.cache_key == cache_key, Interpretation.status == "ok")
                .order_by(Interpretation.created_at.desc())
            )
        ).scalars().first()
        if cached is not None:
            return await _to_response(session, cached, from_cache=True)

    finding = await _load_literal_record(session, target[0], target[1])
    if finding is None:
        raise FindingNotRetrievedError(f"{table}:{pk} could not be resolved to an evidentiary record")

    other_ids = [rid for rid in allowed_ids if rid != target][:MAX_CONTEXT_RECORDS]
    context_records = []
    for t, p in other_ids:
        rec = await _load_literal_record(session, t, p)
        if rec:
            context_records.append(rec)

    allowed_ids_shown = [target] + [(c["table"], c["pk"]) for c in context_records]
    evidence_thin = len(allowed_ids) <= 2
    system, user = _build_prompt(finding, context_records, allowed_ids_shown)

    try:
        provider = ClaudeInterpretationProvider()
    except ProviderUnavailable as exc:
        contract = _fallback_contract(finding, f"provider_unavailable: {exc}")
        status, rejection_reason, model_label, provider_name = "degraded", str(exc), "none", "none"
        system_used, user_used = system, user
    else:
        contract, status, rejection_reason, turns = await _run_with_provider(
            provider, system, user, allowed_ids, evidence_thin
        )
        model_label, provider_name = provider.model, provider.name
        if contract is None:
            contract = _fallback_contract(finding, rejection_reason or "unknown_provider_failure")
        # Record the exact prompt(s) actually used for reproducibility.
        if turns:
            system_used = system
            user_used = json.dumps(
                [m for m in turns[-1].messages if m["role"] != "assistant"] or [{"role": "user", "content": user}],
                default=str,
            )
        else:
            system_used, user_used = system, user

    row = Interpretation(
        retrieval_set_id=retrieval_set_id,
        table=target[0], pk=target[1],
        cache_key=cache_key, contract_version=CONTRACT_VERSION,
        provider=provider_name, model=model_label,
        system_prompt=system_used, user_prompt=user_used,
        output=contract.to_dict(), status=status, rejection_reason=rejection_reason,
    )
    session.add(row)
    await session.commit()
    return await _to_response(session, row, from_cache=False)
