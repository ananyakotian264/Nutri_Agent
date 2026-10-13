"""FastAPI entry point for Nutri-Agent.

Authentication uses opaque, revocable bearer sessions. The browser never
chooses a user id for data access; every account-scoped route derives it from
the authenticated session.
"""

import asyncio
import hashlib
import logging
import math
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from passlib.context import CryptContext

import db
from gateway import gateway
from metrics import calculate_metrics
from orchestrator import Agent, MCPToolBridge

# Keep the existing Windows MCP subprocess shutdown fix in place. This only
# suppresses expected broken-pipe/reset errors while the child process closes.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    from asyncio.proactor_events import _ProactorBasePipeTransport

    _original_call_connection_lost = _ProactorBasePipeTransport._call_connection_lost

    def _silence_closed_pipe(func):
        def wrapper(self, exc=None):
            try:
                return func(self, exc)
            except (ConnectionResetError, BrokenPipeError):
                return None
        return wrapper

    _ProactorBasePipeTransport._call_connection_lost = _silence_closed_pipe(_original_call_connection_lost)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("nutri_api")
bridge = MCPToolBridge()
agent: Agent | None = None
agent_startup_error: str | None = None
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_TTL = timedelta(days=30)
bearer_scheme = HTTPBearer(auto_error=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    server_script = str(Path(__file__).parent / "mcp_server.py")
    global agent, agent_startup_error
    try:
        await bridge.connect(server_script)
        agent = Agent(bridge)
        agent_startup_error = None
    except Exception:
        # Sign-in and manual logging remain available if MCP startup fails.
        agent_startup_error = "mcp_startup_failed"
        log.exception("MCP agent could not start; AI logging is disabled")
    yield
    agent = None
    await bridge.close()


app = FastAPI(title="Nutri-Agent API", version="2.0.0", lifespan=lifespan)
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,https://nutri-agent-mu.vercel.app",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path in {"/login", "/signup", "/logout"}:
        response.headers["Cache-Control"] = "no-store"
    return response


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(StrictModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=72)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def limit_bcrypt_bytes(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be 72 UTF-8 bytes or fewer")
        return value


class SignupIn(Credentials):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=72)


class ProfileIn(StrictModel):
    height_cm: float = Field(gt=50, le=300, allow_inf_nan=False)
    weight_kg: float = Field(gt=10, le=500, allow_inf_nan=False)
    age: int = Field(ge=10, le=120)
    sex: Literal["male", "female"]
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"]
    goal: Literal["lose", "maintain", "gain"]


class ChatIn(StrictModel):
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def require_nonempty_message(cls, value):
        if not value.strip():
            raise ValueError("Enter a food description")
        return value.strip()


class ManualLogIn(StrictModel):
    food_name: str = Field(min_length=1, max_length=120)
    calories: float = Field(ge=0, le=100000, allow_inf_nan=False)
    protein_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    carbs_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    fat_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    fiber_g: float = Field(ge=0, le=10000, allow_inf_nan=False)

    @field_validator("food_name")
    @classmethod
    def trim_food_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Food name cannot be blank")
        return value


class PredictionCheckIn(StrictModel):
    predicted_food: str = Field(min_length=1, max_length=120)
    actual_food: str = Field(min_length=1, max_length=120)
    predicted_calories: float = Field(ge=0, le=100000, allow_inf_nan=False)
    predicted_protein_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    predicted_carbs_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    predicted_fat_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    predicted_fiber_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    actual_calories: float = Field(ge=0, le=100000, allow_inf_nan=False)
    actual_protein_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    actual_carbs_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    actual_fat_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    actual_fiber_g: float = Field(ge=0, le=10000, allow_inf_nan=False)

    @field_validator("predicted_food", "actual_food")
    @classmethod
    def trim_check_food(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Food labels cannot be blank")
        return value


class PredictionActualIn(StrictModel):
    actual_food: str = Field(min_length=1, max_length=120)
    actual_calories: float = Field(ge=0, le=100000, allow_inf_nan=False)
    actual_protein_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    actual_carbs_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    actual_fat_g: float = Field(ge=0, le=10000, allow_inf_nan=False)
    actual_fiber_g: float = Field(ge=0, le=10000, allow_inf_nan=False)

    @field_validator("actual_food")
    @classmethod
    def trim_actual_food(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Food name cannot be blank")
        return value


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session(user_id: int) -> dict:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + SESSION_TTL
    db.create_session(token_digest(token), user_id, expires_at)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": int(SESSION_TTL.total_seconds()),
    }


async def authenticated_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> int:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Please sign in to continue", headers={"WWW-Authenticate": "Bearer"})
    user_id = db.get_user_id_for_session(token_digest(credentials.credentials))
    if user_id is None:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.", headers={"WWW-Authenticate": "Bearer"})
    return user_id


@app.get("/health")
async def health():
    if not gateway.configured:
        ai_status = "missing_groq_api_key"
    elif agent is None:
        ai_status = agent_startup_error or "mcp_not_ready"
    else:
        ai_status = "ready"
    return {"status": "ok", "ai_available": ai_status == "ready", "ai_status": ai_status}


@app.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(user: SignupIn):
    hashed_password = await asyncio.to_thread(pwd_context.hash, user.password)
    user_id = db.create_user(user.username, hashed_password)
    if not user_id:
        raise HTTPException(status_code=409, detail="That username is already in use")
    return {"message": "Account created", "username": user.username, **issue_session(user_id)}


@app.post("/login")
async def login(user: Credentials):
    db_user = db.get_user_by_username(user.username)
    # Perform a hash even for unknown accounts to reduce username timing leaks.
    if db_user:
        valid = await asyncio.to_thread(pwd_context.verify, user.password, db_user["password_hash"])
    else:
        await asyncio.to_thread(pwd_context.hash, secrets.token_urlsafe(12))
        valid = False
    if not valid:
        raise HTTPException(status_code=401, detail="Username or password is incorrect")
    return {"message": "Signed in", "username": db_user["username"], **issue_session(int(db_user["id"]))}


@app.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    if credentials and credentials.scheme.lower() == "bearer":
        db.revoke_session(token_digest(credentials.credentials))
    return None


@app.post("/profile")
async def set_profile(body: ProfileIn, user_id: int = Depends(authenticated_user_id)):
    if not bridge.session:
        raise HTTPException(status_code=503, detail="Profile calculator is temporarily unavailable")
    try:
        bmi_result = await asyncio.wait_for(
            bridge.call_tool("calculate_bmi", {"weight_kg": body.weight_kg, "height_cm": body.height_cm}),
            timeout=15,
        )
        target_payload = body.model_dump()
        targets = await asyncio.wait_for(
            bridge.call_tool("calculate_daily_targets", target_payload), timeout=15
        )
        record = {**target_payload, "bmi": bmi_result["bmi"], "bmi_category": bmi_result["category"], **targets}
        db.save_profile(user_id, record)
        return record
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="The nutrition calculator took too long. Please try again.")
    except Exception:
        log.exception("Profile calculation failed for an authenticated account")
        raise HTTPException(status_code=502, detail="We could not calculate your profile right now. Please try again.")


@app.get("/profile")
async def read_profile(user_id: int = Depends(authenticated_user_id)):
    profile = db.get_profile(user_id)
    if not profile:
        raise HTTPException(404, "No profile saved for this account yet.")
    return profile


@app.post("/log-food")
async def log_food(body: ChatIn, user_id: int = Depends(authenticated_user_id)):
    if not gateway.configured:
        raise HTTPException(status_code=503, detail="AI food logging is not configured. Add GROQ_API_KEY to the backend environment, then restart the service.")
    if not agent:
        raise HTTPException(status_code=503, detail="The AI food service did not start correctly. Check the backend logs, then try again or use manual logging.")
    try:
        result = await asyncio.wait_for(agent.run(body.message, user_id=user_id), timeout=90)
        if not result.get("predictions"):
            raise HTTPException(status_code=502, detail="The AI did not return a nutrition estimate. Include a food name and portion, then try again.")
        totals, meals = db.get_daily_totals(user_id)
        return {"reply": result["reply"], "trace": result["trace"], "predictions": result["predictions"], "totals": totals, "meals": meals}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Food logging timed out. Please try again.")
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("AI food logging failed (%s)", type(exc).__name__)
        message, response_status = provider_error_message(exc)
        raise HTTPException(status_code=response_status, detail=message)


def provider_error_message(error: Exception) -> tuple[str, int]:
    """Translate provider failures into safe, actionable UI messages."""
    error_type = type(error).__name__
    if error_type in {"AuthenticationError", "PermissionDeniedError"}:
        return "The AI provider rejected its credentials. Check GROQ_API_KEY on the backend.", 503
    if error_type == "NotFoundError":
        return "Groq could not find the configured model or its fallback. Set GROQ_MODEL to openai/gpt-oss-20b on the backend.", 503
    if error_type == "RateLimitError":
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", {}) or {}
        retry_after = headers.get("retry-after")
        try:
            retry_seconds = float(retry_after)
        except (TypeError, ValueError):
            retry_seconds = None
        if retry_seconds is not None and math.isfinite(retry_seconds) and 0 < retry_seconds <= 86400:
            return f"Groq's rate limit was reached. Try again in about {math.ceil(retry_seconds)} seconds.", 429

        reset = headers.get("x-ratelimit-reset-tokens") or headers.get("x-ratelimit-reset-requests")
        if reset and all(character.isdigit() or character in "m.s" for character in str(reset)):
            return f"Groq's rate limit was reached. Try again after the provider reset ({reset}).", 429
        return "Groq's request or token limit has been reached. Check the Groq Console Limits page for its reset time.", 429
    if error_type in {"APIConnectionError", "APITimeoutError", "InternalServerError"}:
        return "The AI provider could not be reached just now. Try again shortly.", 502
    if error_type == "BadRequestError":
        body = getattr(error, "body", {}) or {}
        provider_detail = body.get("error", {}) if isinstance(body, dict) else {}
        if isinstance(provider_detail, dict) and provider_detail.get("code") == "tool_use_failed":
            return "The model returned an incompatible tool call. Restart the updated backend and try again.", 502
        return "Groq rejected the model request. Check that the backend is using the updated model and agent configuration.", 502
    return "The AI provider could not complete this request. Check the backend AI configuration and try again.", 502


@app.post("/predict-food")
async def predict_food(body: ChatIn, user_id: int = Depends(authenticated_user_id)):
    if not gateway.configured:
        raise HTTPException(status_code=503, detail="AI prediction is not configured. Add GROQ_API_KEY to the backend environment, then restart the service.")
    if not agent:
        raise HTTPException(status_code=503, detail="The AI food service did not start correctly. Check the backend logs, then try again.")
    started_at = time.perf_counter()
    try:
        result = await asyncio.wait_for(agent.run(body.message, user_id=user_id, persist=False), timeout=90)
        if not result.get("predictions"):
            raise HTTPException(status_code=502, detail="The model did not return nutrition values. Add a food and portion description, then try again.")
        prediction_records = db.save_model_predictions(
            user_id, body.message, gateway.active_model, result["predictions"]
        )
        saved_predictions = db.get_model_predictions(user_id)
        metrics = calculate_metrics(db.get_metric_examples(user_id))
        return {
            "reply": result["reply"],
            "predictions": result["predictions"],
            "trace": result["trace"],
            "latency_ms": round((time.perf_counter() - started_at) * 1000),
            "model": gateway.active_model,
            "saved_to_log": False,
            "prediction_records": prediction_records,
            "saved_predictions": saved_predictions,
            "metrics": metrics,
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="The prediction timed out. Try a shorter food description.")
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("AI prediction failed (%s)", type(exc).__name__)
        message, response_status = provider_error_message(exc)
        raise HTTPException(status_code=response_status, detail=message)


@app.post("/log-manual")
async def log_manual(body: ManualLogIn, user_id: int = Depends(authenticated_user_id)):
    db.insert_meal(
        user_id, body.food_name, body.calories, body.protein_g, body.carbs_g,
        body.fat_g, body.fiber_g, source="manual",
    )
    totals, meals = db.get_daily_totals(user_id)
    return {"totals": totals, "meals": meals}


@app.delete("/meals/{meal_id}")
async def remove_meal(meal_id: int, user_id: int = Depends(authenticated_user_id)):
    if not db.delete_meal(user_id, meal_id):
        raise HTTPException(status_code=404, detail="That food entry was not found")
    totals, meals = db.get_daily_totals(user_id)
    return {"totals": totals, "meals": meals}


def prediction_check_payload(user_id: int) -> dict:
    checks = db.get_prediction_checks(user_id)
    return {"checks": checks, "metrics": calculate_metrics(checks)}


def model_prediction_payload(user_id: int) -> dict:
    predictions = db.get_model_predictions(user_id)
    examples = db.get_metric_examples(user_id)
    return {"predictions": predictions, "metrics": calculate_metrics(examples)}


@app.get("/model-predictions")
async def read_model_predictions(user_id: int = Depends(authenticated_user_id)):
    return model_prediction_payload(user_id)


@app.put("/model-predictions/{prediction_id}/actual")
async def save_model_prediction_actual(
    prediction_id: int,
    body: PredictionActualIn,
    user_id: int = Depends(authenticated_user_id),
):
    if not db.update_model_prediction_actual(user_id, prediction_id, body.model_dump()):
        raise HTTPException(status_code=404, detail="That saved prediction was not found")
    return model_prediction_payload(user_id)


@app.delete("/model-predictions/{prediction_id}")
async def remove_model_prediction(prediction_id: int, user_id: int = Depends(authenticated_user_id)):
    if not db.delete_model_prediction(user_id, prediction_id):
        raise HTTPException(status_code=404, detail="That saved prediction was not found")
    return model_prediction_payload(user_id)


@app.get("/prediction-checks")
async def read_prediction_checks(user_id: int = Depends(authenticated_user_id)):
    return prediction_check_payload(user_id)


@app.post("/prediction-checks", status_code=status.HTTP_201_CREATED)
async def create_prediction_check(body: PredictionCheckIn, user_id: int = Depends(authenticated_user_id)):
    db.add_prediction_check(user_id, body.model_dump())
    return prediction_check_payload(user_id)


@app.delete("/prediction-checks/{check_id}")
async def remove_prediction_check(check_id: int, user_id: int = Depends(authenticated_user_id)):
    if not db.delete_prediction_check(user_id, check_id):
        raise HTTPException(status_code=404, detail="That verified comparison was not found")
    return prediction_check_payload(user_id)


@app.get("/summary")
async def summary(user_id: int = Depends(authenticated_user_id)):
    totals, meals = db.get_daily_totals(user_id)
    profile = db.get_profile(user_id)
    return {"totals": totals, "meals": meals, "targets": profile}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
