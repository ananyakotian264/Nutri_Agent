import unittest

from nutrition import normalize_usda_food, rank_usda_foods


class UsdaUnitNormalizationTests(unittest.TestCase):
    def test_kilojoules_are_converted_to_kilocalories_and_macros_to_grams(self):
        food = {
            "description": "Egg, whole, raw, fresh",
            "foodNutrients": [
                {"nutrientName": "Energy", "unitName": "kJ", "value": 599},
                {"nutrientName": "Protein", "unitName": "g", "value": 12.6},
                {"nutrientName": "Carbohydrate, by difference", "unitName": "g", "value": 0.72},
                {"nutrientName": "Total lipid (fat)", "unitName": "g", "value": 9.5},
                {"nutrientName": "Fiber, total dietary", "unitName": "g", "value": 0},
            ],
        }
        result = normalize_usda_food(food)
        self.assertTrue(result["found"])
        self.assertAlmostEqual(result["calories_per_100g"], 143.164, places=2)
        self.assertEqual(result["protein_g_per_100g"], 12.6)
        self.assertEqual(result["carbs_g_per_100g"], 0.72)

    def test_native_kcal_is_preferred_if_usda_returns_both_energy_units(self):
        result = normalize_usda_food({
            "description": "Egg",
            "foodNutrients": [
                {"nutrientName": "Energy", "unitName": "kJ", "value": 599},
                {"nutrientName": "Energy", "unitName": "kcal", "value": 143},
            ],
        })
        self.assertEqual(result["calories_per_100g"], 143)

    def test_newer_atwater_energy_is_preferred_when_present(self):
        result = normalize_usda_food({
            "description": "Egg",
            "foodNutrients": [
                {"nutrientName": "Energy", "unitName": "kJ", "value": 599},
                {"nutrientName": "Energy (Atwater General Factors)", "unitName": "kcal", "value": 143},
            ],
        })
        self.assertEqual(result["calories_per_100g"], 143)

    def test_unknown_energy_unit_is_not_mislabeled_as_kcal(self):
        result = normalize_usda_food({
            "description": "Unknown food",
            "foodNutrients": [{"nutrientName": "Energy", "unitName": "unknown", "value": 599}],
        })
        self.assertFalse(result["found"])

    def test_usda_candidates_are_reranked_by_food_name_relevance(self):
        def candidate(name):
            return {"description": name, "foodNutrients": [
                {"nutrientName": "Energy", "unitName": "kcal", "value": 50},
            ]}

        ranked = rank_usda_foods("banana", [candidate("Apple, raw"), candidate("Banana, raw")])
        self.assertEqual(ranked[0]["food_name"], "Banana, raw")
        self.assertEqual(ranked[0]["match_strength"], "high")
        self.assertGreater(ranked[0]["match_score"], ranked[1]["match_score"])

    def test_material_food_mismatch_is_penalized(self):
        def candidate(name):
            return {"description": name, "foodNutrients": [
                {"nutrientName": "Energy", "unitName": "kcal", "value": 250},
            ]}

        ranked = rank_usda_foods("chicken fry", [
            candidate("Chicken, meatless, breaded, fried"),
            candidate("Chicken, broilers, meat and skin, cooked, fried"),
        ])
        self.assertEqual(ranked[0]["food_name"], "Chicken, broilers, meat and skin, cooked, fried")


if __name__ == "__main__":
    unittest.main()
