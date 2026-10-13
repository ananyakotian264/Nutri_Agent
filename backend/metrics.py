"""Metrics derived from a user's explicitly verified prediction examples."""

from math import sqrt

NUTRIENTS = {
    "calories": ("predicted_calories", "actual_calories"),
    "protein_g": ("predicted_protein_g", "actual_protein_g"),
    "carbs_g": ("predicted_carbs_g", "actual_carbs_g"),
    "fat_g": ("predicted_fat_g", "actual_fat_g"),
    "fiber_g": ("predicted_fiber_g", "actual_fiber_g"),
}


def _label(value: str) -> str:
    return " ".join(value.casefold().split())


def _classification(rows: list[dict]) -> dict:
    labels = sorted({_label(row[key]) for row in rows for key in ("predicted_food", "actual_food")})
    actuals = [_label(row["actual_food"]) for row in rows]
    predicted = [_label(row["predicted_food"]) for row in rows]
    per_class = []
    for label in labels:
        tp = sum(a == label and p == label for a, p in zip(actuals, predicted))
        fp = sum(a != label and p == label for a, p in zip(actuals, predicted))
        fn = sum(a == label and p != label for a, p in zip(actuals, predicted))
        tn = len(rows) - tp - fp - fn
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        specificity = tn / (tn + fp) if tn + fp else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class.append({"label": label, "true_positive": tp, "false_positive": fp, "false_negative": fn,
                          "true_negative": tn, "support": tp + fn, "precision": precision,
                          "recall": recall, "specificity": specificity,
                          "balanced_accuracy": (recall + specificity) / 2, "f1": f1})

    count = len(rows)
    correct = sum(a == p for a, p in zip(actuals, predicted))
    predicted_counts = [sum(label == guess for guess in predicted) for label in labels]
    actual_counts = [sum(label == actual for actual in actuals) for label in labels]
    mcc_denominator = sqrt(
        (count * count - sum(value * value for value in predicted_counts))
        * (count * count - sum(value * value for value in actual_counts))
    ) if count else 0.0
    mcc_numerator = correct * count - sum(p * a for p, a in zip(predicted_counts, actual_counts))
    weighted = lambda key: sum(item[key] * item["support"] for item in per_class) / count if count else 0.0
    macro = lambda key: sum(item[key] for item in per_class) / len(per_class) if per_class else 0.0
    return {
        "sample_count": count,
        "accuracy": correct / count if count else 0.0,
        "balanced_accuracy": macro("balanced_accuracy"),
        "matthews_correlation_coefficient": mcc_numerator / mcc_denominator if mcc_denominator else None,
        "micro_precision": correct / count if count else 0.0,
        "micro_recall": correct / count if count else 0.0,
        "micro_f1": correct / count if count else 0.0,
        "macro_precision": macro("precision"),
        "macro_recall": macro("recall"),
        "macro_f1": macro("f1"),
        "weighted_precision": weighted("precision"),
        "weighted_recall": weighted("recall"),
        "weighted_f1": weighted("f1"),
        "labels": labels,
        "confusion_matrix": [[sum(a == actual and p == guess for a, p in zip(actuals, predicted))
                              for guess in labels] for actual in labels],
        "per_class": per_class,
    }


def _regression(rows: list[dict], predicted_key: str, actual_key: str) -> dict:
    errors = [float(row[predicted_key]) - float(row[actual_key]) for row in rows]
    absolute = [abs(error) for error in errors]
    actuals = [float(row[actual_key]) for row in rows]
    count = len(rows)
    mae = sum(absolute) / count if count else 0.0
    mse = sum(error * error for error in errors) / count if count else 0.0
    actual_total = sum(abs(value) for value in actuals)
    mape_values = [abs(error / actual) for error, actual in zip(errors, actuals) if actual != 0]
    mean_actual = sum(actuals) / count if count else 0.0
    total_variance = sum((actual - mean_actual) ** 2 for actual in actuals)
    r_squared = 1 - sum(error * error for error in errors) / total_variance if count > 1 and total_variance else None
    sorted_absolute = sorted(absolute)
    median_absolute = (sorted_absolute[(count - 1) // 2] + sorted_absolute[count // 2]) / 2 if count else 0.0
    return {
        "sample_count": count,
        "mae": mae,
        "mse": mse,
        "rmse": sqrt(mse),
        "mean_error": sum(errors) / count if count else 0.0,
        "median_absolute_error": median_absolute,
        "mape": sum(mape_values) / len(mape_values) if mape_values else None,
        "mape_sample_count": len(mape_values),
        "wape": sum(absolute) / actual_total if actual_total else None,
        "r_squared": r_squared,
    }


def calculate_metrics(rows: list[dict]) -> dict:
    return {
        "classification": _classification(rows),
        "nutrition": {name: _regression(rows, *keys) for name, keys in NUTRIENTS.items()},
    }
