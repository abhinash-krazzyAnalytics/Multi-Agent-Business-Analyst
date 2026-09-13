"""
Orchestrates the Master -> {Text-to-SQL -> SQL Exec -> Analyst} / Thinker ->
Visualization -> Final Response flow described in the design doc.

Uses LangGraph's StateGraph when available. If LangGraph isn't installed,
falls back to a plain Python function with identical control flow, so this
module works either way.
"""

from typing import Generator, Tuple
import re
from config.settings import MAX_FOLLOW_UP_ITERATIONS
from graph.state import AnalystState
from agents.master_agent import run_master_agent
from agents.text_to_sql_agent import run_text_to_sql_agent
from agents.analyst_agent import run_analyst_agent
from agents.thinker_agent import run_thinker_agent
from tools.sqlite_tool import execute_sql
from tools.chart_tool import build_chart
from tools.memory_tool import save_step, get_last_filters
from tools.schema_tool import get_database_schema, get_database_date_range

_SCHEMA_QUESTION_RE = re.compile(
    r"\b(tables?|columns?)\b(?!\s+(format|view|form))|\bdatabase\s+schema\b|\bwhat\s+data\s+(do you have|is available|exists)\b",
    re.IGNORECASE,
)


def _is_schema_question(question: str) -> bool:
    return bool(_SCHEMA_QUESTION_RE.search(question))


def _describe_schema() -> str:
    schema = get_database_schema()
    lines = [f"The database has {len(schema)} tables:\n"]
    for table, columns in schema.items():
        col_list = ", ".join(name for name, _ in columns)
        lines.append(f"- **{table}** — {col_list}")

    if "sales" in schema:
        date_range = get_database_date_range("sales", "sale_date")
        lines.append(
            f"\nThe `sales` table covers {date_range['min_date']} through {date_range['max_date']}."
        )

    return "\n".join(lines)


def run_workflow_streaming(session_id: str, user_question: str) -> Generator[Tuple[str, dict], None, None]:
    """
    Runs the full workflow for one user turn, yielding
    (progress_message, partial_state) tuples so the UI can show live
    progress, and finally yielding the completed state.
    """
    state: AnalystState = {
        "session_id": session_id,
        "user_question": user_question,
        "previous_filters": get_last_filters(session_id),
        "iterations": 0,
        "progress_log": [],
    }

    yield "Understanding your question…", state

    if _is_schema_question(user_question):
        yield "Checking database schema…", state
        state["route"] = "SCHEMA_INFO"
        state["final_answer"] = _describe_schema()
        save_step(session_id, user_question, "SCHEMA_INFO", summary=state["final_answer"])
        yield "Done", state
        return

    state = run_master_agent(state)

    if state.get("needs_clarification"):
        state["final_answer"] = state.get("clarification_question") or (
            "Could you clarify what you'd like to know?"
        )
        yield "Needs clarification", state
        return

    route = state.get("route")

    if route == "GENERAL_REASONING":
        yield "Thinking it through…", state
        state = run_thinker_agent(state)
        if state.get("thinker_answer") is None:
            state["final_answer"] = "I need more specific information to answer that."
        else:
            state["final_answer"] = state["thinker_answer"]
        save_step(session_id, user_question, route, summary=state["final_answer"])
        yield "Done", state
        return

    # DATA_ANALYSIS or DATA_AND_REASONING: run the SQL -> Analyst loop,
    # allowing the Analyst to request more data up to MAX_FOLLOW_UP_ITERATIONS.
    while True:
        state["iterations"] = state.get("iterations", 0) + 1

        yield "Checking the database schema and generating SQL…", state
        state = run_text_to_sql_agent(state)

        if state.get("sql_status") != "SUCCESS" or not state.get("sql_query"):
            state["final_answer"] = (
                "I couldn't safely generate a query for that: "
                f"{state.get('sql_error', 'missing information.')}"
            )
            yield "Needs more information", state
            save_step(session_id, user_question, route, summary=state["final_answer"])
            return

        yield "Running the query…", state
        try:
            result = execute_sql(state["sql_query"])
            state["query_columns"] = result["columns"]
            state["query_results"] = result["rows"]
        except Exception as e:
            state["final_answer"] = f"The query failed to execute: {e}"
            yield "Query failed", state
            save_step(session_id, user_question, route, sql_query=state["sql_query"], summary=state["final_answer"])
            return

        yield "Analyzing the results…", state
        state = run_analyst_agent(state)

        if state.get("analysis_status") == "NEEDS_MORE_DATA" and state["iterations"] < MAX_FOLLOW_UP_ITERATIONS:
            yield "Needs more data — refining the query…", state
            continue
        break

    # Optionally handle a general-reasoning add-on for DATA_AND_REASONING
    if route == "DATA_AND_REASONING":
        yield "Adding broader context…", state
        state = run_thinker_agent(state)

    # Visualization — built and yielded *before* the final answer text is
    # composed below, so the UI can render the chart while the chat bubble
    # still shows a progress placeholder, instead of only revealing the
    # chart at the same instant as the finished text.
    if state.get("chart_required") and state.get("chart_config") and state.get("query_results"):
        yield "Preparing a chart…", state
        try:
            state["chart_figure"] = build_chart(
                state["chart_config"], state["query_results"], state["query_columns"]
            )
        except Exception as e:
            state.setdefault("limitations", []).append(f"Could not render chart: {e}")
            state["chart_figure"] = None
    else:
        state["chart_figure"] = None

    yield "Chart ready — finishing the summary…", state

    # Compose final answer text
    parts = []
    if state.get("analysis_summary"):
        parts.append(state["analysis_summary"])
    if state.get("insights"):
        parts.append("\n\n**Key findings:**\n" + "\n".join(f"- {i}" for i in state["insights"]))
    if state.get("limitations"):
        parts.append("\n\n*Limitations:* " + "; ".join(state["limitations"]))
    if route == "DATA_AND_REASONING" and state.get("thinker_answer"):
        parts.append("\n\n" + state["thinker_answer"])
    if state.get("follow_up_question"):
        parts.append(f"\n\n{state['follow_up_question']}")

    state["final_answer"] = "".join(parts) if parts else "I wasn't able to produce an answer for that."

    # Carry forward only the filters the Text-to-SQL Agent explicitly says it
    # applied this turn (year/region/category/product/...), rather than
    # regex-guessing from the raw SQL text — a query that merely mentions a
    # 4-digit product code or category name no longer misfires this.
    new_filters = dict(state.get("previous_filters", {}))
    new_filters.update(state.get("detected_filters") or {})
    state["previous_filters"] = new_filters

    save_step(
        session_id, user_question, route,
        sql_query=state.get("sql_query"), filters=new_filters,
        summary=state.get("analysis_summary"),
    )

    yield "Done", state