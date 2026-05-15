"""Resume parsing: PDF -> text -> structured CandidateProfile."""
import json
import fitz  # PyMuPDF
from app.config import chat, ROUTER_MODEL
from app.schemas import CandidateProfile, Experience, Project


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract raw text from a PDF resume."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text_parts = [page.get_text() for page in doc]
    doc.close()
    return "\n".join(text_parts).strip()


EXTRACTION_PROMPT = """You are a resume parser. Extract structured info from the resume below.

Return ONLY valid JSON matching this exact schema (no markdown fences, no commentary):
{{
  "name": "string",
  "email": "string",
  "phone": "string",
  "location": "string",
  "summary": "2-3 sentence professional summary",
  "skills": ["skill1", "skill2", ...],
  "experience": [
    {{"company": "string", "role": "string", "duration": "string", "bullets": ["bullet 1", "bullet 2"]}}
  ],
  "projects": [
    {{"name": "string", "description": "1-line description", "tech": ["tech1", "tech2"]}}
  ],
  "education": ["Degree, Institution, Year"]
}}

Rules:
- If a field is missing, use empty string or empty list.
- Bullets should be short, achievement-oriented (max 6 per role).
- Skills should be specific technical skills, not soft skills.
- Do NOT invent information.

RESUME TEXT:
\"\"\"
{resume_text}
\"\"\"
"""


def parse_resume(pdf_bytes: bytes) -> CandidateProfile:
    """Parse a PDF resume into a CandidateProfile."""
    text = extract_text_from_pdf(pdf_bytes)
    if not text:
        raise ValueError("Could not extract text from PDF. Is it a scanned image?")

    prompt = EXTRACTION_PROMPT.format(resume_text=text[:8000])
    raw = chat(
        messages=[{"role": "user", "content": prompt}],
        model=ROUTER_MODEL,
        temperature=0.1,
        json_mode=True,
        max_tokens=2048,
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM did not return valid JSON: {e}\nRaw: {raw[:300]}")

    # Coerce into our schema with defensive defaults
    profile = CandidateProfile(
        name=data.get("name", ""),
        email=data.get("email", ""),
        phone=data.get("phone", ""),
        location=data.get("location", ""),
        summary=data.get("summary", ""),
        skills=data.get("skills", []) or [],
        experience=[Experience(**e) for e in (data.get("experience") or [])],
        projects=[Project(**p) for p in (data.get("projects") or [])],
        education=data.get("education", []) or [],
        raw_text=text,
    )
    return profile
