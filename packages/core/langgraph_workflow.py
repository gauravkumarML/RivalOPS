from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from langgraph.graph import StateGraph, END
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .ingestion import ingest_target
from .models import (
    Analysis,
    AnalysisDecisionEnum,
    Briefing,
    ReviewStatusEnum,
    Run,
    RunStatusEnum,
    Snapshot,
    Target,
)


client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None


@dataclass
class WorkflowState:
    target_id: int
    run_id: Optional[int] = None
    snapshot_id: Optional[int] = None
    decision: Optional[str] = None  # "no_change" or "drift"
    drift_score: Optional[float] = None
    analysis_id: Optional[int] = None
    briefing_id: Optional[int] = None


async def node_fetch_history(state: WorkflowState) -> WorkflowState:
    # For now, we just ensure the Target exists; later we can enrich with history.
    with get_session() as session:
        target = session.get(Target, state.target_id)
        if not target:
            raise ValueError(f"Target {state.target_id} not found")

        run = Run(
            target_id=target.id,
            started_at=datetime.utcnow(),
            status=RunStatusEnum.SUCCESS,
            attempt=1,
        )
        session.add(run)
        session.flush()
        state.run_id = run.id
    return state


async def node_scrape(state: WorkflowState) -> WorkflowState:
    snapshot: Snapshot = await ingest_target(state.target_id)
    state.snapshot_id = snapshot.id
    return state


