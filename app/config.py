"""Centralized config + LLM client factory."""
import os
from functools import lru_cache
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "llama-3.1-8b-instant")
SYNTHESIS_MODEL = os.getenv("SYNTHESIS_MODEL", "llama-3.3-70b-versatile")


@lru_cache(maxsize=1)
def get_groq() -> Groq:
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY missing. Copy .env.example to .env and fill it in."
        )
    return Groq(api_key=GROQ_API_KEY)


def chat(messages: list[dict], model: str = None, temperature: float = 0.3,
         json_mode: bool = False, max_tokens: int = 2048) -> str:
    """Thin wrapper around Groq chat completions."""
    client = get_groq()
    kwargs = {
        "model": model or SYNTHESIS_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""
