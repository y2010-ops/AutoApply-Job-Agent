"""Pydantic schemas — the shared contract between all agents."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class Experience(BaseModel):
    company: str
    role: str
    duration: str = ""
    bullets: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    description: str = ""
    tech: list[str] = Field(default_factory=list)


class CandidateProfile(BaseModel):
    """Structured representation of the candidate, derived from resume."""
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    raw_text: str = ""  # original resume text, kept for embeddings


class Job(BaseModel):
    """A normalized job posting from any source."""
    id: str
    source: str  # "remoteok" | "hn" | "greenhouse"
    title: str
    company: str
    location: str = ""
    description: str
    url: str
    tags: list[str] = Field(default_factory=list)
    posted_at: Optional[str] = None


class ScoredJob(BaseModel):
    """A job with a match score and reasoning."""
    job: Job
    score: float  # 0..1
    reasoning: str = ""
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)


class TailoredApplication(BaseModel):
    """The final application package for one job."""
    job: Job
    score: float
    reasoning: str
    tailored_bullets: list[str] = Field(default_factory=list)
    cover_letter: str = ""
    answers: dict[str, str] = Field(default_factory=dict)  # common screening Qs
    apply_url: str = ""


class PreferencesInput(BaseModel):
    """User-supplied job preferences."""
    roles: list[str] = Field(default_factory=lambda: ["AI Engineer", "ML Engineer"])
    keywords: list[str] = Field(default_factory=list)
    location: str = "Remote"
    max_jobs: int = 10


class PipelineState(BaseModel):
    """The state object passed through the LangGraph pipeline."""
    profile: Optional[CandidateProfile] = None
    preferences: Optional[PreferencesInput] = None
    raw_jobs: list[Job] = Field(default_factory=list)
    scored_jobs: list[ScoredJob] = Field(default_factory=list)
    applications: list[TailoredApplication] = Field(default_factory=list)
    error: Optional[str] = None
