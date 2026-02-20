def generate_recommendations(validation_result: dict):
    recommendations = []

    # Missing fields
    for field in validation_result.get("missing_fields", []):
        recommendations.append(
            f"Add missing required section: '{field}'."
        )

    # Violations
    for violation in validation_result.get("violations", []):
        if violation.startswith("MIN_LENGTH"):
            recommendations.append(
                "Expand the section to meet minimum length requirements and provide deeper theoretical or methodological detail."
            )

        elif violation.startswith("TYPE"):
            recommendations.append(
                "Correct data types to match schema requirements (e.g., numeric fields must be integers)."
            )

        elif violation.startswith("ENUM"):
            recommendations.append(
                "Ensure values match one of the allowed predefined options."
            )

        elif violation.startswith("REQUIRED_MISSING"):
            recommendations.append(
                "Complete all mandatory structural components of the proposal."
            )

        else:
            recommendations.append(
                f"Review issue: {violation} and adjust proposal accordingly."
            )

    return recommendations