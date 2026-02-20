# mcp_server/quality/schema.py

ResearchProposalSchema = {
    "required_fields": [
        "title",
        "research_question",
        "theoretical_background",
        "methodology_type",
        "research_design",
        "sample",
        "data_collection",
        "analysis_plan",
        "expected_contribution",
        "author_role",
        "submission_target"
    ],

    "critical_fields": [
        "research_question",
        "methodology_type",
        "analysis_plan"
    ],

    "threshold": 0.95
}