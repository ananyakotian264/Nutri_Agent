"""
mcp_server.py — The MCP SERVER.

This process knows nothing about Groq, agents, or the frontend. Its only
job is to expose a small set of well-documented TOOLS over the Model
Context Protocol. Any MCP-compatible client (our own host, Claude Desktop,
another agent, whatever) could talk to this same server and get the same
capabilities. That decoupling — capability provider vs. capability user —
is the entire point of MCP.

Transport: stdio. The host process (main.py) will spawn this file as a
subprocess and talk to it over stdin/stdout using the MCP wire protocol.
That's why this file must never `print()` anything itself — stdout is the
protocol channel, not a debug console. Use logging to stderr if you need to.

Run it standalone for a sanity check (it will just idle, waiting on stdio):
    python mcp_server.py
"""

import os
import sys
import logging
import math
import traceback

# --- CRITICAL WINDOWS FIX: Force stdout to UTF-8 so docstring emojis/dashes don't crash the stream ---
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

import db
from nutrition import rank_usda_foods

load_dotenv()

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("mcp_server")

USDA_API_KEY = os.getenv("USDA_API_KEY")
USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

db.init_db()

mcp = FastMCP("nutrition-tools")


# ---------------------------------------------------------------------------
# Tool 1: USDA lookup — grounds the agent in real data instead of pure
# LLM guesswork whenever a match exists.
# ---------------------------------------------------------------------------
@mcp.tool()
def search_usda_food(query: str) -> dict:
    """
    Search the USDA FoodData Central database for a food and return its
    nutrition facts per 100g. Best for single ingredients or common branded
    foods (e.g. "chicken breast", "white rice", "banana"). Composite dishes
    like restaurant meals ("chicken shawarma wrap") often will NOT be found
    here with good precision — if results look irrelevant or missing key
    nutrients, fall back to your own best estimate instead of trusting a bad
    match.

    Args:
        query: the food name to search for.

    Returns:
        A dict with "found" (bool) and, if found, "food_name",
        "calories_per_100g", "protein_g_per_100g", "carbs_g_per_100g",
        "fat_g_per_100g", "fiber_g_per_100g", and a heuristic match score.
    """
    if not USDA_API_KEY or USDA_API_KEY == "your_usda_key_here":
        return {"found": False, "error": "USDA_API_KEY is not configured on the server."}

    try:
        resp = httpx.get(
            USDA_SEARCH_URL,
            params={"query": query, "api_key": USDA_API_KEY, "pageSize": 25, "dataType": "Foundation,SR Legacy"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        # HTTP exception strings may include the API key in the request URL.
        log.warning("USDA request failed (%s)", type(e).__name__)
        return {"found": False, "error": "USDA lookup failed. Try again later."}

    foods = data.get("foods", [])
    if not foods:
        return {"found": False, "error": "No matches in USDA database."}

    ranked = rank_usda_foods(query, foods)
    if not ranked:
        return {"found": False, "error": "USDA matches did not provide usable energy data."}
    return {**ranked[0], "search_query": query, "candidate_count": len(ranked)}


# ---------------------------------------------------------------------------
# Tool 2 & 3: pure math, no external calls. Deterministic health formulas
# live here rather than being "guessed" by the LLM, which is a bad idea for
# anything a person might actually rely on.
# ---------------------------------------------------------------------------
@mcp.tool()
def calculate_bmi(weight_kg: float, height_cm: float) -> dict:
    """
    Calculate Body Mass Index and its standard WHO category.

    Args:
        weight_kg: body weight in kilograms.
        height_cm: height in centimeters.
    """
    height_m = height_cm / 100
    bmi = round(weight_kg / (height_m ** 2), 1)

    if bmi < 18.5:
        category = "Underweight"
    elif bmi < 25:
        category = "Normal weight"
    elif bmi < 30:
        category = "Overweight"
    else:
        category = "Obese"

    return {"bmi": bmi, "category": category}


@mcp.tool()
def calculate_daily_targets(
    weight_kg: float,
    height_cm: float,
    age: int,
    sex: str,
    activity_level: str,
    goal: str,
) -> dict:
    """
    Compute recommended daily calorie, protein, carb, fat and fiber targets
    from body stats using the Mifflin-St Jeor equation for BMR, an activity
    multiplier for TDEE, and evidence-based macro ratios adjusted for the
    stated goal.

    Args:
        weight_kg: body weight in kilograms.
        height_cm: height in centimeters.
        age: age in years.
        sex: "male" or "female".
        activity_level: one of "sedentary", "light", "moderate", "active", "very_active".
        goal: one of "lose", "maintain", "gain".
    """
    if sex.lower() == "male":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

    multipliers = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very_active": 1.9,
    }
    tdee = bmr * multipliers.get(activity_level.lower(), 1.375)

    goal = goal.lower()
    if goal == "lose":
        calorie_target = tdee - 500
        protein_per_kg = 1.8  # higher protein preserves muscle in a deficit
    elif goal == "gain":
        calorie_target = tdee + 300
        protein_per_kg = 1.8
    else:
        calorie_target = tdee
        protein_per_kg = 1.6

    calorie_target = max(calorie_target, 1200)  # safety floor
    protein_target_g = round(weight_kg * protein_per_kg, 1)
    fiber_target_g = round(calorie_target / 1000 * 14, 1)  # 14g / 1000 kcal, standard guideline
    fat_target_g = round(calorie_target * 0.25 / 9, 1)  # ~25% of calories from fat

    protein_cal = protein_target_g * 4
    fat_cal = fat_target_g * 9
    carb_target_g = round(max(calorie_target - protein_cal - fat_cal, 0) / 4, 1)

    return {
        "bmr": round(bmr),
        "tdee": round(tdee),
        "calorie_target": round(calorie_target),
        "protein_target_g": protein_target_g,
        "carb_target_g": carb_target_g,
        "fat_target_g": fat_target_g,
        "fiber_target_g": fiber_target_g,
    }


# ---------------------------------------------------------------------------
# Tool 4-6: persistence, exposed as tools so the AGENT decides when to
# read/write state, rather than the backend silently doing it around the
# agent. Keeping this state-changing action behind an explicit tool call
# also means every write shows up in the agent's visible trace.
# ---------------------------------------------------------------------------
@mcp.tool()
def log_meal(user_id: int, food_name: str, calories: float, protein_g: float, carbs_g: float, fat_g: float, fiber_g: float, source: str = "estimated", portion_grams: float | None = None) -> dict:
    """
    Persist a meal to today's food log.

    Args:
        user_id: account id, assigned by the authenticated API server.
        food_name: descriptive name of what was eaten.
        calories, protein_g, carbs_g, fat_g, fiber_g: nutrition for the
            ENTIRE portion eaten (not per 100g — scale USDA per-100g values
            to the actual portion size first).
        portion_grams: estimated edible portion weight in grams, when known.
        source: "usda" if grounded in a USDA lookup, "estimated" if it's
            your best-effort estimate, "manual" if the user gave exact numbers.
    """
    food_name = food_name.strip()
    if not food_name or len(food_name) > 120:
        return {"status": "rejected", "reason": "Food name must contain 1 to 120 characters."}
    if not math.isfinite(calories) or calories < 0 or calories > 100000:
        return {"status": "rejected", "reason": "Calories must be a finite, non-negative value."}
    macro_values = (protein_g, carbs_g, fat_g, fiber_g)
    if any(not math.isfinite(value) or value < 0 or value > 10000 for value in macro_values):
        return {"status": "rejected", "reason": "Nutrition values must be finite, non-negative numbers."}
    if portion_grams is not None and (not math.isfinite(portion_grams) or portion_grams <= 0 or portion_grams > 100000):
        return {"status": "rejected", "reason": "Portion weight must be a positive, finite number of grams."}
    if source not in {"usda", "estimated", "manual"}:
        source = "estimated"
    meal_id = db.insert_meal(user_id, food_name, calories, protein_g, carbs_g, fat_g, fiber_g, source)
    return {"meal_id": meal_id, "status": "logged", "portion_grams": portion_grams}


@mcp.tool()
def get_daily_summary(user_id: int, target_date: str = "") -> dict:
    """
    Get today's (or a given YYYY-MM-DD date's) total calories/macros logged
    so far, plus the individual meals.

    Args:
    user_id: account id, assigned by the authenticated API server.
    target_date: optional ISO date string; defaults to today.
    """
    totals, meals = db.get_daily_totals(user_id, target_date or None)
    return {"totals": totals, "meals": meals}


@mcp.tool()
def get_saved_profile(user_id: int) -> dict:
    """Fetch the authenticated user's saved profile and computed targets."""
    profile = db.get_profile(user_id)
    return profile or {"error": "No profile saved yet."}


if __name__ == "__main__":
    try:
        mcp.run(transport="stdio")
    except Exception as e:
        log.critical("MCP Server crashed: %s\n%s", e, traceback.format_exc())
        sys.exit(1)
