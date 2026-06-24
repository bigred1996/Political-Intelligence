"""Goal B3 — the multi-step research loop (the "deep research" engine).

Sits strictly on top of B1 (`search.retrieval` + `pipeline.citation_registry`)
and B2 (`pipeline.interpretation`): it plans gap-driven queries, retrieves via
B1, interprets each evidentiary finding via B2, checks for remaining gaps,
loops, then synthesizes ACROSS all findings. It does NOT generate the final PDF
(B6) or the intake form (B4); the depth tier is passed in.

Hard cost guardrails are enforced IN CODE here, never via a prompt:
  * the round loop is bounded by `range(...max_rounds)` — the planner's
    `material_gaps_remain` can only stop it early, never extend it;
  * a running `interp_used` counter caps total B2 interpretation calls per run.
Both caps come from `TIERS[depth_tier]` and are stored on the run row so a
later replay does not depend on this table staying constant.

Everything is reproducible from the persisted `ResearchRun` row:
`get_research_run_response` rehydrates the whole trail (rounds, retrieval sets,
interpretations, synthesis) without re-calling any model.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.research_run import ResearchRun
from pipeline.ai_provider import (
    ClaudeResearchPlanner,
    ClaudeSynthesisProvider,
    ProviderError,
    ProviderTurn,
    ProviderUnavailable,
)
from pipeline.citation_registry import get_retrieval_set, save_retrieval_set
from pipeline.interpretation import (
    _load_literal_record,
    get_interpretation_response,
    interpret_finding,
)
from pipeline.interpretation_contract import find_conclusion_language
from pipeline.synthesis_contract import (
    _VALID_CONFIDENCE,
    _VALID_LABELS,
    SynthesisContract,
    SynthesisItem,
    build_correction_message,
    contract_from_tool_input,
    validate_synthesis,
)
from search.retrieval import internal_url, is_evidentiary, retrieve

log = structlog.get_logger()

CONTRACT_VERSION = "b3-v1"

# (max_rounds, max_interpretations) per depth tier. Both are HARD caps enforced
# in code below — the cost guardrail. An unknown tier clamps to "standard".
TIERS: dict[str, tuple[int, int]] = {
    "brief": (2, 8),
    "standard": (4, 20),
    "deep": (6, 36),
}
DEFAULT_TIER = "standard"

MAX_QUERIES_PER_ROUND = 4   # secondary guard: bound queries planned per round
# Retrieval breadth per query. Kept wide on purpose: the final retrieve() ranking
# is pure score-descending, so a dominant exact-match source (contracts) floods
# the head — a small pool would be ALL contracts and `_interleave_by_table` would
# have nothing else to spread the interpretation cap across. A wide pool lets the
# round-robin actually draw on donations/lobbying/bills/etc. The interpretation
# cap (TIERS) still bounds how many of these become B2 calls.
PER_QUERY_LIMIT = 60


def resolve_tier(depth_tier: str | None) -> tuple[str, int, int]:
    tier = (depth_tier or DEFAULT_TIER).lower()
    if tier not in TIERS:
        tier = DEFAULT_TIER
    max_rounds, max_interp = TIERS[tier]
    return tier, max_rounds, max_interp


def _norm_query(q: str) -> str:
    return " ".join((q or "").lower().split())


def _interleave_by_table(
    candidates: list[tuple[str, str, str, str]],
) -> list[tuple[str, str, str, str]]:
    """Round-robin the round's evidentiary candidates across source tables so a
    single dominant source (contracts always outnumber everything) can't consume
    the whole interpretation cap. Dedup by (table, pk) keeping first occurrence —
    candidates arrive in retrieval-score order, so per-table order is preserved.
    Each tuple is (retrieval_set_id, table, pk, title)."""
    per_table: dict[str, list[tuple[str, str, str, str]]] = {}
    seen: set[tuple[str, str]] = set()
    for cand in candidates:
        _, table, pk, _ = cand
        key = (table, pk)
        if key in seen:
            continue
        seen.add(key)
        per_table.setdefault(table, []).append(cand)
    # One pass takes the next item from every non-empty per-table queue, in
    # descending queue size (broadest sources first), until all are drained.
    queues = sorted(per_table.values(), key=len, reverse=True)
    ordered: list[tuple[str, str, str, str]] = []
    while queues:
        queues = [q for q in queues if q]
        for q in queues:
            ordered.append(q.pop(0))
    return ordered


# --- planner --------------------------------------------------------------

class _PlanResult:
    __slots__ = ("queries", "gaps_remain", "error", "calls")

    def __init__(self, queries: list[str], gaps_remain: bool, error: bool, calls: int):
        self.queries = queries
        self.gaps_remain = gaps_remain
        self.error = error
        self.calls = calls


def _plan_system() -> str:
    return (
        "You plan retrieval for a Canadian political/regulatory due-diligence "
        "research run over INTERNAL records only. Given the topic and the "
        "findings already gathered, propose the next round of gap-driven "
        "queries — target what is still unknown, never repeat earlier queries. "
        "If material questions are answered, set material_gaps_remain=false. "
        "Call plan_research_round."
    )


def _plan_user(topic: str, findings: list[dict[str, Any]], prior_queries: list[str]) -> str:
    summary = "\n".join(
        f"- ({f['table']}:{f['pk']}) {f.get('source_fact', '')[:200]}" for f in findings
    ) or "(no findings yet)"
    asked = "; ".join(prior_queries) or "(none)"
    return (
        f"TOPIC: {topic}\n\n"
        f"ALREADY ASKED: {asked}\n\n"
        f"FINDINGS SO FAR:\n{summary}\n\n"
        "Propose the next gap-driven queries by calling plan_research_round."
    )


async def _plan_round(
    planner: ClaudeResearchPlanner | None, topic: str,
    findings: list[dict[str, Any]], prior_queries: list[str],
) -> _PlanResult:
    """Ask the planner for the next round's queries. With no provider (no key)
    this returns a clean stop — the deterministic seed round has already run, so
    a keyless run is exactly one round. A provider error is reported as
    error=True so the orchestrator can degrade and preserve prior rounds."""
    if planner is None:
        return _PlanResult([], False, error=False, calls=0)
    try:
        turn: ProviderTurn = await planner.call(_plan_system(), _plan_user(topic, findings, prior_queries))
    except ProviderError as exc:
        log.warning("research_plan_failed", error=str(exc))
        return _PlanResult([], False, error=True, calls=0)
    data = turn.tool_input or {}
    queries = [str(q) for q in (data.get("queries") or []) if str(q).strip()]
    return _PlanResult(queries, bool(data.get("material_gaps_remain")), error=False, calls=1)


# --- synthesis ------------------------------------------------------------

def _synth_system() -> str:
    return (
        "You synthesize ACROSS many interpreted due-diligence findings into a "
        "structured run result. Hard rules enforced in code: never include a "
        "buy/sell/proceed/valuation conclusion anywhere; cite ONLY finding ids "
        "from ALLOWED_FINDING_IDS; label every theme/risk/opportunity observed, "
        "inferred, or speculative; coverage_summary must state what was searched "
        "and what is thin. Call build_synthesis."
    )


def _synth_user(topic: str, findings: list[dict[str, Any]], allowed_ids: list[tuple[str, str]]) -> str:
    import json

    allowed = ", ".join(f"{t}:{p}" for t, p in allowed_ids)
    body = [
        {
            "id": f"{f['table']}:{f['pk']}",
            "source_fact": f.get("source_fact", ""),
            "interpretation": f.get("interpretation", ""),
            "confidence": f.get("confidence", ""),
        }
        for f in findings
    ]
    return (
        f"TOPIC: {topic}\n\n"
        f"ALLOWED_FINDING_IDS (cite ONLY these, exactly as written): {allowed}\n\n"
        f"INTERPRETED FINDINGS:\n{json.dumps(body, default=str)[:9000]}\n\n"
        "Produce the cross-finding synthesis by calling build_synthesis."
    )


def _fallback_synthesis(findings: list[dict[str, Any]], reason: str) -> SynthesisContract:
    """Deterministic, AI-free synthesis: cluster findings by source table,
    cite only real finding ids, claim nothing beyond what was observed."""
    by_table: dict[str, list[tuple[str, str]]] = {}
    for f in findings:
        by_table.setdefault(str(f["table"]), []).append((str(f["table"]), str(f["pk"])))
    themes = [
        SynthesisItem(
            text=f"{len(ids)} retrieved record(s) from {table}.",
            label="observed",
            finding_ids=ids,
            title=f"{table} records",
        )
        for table, ids in sorted(by_table.items())
    ]
    coverage = (
        f"Deterministic synthesis ({reason}): {len(findings)} finding(s) across "
        f"{len(by_table)} source table(s), clustered by source. No automated "
        "risk, opportunity, or cross-finding assessment was produced — this is a "
        "placeholder, not an analysis. Have an analyst review the findings directly."
    )
    return SynthesisContract(
        themes=themes,
        material_risks=[],
        opportunities=[],
        diligence_questions=["Have these findings been reviewed by an analyst?"],
        overall_confidence="low",
        coverage_summary=coverage,
        generated_by="template_fallback",
    )


def _deterministic_coverage(findings: list[dict[str, Any]]) -> str:
    """A coverage_summary built from the run when the model omits or fouls its
    own — never empty, never conclusion language, so it always passes rule #5."""
    by_table: dict[str, int] = {}
    for f in findings:
        by_table[str(f["table"])] = by_table.get(str(f["table"]), 0) + 1
    parts = ", ".join(f"{t} ({n})" for t, n in sorted(by_table.items()))
    return (
        f"Coverage: {len(findings)} interpreted finding(s) across "
        f"{len(by_table)} source table(s): {parts}. Some model-proposed "
        "synthesis items were dropped during validation; see the evidence "
        "appendix for the full finding set this run is grounded in."
    )


