import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    # Sessions only hold UI messages today. Generate a per-process development
    # key when none is configured; shared deployments must set a stable secret.
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'chronoops.db'}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024)))
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    MAX_LOG_CHARS = int(os.getenv("MAX_LOG_CHARS", "16000"))
    MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "5000"))
    MAX_COMPLETION_TOKENS = int(os.getenv("MAX_COMPLETION_TOKENS", "900"))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

