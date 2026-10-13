import { useState } from "react";
import { api } from "../api";

const sourceLabel = { usda: "USDA data", estimated: "Estimated", manual: "Entered by you" };

export default function MealHistory({ meals = [], onDeleted }) {
  const [deletingId, setDeletingId] = useState(null);
  const [error, setError] = useState("");

  async function removeMeal(meal) {
    setDeletingId(meal.id);
    setError("");
    try {
      onDeleted(await api.deleteMeal(meal.id));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setDeletingId(null);
    }
  }

  if (!meals.length) return <div className="meal-empty"><span aria-hidden="true">◌</span><p>Your food log is empty for today.</p><small>Add a meal when you’re ready. It’s fine to start with a rough description.</small></div>;

  return <div className="meal-list">{error && <p className="meal-delete-error" role="alert">{error}</p>}{[...meals].reverse().map((meal) => <article className="meal-item" key={meal.id}>
    <span className={`meal-source-dot ${meal.source || "unknown"}`} aria-hidden="true" />
    <div className="meal-details"><strong>{meal.food_name}</strong><span>{sourceLabel[meal.source] || "Nutrition source not available"}{meal.logged_at ? ` · ${new Date(meal.logged_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : ""}</span></div>
    <div className="meal-calories"><strong>{Math.round(Number(meal.calories) || 0)}</strong><span>kcal</span></div>
    <button type="button" className="entry-delete-button" aria-label={`Delete ${meal.food_name}`} disabled={deletingId === meal.id} onClick={() => removeMeal(meal)}>{deletingId === meal.id ? "Removing…" : "Delete"}</button>
  </article>)}</div>;
}
