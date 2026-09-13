import json
import pandas as pd
from config.settings import MODEL_CONFIG
from prompts.analyst_prompt import ANALYST_AGENT_SYSTEM_PROMPT
from tools.llm_client import call_ollama_json, ollama_is_available


def run_analyst_agent(state: dict) -> dict:
    question = state["user_intent"]
    columns = state.get("query_columns", [])
    rows = state.get("query_results", [])

    if not rows:
        state["analysis_status"] = "NEEDS_MORE_DATA"
        state["analysis_summary"] = "The query returned no rows for this request."
        state["insights"] = []
        state["limitations"] = ["No data matched the given filters."]
        state["key_metrics"] = []
        state["chart_required"] = False
        return state

    if ollama_is_available():
        context = _build_context(question, columns, rows, state)
        try:
            result = call_ollama_json(MODEL_CONFIG["analyst_agent"], ANALYST_AGENT_SYSTEM_PROMPT, context)
            return _apply_result(state, result, columns, rows)
        except Exception as e:
            state.setdefault("progress_log", []).append(f"Analyst Agent LLM call failed, using fallback analyzer ({e}).")

    result = _fallback_analysis(question, columns, rows)
    return _apply_result(state, result, columns, rows)


def _build_context(question: str, columns: list, rows: list, state: dict) -> str:
    preview = rows[:50]
    return (
        f"USER QUESTION:\n{question}\n\n"
        f"SQL QUERY:\n{state.get('sql_query')}\n\n"
        f"COLUMNS: {columns}\n"
        f"ROW COUNT: {len(rows)}\n"
        f"ROWS (up to first 50):\n{json.dumps(preview, default=str)}\n\n"
        f"USER EXPLICITLY ASKED FOR A CHART/VISUALIZATION: "
        f"{state.get('requires_visualization', False)}\n"
        "If true, or if the data has more than one row and a clear category/"
        "time dimension plus a numeric measure, set chart_recommendation.required "
        "to true rather than defaulting to false.\n"
    )


def _apply_result(state: dict, result: dict, columns: list = None, rows: list = None) -> dict:
    state["analysis_status"] = result.get("status", "SUCCESS")
    state["analysis_summary"] = result.get("summary")
    state["key_metrics"] = result.get("key_metrics", [])
    state["insights"] = result.get("insights", [])
    state["limitations"] = result.get("limitations", [])
    state["follow_up_question"] = result.get("follow_up_question")

    chart_rec = result.get("chart_recommendation") or {}
    chart_required = bool(chart_rec.get("required", False))
    chart_config = chart_rec if chart_required else None

    # Safety net: don't rely solely on the (LLM or keyword) analyst deciding
    # to recommend a chart. If the data plainly supports one — more than one
    # row, at least one numeric measure and one category/time dimension — and
    # nothing usable was recommended, derive a chart config ourselves so the
    # user still sees a graph whenever their data can support one.
    if not chart_config and columns and rows:
        chart_config = _infer_chart_config(columns, rows)
        chart_required = chart_config is not None

    state["chart_required"] = chart_required
    state["chart_config"] = chart_config
    return state


def _infer_chart_config(columns: list, rows: list) -> dict | None:
    """Best-effort chart recommendation derived directly from the shape of
    the query result, used whenever the analyst didn't already provide a
    usable one. Mirrors the heuristic in _fallback_analysis."""
    if len(rows) < 2:
        return None
    try:
        df = pd.DataFrame(rows, columns=columns)
    except Exception:
        return None

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    dim_cols = [c for c in df.columns if c not in numeric_cols]
    if not numeric_cols or not dim_cols:
        return None

    dim = dim_cols[0]
    metric = numeric_cols[0]
    is_time_series = dim.lower() in ("month", "year", "date", "sale_date")
    return {
        "required": True,
        "chart_type": "line" if is_time_series else "bar",
        "x_column": dim,
        "y_columns": [metric],
        "title": f"{metric.replace('_', ' ').title()} by {dim.title()}",
    }


# ---------------------------------------------------------------------
# Offline/demo fallback: deterministic pandas-based analysis, per the
# design doc's rule that calculations should be deterministic in
# Python rather than left entirely to the LLM.
# ---------------------------------------------------------------------

def _fallback_analysis(question: str, columns: list, rows: list) -> dict:
    df = pd.DataFrame(rows, columns=columns)
    q = question.lower()

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    dim_cols = [c for c in df.columns if c not in numeric_cols]

    key_metrics = []
    insights = []
    chart_rec = {"required": False, "chart_type": None, "x_column": None, "y_columns": [], "title": ""}

    primary_metric = "total_sales" if "total_sales" in df.columns else (numeric_cols[0] if numeric_cols else None)

    if primary_metric:
        total = float(df[primary_metric].sum())
        key_metrics.append({"name": f"Total {primary_metric.replace('_', ' ')}", "value": round(total, 2), "unit": "currency"})

    if len(df) > 1 and primary_metric and dim_cols:
        dim = dim_cols[0]
        # If it looks like a time series (monthly), compute month-over-month growth
        if dim == "month":
            df_sorted = df.sort_values("month")
            first_val = df_sorted[primary_metric].iloc[0]
            last_val = df_sorted[primary_metric].iloc[-1]
            if first_val:
                growth = (last_val - first_val) / first_val * 100
                insights.append(
                    f"{primary_metric.replace('_', ' ').title()} went from {first_val:,.0f} in "
                    f"{df_sorted['month'].iloc[0]} to {last_val:,.0f} in {df_sorted['month'].iloc[-1]} "
                    f"({growth:+.1f}%)."
                )
                key_metrics.append({"name": "Period growth", "value": round(growth, 1), "unit": "percent"})
            chart_rec = {
                "required": True, "chart_type": "line", "x_column": "month",
                "y_columns": [primary_metric], "title": f"{primary_metric.replace('_', ' ').title()} Over Time",
            }
        else:
            top_row = df.sort_values(primary_metric, ascending=False).iloc[0]
            insights.append(f"'{top_row[dim]}' leads with {top_row[primary_metric]:,.0f} in {primary_metric.replace('_', ' ')}.")
            chart_rec = {
                "required": True, "chart_type": "bar", "x_column": dim,
                "y_columns": [primary_metric], "title": f"{primary_metric.replace('_', ' ').title()} by {dim.title()}",
            }
    elif primary_metric:
        insights.append(f"Total {primary_metric.replace('_', ' ')} across the selected period: {df[primary_metric].sum():,.0f}.")

    summary = insights[0] if insights else f"Returned {len(df)} row(s) for this query."

    return {
        "status": "SUCCESS",
        "summary": summary,
        "key_metrics": key_metrics,
        "insights": insights,
        "calculations": [],
        "limitations": [] if len(df) > 0 else ["No data available for the requested filters."],
        "chart_recommendation": chart_rec,
        "follow_up_question": None,
        "missing_information": [],
    }