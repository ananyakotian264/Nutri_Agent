"""Normalize USDA FoodData Central nutrient units for the app's display units."""

import math
import re

KILOJOULES_PER_KILOCALORIE = 4.184


def _amount_in_grams(nutrient: dict) -> float | None:
    value = nutrient.get("value")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    unit = str(nutrient.get("unitName") or "").strip().casefold()
    if unit in {"g", "gram", "grams"}:
        return value
    if unit in {"mg", "milligram", "milligrams"}:
        return value / 1000
    return None


def normalize_usda_food(food: dict) -> dict:
    """Return per-100g values, always kcal and grams, or a safe unusable result."""
    nutrients = food.get("foodNutrients") or []
    energy_candidates = []
    for nutrient in nutrients:
        name = str(nutrient.get("nutrientName") or "").strip().casefold()
        name_priority = {
            "energy (atwater general factors)": 0,
            "metabolizable energy (atwater general factor)": 0,
            "energy (atwater specific factors)": 1,
            "metabolizable energy (atwater specific factor)": 1,
            "energy": 2,
        }.get(name)
        if name_priority is None:
            continue
        try:
            value = float(nutrient.get("value"))
        except (TypeError, ValueError):
            continue
        unit = str(nutrient.get("unitName") or "").strip().casefold()
        if unit in {"kcal", "kilocalorie", "kilocalories"}:
            unit_priority = 0
        elif unit in {"kj", "kilojoule", "kilojoules"}:
            unit_priority = 1
        else:
            continue
        energy_candidates.append((name_priority, unit_priority, value))

    if not energy_candidates:
        return {"found": False, "error": "USDA match did not provide energy in a recognized unit."}

    # Prefer newer Atwater values and native kcal values when multiple are supplied.
    _, unit_priority, energy_value = min(energy_candidates, key=lambda candidate: (candidate[0], candidate[1]))
    calories = energy_value if unit_priority == 0 else energy_value / KILOJOULES_PER_KILOCALORIE
    aliases = {
        "protein_g_per_100g": {"protein"},
        "carbs_g_per_100g": {"carbohydrate, by difference", "carbohydrate"},
        "fat_g_per_100g": {"total lipid (fat)", "total lipid"},
        "fiber_g_per_100g": {"fiber, total dietary", "fiber"},
    }
    portions = []
    for portion in food.get("foodPortions", []):
        try:
            gram_weight = float(portion.get("gramWeight"))
        except (AttributeError, TypeError, ValueError):
            continue
        if gram_weight <= 0:
            continue
        measure_unit = portion.get("measureUnit") or {}
        portions.append({
            "description": portion.get("modifier") or measure_unit.get("name"),
            "amount": portion.get("amount"),
            "gram_weight": gram_weight,
        })

    result = {
        "found": True,
        "food_name": food.get("description"),
        "fdc_id": food.get("fdcId"),
        "data_type": food.get("dataType"),
        "calories_per_100g": calories,
        "portions": portions,
    }
    for output_key, accepted_names in aliases.items():
        amount = None
        for nutrient in nutrients:
            name = str(nutrient.get("nutrientName") or "").strip().casefold()
            if name in accepted_names:
                normalized = _amount_in_grams(nutrient)
                if normalized is not None:
                    amount = normalized
                    break
        result[output_key] = amount
    return result


def _words(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", str(value).casefold())
    ignored = {"a", "an", "the", "of", "and", "with", "fresh", "raw"}
    synonyms = {"fried": "fry", "fries": "fry", "frying": "fry", "baked": "bake", "roasted": "roast", "grilled": "grill"}
    return {synonyms.get(word, word) for word in words if word not in ignored and not word.isdigit()}


def _char_ngrams(value: str) -> dict[str, float]:
    normalized = " ".join(sorted(_words(value)))
    padded = f"  {normalized}  "
    counts: dict[str, float] = {}
    for size in (2, 3, 4):
        for start in range(max(0, len(padded) - size + 1)):
            gram = padded[start:start + size]
            counts[gram] = counts.get(gram, 0.0) + 1.0
    return counts


def rank_usda_foods(query: str, foods: list[dict]) -> list[dict]:
    """Rank USDA candidates with query coverage and character TF-IDF similarity.

    The score is a retrieval relevance heuristic, not a calibrated probability
    or measured accuracy. It helps rerank a small USDA result set without
    pretending we have labeled food-match training data.
    """
    candidates = []
    for food in foods:
        normalized = normalize_usda_food(food)
        if not normalized.get("found"):
            continue
        candidates.append((food, normalized))
    if not candidates:
        return []

    query_words = _words(query)
    query_ngrams = _char_ngrams(query)
    docs = [_char_ngrams(food.get("description") or "") for food, _ in candidates]
    document_frequency: dict[str, int] = {}
    for document in docs:
        for gram in document:
            document_frequency[gram] = document_frequency.get(gram, 0) + 1

    total_docs = len(docs) + 1

    def tfidf(counts: dict[str, float]) -> dict[str, float]:
        vector = {
            gram: (1 + math.log(count)) * (1 + math.log(total_docs / (document_frequency.get(gram, 0) + 1)))
            for gram, count in counts.items()
        }
        norm = math.sqrt(sum(value * value for value in vector.values()))
        return {gram: value / norm for gram, value in vector.items()} if norm else {}

    query_vector = tfidf(query_ngrams)
    ranked = []
    for (food, normalized), grams in zip(candidates, docs):
        description = str(food.get("description") or "")
        candidate_words = _words(description)
        overlap = len(query_words & candidate_words)
        precision = overlap / len(candidate_words) if candidate_words else 0.0
        recall = overlap / len(query_words) if query_words else 0.0
        token_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        candidate_vector = tfidf(grams)
        char_similarity = sum(value * candidate_vector.get(gram, 0.0) for gram, value in query_vector.items())
        score = 0.55 * token_f1 + 0.45 * char_similarity
        # These descriptors can change the food materially, so do not let a
        # generic shared word (such as "chicken") hide a diet/state mismatch.
        critical_mismatch = {"meatless", "vegetarian", "vegan", "canned", "frozen", "smoked"} & candidate_words - query_words
        score = max(0.0, score - min(0.6, 0.3 * len(critical_mismatch)))
        ranked.append((score, food, normalized))

    ranked.sort(key=lambda item: (item[0], item[1].get("dataType") in {"Foundation", "SR Legacy"}), reverse=True)
    result = []
    for index, (score, food, normalized) in enumerate(ranked):
        next_score = ranked[index + 1][0] if index + 1 < len(ranked) else 0.0
        margin = score - next_score
        strength = "high" if score >= 0.72 and margin >= 0.05 else "medium" if score >= 0.42 else "low"
        result.append({**normalized, "match_score": round(score * 100, 1), "match_strength": strength,
                       "match_margin": round(margin * 100, 1)})
    return result
