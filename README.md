# Nutri-Agent

Nutri-Agent is a personal nutrition journal with a React/Vite client, FastAPI service, SQLite storage, and a Groq-backed MCP agent. It supports manual meal entry, natural-language food logging, profile-based nutrition targets, and live model predictions.

## Project layout

```text
backend/
  main.py          FastAPI routes, validation, bearer authentication
  db.py            SQLite persistence and additive schema setup
  gateway.py       Groq model gateway
  orchestrator.py  MCP tool bridge and agent loop
  mcp_server.py    USDA lookup and account-scoped nutrition tools
frontend/
  index.html       Vite entry document
  src/App.jsx      Authentication, navigation, and nutrition dashboard
  src/components/  Profile, logging, nutrition, history, and prediction UI
```

The backend creates the database tables and indexes at startup. Existing user, profile, and meal tables are kept; authentication sessions are added without replacing existing data.

## Run locally

Use Python 3.10+ and Node.js 18+.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:5173`; the API runs at `http://localhost:8000`. Set `VITE_API_URL` in `frontend/.env.local` to point the client at a different API URL. Production defaults to the current Render API URL.

## Deployment

The root `render.yaml` Blueprint deploys both the FastAPI API and Vite frontend on Render; Vercel is not required. In Render, create a Blueprint from this repository and set `GROQ_API_KEY` when prompted. USDA lookup is optional. The frontend is a free Render Static Site; the API uses Render Free. The API sleeps after 15 minutes without traffic, so its first request after idle can take about a minute to wake. Its filesystem is temporary: SQLite accounts, profiles, meals, and prediction history can be lost after a restart, redeploy, or spin-down. This setup is suitable for a free demo, not durable personal data storage. The local database and `.env.local` must not be uploaded. If Render assigns a different frontend hostname, update the API's `CORS_ORIGINS` to include that exact origin.

## Configuration

Copy `backend/.env.example` to `backend/.env`. Keep provider keys in the backend environment only.

| Variable | Purpose |
| --- | --- |
| `GROQ_API_KEY` | Enables model predictions and AI food logging. Without it, sign-in, profiles, and manual logging can still run. |
| `GROQ_MODEL` | Optional Groq model ID; defaults to `openai/gpt-oss-20b`. If a configured model is unavailable, the backend retries with that default. |
| `USDA_API_KEY` | USDA FoodData Central API key. If unset, the backend uses USDA's public `DEMO_KEY`, which is heavily rate limited; add your own free key in Render for reliable lookups. |
| `CORS_ORIGINS` | Comma-separated exact browser origins allowed to call the API. |
| `NUTRI_DATABASE_PATH` | Optional SQLite file path. Defaults to `backend/nutri_agent.db`. |
| `LOG_LEVEL` | Optional server log level; defaults to `INFO`. |

Frontend configuration:

```env
VITE_API_URL=http://localhost:8000
```

Do not put Groq or USDA credentials in any `VITE_` variable. Vite embeds those values in browser assets.

## Authentication and data ownership

Signup and login return a random, expiring bearer token. Only its SHA-256 hash is stored in SQLite. The frontend stores the token in browser storage and sends it in the `Authorization: Bearer …` header. Account-scoped routes derive the user id from that session; request bodies and query strings cannot select another user's account. Logout revokes the current session. Users with an old numeric `nutri_user_id` value will need to sign in again; saved nutrition data remains in the existing database.

Passwords are bcrypt-hashed, new passwords must be at least eight characters, and passwords longer than bcrypt's 72-byte input limit are rejected instead of being silently truncated. AI tool calls receive the authenticated user id from the API layer, not from model-generated arguments.

## Nutrition data and limitations

- A USDA meal source is recorded only when an actual USDA search result was returned during that agent run. Other AI-created values are labeled as estimates.
- USDA values are references and can differ by preparation, brand, and portion. AI-generated nutrition values are estimates.
- Manual nutrition entries are stored as entered. The app does not infer missing values.
- Profile targets use deterministic BMI and Mifflin–St Jeor calculations with activity and goal adjustments. They are general estimates, not individualized medical advice.
- Image uploads, OpenFoodFacts, water tracking, history analytics, and coaching are not implemented in the current codebase.

## Live model prediction

Open **Model prediction** after signing in and type a meal description. The AI returns predicted calories and macros, its data source, the model's explanation, and response time. Predictions in this view do not change the food log; use **Describe meal** on the dashboard when you want the AI to estimate and save a meal, or **Enter nutrition** for manual values. No dataset file is needed. To calculate model metrics, record actual values from a package or independently checked source alongside a prediction. Classification accuracy, precision, recall, F1, specificity, balanced accuracy, Matthews correlation, per-label scores, and a confusion matrix are calculated from these verified comparisons. Nutrition metrics include MAE, MSE, RMSE, signed and median absolute error, MAPE, WAPE, and R². Deleting a saved comparison removes it from all scores.

If AI is unavailable, the page reports whether the backend is missing `GROQ_API_KEY`, the agent failed to start, or the provider could not complete the request. USDA lookup is optional; without it, the model can still return a clearly labeled estimate. USDA energy is normalized to kcal (including kJ-to-kcal conversion) before the model uses it; macro amounts are normalized to grams.

## API routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/health` | API and AI readiness status |
| `POST` | `/signup`, `/login` | Create a session or sign in |
| `POST` | `/logout` | Revoke the bearer session |
| `GET`, `POST` | `/profile` | Read or calculate the current account profile |
| `GET` | `/summary` | Current day's totals and meals |
| `POST` | `/log-food` | Agent-assisted food logging |
| `POST` | `/predict-food` | Live prediction, automatically saved to prediction history |
| `GET` | `/model-predictions` | Read saved model results and metrics |
| `PUT` | `/model-predictions/{prediction_id}/actual` | Save actual values and recalculate metrics |
| `DELETE` | `/model-predictions/{prediction_id}` | Delete a saved model result |
| `POST` | `/log-manual` | Validated manual meal entry |
| `DELETE` | `/meals/{meal_id}` | Delete a meal owned by the current account |
| `GET`, `POST` | `/prediction-checks` | Read or save verified prediction comparisons and calculated metrics |
| `DELETE` | `/prediction-checks/{check_id}` | Delete a comparison and recalculate metrics |

## Checks

```powershell
cd backend
python -m unittest discover -s tests

cd ..\frontend
npm run build
```

Unit tests use deterministic local examples and do not call Groq or USDA.
