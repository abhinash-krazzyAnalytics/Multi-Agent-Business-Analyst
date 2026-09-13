"""
Multi-Agent Business Analyst — Gradio chat UI, styled after Claude.ai.

Run with:  python app.py
"""

import uuid
import gradio as gr
import pandas as pd

from graph.workflow import run_workflow_streaming
from tools.llm_client import ollama_is_available

# --------------------------------------------------------------------------
# Claude-esque visual theme
# --------------------------------------------------------------------------

CLAUDE_CSS = """
:root, .dark, .gradio-container.dark {
    --claude-bg: #FFFFFF;
    --claude-surface: #FFFFFF;
    --claude-border: #E6E0D6;
    --claude-text: #1A1A1A;
    --claude-text-soft: #6B6B6B;
    --claude-accent: #C2694A;
    --claude-accent-soft: #EFDDD3;

    /* Force Gradio's own theme variables to stay light, regardless of
       the browser/OS dark-mode setting (this is what was causing the
       black panels). */
    --body-background-fill: #FFFFFF !important;
    --background-fill-primary: #FFFFFF !important;
    --background-fill-secondary: #FFFFFF !important;
    --block-background-fill: #FFFFFF !important;
    --panel-background-fill: #FFFFFF !important;
    --input-background-fill: #FFFFFF !important;
    --body-text-color: #1A1A1A !important;
    --body-text-color-subdued: #6B6B6B !important;
    --border-color-primary: #E6E0D6 !important;
    --border-color-accent: #E6E0D6 !important;
    --block-border-color: #E6E0D6 !important;
    --neutral-950: #1A1A1A !important;
}

html, body {
    background: #FFFFFF !important;
}

.gradio-container {
    background: var(--claude-bg) !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif !important;
    max-width: 900px !important;
    margin: 0 auto !important;
}

.gradio-container * {
    border-color: var(--claude-border) !important;
}

#app-header {
    padding: 22px 4px 6px 4px;
    border-bottom: none;
}

#app-header h1 {
    font-size: 1.35rem;
    font-weight: 600;
    color: var(--claude-text);
    margin: 0;
    letter-spacing: -0.01em;
}

#app-header p {
    color: var(--claude-text-soft);
    font-size: 0.88rem;
    margin: 4px 0 0 0;
}

#status-pill {
    display: inline-block;
    font-size: 0.72rem;
    padding: 3px 10px;
    border-radius: 999px;
    background: var(--claude-accent-soft);
    color: var(--claude-accent);
    font-weight: 600;
    letter-spacing: 0.01em;
}

/* Chat area */
#chatbot,
#chatbot > div,
#chatbot .bubble-wrap,
#chatbot .wrap,
#chatbot .panel {
    background: #FFFFFF !important;
    border: 1px solid var(--claude-border) !important;
    border-radius: 16px !important;
}

#chatbot .message-wrap {
    padding: 4px 0 !important;
}

#chatbot .message-wrap * {
    color: var(--claude-text) !important;
}

#chatbot .user {
    background: var(--claude-accent) !important;
    color: #FFF7F2 !important;
    border-radius: 18px 18px 4px 18px !important;
    border: none !important;
}

#chatbot .bot {
    background: var(--claude-surface) !important;
    color: var(--claude-text) !important;
    border: 1px solid var(--claude-border) !important;
    border-radius: 18px 18px 18px 4px !important;
}

#chatbot .bot p, #chatbot .bot li {
    font-size: 0.96rem;
    line-height: 1.55;
}

/* Composer */
#composer-row {
    background: var(--claude-surface);
    border: 1px solid var(--claude-border);
    border-radius: 22px;
    padding: 6px 6px 6px 18px;
    box-shadow: 0 1px 2px rgba(61, 57, 41, 0.04);
}

#composer-row textarea {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    font-size: 0.96rem !important;
    color: var(--claude-text) !important;
}

#send-btn {
    background: var(--claude-accent) !important;
    color: white !important;
    border-radius: 16px !important;
    border: none !important;
    min-width: 44px !important;
}

#send-btn:hover {
    background: #A85138 !important;
}

#examples-row button {
    background: var(--claude-surface) !important;
    border: 1px solid var(--claude-border) !important;
    color: var(--claude-text-soft) !important;
    border-radius: 14px !important;
    font-size: 0.82rem !important;
}

/* Accumulating chart/table cards — one per turn that produced a chart or
   table, stacked oldest-first, newest at the bottom, never replaced. */
#charts-column {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.chart-card {
    border: 1px solid var(--claude-border) !important;
    border-radius: 16px !important;
    padding: 8px 10px;
    background: #FFFFFF !important;
}

.chart-card-question {
    font-size: 0.82rem !important;
    color: var(--claude-text-soft) !important;
    margin: 2px 4px 4px 4px !important;
}

.chart-card-plot,
.chart-card-plot > div,
.chart-card-plot .plot-container,
.chart-card-plot .js-plotly-plot,
.chart-card-plot iframe {
    background: #FFFFFF !important;
}

.chart-card-table,
.chart-card-table table,
.chart-card-table th,
.chart-card-table td {
    background: #FFFFFF !important;
    color: var(--claude-text) !important;
    border-color: var(--claude-border) !important;
}

.chart-card-table th {
    font-weight: 600 !important;
}

footer {display: none !important;}
"""