def _salvage_item(
    item: SynthesisItem, allowed: set[tuple[str, str]],
) -> SynthesisItem | None:
    """Sanitize one theme/risk/opportunity: keep only in-run citations, drop the
    item entirely if it cites nothing valid or contains conclusion language,
    coerce an unknown epistemic label to the weakest ('speculative'). Returns
    None to drop the item — every hard rule is still honored item-by-item."""
    ids = [rid for rid in item.finding_ids if rid in allowed]
    if not ids:
        return None
    if find_conclusion_language(item.title) or find_conclusion_language(item.text):
        return None
    label = item.label if item.label in _VALID_LABELS else "speculative"
    return SynthesisItem(text=item.text, label=label, finding_ids=ids, title=item.title)


def _salvage_synthesis(
    contract: SynthesisContract, allowed_ids: list[tuple[str, str]],
    findings: list[dict[str, Any]],
) -> SynthesisContract | None:
    """Recover the model's real analysis when full validation fails: drop only
    the offending items/questions rather than discarding everything. Returns
    None if nothing survives (caller then uses the deterministic placeholder)."""
    allowed = {(str(t), str(p)) for t, p in allowed_ids}
    themes = [s for s in (_salvage_item(i, allowed) for i in contract.themes) if s]
    risks = [s for s in (_salvage_item(i, allowed) for i in contract.material_risks) if s]
    opps = [s for s in (_salvage_item(i, allowed) for i in contract.opportunities) if s]
    if not (themes or risks or opps):
        return None
    dq = [q for q in contract.diligence_questions if q.strip() and not find_conclusion_language(q)]
    conf = contract.overall_confidence if contract.overall_confidence in _VALID_CONFIDENCE else "low"
    cov = (contract.coverage_summary or "").strip()
    if not cov or find_conclusion_language(cov):
        cov = _deterministic_coverage(findings)
    return SynthesisContract(
        themes=themes, material_risks=risks, opportunities=opps,
        diligence_questions=dq or ["Have these findings been reviewed by an analyst?"],
        overall_confidence=conf, coverage_summary=cov, generated_by="claude_salvaged",
    )


