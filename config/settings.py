import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "database", "business.db")
MEMORY_DB_PATH = os.path.join(BASE_DIR, "memory", "conversation_store.db")

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Model assignment per agent. Point every agent at the same model
# initially for easier debugging, per the design doc's recommendation.
MODEL_CONFIG = {
    "master_agent": os.environ.get("MASTER_MODEL", "qwen2.5:7b"),
    "text_to_sql_agent": os.environ.get("SQL_MODEL", "qwen2.5:7b"),
    "analyst_agent": os.environ.get("ANALYST_MODEL", "qwen2.5:7b"),
    "thinker_agent": os.environ.get("THINKER_MODEL", "gemma3:4b"),
}

# If no reachable Ollama server is found, the app falls back to
# deterministic rule-based agents so the UI/workflow can still be
# exercised end-to-end without a local LLM running.
DEMO_MODE_FALLBACK = True

MAX_FOLLOW_UP_ITERATIONS = 3
SQL_ROW_LIMIT = 500