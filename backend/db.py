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
        CREATE TABLE IF NOT EXISTS prediction_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            predicted_food TEXT NOT NULL,
            actual_food TEXT NOT NULL,
            predicted_calories REAL NOT NULL,
            predicted_protein_g REAL NOT NULL,
            predicted_carbs_g REAL NOT NULL,
            predicted_fat_g REAL NOT NULL,
            predicted_fiber_g REAL NOT NULL,
            actual_calories REAL NOT NULL,
            actual_protein_g REAL NOT NULL,
            actual_carbs_g REAL NOT NULL,
            actual_fat_g REAL NOT NULL,
            actual_fiber_g REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prediction_checks_user_created ON prediction_checks(user_id, created_at)")

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
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_model_predictions_user_created ON model_predictions(user_id, created_at)")
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
        cursor = conn.execute("DELETE FROM meals WHERE user_id = ? AND id = ?", (user_id, meal_id))
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def add_prediction_check(user_id: int, values: dict) -> int:
    fields = (
        "predicted_food", "actual_food", "predicted_calories", "predicted_protein_g",
        "predicted_carbs_g", "predicted_fat_g", "predicted_fiber_g", "actual_calories",
        "actual_protein_g", "actual_carbs_g", "actual_fat_g", "actual_fiber_g",
    )
    conn = get_conn()
    try:
        cursor = conn.execute(
            f"INSERT INTO prediction_checks (user_id, created_at, {', '.join(fields)}) VALUES (?, ?, {', '.join('?' for _ in fields)})",
            (user_id, datetime.now(timezone.utc).isoformat(), *(values[field] for field in fields)),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def get_prediction_checks(user_id: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM prediction_checks WHERE user_id = ? ORDER BY created_at DESC, id DESC",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_prediction_check(user_id: int, check_id: int) -> bool:
    conn = get_conn()
    try:
        cursor = conn.execute("DELETE FROM prediction_checks WHERE user_id = ? AND id = ?", (user_id, check_id))
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def save_model_predictions(user_id: int, description: str, model: str, predictions: list[dict]) -> list[dict]:
    """Persist every prediction in a result as one account-owned history row."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    try:
        ids = []
        for prediction in predictions:
            cursor = conn.execute(
                """INSERT INTO model_predictions (
                    user_id, created_at, description, model, source, predicted_food,
                    predicted_calories, predicted_protein_g, predicted_carbs_g,
                    predicted_fat_g, predicted_fiber_g
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, now, description, model, prediction.get("source", "estimated"),
                 prediction["food_name"], prediction["calories"], prediction["protein_g"],
                 prediction["carbs_g"], prediction["fat_g"], prediction["fiber_g"]),
            )
            ids.append(int(cursor.lastrowid))
        conn.commit()
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT * FROM model_predictions WHERE user_id = ? AND id IN ({placeholders}) ORDER BY id",
            (user_id, *ids),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_model_predictions(user_id: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM model_predictions WHERE user_id = ? ORDER BY created_at DESC, id DESC",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_model_prediction_actual(user_id: int, prediction_id: int, actual: dict) -> bool:
    conn = get_conn()
    try:
        cursor = conn.execute(
            """UPDATE model_predictions SET actual_food = ?, actual_calories = ?,
                actual_protein_g = ?, actual_carbs_g = ?, actual_fat_g = ?, actual_fiber_g = ?
                WHERE user_id = ? AND id = ?""",
            (actual["actual_food"], actual["actual_calories"], actual["actual_protein_g"],
             actual["actual_carbs_g"], actual["actual_fat_g"], actual["actual_fiber_g"],
             user_id, prediction_id),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


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
    """Combine older saved comparisons and model predictions with actual values."""
    checks = get_prediction_checks(user_id)
    model_examples = [
        row for row in get_model_predictions(user_id)
        if row["actual_food"] is not None and row["actual_calories"] is not None
    ]
    return checks + model_examples
