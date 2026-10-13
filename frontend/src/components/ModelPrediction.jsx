import { useEffect, useState } from "react";
import { api } from "../api";

const nutrients = [
  ["protein_g", "Protein", "g"], ["carbs_g", "Carbs", "g"],
  ["fat_g", "Fat", "g"], ["fiber_g", "Fiber", "g"],
];
const actualFields = [
  ["actual_calories", "Calories", "kcal"], ["actual_protein_g", "Protein", "g"],
  ["actual_carbs_g", "Carbs", "g"], ["actual_fat_g", "Fat", "g"], ["actual_fiber_g", "Fiber", "g"],
];

function score(value, digits = 1) {
  return value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toFixed(digits);
}

function ActualValuesForm({ prediction, onSave }) {
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const payload = { actual_food: String(form.get("actual_food")).trim() };
    for (const [key] of actualFields) payload[key] = Number(form.get(key));
    setSaving(true);
    try {
      await onSave(prediction.id, payload);
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  return <form className="actual-values-form" onSubmit={submit}>
    <span className="eyebrow">Actual values</span>
    <label className="verification-label">Food name<input className="field-input" name="actual_food" maxLength="120" required defaultValue={prediction.actual_food || ""} placeholder="Food name" /></label>
    <div className="verification-grid">{actualFields.map(([key, label, unit]) => <label className="verification-label" key={key}>{label} ({unit})<input className="field-input" name={key} type="number" min="0" max={key === "actual_calories" ? "100000" : "10000"} step="any" required defaultValue={prediction[key] ?? ""} /></label>)}</div>
    {error && <p className="prediction-alert" role="alert">{error}</p>}
    <button type="submit" className="quiet-button" disabled={saving}>{saving ? "Saving…" : prediction.actual_food ? "Update actual values" : "Save actual values"}</button>
  </form>;
}

function MetricSummary({ data }) {
  const classification = data?.classification;
  const nutrition = data?.nutrition;
  if (!classification || classification.sample_count === 0) return <div className="surface-card metrics-card"><span className="eyebrow">Model performance</span><h2>Metrics</h2><p className="prediction-copy">Saved predictions appear automatically. Enter actual values for a result to calculate the scores.</p></div>;

  return <section className="surface-card metrics-card">
    <div className="section-heading"><div><span className="eyebrow">Saved model results</span><h2>Prediction metrics</h2></div><span className="count-pill">{classification.sample_count} {classification.sample_count === 1 ? "compared result" : "compared results"}</span></div>
    <p className="prediction-copy">Scores update from predictions with saved actual values. Food names are matched without case or extra-space differences.</p>
    <h3 className="metrics-subheading">Food label classification</h3>
    <div className="metrics-grid">{[
      ["Accuracy", classification.accuracy], ["Balanced accuracy", classification.balanced_accuracy], ["Macro precision", classification.macro_precision], ["Macro recall", classification.macro_recall], ["Macro F1", classification.macro_f1],
      ["Weighted precision", classification.weighted_precision], ["Weighted recall", classification.weighted_recall], ["Weighted F1", classification.weighted_f1], ["Micro F1", classification.micro_f1],
    ].map(([label, value]) => <div key={label}><span>{label}</span><strong>{value == null ? "—" : `${score(value * 100)}%`}</strong></div>)}{<div><span>Matthews correlation</span><strong>{score(classification.matthews_correlation_coefficient, 3)}</strong></div>}</div>
    <details className="metrics-details"><summary>Per-label scores and confusion matrix</summary>
      <div className="metrics-table-wrap"><table className="metrics-table"><thead><tr><th>Food label</th><th>Precision</th><th>Recall</th><th>Specificity</th><th>F1</th><th>TP</th><th>FP</th><th>FN</th><th>TN</th><th>Support</th></tr></thead><tbody>{classification.per_class.map((row) => <tr key={row.label}><th>{row.label}</th><td>{score(row.precision * 100)}%</td><td>{score(row.recall * 100)}%</td><td>{score(row.specificity * 100)}%</td><td>{score(row.f1 * 100)}%</td><td>{row.true_positive}</td><td>{row.false_positive}</td><td>{row.false_negative}</td><td>{row.true_negative}</td><td>{row.support}</td></tr>)}</tbody></table></div>
      <p className="confusion-caption">Confusion matrix: rows are actual labels; columns are predicted labels.</p>
      <div className="metrics-table-wrap"><table className="metrics-table"><thead><tr><th>Actual ↓ / Predicted →</th>{classification.labels.map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{classification.labels.map((label, row) => <tr key={label}><th>{label}</th>{classification.confusion_matrix[row].map((count, column) => <td key={`${row}-${column}`}>{count}</td>)}</tr>)}</tbody></table></div>
    </details>
    <h3 className="metrics-subheading">Nutrition regression errors</h3>
    <div className="metrics-table-wrap"><table className="metrics-table nutrition-metrics"><thead><tr><th>Nutrient</th><th>MAE</th><th>MSE</th><th>RMSE</th><th>Mean error</th><th>Median abs. error</th><th>MAPE</th><th>WAPE</th><th>R²</th></tr></thead><tbody>{Object.entries(nutrition).map(([name, row]) => <tr key={name}><th>{name === "calories" ? "Calories (kcal)" : `${name.replace("_g", "")} (g)`}</th><td>{score(row.mae)}</td><td>{score(row.mse)}</td><td>{score(row.rmse)}</td><td>{score(row.mean_error)}</td><td>{score(row.median_absolute_error)}</td><td>{row.mape == null ? "—" : `${score(row.mape * 100)}%`}</td><td>{row.wape == null ? "—" : `${score(row.wape * 100)}%`}</td><td>{score(row.r_squared, 3)}</td></tr>)}</tbody></table></div>
    <p className="metrics-footnote">MAE = mean absolute error; RMSE = root mean squared error. MAPE ignores zero actual values; WAPE is weighted by actual total. R² requires at least two varying actual values. Classification metrics use exact food labels after case and whitespace normalization.</p>
  </section>;
}

export default function ModelPrediction() {
  const [description, setDescription] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [aiStatus, setAiStatus] = useState("checking");
  const [predictions, setPredictions] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [historyError, setHistoryError] = useState("");
  const [deletingId, setDeletingId] = useState(null);

  useEffect(() => {
    let active = true;
    api.getHealth().then((health) => {
      if (active) setAiStatus(health.ai_status || (health.ai_available ? "ready" : "unavailable"));
    }).catch(() => { if (active) setAiStatus("unreachable"); });
    api.getModelPredictions().then((data) => {
      if (active) { setPredictions(data.predictions || []); setMetrics(data.metrics); }
    }).catch((requestError) => { if (active) setHistoryError(requestError.message); });
    return () => { active = false; };
  }, []);

  async function predict(event) {
    event.preventDefault();
    if (!description.trim()) return;
    setLoading(true); setError(""); setResult(null);
    try {
      const data = await api.predictFood(description.trim());
      setResult(data);
      setPredictions(data.saved_predictions || []);
      setMetrics(data.metrics);
      setHistoryError("");
      setDescription("");
    }
    catch (requestError) { setError(requestError.message); }
    finally { setLoading(false); }
  }

  async function saveActual(id, payload) {
    try {
      const data = await api.saveModelPredictionActual(id, payload);
      setPredictions(data.predictions || []); setMetrics(data.metrics); setHistoryError("");
    } catch (requestError) {
      setHistoryError(requestError.message);
      throw requestError;
    }
  }

  async function deletePrediction(id) {
    setDeletingId(id); setHistoryError("");
    try {
      const data = await api.deleteModelPrediction(id);
      setPredictions(data.predictions || []); setMetrics(data.metrics);
    } catch (requestError) { setHistoryError(requestError.message); }
    finally { setDeletingId(null); }
  }

  const unavailableMessage = aiStatus === "missing_groq_api_key"
    ? "AI predictions need GROQ_API_KEY configured in the backend environment."
    : aiStatus === "mcp_startup_failed" || aiStatus === "mcp_not_ready"
      ? "The AI food service did not start. Check the backend logs."
      : aiStatus === "unreachable" ? "Could not check AI availability. The backend may be offline." : "";

  return <main className="prediction-page">
    <section className="prediction-heading"><div><span className="eyebrow">Ask the nutrition model</span><h1>Model predictions</h1><p>Results save automatically. Add actual values to calculate model performance.</p></div>{result && <div className="prediction-latency"><strong>{result.latency_ms} ms</strong><span>latest response</span></div>}</section>
    {unavailableMessage && <div className="notice-bar prediction-notice" role="status">{unavailableMessage}</div>}
    {error && <div className="notice-bar prediction-alert" role="alert">{error}</div>}
    <div className="prediction-layout">
      <section className="surface-card prediction-form-card"><span className="eyebrow">Try a prediction</span><h2>What did you eat?</h2><p className="prediction-copy">Mention portion size when you can. The model checks available nutrition data and clearly labels estimates.</p>
        <form onSubmit={predict}><label className="visually-hidden" htmlFor="prediction-description">Describe a food or meal</label><textarea id="prediction-description" className="prediction-textarea" rows="5" maxLength="2000" placeholder="For example: one medium bowl of chicken soup, about 350 ml" value={description} onChange={(event) => setDescription(event.target.value)} required /><div className="prediction-form-footer"><span>Each result is saved to your prediction history.</span><span>{description.length}/2000</span></div><button className="primary-button prediction-submit" type="submit" disabled={loading || !description.trim()}>{loading ? <><span className="button-spinner" aria-hidden="true" />Predicting…</> : "Predict and save"}</button></form>
      </section>
      <section className="prediction-results" aria-live="polite">
        {!result && !loading && <div className="surface-card prediction-empty"><span className="empty-diamond" aria-hidden="true">✳</span><h2>Your saved results</h2><p>Model predictions are kept here automatically, even after you leave this page.</p></div>}
        {loading && <div className="surface-card prediction-empty" role="status"><span className="button-spinner" aria-hidden="true" /><h2>Working on your prediction</h2><p>Checking the description and available nutrition data…</p></div>}
        {result && <section className="surface-card prediction-explanation"><span className="eyebrow">Latest prediction saved</span><p>{result.reply}</p><small>{result.model} · {result.latency_ms} ms · stored in your prediction history, not your food log</small></section>}
      </section>
    </div>
    <div className="prediction-data-section"><MetricSummary data={metrics} />
      <section className="surface-card verified-list"><div className="section-heading"><div><span className="eyebrow">Prediction history</span><h2>Predicted and actual values</h2></div><span className="count-pill">{predictions.length} {predictions.length === 1 ? "result" : "results"}</span></div>{historyError && <p className="prediction-alert" role="alert">{historyError}</p>}{!predictions.length ? <p className="prediction-copy">Run a prediction above. Its values will be saved here automatically.</p> : <div className="saved-prediction-list">{predictions.map((prediction) => <article className="saved-prediction" key={prediction.id}>
        <div className="saved-prediction-top"><div><span className="eyebrow">{new Date(prediction.created_at).toLocaleString()}</span><h3>{prediction.predicted_food}</h3><p>{prediction.description}</p></div><div className="saved-prediction-actions"><span className={`source-pill ${prediction.source === "usda" ? "source-usda" : "source-estimated"}`}>{prediction.source === "usda" ? "USDA reference" : "Model estimate"}</span><button className="entry-delete-button" type="button" disabled={deletingId === prediction.id} onClick={() => deletePrediction(prediction.id)}>{deletingId === prediction.id ? "Removing…" : "Delete"}</button></div></div>
        <div className="prediction-value-columns"><div className="predicted-values"><span className="eyebrow">Predicted values</span><strong>{score(prediction.predicted_calories)} <small>kcal</small></strong>{nutrients.map(([key, label, unit]) => <p key={key}><span>{label}</span><b>{score(prediction[`predicted_${key}`])} {unit}</b></p>)}</div><ActualValuesForm key={`${prediction.id}-${prediction.actual_food || "new"}`} prediction={prediction} onSave={saveActual} /></div>
      </article>)}</div>}</section>
    </div>
  </main>;
}