async def _call_llm_analyst(
    *, prompt: str, model: str, temperature: float = 0.0
) -> Dict[str, Any]:
    if client is None:
        raise RuntimeError("OpenAI client not configured (OPENAI_API_KEY missing)")

    response = await client.responses.create(
        model=model,
        input=prompt,
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    # For the OpenAI Responses API, the content is under output[0].content[0].text
    item = response.output[0].content[0]
    if item.type != "output_text":
        raise RuntimeError("Unexpected response type from LLM")
    import json

    return json.loads(item.text)


def _build_analysis_prompt(
    latest_markdown: str,
    history_snippets: List[str],
) -> str:
    history_text = "\n\n---\n\n".join(history_snippets) if history_snippets else "None."
    return f"""
You are a strategic product analyst. Analyze semantic changes on a competitor page.

Return STRICT JSON with the following keys:
- decision: "no_change" or "drift"
- drift_score: float between 0 and 1
- change_types: array of strings (e.g. ["pricing","features","messaging"])
- evidence: array of short quoted snippets with brief explanations
- recommended_followups: array of suggested follow-up questions or checks

Latest page (markdown):
\"\"\"{latest_markdown[:12000]}\"\"\"

Recent history snippets:
\"\"\"{history_text[:6000]}\"\"\"
"""


async def node_analyze(state: WorkflowState) -> WorkflowState:
    if state.snapshot_id is None or state.run_id is None:
        raise ValueError("snapshot_id and run_id required before analysis")

    with get_session() as session:
        snapshot = session.get(Snapshot, state.snapshot_id)
        if not snapshot:
            raise ValueError(f"Snapshot {state.snapshot_id} not found")

        # Fetch a few previous snapshots for context (not heavily used yet).
        history_snippets: List[str] = []
        prev_snaps: List[Snapshot] = (
            session.execute(
                select(Snapshot)
                .where(Snapshot.target_id == snapshot.target_id, Snapshot.id != snapshot.id)
                .order_by(Snapshot.fetched_at.desc())
                .limit(3)
            )
            .scalars()
            .all()
        )
        for s in prev_snaps:
            history_snippets.append(s.content_markdown[:2000])

    prompt = _build_analysis_prompt(snapshot.content_markdown, history_snippets)

    # Cheap-first model
    fast_model = settings.openai_model_fast
    smart_model = settings.openai_model_smart

    result = await _call_llm_analyst(prompt=prompt, model=fast_model)
    decision = result.get("decision", "no_change")
    drift_score = float(result.get("drift_score", 0.0))

    # Escalate if gray zone
    if 0.45 <= drift_score <= 0.65 and smart_model != fast_model:
        result = await _call_llm_analyst(prompt=prompt, model=smart_model)
        decision = result.get("decision", decision)
        drift_score = float(result.get("drift_score", drift_score))

    summary = {
        "change_types": result.get("change_types", []),
        "evidence": result.get("evidence", []),
        "recommended_followups": result.get("recommended_followups", []),
    }

    with get_session() as session:
        analysis = Analysis(
            run_id=state.run_id,
            model=smart_model if 0.45 <= drift_score <= 0.65 else fast_model,
            drift_score=drift_score,
            decision=decision,
            rationale="LLM analysis of semantic changes",
            diff_summary_json=summary,
        )
        session.add(analysis)
        session.flush()
        state.analysis_id = analysis.id
        state.decision = decision
        state.drift_score = drift_score

    return state


async def node_draft_briefing(state: WorkflowState) -> WorkflowState:
    if state.snapshot_id is None or state.analysis_id is None or state.run_id is None:
        raise ValueError("snapshot_id, analysis_id, and run_id required before drafting")

    with get_session() as session:
        snapshot = session.get(Snapshot, state.snapshot_id)
        analysis = session.get(Analysis, state.analysis_id)
        target = session.get(Target, snapshot.target_id) if snapshot else None
        if not snapshot or not analysis or not target:
            raise ValueError("Missing snapshot, analysis, or target")

        summary = analysis.diff_summary_json or {}
        change_types = summary.get("change_types", [])
        evidence = summary.get("evidence", [])
        recommended = summary.get("recommended_followups", [])

    if client is None:
        raise RuntimeError("OpenAI client not configured (OPENAI_API_KEY missing)")

    prompt = f"""
You are an executive briefing generator for a competitive intelligence team.

Write a concise briefing about strategic changes on a competitor page.

Structure:
- title: short, business-readable
- executive_summary: 3-6 bullet points (markdown, high level)
- details_markdown: sections "What changed", "Why it matters", "Recommended actions", "Confidence"
- risk_level: one of "low","medium","high"

Inputs:
- target_label: {target.label if target else ""}
- target_url: {target.url if target else ""}
- drift_score: {state.drift_score}
- change_types: {change_types}
- evidence: {evidence}
- recommended_followups: {recommended}
"""

    response = await client.responses.create(
        model=settings.openai_model_fast,
        input=prompt,
        response_format={"type": "json_object"},
    )
    item = response.output[0].content[0]
    if item.type != "output_text":
        raise RuntimeError("Unexpected response type from LLM")
    import json

    data = json.loads(item.text)

    title = data.get("title") or "Competitor update"
    executive_summary = data.get("executive_summary") or ""
    details_markdown = data.get("details_markdown") or ""
    risk_level = data.get("risk_level") or "medium"

    with get_session() as session:
        briefing = Briefing(
            run_id=state.run_id,
            title=title,
            executive_summary=executive_summary,
            details_markdown=details_markdown,
            risk_level=risk_level,
            review_status=ReviewStatusEnum.PENDING,
        )
        session.add(briefing)
        session.flush()
        state.briefing_id = briefing.id

    return state


async def node_update_run_status(state: WorkflowState) -> WorkflowState:
    """If no drift, mark run and stop; if drift, continue to drafting."""
    if state.run_id is None:
        raise ValueError("run_id is required")

    with get_session() as session:
        run = session.get(Run, state.run_id)
        if not run:
            raise ValueError(f"Run {state.run_id} not found")
        run.ended_at = datetime.utcnow()
        if state.decision == AnalysisDecisionEnum.DRIFT:
            run.status = RunStatusEnum.DRIFT
        elif state.decision == AnalysisDecisionEnum.NO_CHANGE:
            run.status = RunStatusEnum.NO_CHANGE
        else:
            run.status = RunStatusEnum.SUCCESS

    return state


async def node_human_gate(state: WorkflowState) -> WorkflowState:
    """
    Prototype HITL gate inside the workflow:

    - For now, we only ensure the briefing exists and leave it pending.
    - The FastAPI UI will later allow a human to approve/reject and trigger Slack publishing.
    """
    if state.briefing_id is None:
        raise ValueError("briefing_id required for human gate")
    # Nothing else to do synchronously here for v1.
    return state


def build_workflow_graph() -> StateGraph:
    graph = StateGraph(WorkflowState)

    graph.add_node("fetch_history", node_fetch_history)
    graph.add_node("scrape", node_scrape)
    graph.add_node("analyze", node_analyze)
    graph.add_node("update_run_status", node_update_run_status)
    graph.add_node("draft_briefing", node_draft_briefing)
    graph.add_node("human_gate", node_human_gate)

    graph.set_entry_point("fetch_history")
    graph.add_edge("fetch_history", "scrape")
    graph.add_edge("scrape", "analyze")
    graph.add_edge("analyze", "update_run_status")
    # Branch: if no drift, end; if drift, draft briefing then human gate then end.
    graph.add_edge("update_run_status", "draft_briefing")
    graph.add_edge("draft_briefing", "human_gate")
    graph.add_edge("human_gate", END)

    return graph


async def run_workflow_for_target(target_id: int) -> WorkflowState:
    graph = build_workflow_graph()
    app = graph.compile()
    initial = WorkflowState(target_id=target_id)
    final_state: WorkflowState = await app.ainvoke(initial)
    return final_state