def _pick_richer(a: SynthesisContract, b: SynthesisContract) -> SynthesisContract:
    """The re-prompt sometimes returns a thinner (more truncated) object than the
    first attempt — salvage from whichever carried more analysis."""
    return a if len(a.all_items()) >= len(b.all_items()) else b


def _salvage_or_fallback(
    contract: SynthesisContract, findings: list[dict[str, Any]],
    allowed_ids: list[tuple[str, str]], reason: str,
) -> SynthesisContract:
    salvaged = _salvage_synthesis(contract, allowed_ids, findings)
    if salvaged is not None and validate_synthesis(salvaged, allowed_ids).ok:
        log.info(
            "synthesis_salvaged", reason=reason, themes=len(salvaged.themes),
            risks=len(salvaged.material_risks), opportunities=len(salvaged.opportunities),
        )
        return salvaged
    return _fallback_synthesis(findings, reason)


async def _synthesize(
    provider: ClaudeSynthesisProvider | None, topic: str,
    findings: list[dict[str, Any]], allowed_ids: list[tuple[str, str]],
) -> tuple[SynthesisContract, int, bool]:
    """Returns (contract, model_calls, degraded). Reuses validate_synthesis for
    every hard rule; one re-prompt on violation, then item-level salvage of the
    model's analysis, and only a deterministic placeholder if nothing survives."""
    if provider is None or not findings:
        reason = "no findings" if not findings else "provider_unavailable"
        return _fallback_synthesis(findings, reason), 0, provider is not None

    shown = [(f["table"], f["pk"]) for f in findings]
    system, user = _synth_system(), _synth_user(topic, findings, shown)
    try:
        turn = await provider.call(system, user)
    except ProviderError as exc:
        return _fallback_synthesis(findings, f"provider_error: {exc}"), 1, True

    contract = contract_from_tool_input(turn.tool_input, generated_by=provider.name)
    result = validate_synthesis(contract, allowed_ids)
    if result.ok:
        return contract, 1, False

    log.warning("synthesis_validation_failed", errors=result.errors)
    try:
        turn2 = await provider.continue_call(system, turn, build_correction_message(result.errors))
    except ProviderError as exc:
        return _salvage_or_fallback(contract, findings, allowed_ids, f"reprompt_failed: {exc}"), 2, True

    contract2 = contract_from_tool_input(turn2.tool_input, generated_by=provider.name)
    if validate_synthesis(contract2, allowed_ids).ok:
        return contract2, 2, False
    log.warning("synthesis_validation_failed_after_reprompt")
    # Don't throw away a real analysis over a few bad items — salvage the richer
    # of the two attempts; placeholder only if nothing survives validation.
    best = _pick_richer(contract, contract2)
    return _salvage_or_fallback(best, findings, allowed_ids, "validation_failed_after_reprompt"), 2, True


