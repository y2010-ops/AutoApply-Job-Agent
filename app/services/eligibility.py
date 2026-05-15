"""Eligibility filter — applied BEFORE expensive LLM scoring.

Drops jobs that violate hard constraints (YOE, location, visa) so we don't
waste tokens scoring jobs the candidate can't realistically apply to.

This is a rule-based pre-filter. The LLM scorer afterwards handles nuance
(does the candidate's project stack actually match? how strong is the fit?).
"""
from __future__ import annotations
import re
from app.schemas import Job


# Regions that commonly appear as exclusionary location filters
US_ONLY_PATTERNS = [
    r"\bus(a)?\s*only\b",
    r"\bunited states only\b",
    r"\bmust be (located )?in (the )?us\b",
    r"\bus citizen(ship)?\b",
    r"\bus-based\b",
    r"\bremote\s*\(\s*us\s*\)",
    r"\bremote\s*-?\s*us\b",
    r"\bauthori[sz]ed to work in (the )?us\b",
]
EU_ONLY_PATTERNS = [
    r"\beu(rope)?\s*only\b",
    r"\bmust be (located )?in (the )?(eu|europe)\b",
    r"\bremote\s*\(\s*eu(rope)?\s*\)",
]
UK_ONLY_PATTERNS = [
    r"\buk\s*only\b",
    r"\bmust be (located )?in (the )?uk\b",
    r"\bright to work in (the )?uk\b",
]


def _extract_years_required(text: str) -> int | None:
    """Parse minimum years of experience from job description.

    Returns the *lowest* explicit year requirement found, or None.
    Conservative: only matches clear patterns like '5+ years', '5-7 years',
    'minimum 5 years'. Won't match '5 year contract'.
    """
    if not text:
        return None

    patterns = [
        # "5-7 years experience"
        r"(\d{1,2})\+?\s*[-–to]+\s*\d{1,2}\s*years?(?:\s+of)?\s+(?:experience|exp\b)",
        # "9+ years of software engineering experience" / "5+ years experience"
        r"(\d{1,2})\+\s*years?(?:\s+of(?:\s+[\w\s/,&-]{0,80}?)?)?\s+(?:experience|exp\b)",
        # "7+ years building/developing/leading..." (action verbs)
        r"(\d{1,2})\+\s*years?\s+(?:building|developing|leading|designing|engineering|architecting|working)",
        # "Minimum 5 years" / "at least 5 years"
        r"minimum\s+(?:of\s+)?(\d{1,2})\s+years?",
        r"at least\s+(\d{1,2})\s+years?",
        # "5 years of relevant experience"
        r"(\d{1,2})\s+years?\s+(?:of\s+)?(?:relevant\s+|professional\s+|industry\s+)?experience",
    ]

    candidates: list[int] = []
    text_lc = text.lower()
    for pat in patterns:
        for m in re.finditer(pat, text_lc):
            try:
                n = int(m.group(1))
                if 1 <= n <= 25:  # sanity bound
                    candidates.append(n)
            except (ValueError, IndexError):
                continue

    return min(candidates) if candidates else None


def _detect_location_constraint(text: str) -> str | None:
    """Return 'US', 'EU', 'UK', or None for the strictest geo restriction found."""
    if not text:
        return None
    text_lc = text.lower()
    for pat in US_ONLY_PATTERNS:
        if re.search(pat, text_lc):
            return "US"
    for pat in EU_ONLY_PATTERNS:
        if re.search(pat, text_lc):
            return "EU"
    for pat in UK_ONLY_PATTERNS:
        if re.search(pat, text_lc):
            return "UK"
    return None


def _candidate_region(candidate_location: str) -> str:
    """Map a free-form candidate location string to a region code."""
    loc = (candidate_location or "").lower()
    if any(k in loc for k in ["india", "bangalore", "bengaluru", "indore", "delhi", "mumbai", "hyderabad"]):
        return "INDIA"
    if any(k in loc for k in ["usa", "united states", "us", "new york", "nyc", "san francisco", "sf",
                              "bay area", "california", "texas", "boston", "seattle"]):
        return "US"
    if any(k in loc for k in ["uk", "london", "manchester", "edinburgh", "england", "scotland"]):
        return "UK"
    if any(k in loc for k in ["berlin", "amsterdam", "paris", "madrid", "munich", "germany",
                              "france", "spain", "netherlands", "eu", "europe"]):
        return "EU"
    if "remote" in loc:
        return "REMOTE"
    return "OTHER"


class EligibilityResult:
    """Outcome of running eligibility checks for one job."""
    __slots__ = ("eligible", "reasons", "warnings", "years_required")

    def __init__(self):
        self.eligible: bool = True
        self.reasons: list[str] = []   # hard fails -> not eligible
        self.warnings: list[str] = []  # soft concerns -> still eligible but flagged
        self.years_required: int | None = None


def check_eligibility(
    job: Job,
    candidate_years: float,
    candidate_location: str,
    open_to_remote: bool = True,
    yoe_slack: int = 1,
) -> EligibilityResult:
    """Apply hard filters. yoe_slack lets candidate apply to roles up to N years above their level."""
    result = EligibilityResult()
    full_text = f"{job.title}\n{job.location}\n{job.description}"

    # ---- YOE check ----
    yoe_required = _extract_years_required(full_text)
    result.years_required = yoe_required
    if yoe_required is not None:
        if yoe_required - candidate_years > yoe_slack:
            result.eligible = False
            result.reasons.append(
                f"Requires {yoe_required}+ years; candidate has ~{candidate_years:g}"
            )
        elif yoe_required > candidate_years:
            result.warnings.append(
                f"Requires {yoe_required}+ years; stretch for candidate (~{candidate_years:g})"
            )

    # ---- Location / work authorization ----
    geo_restriction = _detect_location_constraint(full_text)
    cand_region = _candidate_region(candidate_location)

    if geo_restriction and cand_region != geo_restriction:
        # Special-case: 'Remote (US)' might still allow non-US if not strictly enforced,
        # but the conservative default is to filter out — candidate can override in UI.
        if not (open_to_remote and cand_region == "REMOTE"):
            result.eligible = False
            result.reasons.append(
                f"Restricted to {geo_restriction}; candidate is in {cand_region}"
            )

    # ---- Senior-level keyword check (catches 'Staff', 'Principal' even without explicit years) ----
    title_lc = job.title.lower()
    senior_titles = ["staff engineer", "principal engineer", "principal scientist",
                     "head of", "director of", "vp of", "chief "]
    if any(t in title_lc for t in senior_titles) and candidate_years < 7:
        if result.eligible:  # don't double-fail
            result.eligible = False
            result.reasons.append(
                f"Senior-level title ('{job.title}') typically needs 7+ years; candidate has ~{candidate_years:g}"
            )

    return result


def filter_eligible(
    jobs: list[Job],
    candidate_years: float,
    candidate_location: str,
    open_to_remote: bool = True,
    yoe_slack: int = 1,
) -> tuple[list[Job], list[tuple[Job, EligibilityResult]]]:
    """Split jobs into (eligible, filtered_out_with_reasons).

    Both lists are returned so the UI can show 'we filtered out N jobs because...'
    rather than silently dropping them.
    """
    eligible: list[Job] = []
    filtered: list[tuple[Job, EligibilityResult]] = []

    for job in jobs:
        res = check_eligibility(
            job, candidate_years, candidate_location,
            open_to_remote=open_to_remote, yoe_slack=yoe_slack,
        )
        if res.eligible:
            eligible.append(job)
        else:
            filtered.append((job, res))
    return eligible, filtered
