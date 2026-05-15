"""Job sources. We use public APIs only — no scraping, no ToS issues.

Sources:
- RemoteOK: https://remoteok.com/api  (public JSON feed)
- HN "Who's Hiring": Algolia search API (Hacker News official search)
"""
from __future__ import annotations
import hashlib
import re
import httpx
from typing import Iterable
from app.schemas import Job
import html
from datetime import datetime

REMOTEOK_URL = "https://remoteok.com/api"
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
HEADERS = {"User-Agent": "AutoApplyAgent/0.1 (educational project)"}


def _hash_id(*parts: str) -> str:
    return hashlib.sha1("||".join(parts).encode()).hexdigest()[:12]


def _clean_html(text: str) -> str:
    """Strip HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)  # decode &amp;, &#x2F;, etc.
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_remoteok(keywords: list[str], limit: int = 20) -> list[Job]:
    """Fetch from RemoteOK and filter by keyword match in title/description."""
    try:
        with httpx.Client(timeout=15.0, headers=HEADERS) as client:
            r = client.get(REMOTEOK_URL)
            r.raise_for_status()
            raw = r.json()
    except Exception as e:
        print(f"[fetch_remoteok] failed: {e}")
        return []

    # The first item is metadata; skip it
    postings = [p for p in raw if isinstance(p, dict) and p.get("position")]
    keywords_lc = [k.lower() for k in keywords] if keywords else []

    jobs: list[Job] = []
    for p in postings:
        title = p.get("position", "")
        company = p.get("company", "")
        desc = _clean_html(p.get("description", ""))
        haystack = f"{title} {desc}".lower()

        if keywords_lc and not any(k in haystack for k in keywords_lc):
            continue

        jobs.append(Job(
            id=_hash_id("remoteok", str(p.get("id", ""))),
            source="remoteok",
            title=title,
            company=company,
            location=p.get("location") or "Remote",
            description=desc[:3000],
            url=p.get("url") or p.get("apply_url") or "",
            tags=p.get("tags", []) or [],
            posted_at=p.get("date"),
        ))
        if len(jobs) >= limit:
            break
    return jobs


def _find_whos_hiring_thread_id() -> str | None:
    """Find the most recent 'Ask HN: Who is hiring?' parent thread."""
    try:
        with httpx.Client(timeout=15.0, headers=HEADERS) as client:
            r = client.get(HN_SEARCH_URL, params={
                "query": "Ask HN Who is hiring",
                "tags": "story,author_whoishiring",
                "hitsPerPage": 5,
            })
            r.raise_for_status()
            for hit in r.json().get("hits", []):
                title = (hit.get("title") or "").lower()
                if "who is hiring" in title and "freelancer" not in title:
                    return str(hit.get("objectID"))
    except Exception as e:
        print(f"[hn thread find] failed: {e}")
    return None


def fetch_hn_whos_hiring(keywords: list[str], limit: int = 20) -> list[Job]:
    """Search ONLY inside the latest 'Who is hiring?' thread comments."""
    thread_id = _find_whos_hiring_thread_id()
    if not thread_id:
        return []

    if not keywords:
        keywords = ["AI", "ML", "engineer"]
    query = " ".join(keywords[:3])

    try:
        with httpx.Client(timeout=15.0, headers=HEADERS) as client:
            r = client.get(HN_SEARCH_URL, params={
                "query": query,
                "tags": f"comment,story_{thread_id}",
                "hitsPerPage": 30,
            })
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        print(f"[fetch_hn] failed: {e}")
        return []

    jobs: list[Job] = []
    for hit in data.get("hits", []):
        # Decode HTML entities (&#x2F; -> /, &amp; -> &, etc.)
        text = html.unescape(_clean_html(hit.get("comment_text", "")))
        if len(text) < 150:
            continue

        # First line of a Who's Hiring post is usually: "COMPANY | ROLE | LOCATION | ..."
        first_line = text.split("\n")[0][:200]
        parts = [p.strip() for p in first_line.split("|")]
        company = parts[0][:60] if parts else "HN Post"
        title = parts[1][:80] if len(parts) > 1 else first_line[:80]
        location = parts[2][:60] if len(parts) > 2 else "Various"

        jobs.append(Job(
            id=_hash_id("hn", str(hit.get("objectID", ""))),
            source="hn",
            title=title or "HN Hiring Post",
            company=company or "Unknown",
            location=location,
            description=text[:3000],
            url=f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            tags=[],
            posted_at=hit.get("created_at"),
        ))
        if len(jobs) >= limit:
            break
    return jobs

def fetch_all_jobs(keywords: list[str], max_jobs: int = 20) -> list[Job]:
    """Fetch from all sources and dedupe."""
    per_source = max(5, max_jobs // 2)
    all_jobs = (
        fetch_remoteok(keywords, limit=per_source) +
        fetch_hn_whos_hiring(keywords, limit=per_source)
    )

    seen = set()
    unique: list[Job] = []
    for j in all_jobs:
        key = (j.title.lower().strip(), j.company.lower().strip())
        if key in seen:
            continue
        seen.add(key)
        unique.append(j)
    return unique[:max_jobs]
