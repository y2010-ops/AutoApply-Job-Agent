"""Match-and-rank: hybrid embedding similarity + LLM reasoning.

Two-stage:
1. Embed candidate profile + all jobs, compute cosine similarity (cheap, fast)
2. For top-K, ask LLM for nuanced fit assessment (expensive, accurate)
"""
from __future__ import annotations
import json
from functools import lru_cache
import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import chat, ROUTER_MODEL
from app.schemas import CandidateProfile, Job, ScoredJob


@lru_cache(maxsize=1)
def _get_embedder() -> SentenceTransformer:
    """Lazy-load embedder. ~80MB download on first run."""
    print("🤖 Loading embedding model (downloading ~80MB on first run, please wait...)")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    print("✅ Embedding model loaded successfully!")
    return model


def _profile_to_text(profile: CandidateProfile) -> str:
    """Flatten a profile into a single string for embedding."""
    parts = [
        profile.summary,
        "Skills: " + ", ".join(profile.skills),
    ]
    for exp in profile.experience:
        parts.append(f"{exp.role} at {exp.company}: " + " ".join(exp.bullets))
    for proj in profile.projects:
        parts.append(f"Project {proj.name}: {proj.description} ({', '.join(proj.tech)})")
    return "\n".join(parts)


def _job_to_text(job: Job) -> str:
    return f"{job.title} at {job.company}\n{job.description}"


def _cosine_scores(profile_text: str, job_texts: list[str]) -> np.ndarray:
    """Returns array of cosine similarities (0..1)."""
    embedder = _get_embedder()
    vecs = embedder.encode([profile_text] + job_texts, normalize_embeddings=True)
    profile_vec, job_vecs = vecs[0], vecs[1:]
    return job_vecs @ profile_vec  # cosine since normalized


REASONING_PROMPT = """You assess fit between a candidate and a job.

CANDIDATE:
- Skills: {skills}
- Summary: {summary}
- Top project: {top_project}
- Experience level: {experience_level}

JOB:
- Title: {title} @ {company}
- Description: {description}

Return ONLY valid JSON:
{{
  "score": <float 0..1>,
  "reasoning": "<2-3 sentences: why this is or isn't a fit>",
  "matched_skills": ["skill1", "skill2"],
  "missing_skills": ["gap1", "gap2"]
}}

Scoring guide — be strict about seniority:
- If job title says "Staff", "Principal", "Lead", "Senior" and candidate has < 3 years: cap score at 0.4
- If job requires "X+ years experience" and candidate has fewer: cap at 0.45
- 0.80-1.0: Strong fit, candidate clearly qualified AND seniority matches
- 0.60-0.79: Good fit with minor gaps
- 0.40-0.59: Stretch — some relevant skills but real gaps
- Below 0.40: Poor fit, recommend skip
"""

def _estimate_experience_level(profile: CandidateProfile) -> str:
    """Crude heuristic for years of experience based on profile."""
    n_exp = len(profile.experience)
    if n_exp == 0:
        return "Student / new grad (0-1 years)"
    if n_exp <= 2:
        return "Early career (~1 year, internships + projects)"
    if n_exp <= 4:
        return "Mid-level (~2-4 years)"
    return "Senior (5+ years)"


def _llm_score(profile: CandidateProfile, job: Job, embed_sim: float) -> ScoredJob:
    top_project = ""
    if profile.projects:
        p = profile.projects[0]
        top_project = f"{p.name} — {p.description} ({', '.join(p.tech)})"

    prompt = REASONING_PROMPT.format(
        skills=", ".join(profile.skills[:20]),
        summary=profile.summary,
        top_project=top_project or "N/A",
        experience_level=_estimate_experience_level(profile),
        title=job.title,
        company=job.company,
        description=job.description[:1500],
    )

    try:
        raw = chat(
            messages=[{"role": "user", "content": prompt}],
            model=ROUTER_MODEL,
            temperature=0.2,
            json_mode=True,
            max_tokens=400,
        )
        data = json.loads(raw)
        llm_score = float(data.get("score", embed_sim))
        final_score = 0.6 * llm_score + 0.4 * float(embed_sim)
        return ScoredJob(
            job=job,
            score=round(final_score, 3),
            reasoning=data.get("reasoning", ""),
            matched_skills=data.get("matched_skills", []) or [],
            missing_skills=data.get("missing_skills", []) or [],
        )
    except Exception as e:
        return ScoredJob(
            job=job,
            score=round(float(embed_sim), 3),
            reasoning=f"(Embedding-only score; LLM reasoning failed: {e})",
        )

def rank_jobs(profile: CandidateProfile, jobs: list[Job],
              top_k_llm: int = 10) -> list[ScoredJob]:
    """Rank jobs against profile. Returns list sorted by score desc."""
    if not jobs:
        return []

    profile_text = _profile_to_text(profile)
    job_texts = [_job_to_text(j) for j in jobs]
    sims = _cosine_scores(profile_text, job_texts)

    # Stage 1: prune by embedding similarity, keep top_k_llm for reasoning
    pairs = sorted(zip(jobs, sims), key=lambda x: x[1], reverse=True)
    top = pairs[:top_k_llm]
    rest = pairs[top_k_llm:]

    # Stage 2: LLM scoring on the top slice
    scored: list[ScoredJob] = [_llm_score(profile, j, s) for j, s in top]

    # Anything below the cutoff just gets the embedding score, no reasoning
    for job, sim in rest:
        scored.append(ScoredJob(
            job=job, score=round(float(sim), 3),
            reasoning="(Below LLM-scoring threshold)"
        ))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored
