from config.settings import MODEL_CONFIG
from prompts.thinker_prompt import THINKER_AGENT_SYSTEM_PROMPT
from tools.llm_client import call_ollama_json, ollama_is_available


def run_thinker_agent(state: dict) -> dict:
    question = state["user_intent"]

    if ollama_is_available():
        try:
            result = call_ollama_json(MODEL_CONFIG["thinker_agent"], THINKER_AGENT_SYSTEM_PROMPT, question)
            state["thinker_answer"] = result.get("answer")
            state["insights"] = result.get("key_points", [])
            state["limitations"] = result.get("limitations", [])
            return state
        except Exception as e:
            state.setdefault("progress_log", []).append(f"Thinker Agent LLM call failed, using fallback answer ({e}).")

    state["thinker_answer"] = (
        "I don't have a local Ollama model running right now, so I can't reason "
        "freely about this yet — but once you connect a model (see README), the "
        "Thinker Agent will answer general questions like this one directly. "
        "In the meantime, I can help with anything about the sales database."
    )
    state["insights"] = []
    state["limitations"] = ["Running without a connected LLM (demo/offline mode)."]
    return state