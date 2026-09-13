"""
Renders a Plotly figure from a structured chart_config produced by the
Analyst Agent. The LLM never writes chart code — it only picks a
chart_type and columns from an approved set, and this module does the
actual rendering.

Claude-esque visual styling: warm, muted palette, no gridlines clutter,
generous margins.
"""

import plotly.graph_objects as go
import pandas as pd

PALETTE = ["#C15F3C", "#6B8F71", "#5B7DB1", "#B8935F", "#8F6B9E", "#4F9E9E"]

BASE_LAYOUT = dict(
    font=dict(family="'Segoe UI', system-ui, sans-serif", size=13, color="#3D3929"),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=50, r=30, t=50, b=45),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    xaxis=dict(showgrid=False, zeroline=False, linecolor="#D9D3C7"),
    yaxis=dict(showgrid=True, gridcolor="#EDE8DD", zeroline=False),
)


def build_chart(chart_config: dict, rows: list, columns: list):
    """
    chart_config: {
        "chart_type": "line" | "bar" | "stacked_bar" | "scatter" | "histogram",
        "x_column": str,
        "y_columns": [str, ...],
        "title": str,
    }
    rows/columns: raw SQL result set to plot.
    """
    df = pd.DataFrame(rows, columns=columns)
    chart_type = chart_config.get("chart_type", "bar")
    x_col = chart_config.get("x_column")
    y_cols = chart_config.get("y_columns", [])
    title = chart_config.get("title", "")

    # Defensive validation: the chart_type/columns come from an LLM (or a
    # heuristic) and may not actually match the query result — fail with a
    # clear message instead of a raw pandas KeyError deep in trace building.
    if chart_type not in ("line", "bar", "stacked_bar", "scatter", "histogram"):
        raise ValueError(f"Unsupported chart_type: {chart_type}")
    if chart_type != "histogram" and (not x_col or x_col not in df.columns):
        raise ValueError(f"Chart x_column '{x_col}' is not one of the result columns {list(df.columns)}.")
    if not y_cols:
        raise ValueError("Chart config has no y_columns.")
    missing_y = [y for y in y_cols if y not in df.columns]
    if missing_y:
        raise ValueError(f"Chart y_columns {missing_y} are not in the result columns {list(df.columns)}.")

    fig = go.Figure()

    if chart_type == "line":
        for i, y in enumerate(y_cols):
            fig.add_trace(go.Scatter(
                x=df[x_col], y=df[y], mode="lines+markers", name=y,
                line=dict(color=PALETTE[i % len(PALETTE)], width=2.5),
                marker=dict(size=5),
            ))

    elif chart_type == "bar":
        for i, y in enumerate(y_cols):
            fig.add_trace(go.Bar(
                x=df[x_col], y=df[y], name=y,
                marker_color=PALETTE[i % len(PALETTE)],
            ))

    elif chart_type == "stacked_bar":
        for i, y in enumerate(y_cols):
            fig.add_trace(go.Bar(
                x=df[x_col], y=df[y], name=y,
                marker_color=PALETTE[i % len(PALETTE)],
            ))
        fig.update_layout(barmode="stack")

    elif chart_type == "scatter":
        y = y_cols[0]
        fig.add_trace(go.Scatter(
            x=df[x_col], y=df[y], mode="markers", name=y,
            marker=dict(color=PALETTE[0], size=8, opacity=0.75),
        ))

    elif chart_type == "histogram":
        y = y_cols[0]
        fig.add_trace(go.Histogram(x=df[y], marker_color=PALETTE[0]))

    else:
        raise ValueError(f"Unsupported chart_type: {chart_type}")

    fig.update_layout(title=title, **BASE_LAYOUT)
    return fig