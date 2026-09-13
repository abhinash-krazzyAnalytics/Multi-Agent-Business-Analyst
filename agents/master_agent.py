import json
from config.settings import MODEL_CONFIG
from prompts.master_prompt import MASTER_AGENT_SYSTEM_PROMPT
from tools.llm_client import call_ollama_json, ollama_is_available
from tools.memory_tool import get_recent_steps

# Keywords used only by the offline/demo fallback router, never by the
# real LLM-backed agent.
_DATA_HINTS = [
    "sales", "revenue", "growth", "region", "category", "product",
    "trend", "compare", "comparison", "average", "avg", "total", "top",
    "kpi", "chart", "graph", "quarter", "month", "year", "2024", "2025",
    "breakdown", "quantity", "units", "transaction", "order", "rank",
    "highest", "lowest", "best", "worst", "distribution", "how many",
    "how much",
]

_REASONING_HINTS = [
    "why", "explain", "advantage", "disadvantage", "recommend",
    "should", "strategy", "best practice", "how does", "what is a",
    "what are the", "define", "pros and cons", "difference between",
]


def run_master_agent(state: dict) -> dict:
    question = state["user_question"]
    history_steps = get_recent_steps(state.get("session_id", "default"), limit=5)

    if ollama_is_available():
        context = _build_context(question, history_steps)
        try:
            result = call_ollama_json(
                MODEL_CONFIG["master_agent"], MASTER_AGENT_SYSTEM_PROMPT, context
            )
            return _apply_routing(state, result)
        except Exception as e:
            state.setdefault("progress_log", []).append(f"Master Agent LLM call failed, using fallback router ({e}).")

    # Demo fallback: broader keyword-based routing that also detects
    # "data + general reasoning" combined requests.
    result = _fallback_route(question)
    return _apply_routing(state, result)


def _build_context(question: str, history_steps: list) -> str:
    history_text = json.dumps(history_steps, indent=2) if history_steps else "None"
    return (
        f"CURRENT USER QUESTION:\n{question}\n\n"
        f"RECENT ANALYTICAL HISTORY (most recent last):\n{history_text}\n"
    )


def _fallback_route(question: str) -> dict:
    q_lower = question.lower()
    needs_data = any(hint in q_lower for hint in _DATA_HINTS)
    needs_reasoning = any(hint in q_lower for hint in _REASONING_HINTS)
    needs_viz = any(w in q_lower for w in ["chart", "graph", "plot", "visualiz"])

    if needs_data and needs_reasoning:
        return {
            "route": "DATA_AND_REASONING",
            "user_intent": question,
            "requires_database": True,
            "requires_analysis": True,
            "requires_visualization": needs_viz,
            "needs_clarification": False,
            "clarification_question": None,
            "reason": "Question references both database metrics and general reasoning/explanation.",
        }

    if needs_data:
        return {
            "route": "DATA_ANALYSIS",
            "user_intent": question,
            "requires_database": True,
            "requires_analysis": True,
            "requires_visualization": needs_viz,
            "needs_clarification": False,
            "clarification_question": None,
            "reason": "Question references sales/business metrics that live in the database.",
        }

    return {
        "route": "GENERAL_REASONING",
        "user_intent": question,
        "requires_database": False,
        "requires_analysis": False,
        "requires_visualization": False,
        "needs_clarification": False,
        "clarification_question": None,
        "reason": "Question does not reference database concepts; treating as general reasoning.",
    }


def _apply_routing(state: dict, result: dict) -> dict:
    state["route"] = result.get("route", "GENERAL_REASONING")
    state["user_intent"] = result.get("user_intent", state.get("user_question"))
    state["requires_database"] = result.get("requires_database", False)
    state["requires_analysis"] = result.get("requires_analysis", False)
    state["requires_visualization"] = result.get("requires_visualization", False)
    state["needs_clarification"] = result.get("needs_clarification", False)
    state["clarification_question"] = result.get("clarification_question")
    state["routing_reason"] = result.get("reason", "")
    return state