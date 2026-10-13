import { useEffect, useState } from "react";
import { api, getAccessToken, setAccessToken } from "./api";
import ProfileSetup from "./components/ProfileSetup";
import NutritionLabel from "./components/NutritionLabel";
import FoodLogger from "./components/FoodLogger";
import AgentReceipt from "./components/AgentReceipt";
import MealHistory from "./components/MealHistory";
import ModelPrediction from "./components/ModelPrediction";

const emptyTotals = { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0 };

function BrandMark() {
  return <span className="brand-mark" aria-hidden="true">n</span>;
}

function AuthScreen({ onAuthenticated, notice }) {
  const [isLogin, setIsLogin] = useState(true);
  const [form, setForm] = useState({ username: "", password: "" });
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const credentials = { username: form.username.trim(), password: form.password };
      const result = isLogin ? await api.login(credentials) : await api.signup(credentials);
      setAccessToken(result.access_token);
      localStorage.setItem("nutri_username", result.username || credentials.username);
      onAuthenticated();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-story" aria-label="About Nutri-Agent">
        <div className="brand-lockup"><BrandMark /><span>nutri<span className="brand-light">agent</span></span></div>
        <div className="story-copy">
          <span className="eyebrow">A little more mindful, every day</span>
          <h1>Feel good about<br />what fuels you.</h1>
          <p>Keep track of what you eat, understand your patterns, and build habits that feel right for you.</p>
        </div>
        <div className="story-note"><span className="story-sun">✳</span><span>Nutrition tracking, with room for real life.</span></div>
        <span className="story-orb story-orb-one" aria-hidden="true" />
        <span className="story-orb story-orb-two" aria-hidden="true" />
      </section>

      <section className="auth-panel">
        <div className="auth-card">
          <div className="mobile-brand brand-lockup"><BrandMark /><span>nutri<span className="brand-light">agent</span></span></div>
          <div className="auth-heading">
            <span className="eyebrow">Your personal nutrition space</span>
            <h2>{isLogin ? "Welcome back" : "Start with a fresh page"}</h2>
            <p>{isLogin ? "Sign in to pick up where you left off." : "Create an account to start your own food journal."}</p>
          </div>

          <div className="auth-switch" role="tablist" aria-label="Account access">
            <button type="button" role="tab" aria-selected={isLogin} className={isLogin ? "selected" : ""} onClick={() => { setIsLogin(true); setError(""); }}>Sign in</button>
            <button type="button" role="tab" aria-selected={!isLogin} className={!isLogin ? "selected" : ""} onClick={() => { setIsLogin(false); setError(""); }}>Create account</button>
          </div>

          <form className="auth-form" onSubmit={submit}>
            <label htmlFor="auth-username">Username</label>
            <input
              id="auth-username"
              name="username"
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck="false"
              minLength={isLogin ? 1 : 3}
              maxLength={64}
              placeholder="Your username"
              value={form.username}
              onChange={(event) => setForm({ ...form, username: event.target.value })}
              required
            />

            <label htmlFor="auth-password">Password</label>
            <div className="password-field">
              <input
                id="auth-password"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete={isLogin ? "current-password" : "new-password"}
                minLength={isLogin ? 1 : 8}
                maxLength={72}
                placeholder={isLogin ? "Your password" : "At least 8 characters"}
                value={form.password}
                onChange={(event) => setForm({ ...form, password: event.target.value })}
                required
              />
              <button type="button" className="password-toggle" onClick={() => setShowPassword((shown) => !shown)} aria-label={showPassword ? "Hide password" : "Show password"}>
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>

            {notice && <p className="auth-notice" role="status">{notice}</p>}
            {error && <p className="form-error" role="alert">{error}</p>}
            {!isLogin && <p className="password-hint">Use at least 8 characters. Your password is stored as a secure hash.</p>}
            <button className="primary-button auth-submit" type="submit" disabled={submitting}>
              {submitting ? <><span className="button-spinner" aria-hidden="true" />Please wait…</> : isLogin ? "Sign in to your account" : "Create my account"}
            </button>
          </form>
          <p className="auth-footnote">By continuing, you agree to use nutrition estimates as general guidance, not medical advice.</p>
        </div>
        <footer className="auth-footer">Made for everyday choices <span>·</span> Your data stays tied to your account</footer>
      </section>
    </main>
  );
}

