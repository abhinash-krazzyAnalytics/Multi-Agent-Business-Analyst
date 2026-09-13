import json
import re
from config.settings import MODEL_CONFIG
from prompts.sql_prompt import SQL_AGENT_SYSTEM_PROMPT
from tools.llm_client import call_ollama_json, ollama_is_available
from tools.schema_tool import schema_as_prompt_text
from tools.sql_validator import validate_sql, SQLValidationError
from tools.schema_tool import schema_as_prompt_text, get_distinct_values


def run_text_to_sql_agent(state: dict) -> dict:
    question = state["user_intent"]
    previous_filters = state.get("previous_filters", {})

    if ollama_is_available():
        context = _build_context(question, previous_filters)
        try:
            result = call_ollama_json(MODEL_CONFIG["text_to_sql_agent"], SQL_AGENT_SYSTEM_PROMPT, context)
            return _apply_result(state, result)
        except Exception as e:
            state.setdefault("progress_log", []).append(f"Text-to-SQL LLM call failed, using fallback SQL builder ({e}).")

    result = _fallback_sql(question, previous_filters)
    return _apply_result(state, result)


def _build_context(question: str, previous_filters: dict) -> str:
    schema_text = schema_as_prompt_text()
    return (
        f"DATABASE SCHEMA:\n{schema_text}\n\n"
        f"PREVIOUS FILTERS (reuse unless the question changes them):\n{json.dumps(previous_filters)}\n\n"
        f"USER QUESTION:\n{question}\n"
    )


def _apply_result(state: dict, result: dict) -> dict:
    status = result.get("status", "NEEDS_CLARIFICATION")
    state["sql_status"] = status
    # Structured filters this turn actually applied (year/region/category/
    # product/etc). Used by the workflow to update conversation memory
    # instead of guessing from the raw SQL text.
    state["detected_filters"] = result.get("detected_filters") or {}

    if status != "SUCCESS" or not result.get("sql"):
        state["sql_query"] = None
        state["sql_error"] = "; ".join(result.get("missing_information", [])) or "Could not generate SQL."
        return state

    try:
        safe_sql = validate_sql(result["sql"])
        state["sql_query"] = safe_sql
        state["sql_error"] = None
    except SQLValidationError as e:
        state["sql_status"] = "NEEDS_CLARIFICATION"
        state["sql_query"] = None
        state["sql_error"] = str(e)

    return state

# ---------------------------------------------------------------------
# Offline/demo fallback: a rule-based SQL composer that handles a much
# wider range of question shapes than a fixed template list — metric
# selection (sum/avg/count/quantity), named entity filters (a specific
# region/category/product mentioned by name), single-year filtering,
# multi-year comparison (grouped by year), and single-dimension
# breakdowns/top-N. It is NOT a general text-to-SQL model — for truly
# open-ended queries, connect Ollama so the real LLM-backed agent runs
# instead of this fallback.
# ---------------------------------------------------------------------

_YEAR_RE = re.compile(r"\b(20\d{2})\b")

_METRIC_PATTERNS = [
    (re.compile(r"\b(average|avg|mean)\b"), "AVG(amount)", "avg_sales"),
    (re.compile(r"\b(quantity|units?( sold)?)\b"), "SUM(quantity)", "total_quantity"),
    (re.compile(r"\b(transactions?|orders?|number of sales|how many sales)\b"), "COUNT(*)", "num_transactions"),
]

_DIMENSION_COLUMNS = ["region", "category", "product"]


def _detect_metric(q: str):
    for pattern, expr, alias in _METRIC_PATTERNS:
        if pattern.search(q):
            return expr, alias
    return "SUM(amount)", "total_sales"


def _detect_named_filters(question: str) -> dict:
    """Finds literal region/category/product names mentioned in the
    question (e.g. 'sales in Europe', 'Running Shoes') using the
    database's own distinct values, rather than a hardcoded list."""
    q_lower = question.lower()
    filters = {}
    for col in _DIMENSION_COLUMNS:
        try:
            values = get_distinct_values("sales", col)
        except Exception:
            values = []
        for v in values:
            if v and v.lower() in q_lower:
                filters[col] = v
                break
    return filters


def _fallback_sql(question: str, previous_filters: dict) -> dict:
    q = question.lower()
    years = sorted(set(_YEAR_RE.findall(question)))
    named_filters = _detect_named_filters(question)
    metric_expr, metric_alias = _detect_metric(q)

    monthly = any(w in q for w in ["month", "trend", "over time"])
    growth_wording = any(w in q for w in ["growth", "grew", "increase", "decrease", "change"])
    compare_years = len(years) >= 2 or (growth_wording and not years)

    top_match = re.search(r"top\s+(\d+)", q)
    top_n = int(top_match.group(1)) if top_match else (5 if re.search(r"\btop\b", q) else None)

    assumptions = []
    where_clauses = []

    if not compare_years:
        year = years[0] if years else (previous_filters.get("year") if not growth_wording else None)
        if year:
            where_clauses.append(f"strftime('%Y', sale_date) = '{year}'")
        elif not years:
            assumptions.append("No year specified; using all available data.")

    for col, value in named_filters.items():
        safe_value = value.replace("'", "''")
        where_clauses.append(f"{col} = '{safe_value}'")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    group_dims = []
    if compare_years:
        group_dims.append("strftime('%Y', sale_date) AS year")
    elif monthly:
        group_dims.append("strftime('%Y-%m', sale_date) AS month")

    breakdown_dim = None
    for col in _DIMENSION_COLUMNS:
        keyword = "categor" if col == "category" else col
        if keyword in q and col not in named_filters:
            breakdown_dim = col
            break
    if breakdown_dim and not monthly:
        group_dims.append(breakdown_dim)
    elif top_n and not group_dims:
        group_dims.append("product")

    if not group_dims:
        sql = f"SELECT {metric_expr} AS {metric_alias} FROM sales {where_sql}".strip()
        explanation = f"Overall {metric_alias.replace('_', ' ')}" + (" for the matched filters." if where_sql else " across all data.")
    else:
        select_cols = ", ".join(group_dims)
        group_by_cols = ", ".join(d.split(" AS ")[0] for d in group_dims)
        order_and_limit = []
        if top_n or breakdown_dim:
            order_and_limit.append(f"ORDER BY {metric_alias} DESC")
        else:
            order_and_limit.append(f"ORDER BY {group_by_cols}")
        if top_n:
            order_and_limit.append(f"LIMIT {top_n}")

        sql = (
            f"SELECT {select_cols}, {metric_expr} AS {metric_alias} "
            f"FROM sales {where_sql} "
            f"GROUP BY {group_by_cols} {' '.join(order_and_limit)}"
        ).strip()
        readable_dims = ", ".join(d.split(" AS ")[-1] for d in group_dims)
        explanation = f"{metric_alias.replace('_', ' ').title()} broken down by {readable_dims}."

    if named_filters:
        assumptions.append(f"Filtered to: {', '.join(f'{k}={v}' for k, v in named_filters.items())}.")

    detected_filters = dict(named_filters)
    if not compare_years:
        year = years[0] if years else (previous_filters.get("year") if not growth_wording else None)
        if year:
            detected_filters["year"] = year

    return {
        "status": "SUCCESS",
        "sql": sql,
        "tables_used": ["sales"],
        "columns_used": [d.split(" AS ")[-1] for d in group_dims] + [metric_alias],
        "assumptions": assumptions,
        "missing_information": [],
        "explanation": explanation,
        "detected_filters": detected_filters,
    }