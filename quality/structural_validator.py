# mcp_server/quality/structural_validator.py

from .schema import ResearchProposalSchema


def structural_validate(proposal: dict):

    required = ResearchProposalSchema["required_fields"]
    critical = ResearchProposalSchema["critical_fields"]

    result = {
        "missing_fields": [],
        "hard_block": False,
        "structural_score": 1.0
    }

    # בדיקת שדות חסרים
    for field in required:
        if field not in proposal or not proposal[field]:
            result["missing_fields"].append(field)

    # הורדת ניקוד
    if result["missing_fields"]:
        missing_ratio = len(result["missing_fields"]) / len(required)
        result["structural_score"] -= missing_ratio
        result["structural_score"] = max(result["structural_score"], 0)

    # Hard Block אם חסר שדה קריטי
    for field in critical:
        if field in result["missing_fields"]:
            result["hard_block"] = True

    return result