function DashboardSkeleton() {
  return <div className="dashboard-skeleton" aria-label="Loading your nutrition dashboard" role="status">
    <div className="skeleton skeleton-title" /><div className="skeleton skeleton-card" /><div className="skeleton skeleton-card" />
  </div>;
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(Boolean(getAccessToken()));
  const [authNotice, setAuthNotice] = useState("");
  const [profile, setProfile] = useState(null);
  const [totals, setTotals] = useState(emptyTotals);
  const [meals, setMeals] = useState([]);
  const [trace, setTrace] = useState([]);
  const [reply, setReply] = useState(null);
  const [dashboardError, setDashboardError] = useState("");
  const [loading, setLoading] = useState(Boolean(getAccessToken()));
  const [activeView, setActiveView] = useState("dashboard");
  const [dashboardReloadKey, setDashboardReloadKey] = useState(0);

  useEffect(() => {
    function expireSession() {
      setAuthenticated(false);
      setProfile(null);
      setTotals(emptyTotals);
      setMeals([]);
      setTrace([]);
      setReply(null);
      setAuthNotice("Your session expired. Sign in again to continue.");
    }
    window.addEventListener("nutri-session-expired", expireSession);
    return () => window.removeEventListener("nutri-session-expired", expireSession);
  }, []);

  useEffect(() => {
    if (!authenticated) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setDashboardError("");
    Promise.allSettled([api.getProfile(), api.getSummary()]).then(([profileResult, summaryResult]) => {
      if (cancelled) return;
      if (profileResult.status === "fulfilled") setProfile(profileResult.value);
      else if (profileResult.reason?.message?.includes("No profile saved")) setProfile(null);
      else if (!profileResult.reason?.message?.includes("expired")) setDashboardError(profileResult.reason?.message || "We could not load your profile.");
      if (summaryResult.status === "fulfilled") {
        setTotals(summaryResult.value.totals || emptyTotals);
        setMeals(summaryResult.value.meals || []);
        if (summaryResult.value.targets) setProfile(summaryResult.value.targets);
      } else if (!summaryResult.reason?.message?.includes("expired")) {
        setDashboardError(summaryResult.reason?.message || "We could not load your nutrition summary.");
      }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [authenticated, dashboardReloadKey]);

  function handleResult(result) {
    setTotals(result.totals || emptyTotals);
    setMeals(result.meals || []);
    setTrace(result.trace || []);
    setReply(result.reply || null);
  }

  function handleMealDeleted(result) {
    setTotals(result.totals || emptyTotals);
    setMeals(result.meals || []);
  }

  async function handleLogout() {
    try { await api.logout(); } catch { /* Local sign-out still works if the service is offline. */ }
    setAccessToken(null);
    localStorage.removeItem("nutri_username");
    setAuthenticated(false);
    setProfile(null);
    setTotals(emptyTotals);
    setMeals([]);
    setTrace([]);
    setReply(null);
  }

  if (!authenticated) return <AuthScreen onAuthenticated={() => { setAuthNotice(""); setAuthenticated(true); }} notice={authNotice} />;
  if (loading) return <div className="app-shell"><DashboardSkeleton /></div>;

  const username = localStorage.getItem("nutri_username") || "there";
  const today = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" }).format(new Date());

  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand-lockup" href="#main" aria-label="Nutri-Agent home" onClick={(event) => { event.preventDefault(); setActiveView("dashboard"); }}><BrandMark /><span>nutri<span className="brand-light">agent</span></span></a>
        <nav className="app-nav" aria-label="Main navigation"><button className={activeView === "dashboard" ? "active" : ""} onClick={() => setActiveView("dashboard")}>My nutrition</button><button className={activeView === "prediction" ? "active" : ""} onClick={() => setActiveView("prediction")}>Model prediction</button></nav>
        <div className="header-right"><span className="user-chip"><span className="user-avatar">{username.slice(0, 1).toUpperCase()}</span><span>{username}</span></span><button className="quiet-button" onClick={handleLogout}>Sign out</button></div>
      </header>

      {activeView === "prediction" ? <ModelPrediction /> : <>
      <main className="dashboard" id="main">
        <section className="welcome-row">
          <div><span className="eyebrow">Your daily overview</span><h1>Good day, {username}</h1><p>A small check-in can help you see how your choices add up.</p></div>
          <div className="date-pill"><span aria-hidden="true">◷</span>{today}</div>
        </section>

        {dashboardError && <div className="notice-bar" role="alert"><span>{dashboardError}</span><button className="quiet-button" onClick={() => setDashboardReloadKey((key) => key + 1)}>Try again</button></div>}

        <div className="dashboard-grid">
          <section className="dashboard-main-column">
            <ProfileSetup profile={profile} onSaved={setProfile} />
            <NutritionLabel totals={totals} targets={profile} />
            <section className="surface-card meal-card"><div className="section-heading"><div><span className="eyebrow">Today</span><h2>Your food log</h2></div><span className="count-pill">{meals.length} {meals.length === 1 ? "entry" : "entries"}</span></div><MealHistory meals={meals} onDeleted={handleMealDeleted} /></section>
          </section>

          <section className="dashboard-side-column">
            <FoodLogger onResult={handleResult} />
            {reply && <div className="reply-card"><span className="reply-icon" aria-hidden="true">✳</span><p>{reply}</p></div>}
            <AgentReceipt trace={trace} />
            <div className="helper-card"><span className="helper-icon" aria-hidden="true">✦</span><div><h3>Estimates, with context</h3><p>Food logging can use estimates when exact nutrition data is unavailable. Check the source label beside each entry.</p></div></div>
          </section>
        </div>
      </main>
      <footer className="app-footer">Nutri-Agent <span>·</span> For general wellness tracking</footer>
      </>}
    </div>
  );
}
