"""LangGraph pipeline: profile -> discover -> rank -> tailor.

Each node is a thin wrapper around a service. State is the shared PipelineState.
"""
from __future__ import annotations
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

from app.schemas import (
    PipelineState, CandidateProfile, PreferencesInput, Job, ScoredJob,
    TailoredApplication,
)
from app.services.job_sources import fetch_all_jobs
from app.services.matcher import rank_jobs
from app.services.tailor import tailor_application


# LangGraph wants a TypedDict-compatible state. We mirror PipelineState fields.
class GraphState(TypedDict, total=False):
    profile: Optional[CandidateProfile]
    preferences: Optional[PreferencesInput]
    raw_jobs: list[Job]
    scored_jobs: list[ScoredJob]
    applications: list[TailoredApplication]
    error: Optional[str]


# ---- Nodes ----

def node_discover_jobs(state: GraphState) -> GraphState:
    print("\n▶️ NODE: Discovering jobs...")
    prefs = state.get("preferences")
    if not prefs:
        print("❌ Error: No preferences provided")
        return {"error": "No preferences provided", "raw_jobs": []}
    # Keywords come from explicit input + role names
    keywords = list({*prefs.keywords, *prefs.roles})
    jobs = fetch_all_jobs(keywords, max_jobs=prefs.max_jobs * 2)
    print(f"✅ Discovered {len(jobs)} jobs.")
    return {"raw_jobs": jobs}


def node_rank(state: GraphState) -> GraphState:
    print("\n▶️ NODE: Ranking jobs...")
    profile = state.get("profile")
    jobs = state.get("raw_jobs", [])
    if not profile:
        print("❌ Error: No profile to match against")
        return {"error": "No profile to match against", "scored_jobs": []}
    if not jobs:
        print("⚠️ No jobs to rank.")
        return {"scored_jobs": []}
    ranked = rank_jobs(profile, jobs, top_k_llm=min(10, len(jobs)))
    print(f"✅ Ranked {len(ranked)} jobs.")
    return {"scored_jobs": ranked}


def node_tailor(state: GraphState) -> GraphState:
    print("\n▶️ NODE: Tailoring applications...")
    profile = state.get("profile")
    scored = state.get("scored_jobs", [])
    prefs = state.get("preferences")
    if not profile or not scored:
        print("⚠️ Missing profile or scored jobs, skipping tailor.")
        return {"applications": []}

    # Only tailor the top N — generation is the expensive step
    top_n = min(prefs.max_jobs if prefs else 5, len(scored))
    print(f"✍️ Generating tailored applications for top {top_n} jobs...")
    apps = [tailor_application(profile, s) for s in scored[:top_n]]
    print(f"✅ Successfully tailored {len(apps)} applications.")
    return {"applications": apps}


# ---- Graph construction ----

def build_pipeline():
    """Build and compile the LangGraph pipeline."""
    g = StateGraph(GraphState)
    g.add_node("discover", node_discover_jobs)
    g.add_node("rank", node_rank)
    g.add_node("tailor", node_tailor)

    g.set_entry_point("discover")
    g.add_edge("discover", "rank")
    g.add_edge("rank", "tailor")
    g.add_edge("tailor", END)
    return g.compile()


# Compile once at module load
PIPELINE = build_pipeline()


def run_pipeline(profile: CandidateProfile, prefs: PreferencesInput) -> PipelineState:
    """Public entrypoint. Sync — fine for MVP, FastAPI runs us in a threadpool."""
    initial: GraphState = {
        "profile": profile,
        "preferences": prefs,
        "raw_jobs": [],
        "scored_jobs": [],
        "applications": [],
        "error": None,
    }
    final = PIPELINE.invoke(initial)
    return PipelineState(**final)
