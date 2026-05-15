# AutoApply Agent — MVP

> Multi-agent AI system that finds matching jobs, scores them against your resume, and drafts tailored applications. **Human-in-loop apply** — no ToS violations, no auto-submit.

## What it does

1. **Parses your resume** (PDF → structured profile via PyMuPDF + LLM)
2. **Discovers jobs** from RemoteOK + HN "Who's Hiring" (public APIs only)
3. **Ranks matches** using a hybrid: sentence-transformer embeddings + LLM reasoning
4. **Tailors each application** — rewrites bullets, drafts a cover letter, answers common screening questions
5. **You review and apply** — one click opens the posting, one click copies the draft

## Architecture

```
PDF Resume ──► Profile Agent ──┐
                               │
Preferences ──► Discovery ──► Match & Rank ──► Tailor ──► Review UI
                  (HTTP)       (embed+LLM)    (Llama 3.3)
```

Built as a **LangGraph state machine** with 3 nodes (discover → rank → tailor), each wrapping a focused service module.

### Stack
- **FastAPI** — backend + HTML rendering
- **LangGraph** — agent orchestration
- **Groq** — Llama 3.1 8B (routing/extraction) + Llama 3.3 70B (synthesis)
- **sentence-transformers** (`all-MiniLM-L6-v2`) — local embeddings
- **PyMuPDF** — PDF parsing
- **Vanilla JS** frontend — no build step, no framework lock-in

## Setup

```bash
git clone <repo>
cd autoapply
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and paste your GROQ_API_KEY
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000

## Project structure

```
app/
├── main.py              # FastAPI routes
├── config.py            # Env + LLM client
├── schemas.py           # Pydantic models (shared contract)
├── agents/
│   └── pipeline.py      # LangGraph orchestrator
├── services/
│   ├── resume_parser.py # PDF → CandidateProfile
│   ├── job_sources.py   # RemoteOK + HN fetchers
│   ├── matcher.py       # Embedding + LLM scoring
│   └── tailor.py        # Bullet rewriting + cover letter
├── templates/
│   └── index.html
└── static/
    ├── style.css
    └── app.js
```

## Design decisions

**Why human-in-loop?** Auto-submission to LinkedIn/Indeed violates their ToS and produces low-quality spammy applications. This MVP optimizes for the actual bottleneck — tailoring quality at speed — and leaves submission to the human.

**Why hybrid scoring?** Pure keyword/embedding matching misses nuance ("knows ML" vs "shipped production ML"). Pure LLM scoring is expensive and slow. We prune with embeddings, reason with LLM.

**Why no database?** Single-user MVP, in-memory sessions. Add SQLite + auth in v2 when there's a reason to.

## Roadmap (v2 candidates)

- [ ] Greenhouse / Lever / Workday public board adapters
- [ ] Chrome extension for true one-click apply
- [ ] SQLite persistence + application tracking
- [ ] PDF export of tailored resume
- [ ] Feedback loop: track which applications got replies, retrain ranking

## Ethics

This tool exists to help job seekers spend less time on repetitive busywork. It does **not** mass-submit applications, fake credentials, or bypass anti-bot measures. You stay accountable for what gets sent.
