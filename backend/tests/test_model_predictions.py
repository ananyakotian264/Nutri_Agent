import tempfile
import unittest
from pathlib import Path

import db
from metrics import calculate_metrics


class AutomaticPredictionAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.old_db_path = db.DB_PATH
        db.DB_PATH = Path(self.temp_dir.name) / "audits.sqlite3"
        db.init_db()
        self.owner = db.create_user("audit.owner", "hash")
        self.other = db.create_user("audit.other", "hash")

    def tearDown(self):
        db.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    @staticmethod
    def prediction(source="usda", portion=150, reference=True):
        item = {
            "food_name": "Orange",
            "calories": 93,
            "protein_g": 1.8,
            "carbs_g": 23.1,
            "fat_g": 0.2,
            "fiber_g": 4.7,
            "source": source,
            "portion_grams": portion,
        }
        if reference:
            item["reference"] = {
                "found": True,
                "food_name": "Oranges, raw",
                "fdc_id": 123,
                "calories_per_100g": 62,
                "protein_g_per_100g": 1.2,
                "carbs_g_per_100g": 15.4,
                "fat_g_per_100g": 0.2,
                "fiber_g_per_100g": 3.1,
                "match_score": 89,
                "match_strength": "high",
            }
        return item

    def test_only_complete_usda_reference_is_scored_automatically(self):
        meal_id = db.insert_meal(self.owner, "Orange", 93, 1.8, 23.1, 0.2, 4.7, source="usda")
        db.save_automatic_prediction_audits(self.owner, "one orange", "test-model", [
            {**self.prediction(), "meal_id": meal_id},
        ])

        rows = db.get_automatic_prediction_audits(self.owner)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["reference_verified"])
        self.assertEqual(rows[0]["reference_calories"], 93)
        self.assertAlmostEqual(rows[0]["reference_carbs_g"], 23.1)
        metrics = calculate_metrics(rows)
        self.assertEqual(metrics["total_count"], 1)
        self.assertEqual(metrics["reference_coverage_percent"], 100)
        self.assertEqual(metrics["match_strength_counts"]["high"], 1)
        self.assertEqual(metrics["average_match_score"], 89)
        self.assertEqual(db.get_automatic_prediction_audits(self.other), [])

    def test_estimates_and_missing_portion_remain_unscored(self):
        meal_ids = [
            db.insert_meal(self.owner, "Estimated meal", 100, 5, 10, 2, 1, source="estimated"),
            db.insert_meal(self.owner, "No weight", 100, 5, 10, 2, 1, source="usda"),
        ]
        db.save_automatic_prediction_audits(self.owner, "meal", "test-model", [
            {**self.prediction(source="estimated"), "meal_id": meal_ids[0]},
            {**self.prediction(portion=None), "meal_id": meal_ids[1]},
        ])

        rows = db.get_automatic_prediction_audits(self.owner)
        metrics = calculate_metrics(rows)
        self.assertEqual(len(rows), 2)
        self.assertFalse(any(row["reference_verified"] for row in rows))
        self.assertEqual(metrics["total_count"], 2)
        self.assertEqual(metrics["reference_coverage_percent"], 100)
        self.assertEqual(metrics["direct_source_count"], 0)
        self.assertEqual(metrics["average_match_score"], 89)

    def test_deleting_meal_cascades_its_automatic_audit(self):
        meal_id = db.insert_meal(self.owner, "Orange", 93, 1.8, 23.1, 0.2, 4.7, source="usda")
        db.save_automatic_prediction_audits(self.owner, "orange", "test-model", [
            {**self.prediction(), "meal_id": meal_id},
        ])
        audit_id = db.get_automatic_prediction_audits(self.owner)[0]["id"]

        self.assertTrue(db.delete_meal(self.owner, meal_id))
        self.assertEqual(db.get_automatic_prediction_audits(self.owner), [])
        self.assertFalse(db.delete_automatic_prediction_audit(self.other, audit_id))


if __name__ == "__main__":
    unittest.main()
