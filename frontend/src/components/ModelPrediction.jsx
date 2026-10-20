import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

const nutrients = [
  ["calories", "Calories", "kcal"], ["protein_g", "Protein", "g"],
  ["carbs_g", "Carbohydrates", "g"], ["fat_g", "Fat", "g"], ["fiber_g", "Fiber", "g"],
];

function value(number, digits = 1) {
  return number == null || !Number.isFinite(Number(number)) ? "—" : Number(number).toFixed(digits);
}

function QualityOverview({ metrics }) {
  const counts = metrics?.match_strength_counts || {};
  const total = metrics?.total_count || 0;
  const matched = metrics?.usda_match_count || 0;
  const high = counts.high || 0;
  const average = metrics?.average_match_score;
  const direct = metrics?.direct_source_count || 0;

  return <section className="surface-card metrics-card">
    <div className="section-heading"><div><span className="eyebrow">Automatic food match audit</span><h2>Retrieved data quality</h2></div><span className="count-pill">{total} {total === 1 ? "meal" : "meals"}</span></div>
    <p className="prediction-copy">USDA candidates are automatically reranked with token overlap and character TF-IDF similarity. When a suitable record and portion are available, the app calculates nutrients directly from USDA values instead of asking the language model to copy them.</p>
    <div className="evolution-kpis">
      <div><span>USDA match coverage</span><strong>{metrics?.reference_coverage_percent == null ? "—" : `${value(metrics.reference_coverage_percent)}%`}</strong><small>{matched} of {total} saved meals had a usable USDA match</small></div>
      <div><span>High relevance matches</span><strong>{total ? `${high} / ${total}` : "—"}</strong><small>Strongest lexical match group</small></div>
      <div><span>Average match relevance</span><strong>{average == null ? "—" : `${value(average)}/100`}</strong><small>{metrics?.score_count || 0} USDA matches scored</small></div>
      <div><span>Nutrition from USDA</span><strong>{direct} / {total}</strong><small>Values calculated directly for the portion</small></div>
    </div>
    <p className="metric-definition">Match relevance is a heuristic ranking score, not a probability or accuracy percentage. It measures text similarity between your food query and USDA candidate names. Real accuracy, precision, and nutrient error require independent labeled truth; this page does not claim those from a self-comparison.</p>
    <div className="nutrition-error-section">
      <h3>Match relevance breakdown</h3>
      <div className="nutrition-error-table-wrap"><table className="nutrition-error-table"><thead><tr><th>Match group</th><th>Meals</th><th>Meaning</th></tr></thead><tbody>
        <tr><th>High</th><td>{counts.high || 0}</td><td>Strong text match; still review the selected food</td></tr>
        <tr><th>Medium</th><td>{counts.medium || 0}</td><td>Possible match; less certain wording overlap</td></tr>
        <tr><th>Low</th><td>{counts.low || 0}</td><td>Weak match; app falls back to estimate values</td></tr>
        <tr><th>No USDA match</th><td>{Math.max(0, total - matched)}</td><td>No usable candidate returned by USDA</td></tr>
      </tbody></table></div>
    </div>
  </section>;
}

function NutritionValues({ prediction }) {
  if (!prediction.reference_verified) return <div className="audit-unverified"><strong>AI estimate · not independently verified</strong><span>No sufficiently relevant USDA record and complete portion data were available.</span></div>;
  return <div className="compared-values">
    <div className="compared-row compared-heading"><span>Nutrient</span><span>Calculated serving value</span><span>Source</span><span>Portion</span></div>
    {nutrients.map(([key, label, unit]) => <div className="compared-row" key={key}>
      <span>{label}</span><strong>{value(prediction[`predicted_${key}`])} {unit}</strong>
      <span>USDA · {prediction.reference_food}</span><span>{value(prediction.portion_grams, 0)} g</span>
    </div>)}
  </div>;
}

export default function ModelPrediction() {
  const [predictions, setPredictions] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState(null);

  const refresh = useCallback(async () => {
    const data = await api.getModelPredictions();
    const rows = data.predictions || [];
    if (!Number.isInteger(data.metrics?.total_count) || data.metrics.total_count !== rows.length) {
      setPredictions(rows);
      setMetrics(null);
      throw new Error("The food data audit is out of sync. Deploy the backend and frontend from the same project version.");
    }
    setPredictions(rows);
    setMetrics(data.metrics);
    setError("");
  }, []);

  useEffect(() => {
    let active = true;
    refresh().catch((requestError) => { if (active) setError(requestError.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [refresh]);

  async function deleteAudit(id) {
    setDeletingId(id);
    try { await api.deleteModelPrediction(id); await refresh(); }
    catch (requestError) { setError(requestError.message); }
    finally { setDeletingId(null); }
  }

  const directCount = predictions.filter((row) => row.reference_verified).length;

  return <main className="prediction-page">
    <section className="prediction-heading"><div><span className="eyebrow">Automatic retrieval quality</span><h1>Food data quality</h1><p>Matches and nutrition values are checked automatically as meals are logged.</p></div></section>
    {error && <div className="notice-bar prediction-alert" role="alert">{error}</div>}
    <div className="prediction-data-section">
      <QualityOverview metrics={metrics} />
      <section className="surface-card verified-list">
        <div className="section-heading"><div><span className="eyebrow">Retrieved food data</span><h2>Automatic audit history</h2></div><span className="count-pill">{directCount} USDA · {predictions.length - directCount} estimated</span></div>
        <p className="prediction-copy">The relevance score describes name matching only. It cannot confirm serving size or prove USDA data is correct for the food you ate.</p>
        {loading ? <p className="prediction-copy" role="status">Loading food data…</p> : !predictions.length ? <div className="evolution-empty-state"><h3>No AI meal results yet</h3><p>Log a meal using Describe meal. USDA match quality and calculated nutrient values will appear automatically when available.</p></div> : <div className="saved-prediction-list">{predictions.map((prediction) => <article className="saved-prediction" key={prediction.id}>
          <div className="saved-prediction-top"><div><span className="eyebrow">{new Date(prediction.created_at).toLocaleString()}</span><h3>{prediction.predicted_food}</h3><p>Input: {prediction.description}{prediction.portion_grams ? ` · ${value(prediction.portion_grams, 0)} g portion` : ""}</p></div><div className="saved-prediction-actions"><span className={`source-pill ${prediction.reference_verified ? "source-usda" : "source-estimated"}`}>{prediction.matched_food ? `${prediction.match_strength || "unscored"} match · ${value(prediction.match_score)} / 100` : "No USDA match"}</span><button className="entry-delete-button" type="button" disabled={deletingId === prediction.id} onClick={() => deleteAudit(prediction.id)}>{deletingId === prediction.id ? "Removing…" : "Delete audit"}</button></div></div>
          <NutritionValues prediction={prediction} />
        </article>)}</div>}
      </section>
    </div>
  </main>;
}
