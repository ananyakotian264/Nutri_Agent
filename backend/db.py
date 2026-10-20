"""
db.py — Persistence layer.

A tiny SQLite wrapper. Three tables:
  users   -> stores user credentials (username, password_hash)
  profile -> single-row per user with body stats + computed targets
  meals   -> every logged meal, timestamped and tied to a specific user

This file has nothing agentic about it on purpose. Storage is a plain,
boring utility that tools call into — it should not know about the LLM,
Groq, or MCP at all. Keeping it dumb is what makes the rest of the system
testable.
"""

import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("NUTRI_DATABASE_PATH", Path(__file__).parent / "nutri_agent.db"))


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    # Enable foreign key constraints in SQLite to link tables safely
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db():
    conn = get_conn()
    
    # 1. Users Table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
        """
    )

    # Opaque bearer sessions are stored by hash so a database read cannot
    # directly be used as a browser credential.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    
    # 2. Profile Table (Linked to users.id)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS profile (
            user_id INTEGER PRIMARY KEY,
            height_cm REAL,
            weight_kg REAL,
            age INTEGER,
            sex TEXT,
            activity_level TEXT,
            goal TEXT,
            bmi REAL,
            bmi_category TEXT,
            calorie_target REAL,
            protein_target_g REAL,
            carb_target_g REAL,
            fiber_target_g REAL,
            fat_target_g REAL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    
    # 3. Meals Table (Linked to users.id)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            logged_at TEXT NOT NULL,
            food_name TEXT NOT NULL,
            calories REAL NOT NULL,
            protein_g REAL NOT NULL,
            carbs_g REAL NOT NULL,
            fat_g REAL NOT NULL,
            fiber_g REAL NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meals_user_logged_at ON meals(user_id, logged_at)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            description TEXT NOT NULL,
            model TEXT NOT NULL,
            source TEXT NOT NULL,
            predicted_food TEXT NOT NULL,
            predicted_calories REAL NOT NULL,
            predicted_protein_g REAL NOT NULL,
            predicted_carbs_g REAL NOT NULL,
            predicted_fat_g REAL NOT NULL,
            predicted_fiber_g REAL NOT NULL,
            actual_food TEXT,
            actual_calories REAL,
            actual_protein_g REAL,
            actual_carbs_g REAL,
            actual_fat_g REAL,
            actual_fiber_g REAL,
            matched_meal_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    prediction_columns = {row["name"] for row in conn.execute("PRAGMA table_info(model_predictions)")}
    if "matched_meal_id" not in prediction_columns:
        conn.execute("ALTER TABLE model_predictions ADD COLUMN matched_meal_id INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_model_predictions_user_created ON model_predictions(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_model_predictions_matched_meal ON model_predictions(user_id, matched_meal_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_model_predictions_one_per_meal ON model_predictions(user_id, matched_meal_id) WHERE matched_meal_id IS NOT NULL")

    conn.execute(
        """CREATE TABLE IF NOT EXISTS automatic_prediction_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            meal_id INTEGER NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            model TEXT NOT NULL,
            description TEXT NOT NULL,
            source TEXT NOT NULL,
            predicted_food TEXT NOT NULL,
            predicted_calories REAL NOT NULL,
            predicted_protein_g REAL NOT NULL,
            predicted_carbs_g REAL NOT NULL,
            predicted_fat_g REAL NOT NULL,
            predicted_fiber_g REAL NOT NULL,
            portion_grams REAL,
            reference_food TEXT,
            reference_fdc_id TEXT,
            reference_calories_per_100g REAL,
            reference_protein_g_per_100g REAL,
            reference_carbs_g_per_100g REAL,
            reference_fat_g_per_100g REAL,
            reference_fiber_g_per_100g REAL,
            matched_food TEXT,
            match_score REAL,
            match_strength TEXT,
            lookup_error TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (meal_id) REFERENCES meals (id) ON DELETE CASCADE
        )"""
    )
    audit_columns = {row["name"] for row in conn.execute("PRAGMA table_info(automatic_prediction_audits)")}
    for column, declaration in (
        ("matched_food", "TEXT"),
        ("match_score", "REAL"),
        ("match_strength", "TEXT"),
        ("lookup_error", "TEXT"),
    ):
        if column not in audit_columns:
            conn.execute(f"ALTER TABLE automatic_prediction_audits ADD COLUMN {column} {declaration}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_automatic_prediction_audits_user_created ON automatic_prediction_audits(user_id, created_at)")
    conn.commit()
    conn.close()


# --- Authentication Methods ---

def create_user(username: str, password_hash: str):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash)
        )
        conn.commit()
        user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        user_id = None # Returns None if username already exists
    finally:
        conn.close()
    return user_id


def get_user_by_username(username: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_session(token_hash: str, user_id: int, expires_at: datetime):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO auth_sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token_hash, user_id, expires_at.isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        conn.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (datetime.now(timezone.utc).isoformat(),))
        conn.commit()
    finally:
        conn.close()


def get_user_id_for_session(token_hash: str):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT user_id FROM auth_sessions WHERE token_hash = ? AND expires_at > ?",
            (token_hash, datetime.now(timezone.utc).isoformat()),
        ).fetchone()
        return int(row["user_id"]) if row else None
    finally:
        conn.close()


def revoke_session(token_hash: str):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))
        conn.commit()
    finally:
        conn.close()


# --- Profile Methods ---

def save_profile(user_id: int, data: dict):
    conn = get_conn()
    fields = (
        "height_cm", "weight_kg", "age", "sex", "activity_level", "goal",
        "bmi", "bmi_category", "calorie_target", "protein_target_g",
        "carb_target_g", "fiber_target_g", "fat_target_g",
    )
    values = [data.get(f) for f in fields]
    values.insert(0, user_id) # Put user_id at the start of the list
    
    conn.execute(
        f"""
        INSERT INTO profile (user_id, {", ".join(fields)})
        VALUES (?, {", ".join(["?"] * len(fields))})
        ON CONFLICT(user_id) DO UPDATE SET
        {", ".join(f"{f}=excluded.{f}" for f in fields)}
        """,
        values,
    )
    conn.commit()
    conn.close()


def get_profile(user_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM profile WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# --- Meal Methods ---

def insert_meal(user_id: int, food_name: str, calories: float, protein_g: float, carbs_g: float, fat_g: float, fiber_g: float, source: str = "manual"):
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO meals (user_id, logged_at, food_name, calories, protein_g, carbs_g, fat_g, fiber_g, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, datetime.now().isoformat(), food_name, calories, protein_g, carbs_g, fat_g, fiber_g, source),
    )
    conn.commit()
    meal_id = cur.lastrowid
    conn.close()
    return meal_id


def get_meals_for_date(user_id: int, target_date: str | None = None):
    target_date = target_date or date.today().isoformat()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM meals WHERE user_id = ? AND logged_at LIKE ? ORDER BY logged_at ASC",
        (user_id, f"{target_date}%"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_manual_meal(user_id: int, meal_id: int):
    """Return an account-owned, manually entered meal suitable as reference data."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM meals WHERE id = ? AND user_id = ? AND source = 'manual'",
            (meal_id, user_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_daily_totals(user_id: int, target_date: str | None = None):
    meals = get_meals_for_date(user_id, target_date)
    totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fiber_g": 0.0}
    for m in meals:
        for k in totals:
            totals[k] += m[k]
    return totals, meals


def delete_meal(user_id: int, meal_id: int) -> bool:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE model_predictions SET matched_meal_id = NULL WHERE user_id = ? AND matched_meal_id = ?",
            (user_id, meal_id),
        )
        cursor = conn.execute("DELETE FROM meals WHERE user_id = ? AND id = ?", (user_id, meal_id))
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def save_model_predictions(
    user_id: int,
    description: str,
    model: str,
    predictions: list[dict],
    matched_meal_id: int,
) -> list[dict]:
    """Persist every prediction in a result as one account-owned history row."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    try:
        meal = conn.execute(
            "SELECT id, source FROM meals WHERE id = ? AND user_id = ?",
            (matched_meal_id, user_id),
        ).fetchone()
        if not meal or meal["source"] != "manual":
            raise ValueError("Automatic model comparisons require a manual nutrition entry owned by this account.")
        ids = []
        for prediction in predictions:
            cursor = conn.execute(
                """INSERT INTO model_predictions (
                    user_id, created_at, description, model, source, predicted_food,
                    predicted_calories, predicted_protein_g, predicted_carbs_g,
                    predicted_fat_g, predicted_fiber_g, matched_meal_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, now, description, model, prediction.get("source", "estimated"),
                 prediction["food_name"], prediction["calories"], prediction["protein_g"],
                 prediction["carbs_g"], prediction["fat_g"], prediction["fiber_g"], matched_meal_id),
            )
            ids.append(int(cursor.lastrowid))
        conn.commit()
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"""SELECT p.*, m.id AS linked_meal_id, m.food_name AS linked_food_name,
                       m.calories AS linked_calories, m.protein_g AS linked_protein_g,
                       m.carbs_g AS linked_carbs_g, m.fat_g AS linked_fat_g,
                       m.fiber_g AS linked_fiber_g, m.source AS linked_source
                FROM model_predictions p
                LEFT JOIN meals m ON m.id = p.matched_meal_id AND m.user_id = p.user_id
                WHERE p.user_id = ? AND p.id IN ({placeholders}) ORDER BY p.id""",
            (user_id, *ids),
        ).fetchall()
        return [_prediction_with_meal(dict(row)) for row in rows]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_model_predictions(user_id: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT p.*, m.id AS linked_meal_id, m.food_name AS linked_food_name,
                      m.calories AS linked_calories, m.protein_g AS linked_protein_g,
                      m.carbs_g AS linked_carbs_g, m.fat_g AS linked_fat_g,
                      m.fiber_g AS linked_fiber_g, m.source AS linked_source
               FROM model_predictions p
               LEFT JOIN meals m ON m.id = p.matched_meal_id AND m.user_id = p.user_id
               WHERE p.user_id = ? AND p.matched_meal_id IS NOT NULL
                 AND m.source = 'manual' ORDER BY p.created_at DESC, p.id DESC""",
            (user_id,),
        ).fetchall()
        return [_prediction_with_meal(dict(row)) for row in rows]
    finally:
        conn.close()


def get_model_prediction_for_meal(user_id: int, meal_id: int) -> dict | None:
    return next((row for row in get_model_predictions(user_id) if row["matched_meal_id"] == meal_id), None)


def _prediction_with_meal(row: dict) -> dict:
    """Expose actuals only from the linked manual meal, never from typed metric inputs."""
    meal_id = row.pop("linked_meal_id", None)
    row.pop("linked_source", None)
    row["matched_meal_id"] = meal_id
    row["actual_food"] = row.pop("linked_food_name", None)
    for key in ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g"):
        row[f"actual_{key}"] = row.pop(f"linked_{key}", None)
    return row


def delete_model_prediction(user_id: int, prediction_id: int) -> bool:
    conn = get_conn()
    try:
        cursor = conn.execute(
            "DELETE FROM model_predictions WHERE user_id = ? AND id = ?",
            (user_id, prediction_id),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def get_metric_examples(user_id: int) -> list[dict]:
    """Return only predictions with a USDA record and known serving weight."""
    return [row for row in get_automatic_prediction_audits(user_id) if row["reference_verified"]]


def save_automatic_prediction_audits(user_id: int, description: str, model: str, predictions: list[dict]) -> None:
    """Save each model output with the USDA evidence available during retrieval."""
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    try:
        for prediction in predictions:
            meal_id = prediction.get("meal_id")
            if meal_id is None:
                continue
            meal = conn.execute("SELECT id FROM meals WHERE id = ? AND user_id = ?", (meal_id, user_id)).fetchone()
            if not meal:
                continue
            reference = prediction.get("reference") if isinstance(prediction.get("reference"), dict) else {}
            portion_grams = prediction.get("portion_grams")
            values = {
                "calories": reference.get("calories_per_100g"),
                "protein_g": reference.get("protein_g_per_100g"),
                "carbs_g": reference.get("carbs_g_per_100g"),
                "fat_g": reference.get("fat_g_per_100g"),
                "fiber_g": reference.get("fiber_g_per_100g"),
            }
            verified = (
                prediction.get("source") == "usda"
                and reference.get("found") is True
                and reference.get("match_strength") in {"high", "medium"}
                and isinstance(portion_grams, (int, float))
                and 0 < float(portion_grams) <= 100000
                and all(isinstance(value, (int, float)) for value in values.values())
            )
            conn.execute(
                """INSERT INTO automatic_prediction_audits (
                    user_id, meal_id, created_at, model, description, source, predicted_food,
                    predicted_calories, predicted_protein_g, predicted_carbs_g, predicted_fat_g,
                    predicted_fiber_g, portion_grams, reference_food, reference_fdc_id,
                    reference_calories_per_100g, reference_protein_g_per_100g,
                    reference_carbs_g_per_100g, reference_fat_g_per_100g, reference_fiber_g_per_100g,
                    matched_food, match_score, match_strength, lookup_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(meal_id) DO UPDATE SET
                    created_at=excluded.created_at, model=excluded.model, description=excluded.description,
                    source=excluded.source, predicted_food=excluded.predicted_food,
                    predicted_calories=excluded.predicted_calories,
                    predicted_protein_g=excluded.predicted_protein_g,
                    predicted_carbs_g=excluded.predicted_carbs_g, predicted_fat_g=excluded.predicted_fat_g,
                    predicted_fiber_g=excluded.predicted_fiber_g, portion_grams=excluded.portion_grams,
                    reference_food=excluded.reference_food, reference_fdc_id=excluded.reference_fdc_id,
                    reference_calories_per_100g=excluded.reference_calories_per_100g,
                    reference_protein_g_per_100g=excluded.reference_protein_g_per_100g,
                    reference_carbs_g_per_100g=excluded.reference_carbs_g_per_100g,
                    reference_fat_g_per_100g=excluded.reference_fat_g_per_100g,
                    reference_fiber_g_per_100g=excluded.reference_fiber_g_per_100g,
                    matched_food=excluded.matched_food, match_score=excluded.match_score,
                    match_strength=excluded.match_strength, lookup_error=excluded.lookup_error""",
                (user_id, meal_id, now, model, description, prediction.get("source", "estimated"),
                 prediction["food_name"], prediction["calories"], prediction["protein_g"],
                 prediction["carbs_g"], prediction["fat_g"], prediction["fiber_g"],
                 float(portion_grams) if verified else None,
                 reference.get("food_name") if verified else None,
                 str(reference.get("fdc_id")) if verified and reference.get("fdc_id") is not None else None,
                 *(values[key] if verified else None for key in ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")),
                 reference.get("food_name") if reference.get("found") else None,
                 reference.get("match_score") if reference.get("found") else None,
                 reference.get("match_strength") if reference.get("found") else None,
                 str(prediction.get("lookup_error") or "")[:200] or None),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_automatic_prediction_audits(user_id: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT a.*, m.logged_at FROM automatic_prediction_audits a
               JOIN meals m ON m.id = a.meal_id AND m.user_id = a.user_id
               WHERE a.user_id = ? ORDER BY a.created_at DESC, a.id DESC""",
            (user_id,),
        ).fetchall()
        result = []
        nutrient_keys = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")
        for raw in rows:
            row = dict(raw)
            row["reference_verified"] = (
                row["reference_food"] is not None
                and row["portion_grams"] is not None
                and row["match_strength"] in {"high", "medium"}
            )
            for nutrient in nutrient_keys:
                per_100g = row.pop(f"reference_{nutrient}_per_100g")
                row[f"reference_{nutrient}"] = (
                    float(per_100g) * float(row["portion_grams"]) / 100
                    if row["reference_verified"] and per_100g is not None else None
                )
            result.append(row)
        return result
    finally:
        conn.close()


def delete_automatic_prediction_audit(user_id: int, audit_id: int) -> bool:
    conn = get_conn()
    try:
        cursor = conn.execute("DELETE FROM automatic_prediction_audits WHERE user_id = ? AND id = ?", (user_id, audit_id))
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()
