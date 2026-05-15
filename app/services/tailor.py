"""Tailor service: rewrite resume bullets + generate cover letter for a job."""
from __future__ import annotations
import json
from app.config import chat, SYNTHESIS_MODEL
from app.schemas import CandidateProfile, ScoredJob, TailoredApplication


TAILOR_PROMPT = """You are an expert career coach. Tailor the candidate's existing experience to the target job.

CANDIDATE PROFILE:
Name: {name}
Summary: {summary}
Skills: {skills}
Top experience:
{experience_block}
Top projects:
{projects_block}

TARGET JOB:
{job_title} at {job_company}
{job_description}

MATCH ANALYSIS:
- Matched skills: {matched_skills}
- Gaps: {missing_skills}

Return ONLY valid JSON:
{{
  "tailored_bullets": [
    "5 resume bullets rewritten/reordered to emphasize fit with this job. Use real achievements from the profile — never invent. Use STAR format, lead with impact, include metrics where the profile has them."
  ],
  "cover_letter": "A 3-paragraph cover letter (180-250 words). Paragraph 1: hook + role interest. Paragraph 2: 2-3 specific proof points from candidate's actual experience matching the job. Paragraph 3: brief close with concrete next step. Sound human, not corporate. No 'I am writing to express my interest' openings. No em dashes.",
  "screening_answers": {{
    "why_this_role": "2-3 sentences",
    "relevant_experience": "2-3 sentences citing specific work",
    "years_experience": "honest estimate based on profile, e.g. '1 year via internship + projects'"
  }}
}}

Rules:
- Never fabricate experience the candidate doesn't have.
- Be specific. "Built RAG pipeline with LangGraph" beats "worked on AI systems."
- Tone: confident, direct, natural. Avoid AI tells (delve, leverage, robust, cutting-edge).
"""


def _format_experience(profile: CandidateProfile) -> str:
    lines = []
    for exp in profile.experience[:3]:
        lines.append(f"- {exp.role} at {exp.company} ({exp.duration})")
        for b in exp.bullets[:4]:
            lines.append(f"    • {b}")
    return "\n".join(lines) or "(none)"


def _format_projects(profile: CandidateProfile) -> str:
    lines = []
    for p in profile.projects[:3]:
        tech = f" [{', '.join(p.tech)}]" if p.tech else ""
        lines.append(f"- {p.name}: {p.description}{tech}")
    return "\n".join(lines) or "(none)"


def tailor_application(profile: CandidateProfile, scored: ScoredJob) -> TailoredApplication:
    job = scored.job
    prompt = TAILOR_PROMPT.format(
        name=profile.name or "Candidate",
        summary=profile.summary,
        skills=", ".join(profile.skills[:25]),
        experience_block=_format_experience(profile),
        projects_block=_format_projects(profile),
        job_title=job.title,
        job_company=job.company,
        job_description=job.description[:2000],
        matched_skills=", ".join(scored.matched_skills) or "n/a",
        missing_skills=", ".join(scored.missing_skills) or "none noted",
    )

    try:
        raw = chat(
            messages=[{"role": "user", "content": prompt}],
            model=SYNTHESIS_MODEL,
            temperature=0.5,
            json_mode=True,
            max_tokens=1500,
        )
        data = json.loads(raw)
    except Exception as e:
        return TailoredApplication(
            job=job, score=scored.score, reasoning=scored.reasoning,
            tailored_bullets=[], cover_letter=f"(Generation failed: {e})",
            apply_url=job.url,
        )

    # Defensive coercion — LLM sometimes returns cover_letter as a list of paragraphs
    cover_letter_raw = data.get("cover_letter", "")
    if isinstance(cover_letter_raw, list):
        cover_letter = "\n\n".join(str(p) for p in cover_letter_raw)
    else:
        cover_letter = str(cover_letter_raw or "")

    # Same defensive treatment for bullets in case the LLM nests them
    bullets_raw = data.get("tailored_bullets", []) or []
    if isinstance(bullets_raw, str):
        bullets = [bullets_raw]
    else:
        bullets = [str(b) for b in bullets_raw if b]

    # And for answers — coerce values to strings
    answers_raw = data.get("screening_answers", {}) or {}
    answers = {k: (str(v) if not isinstance(v, str) else v) for k, v in answers_raw.items()}

    return TailoredApplication(
        job=job,
        score=scored.score,
        reasoning=scored.reasoning,
        tailored_bullets=bullets,
        cover_letter=cover_letter,
        answers=answers,
        apply_url=job.url,
    )