EXAMPLE_QUESTIONS = [
    "What were monthly sales in 2025?",
    "Top 5 products in 2024",
    "Compare sales by region",
    "What are the advantages of a star schema?",
]


def new_session():
    return str(uuid.uuid4())


def respond(user_message, chat_history, charts_history, session_id):
    """
    charts_history is a list of per-turn entries:
      {"question": str, "fig": plotly Figure or None, "table": DataFrame or None}
    Entries accumulate across the whole session — a new turn's chart/table is
    appended as a new card below the previous ones; nothing is ever replaced
    or hidden once shown. Rendered by the @gr.render block below.
    """
    chat_history = chat_history or []
    charts_history = list(charts_history or [])

    if not user_message or not user_message.strip():
        yield chat_history, charts_history, session_id, ""
        return

    chat_history = chat_history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": "…"},
    ]
    yield chat_history, charts_history, session_id, ""

    # Index of the card for *this* turn, once/if one gets created — kept so
    # a table that arrives before the chart (or vice versa) updates the same
    # card instead of creating two.
    this_turn_card_index = None

    def _sync_card(state):
        nonlocal this_turn_card_index
        chart_fig = state.get("chart_figure")
        columns = state.get("query_columns")
        rows = state.get("query_results")
        table_df = pd.DataFrame(rows, columns=columns) if columns and rows else None

        if chart_fig is None and table_df is None:
            return

        if this_turn_card_index is None:
            charts_history.append({"question": user_message, "fig": chart_fig, "table": table_df})
            this_turn_card_index = len(charts_history) - 1
        else:
            card = charts_history[this_turn_card_index]
            if chart_fig is not None:
                card["fig"] = chart_fig
            if table_df is not None:
                card["table"] = table_df

    try:
        final_state = None
        for progress_msg, state in run_workflow_streaming(session_id, user_message):
            final_state = state
            chat_history[-1] = {"role": "assistant", "content": f"_{progress_msg}_"}
            # Reveal the chart/table for this turn as soon as they exist in
            # the streamed state — appended as a new card below any earlier
            # turns' cards, well before the final answer text is composed.
            _sync_card(state)
            yield chat_history, charts_history, session_id, ""

        answer = final_state.get("final_answer", "I wasn't able to produce an answer.")
        chat_history[-1] = {"role": "assistant", "content": answer}
        _sync_card(final_state)  # catch-all in case nothing arrived mid-stream
        yield chat_history, charts_history, session_id, ""

    except Exception:
        import traceback
        error_text = "⚠️ Something went wrong:\n\n```\n" + traceback.format_exc() + "\n```"
        chat_history[-1] = {"role": "assistant", "content": error_text}
        yield chat_history, charts_history, session_id, ""


def use_example(example_text):
    return example_text


with gr.Blocks(title="Business Analyst") as demo:
    session_state = gr.State(new_session())

    with gr.Column(elem_id="app-header"):
        status = "🟢 Connected to local Ollama model" if ollama_is_available() else "○ Demo mode (no local Ollama detected — using offline fallback agents)"
        gr.HTML(f"""
            <h1>Business Analyst</h1>
            <p>Ask about your sales data, or anything else. <span id="status-pill">{status}</span></p>
        """)

    # One card per turn that produced a chart/table, oldest on top, newest
    # appended at the bottom — never overwritten or cleared on the next
    # question. Populated as soon as data's ready in the workflow stream
    # (see respond()), so each card appears before that turn's written
    # answer, not after it.
    charts_state = gr.State([])

    with gr.Column(elem_id="charts-column"):
        @gr.render(inputs=charts_state)
        def render_charts(charts):
            for card in charts:
                if card.get("fig") is None and card.get("table") is None:
                    continue
                with gr.Column(elem_classes="chart-card"):
                    gr.Markdown(f"_{card['question']}_", elem_classes="chart-card-question")
                    if card.get("fig") is not None:
                        gr.Plot(card["fig"], show_label=False, elem_classes="chart-card-plot")
                    if card.get("table") is not None:
                        gr.Dataframe(
                            card["table"], show_label=False, wrap=True,
                            elem_classes="chart-card-table",
                        )

    chatbot = gr.Chatbot(
        elem_id="chatbot",
        height=440,
        show_label=False,
        avatar_images=(None, None),
        layout="bubble",
    )

    with gr.Row(elem_id="examples-row"):
        example_buttons = [gr.Button(q, size="sm") for q in EXAMPLE_QUESTIONS]

    with gr.Row(elem_id="composer-row"):
        msg_box = gr.Textbox(
            placeholder="Ask a question about your sales data…",
            show_label=False,
            scale=9,
            container=False,
            lines=1,
            max_lines=6,
        )
        send_btn = gr.Button("↑", elem_id="send-btn", scale=1)

    msg_box.submit(
        respond,
        inputs=[msg_box, chatbot, charts_state, session_state],
        outputs=[chatbot, charts_state, session_state, msg_box],
    )
    send_btn.click(
        respond,
        inputs=[msg_box, chatbot, charts_state, session_state],
        outputs=[chatbot, charts_state, session_state, msg_box],
    )

    for btn in example_buttons:
        btn.click(use_example, inputs=[btn], outputs=[msg_box])


if __name__ == "__main__":
    demo.queue().launch(css=CLAUDE_CSS)