from typing import TypedDict, Any, Optional, List


class AnalystState(TypedDict, total=False):
    # Conversation
    session_id: str
    user_question: str
    messages: List[dict]

    # Routing
    route: str
    user_intent: str
    requires_database: bool
    requires_analysis: bool
    requires_visualization: bool
    needs_clarification: bool
    clarification_question: Optional[str]
    routing_reason: str

    # Database
    schema: dict
    sql_query: Optional[str]
    sql_status: str
    sql_error: Optional[str]
    query_results: Any
    query_columns: List[str]

    # Analysis
    analysis_status: str
    analysis_summary: Optional[str]
    analytical_steps: List[dict]
    key_metrics: List[dict]
    insights: List[str]
    assumptions: List[str]
    limitations: List[str]

    # Thinker
    thinker_answer: Optional[str]

    # Visualization
    chart_required: bool
    chart_type: Optional[str]
    chart_config: Optional[dict]
    chart_figure: Any

    # Conversation continuation / memory
    previous_filters: dict
    pending_question: Optional[str]
    follow_up_question: Optional[str]
    iterations: int

    # Final response
    final_answer: Optional[str]
    progress_log: List[str]