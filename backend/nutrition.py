"""Normalize USDA FoodData Central nutrient units for the app's display units."""

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
    result = {"found": True, "food_name": food.get("description"), "calories_per_100g": calories}
    for output_key, accepted_names in aliases.items():
        amount = 0.0
        for nutrient in nutrients:
            name = str(nutrient.get("nutrientName") or "").strip().casefold()
            if name in accepted_names:
                normalized = _amount_in_grams(nutrient)
                if normalized is not None:
                    amount = normalized
                    break
        result[output_key] = amount
    return result