# --- orchestrator ---------------------------------------------------------

async def run_research(
    session: AsyncSession, topic: str, depth_tier: str = DEFAULT_TIER,
    entity: str | None = None,
) -> dict[str, Any]:
    """`entity` (when the run is about one company — i.e. diligence) anchors
    every round's retrieval on that entity's canonical name instead of loose
    keyword/semantic matching, so the report can never attribute another
    company's records to the target. None = thematic research (unchanged)."""
    tier, max_rounds, max_interp = resolve_tier(depth_tier)

    run = ResearchRun(
        topic=topic, depth_tier=tier, contract_version=CONTRACT_VERSION,
        max_rounds=max_rounds, max_interpretations=max_interp, status="running",
    )
    session.add(run)
    await session.commit()

    try:
        planner: ClaudeResearchPlanner | None = ClaudeResearchPlanner()
    except ProviderUnavailable:
        planner = None
    try:
        synth_provider: ClaudeSynthesisProvider | None = ClaudeSynthesisProvider()
    except ProviderUnavailable:
        synth_provider = None

    provider_name = "claude" if (planner or synth_provider) else "none"
    model_label = (planner or synth_provider).model if (planner or synth_provider) else "none"

    rounds: list[dict[str, Any]] = []
    interpretation_ids: list[str] = []         # flat, de-duplicated
    interpreted: dict[tuple[str, str], dict[str, Any]] = {}  # (table,pk) -> B2 response
    seen_queries: set[str] = set()
    interp_used = 0
    model_calls = 0
    planner_failed = False

    round_index = 0
    while round_index < max_rounds:
        round_index += 1

        if round_index == 1:
            queries = [topic]  # deterministic seed round — always search the topic
            gaps_remain = True
        else:
            plan = await _plan_round(
                planner, topic, list(interpreted.values()), sorted(seen_queries)
            )
            model_calls += plan.calls
            if plan.error:
                planner_failed = True
                round_index -= 1  # this round never happened
                break
            if not plan.gaps_remain or not plan.queries:
                round_index -= 1
                break
            queries = plan.queries
            gaps_remain = plan.gaps_remain

        new_queries = [q for q in queries if _norm_query(q) not in seen_queries][:MAX_QUERIES_PER_ROUND]
        if not new_queries:
            round_index -= 1
            break

        round_rec: dict[str, Any] = {
            "round": round_index, "queries": new_queries,
            "retrieval_set_ids": [], "interpretation_ids": [], "coverage_gaps": [],
            "gap_assessment": {"material_gaps_remain": gaps_remain},
        }

        # First retrieve every query in the round and collect its evidentiary
        # candidates; pseudo-hits become coverage gaps (never an interpret call —
        # they'd crash B2). Defer interpretation until all queries are in so the
        # cap can be spent round-robin across source tables, not first-come.
        candidates: list[tuple[str, str, str, str]] = []
        for q in new_queries:
            seen_queries.add(_norm_query(q))
            result = await retrieve(session, q, limit=PER_QUERY_LIMIT, balanced=True, entity=entity)
            saved = await save_retrieval_set(
                session, q, result["results"],
                planner=result["plan"].get("planner", "fallback"),
                embedding_model=result["embedding_model"],
            )
            round_rec["retrieval_set_ids"].append(saved.id)
            for hit in result["results"]:
                table, pk = str(hit["table"]), str(hit["pk"])
                if not is_evidentiary(table):
                    round_rec["coverage_gaps"].append(
                        {"type": "non_evidentiary", "table": table, "pk": pk, "title": hit.get("title", "")}
                    )
                    continue
                candidates.append((saved.id, table, pk, hit.get("title", "")))

        # Interpret round-robin across tables so one dominant source can't eat
        # the whole cap; overflow past the cap is logged as a coverage gap.
        for saved_id, table, pk, _title in _interleave_by_table(candidates):
            key = (table, pk)
            if key in interpreted:
                continue  # already interpreted this run — don't spend the cap twice
            if interp_used >= max_interp:
                round_rec["coverage_gaps"].append(
                    {"type": "interpretation_cap_reached", "table": table, "pk": pk}
                )
                continue
            interp = await interpret_finding(session, saved_id, table, pk)
            interp_used += 1
            if interp.get("from_cache") is False:
                model_calls += 1
            interpreted[key] = interp
            interpretation_ids.append(interp["id"])
            round_rec["interpretation_ids"].append(interp["id"])

        rounds.append(round_rec)

        if interp_used >= max_interp:
            break
        # Nothing found at all in the seed round and no provider to plan gaps:
        # there is nothing to research further.
        if round_index == 1 and not interpreted and planner is None:
            break

    # --- cross-finding synthesis ---
    # allowed_ids is the INTERPRETED set, not the broader retrieval union — it
    # must match exactly what ALLOWED_FINDING_IDS shows the model in
    # `_synth_user` below, so every citation that passes validation also has a
    # corresponding row in the evidence appendix (workspace findings).
    findings = list(interpreted.values())
    allowed_ids = sorted({(str(f["table"]), str(f["pk"])) for f in findings})
    synthesis, synth_calls, synth_degraded = await _synthesize(
        synth_provider, topic, findings, allowed_ids
    )
    model_calls += synth_calls

    if not findings:
        status = "insufficient_evidence"
    elif planner_failed:
        status = "degraded"
    else:
        status = "complete"

    run.status = status
    run.rounds = rounds
    run.rounds_used = len(rounds)
    run.interpretation_ids = interpretation_ids
    run.synthesis = synthesis.to_dict()
    run.provider = provider_name
    run.model = model_label
    run.model_call_count = model_calls
    run.completed_at = datetime.now(timezone.utc)
    await session.commit()

    return await _serialize_run(session, run)


