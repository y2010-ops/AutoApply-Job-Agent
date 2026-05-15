"""FastAPI app — endpoints + HTML rendering."""
from __future__ import annotations
import json
import uuid
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.schemas import PreferencesInput, CandidateProfile
from app.services.resume_parser import parse_resume
from app.agents.pipeline import run_pipeline

ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))

app = FastAPI(title="AutoApply Agent", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


# Trivial in-memory session store — fine for single-user MVP
SESSIONS: dict[str, dict] = {}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/upload-resume")
async def upload_resume(resume: UploadFile = File(...)):
    if not resume.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Resume must be a PDF.")
    pdf_bytes = await resume.read()
    if len(pdf_bytes) > 5 * 1024 * 1024:
        raise HTTPException(400, "Resume must be < 5MB.")

    try:
        profile = await run_in_threadpool(parse_resume, pdf_bytes)
    except Exception as e:
        raise HTTPException(500, f"Resume parsing failed: {e}")

    session_id = uuid.uuid4().hex[:12]
    SESSIONS[session_id] = {"profile": profile.model_dump()}
    return JSONResponse({
        "session_id": session_id,
        "profile_preview": {
            "name": profile.name,
            "skills_count": len(profile.skills),
            "experience_count": len(profile.experience),
            "projects_count": len(profile.projects),
            "top_skills": profile.skills[:10],
        },
    })


@app.post("/api/run")
async def run(
    session_id: str = Form(...),
    roles: str = Form("AI Engineer, ML Engineer"),
    keywords: str = Form(""),
    location: str = Form("Remote"),
    max_jobs: int = Form(5),
):
    if session_id not in SESSIONS:
        raise HTTPException(404, "Session not found. Upload your resume first.")

    profile = CandidateProfile(**SESSIONS[session_id]["profile"])
    prefs = PreferencesInput(
        roles=[r.strip() for r in roles.split(",") if r.strip()],
        keywords=[k.strip() for k in keywords.split(",") if k.strip()],
        location=location,
        max_jobs=max(1, min(10, max_jobs)),
    )

    state = await run_in_threadpool(run_pipeline, profile, prefs)
    SESSIONS[session_id]["applications"] = [a.model_dump() for a in state.applications]
    SESSIONS[session_id]["scored_count"] = len(state.scored_jobs)

    return JSONResponse({
        "found": len(state.raw_jobs),
        "scored": len(state.scored_jobs),
        "tailored": len(state.applications),
        "applications": [a.model_dump() for a in state.applications],
    })


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    if session_id not in SESSIONS:
        raise HTTPException(404, "Session not found.")
    return JSONResponse(SESSIONS[session_id])


@app.get("/healthz")
async def healthz():
    return {"ok": True}
