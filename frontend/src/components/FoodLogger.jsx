import { useState } from "react";
import { api } from "../api";

const emptyManual = { food_name: "", calories: "", protein_g: "", carbs_g: "", fat_g: "", fiber_g: "" };
const manualFields = [
  ["calories", "Calories", "kcal"], ["protein_g", "Protein", "g"],
  ["carbs_g", "Carbohydrates", "g"], ["fat_g", "Fat", "g"], ["fiber_g", "Fiber", "g"],
];

export default function FoodLogger({ onResult }) {
  const [message, setMessage] = useState("");
  const [manual, setManual] = useState(emptyManual);
  const [showManual, setShowManual] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submitAgent(event) {
    event.preventDefault();
    if (!message.trim()) return;
    setLoading(true);
    setError("");
    try {
      onResult(await api.logFood(message.trim()));
      setMessage("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  async function submitManual(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    const payload = { food_name: manual.food_name.trim() };
    manualFields.forEach(([field]) => { payload[field] = Number(manual[field]); });
    try {
      const result = await api.logManual(payload);
      onResult({ ...result, reply: `Added ${payload.food_name} to today's log.`, trace: [] });
      setManual(emptyManual);
      setShowManual(false);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  return <section className="logger-card surface-card">
    <div className="section-heading"><div><span className="eyebrow">Make a note</span><h2>Log a meal</h2></div><span className="logger-icon" aria-hidden="true">＋</span></div>
    <p className="logger-description">Describe what you ate in your own words. We’ll use available nutrition data or clearly labeled estimates.</p>
    <div className="logger-mode" role="group" aria-label="Choose logging method">
      <button type="button" aria-pressed={!showManual} className={!showManual ? "active" : ""} onClick={() => { setShowManual(false); setError(""); }}>Describe meal</button>
      <button type="button" aria-pressed={showManual} className={showManual ? "active" : ""} onClick={() => { setShowManual(true); setError(""); }}>Enter nutrition</button>
    </div>

    {!showManual ? <form onSubmit={submitAgent}>
      <label className="visually-hidden" htmlFor="food-description">Describe your meal</label>
      <textarea id="food-description" className="food-textarea" rows="4" maxLength="2000" placeholder="For example: a bowl of lentil soup, two slices of toast, and a cup of tea" value={message} onChange={(event) => setMessage(event.target.value)} required />
      <div className="textarea-footer"><span>Food estimates can vary by recipe and portion.</span><span>{message.length}/2000</span></div>
      <button className="primary-button logger-submit" type="submit" disabled={loading || !message.trim()}>{loading ? <><span className="button-spinner" aria-hidden="true" />Working on it…</> : "Add to my food log"}</button>
    </form> : <form onSubmit={submitManual} className="manual-form">
      <label className="field-label" htmlFor="manual-food">Food, meal, and portion</label>
      <input className="field-input" id="manual-food" type="text" maxLength="120" placeholder="e.g. Homemade vegetable soup, 350 ml" value={manual.food_name} onChange={(event) => setManual({ ...manual, food_name: event.target.value })} required />
      <div className="manual-grid">{manualFields.map(([field, label, unit]) => <label key={field} className="field-label">{label} <span>({unit})</span><input className="field-input" type="number" min="0" max={field === "calories" ? "100000" : "10000"} step="0.1" value={manual[field]} onChange={(event) => setManual({ ...manual, [field]: event.target.value })} required /></label>)}</div>
      <button className="primary-button logger-submit" type="submit" disabled={loading}>{loading ? "Saving…" : "Save nutrition values"}</button>
    </form>}
    {error && <p className="form-error logger-error" role="alert">{error}</p>}
  </section>;
}
