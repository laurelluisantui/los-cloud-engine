"""Environment-based configuration. No hardcoded credentials anywhere."""
import os

DATABASE_URL = os.environ.get(
    "ENGINE_DATABASE_URL", os.environ.get("DATABASE_URL", "sqlite:///./dev.db")
)
INTERNAL_SECRET = os.environ.get("ENGINE_INTERNAL_SECRET", "dev-internal-secret-change-me")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or None
ENGINE_MODEL = os.environ.get("ENGINE_MODEL", "gpt-4o-mini")
MUFFY_MODEL = os.environ.get("MUFFY_MODEL", "gpt-4o")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
ALLOWED_ORIGINS = [url.strip() for url in os.environ.get(
    "ENGINE_ALLOWED_ORIGINS", ""
).split(",") if url.strip()]

DEFAULT_ORG = os.environ.get("ENGINE_DEFAULT_ORG", "laurel")

WORKER_POLL_SECONDS = float(os.environ.get("ENGINE_WORKER_POLL_SECONDS", "2"))
TASK_TIMEOUT_SECONDS = int(os.environ.get("ENGINE_TASK_TIMEOUT_SECONDS", "600"))
MAX_RETRIES = int(os.environ.get("ENGINE_MAX_RETRIES", "3"))

# Repo root (skills/ lives here); skills library is Git-backed at this path.
REPO_ROOT = os.environ.get("ENGINE_REPO_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")
GITHUB_TOKEN = os.environ.get("ENGINE_GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("ENGINE_GITHUB_REPO", "laurelluisantui/los-cloud-engine")
GITHUB_BRANCH = os.environ.get("ENGINE_GITHUB_BRANCH", "main")
# Deployed Postgres must never claim a skill is published without a GitHub commit.
REQUIRE_GITHUB_SYNC = os.environ.get(
    "ENGINE_REQUIRE_GITHUB_SYNC",
    "true" if DATABASE_URL.startswith("postgresql") else "false",
).lower() == "true"
