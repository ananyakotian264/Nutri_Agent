import unittest

from orchestrator import Agent


class UsdaScalingTests(unittest.TestCase):
    def setUp(self):
        self.reference = {
            "found": True,
            "match_strength": "high",
            "calories_per_100g": 200,
            "protein_g_per_100g": 20,
            "carbs_g_per_100g": 10,
            "fat_g_per_100g": 8,
            "fiber_g_per_100g": 2,
            "portions": [{"description": "1 portion", "amount": 1, "gram_weight": 150}],
        }

    def test_usda_nutrients_are_scaled_in_code_not_copied_from_model(self):
        args = {"source": "usda", "portion_grams": 150, "calories": 1, "protein_g": 1,
                "carbs_g": 1, "fat_g": 1, "fiber_g": 1}
        result = Agent._apply_usda_values(args, self.reference, "chicken, 150 g")
        self.assertEqual([result[key] for key in ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")],
                         [300, 30, 15, 12, 3])
        self.assertEqual(args["calories"], 1)

    def test_low_relevance_match_is_not_marked_as_usda_grounded(self):
        reference = {**self.reference, "match_strength": "low"}
        result = Agent._apply_usda_values({"source": "usda", "portion_grams": 150}, reference)
        self.assertEqual(result["source"], "estimated")

    def test_nonstandard_llm_portion_is_rejected_without_explicit_user_weight(self):
        result = Agent._apply_usda_values({"source": "usda", "portion_grams": 200}, self.reference, "one chicken portion")
        self.assertEqual(result["source"], "estimated")

    def test_multiple_standard_portions_are_scaled_from_the_usda_measure(self):
        result = Agent._apply_usda_values({"source": "usda", "portion_grams": 300}, self.reference, "two chicken portions")
        self.assertEqual(result["source"], "usda")
        self.assertEqual(result["portion_grams"], 300)
        self.assertEqual(result["calories"], 600)


if __name__ == "__main__":
    unittest.main()
