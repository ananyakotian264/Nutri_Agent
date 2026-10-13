import tempfile
import unittest
from pathlib import Path

import db
from metrics import calculate_metrics


class ModelPredictionStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_path = db.DB_PATH
        db.DB_PATH = Path(self.temp_dir.name) / "predictions.sqlite3"
        db.init_db()
        self.owner = db.create_user("prediction.owner", "hash")
        self.other = db.create_user("prediction.other", "hash")

    def tearDown(self):
        db.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def test_model_results_persist_actual_values_and_are_account_scoped(self):
        prediction = {
            "food_name": "Four large eggs",
            "calories": 286,
            "protein_g": 25,
            "carbs_g": 1,
            "fat_g": 19,
            "fiber_g": 0,
            "source": "usda",
        }
        saved = db.save_model_predictions(self.owner, "four large eggs", "test-model", [prediction])
        self.assertEqual(len(saved), 1)
        prediction_id = saved[0]["id"]
        self.assertIsNone(saved[0]["actual_food"])
        self.assertEqual(db.get_model_predictions(self.owner)[0]["predicted_calories"], 286)
        self.assertEqual(db.get_model_predictions(self.other), [])
        self.assertEqual(calculate_metrics(db.get_metric_examples(self.owner))["classification"]["sample_count"], 0)

        actual = {
            "actual_food": "Egg, whole, cooked",
            "actual_calories": 294,
            "actual_protein_g": 25,
            "actual_carbs_g": 1,
            "actual_fat_g": 20,
            "actual_fiber_g": 0,
        }
        self.assertFalse(db.update_model_prediction_actual(self.other, prediction_id, actual))
        self.assertTrue(db.update_model_prediction_actual(self.owner, prediction_id, actual))
        metrics = calculate_metrics(db.get_metric_examples(self.owner))
        self.assertEqual(metrics["classification"]["sample_count"], 1)
        self.assertAlmostEqual(metrics["nutrition"]["calories"]["mae"], 8)

        self.assertFalse(db.delete_model_prediction(self.other, prediction_id))
        self.assertTrue(db.delete_model_prediction(self.owner, prediction_id))
        self.assertEqual(db.get_model_predictions(self.owner), [])


if __name__ == "__main__":
    unittest.main()
