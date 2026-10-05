"""Metric names from the deck. Numbers are hypotheses, not results."""

RETRIEVAL_METRICS = ("recall_at_5", "mrr")
CITATION_METRICS = ("citation_validity", "claim_support")
ROUTING_METRICS = ("macro_f1",)
ABSTENTION_METRICS = ("refusal_rate", "false_refusal_rate")
DOCUMENT_METRICS = ("field_level_f1",)
LATENCY_METRICS = ("p50_ms", "p95_ms")

HYPOTHESIS_TARGETS = {
    "routing_macro_f1": 0.90,
    "citation_validity": 1.0,
    "refusal_rate": 0.85,
    "false_refusal_rate": 0.10,
}

INITIAL_SET_SIZES = {
    "retrieval_questions": 50,
    "routing_queries": 60,
    "uploaded_documents": 15,
}
