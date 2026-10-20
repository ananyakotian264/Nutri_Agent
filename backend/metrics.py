"""Automatic USDA retrieval coverage and relevance summaries."""


def calculate_metrics(rows: list[dict]) -> dict:
    """Summarize retrieval evidence without reporting self-comparison as accuracy."""
    total = len(rows)
    matched = [row for row in rows if row.get("matched_food")]
    scores = [float(row["match_score"]) for row in matched if row.get("match_score") is not None]
    strengths = {key: 0 for key in ("high", "medium", "low")}
    for row in matched:
        strength = row.get("match_strength")
        if strength in strengths:
            strengths[strength] += 1

    return {
        "total_count": total,
        "usda_match_count": len(matched),
        "reference_coverage_percent": 100 * len(matched) / total if total else None,
        "direct_source_count": sum(bool(row.get("reference_verified")) for row in rows),
        "match_strength_counts": strengths,
        "average_match_score": sum(scores) / len(scores) if scores else None,
        "score_count": len(scores),
    }