# --- reproducibility / serialization --------------------------------------

async def _resolve_finding(session: AsyncSession, table: str, pk: str) -> dict[str, Any]:
    rec = await _load_literal_record(session, table, pk)
    return {
        "table": table, "pk": pk,
        "title": rec["title"] if rec else f"{table}:{pk}",
        "internal_url": internal_url(table, pk),
    }


async def _resolve_items(
    session: AsyncSession, items: list[dict[str, Any]], allowed: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Resolve each item's finding_ids to fresh internal links, dropping any
    id outside the run's own retrieval-set union, and dropping the WHOLE item
    if nothing it cites survives — an unsupported claim is never rendered as
    fact (see Goal B7)."""
    out = []
    for item in items or []:
        resolved = []
        for ref in item.get("finding_ids", []):
            key = (str(ref["table"]), str(ref["pk"]))
            if key not in allowed:
                log.warning("research_dropped_unsupported_synthesis_item_citation", table=key[0], pk=key[1])
                continue
            resolved.append(await _resolve_finding(session, key[0], key[1]))
        if not resolved:
            log.warning("research_dropped_unsupported_synthesis_item", title=item.get("title") or item.get("text"))
            continue
        out.append({**item, "findings": resolved})
    return out


async def _serialize_run(session: AsyncSession, run: ResearchRun) -> dict[str, Any]:
    """Rehydrate the full reproducible trail for one run — every round's
    queries + retrieval sets, every interpretation, and the synthesis with each
    cited finding resolved to a fresh internal link. No model is called.

    Goal B7: every piece pulled from the stored `rounds`/`synthesis` JSON is
    re-validated against the union of this run's OWN retrieval sets before
    being returned — a direct-DB tamper of either column must not survive a
    read. This is the single root fix: the workspace (`pipeline.diligence`)
    and the frontend both consume this function's output, so fixing it here
    protects both transitively."""
    # Interpretations, loaded once and indexed by id.
    interp_by_id: dict[str, Any] = {}
    for iid in run.interpretation_ids or []:
        resp = await get_interpretation_response(session, iid)
        if resp is not None:
            interp_by_id[iid] = resp

    allowed: set[tuple[str, str]] = set()
    rounds_out = []
    for rd in run.rounds or []:
        sets_out = []
        for sid in rd.get("retrieval_set_ids", []):
            rs = await get_retrieval_set(session, sid)
            sets_out.append({
                "id": sid,
                "query": rs.query if rs else None,
                "result_count": rs.result_count if rs else 0,
            })
            if rs is not None:
                for t, p in rs.record_ids:
                    allowed.add((str(t), str(p)))

        interpretations = []
        for iid in rd.get("interpretation_ids", []):
            interp = interp_by_id.get(iid)
            if interp is None:
                continue
            key = (str(interp.get("table")), str(interp.get("pk")))
            if key not in allowed:
                log.warning("research_dropped_out_of_run_interpretation", table=key[0], pk=key[1])
                continue
            interpretations.append(interp)

        coverage_gaps = []
        for g in rd.get("coverage_gaps", []):
            tbl, pk = g.get("table"), g.get("pk")
            if tbl and pk and (str(tbl), str(pk)) not in allowed:
                log.warning("research_dropped_out_of_run_coverage_gap", table=str(tbl), pk=str(pk))
                continue
            coverage_gaps.append(g)

        rounds_out.append({
            "round": rd.get("round"),
            "queries": rd.get("queries", []),
            "retrieval_sets": sets_out,
            "interpretations": interpretations,
            "coverage_gaps": coverage_gaps,
            "gap_assessment": rd.get("gap_assessment", {}),
        })

    synthesis = dict(run.synthesis or {})
    if synthesis:
        synthesis["themes"] = await _resolve_items(session, synthesis.get("themes", []), allowed)
        synthesis["material_risks"] = await _resolve_items(session, synthesis.get("material_risks", []), allowed)
        synthesis["opportunities"] = await _resolve_items(session, synthesis.get("opportunities", []), allowed)

    return {
        "id": run.id,
        "topic": run.topic,
        "depth_tier": run.depth_tier,
        "status": run.status,
        "contract_version": run.contract_version,
        "max_rounds": run.max_rounds,
        "max_interpretations": run.max_interpretations,
        "rounds_used": run.rounds_used,
        "interpretations_used": len(run.interpretation_ids or []),
        "model": run.model,
        "provider": run.provider,
        "model_call_count": run.model_call_count,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "rounds": rounds_out,
        "synthesis": synthesis,
    }


async def get_research_run(session: AsyncSession, run_id: str) -> ResearchRun | None:
    return (
        await session.execute(select(ResearchRun).where(ResearchRun.id == run_id))
    ).scalar_one_or_none()


async def get_research_run_response(session: AsyncSession, run_id: str) -> dict[str, Any] | None:
    run = await get_research_run(session, run_id)
    if run is None:
        return None
    return await _serialize_run(session, run)


async def list_research_runs(session: AsyncSession, limit: int = 25) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(ResearchRun).order_by(ResearchRun.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": r.id, "topic": r.topic, "depth_tier": r.depth_tier, "status": r.status,
            "rounds_used": r.rounds_used, "max_rounds": r.max_rounds,
            "interpretations_used": len(r.interpretation_ids or []),
            "model_call_count": r.model_call_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
