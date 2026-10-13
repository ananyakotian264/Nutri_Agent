function MacroRow({ label, amount, target, color }) {
  const value = Number(amount) || 0;
  const percent = target ? Math.min((value / target) * 100, 100) : 0;
  return <div className="macro-row">
    <div className="macro-row-top"><span><i style={{ backgroundColor: color }} />{label}</span><strong>{Math.round(value)}<small> g</small>{target ? <em> / {Math.round(target)} g</em> : null}</strong></div>
    {target ? <div className="macro-track"><div style={{ width: `${percent}%`, backgroundColor: color }} /></div> : null}
  </div>;
}

export default function NutritionLabel({ totals = {}, targets }) {
  const consumed = Number(totals.calories) || 0;
  const calorieTarget = Number(targets?.calorie_target) || 0;
  const progress = calorieTarget ? Math.min(consumed / calorieTarget * 100, 100) : 0;
  const remaining = calorieTarget - consumed;

  return <section className="nutrition-card surface-card">
    <div className="section-heading"><div><span className="eyebrow">Your day, in balance</span><h2>Nutrition progress</h2></div><span className="sparkle" aria-hidden="true">✳</span></div>
    <div className="calorie-overview"><div><span className="calorie-total">{Math.round(consumed).toLocaleString()}</span><span className="calorie-unit">kcal</span></div>{calorieTarget ? <span className="calorie-target">of {Math.round(calorieTarget).toLocaleString()} kcal</span> : <span className="calorie-target">Set a profile to add your daily target</span>}</div>
    <div className="calorie-track" role="progressbar" aria-label="Daily calories" aria-valuemin="0" aria-valuemax={calorieTarget || 0} aria-valuenow={consumed}><div style={{ width: `${progress}%` }} /></div>
    {calorieTarget ? <p className="calorie-context">{remaining >= 0 ? `${Math.round(remaining).toLocaleString()} kcal to your estimated target` : `${Math.round(Math.abs(remaining)).toLocaleString()} kcal above your estimated target`}</p> : null}
    <div className="macro-divider" />
    <MacroRow label="Protein" amount={totals.protein_g} target={targets?.protein_target_g} color="#76966b" />
    <MacroRow label="Carbohydrates" amount={totals.carbs_g} target={targets?.carb_target_g} color="#d99a59" />
    <MacroRow label="Fat" amount={totals.fat_g} target={targets?.fat_target_g} color="#c77b79" />
    <MacroRow label="Fiber" amount={totals.fiber_g} target={targets?.fiber_target_g} color="#6d91a0" />
    <p className="nutrition-footnote">Targets are general estimates from your profile. Logged meals may include estimated values.</p>
  </section>;
}
