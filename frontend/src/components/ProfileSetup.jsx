import { useState } from "react";
import { api } from "../api";

const defaults = { height_cm: 170, weight_kg: 70, age: 25, sex: "female", activity_level: "light", goal: "maintain" };

export default function ProfileSetup({ profile, onSaved }) {
  const [form, setForm] = useState(() => profile || defaults);
  const [open, setOpen] = useState(!profile);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const saved = await api.saveProfile({
        ...form,
        height_cm: Number(form.height_cm),
        weight_kg: Number(form.weight_kg),
        age: Number(form.age),
      });
      setForm(saved);
      onSaved(saved);
      setOpen(false);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return <section className="profile-summary surface-card">
      <div><span className="eyebrow">Personal plan</span><strong>{profile?.calorie_target ? `${Math.round(profile.calorie_target).toLocaleString()} kcal target` : "Your nutrition profile"}</strong><p>{profile?.bmi ? `BMI ${profile.bmi} · ${profile.bmi_category}` : "Your targets are ready to use."}</p></div>
      <button className="quiet-button" onClick={() => { setForm(profile || defaults); setOpen(true); }}>Edit profile</button>
    </section>;
  }

  return <form onSubmit={submit} className="profile-form surface-card">
    <div className="section-heading"><div><span className="eyebrow">Personal plan</span><h2>{profile ? "Update your profile" : "Set your starting point"}</h2></div>{profile && <button type="button" className="icon-button" aria-label="Close profile editor" onClick={() => setOpen(false)}>×</button>}</div>
    <p className="profile-intro">A few details help us calculate a useful daily target. You can change these any time.</p>
    <div className="profile-fields">
      <label>Height <span>cm</span><input type="number" min="51" max="300" step="0.1" value={form.height_cm} onChange={(event) => setForm({ ...form, height_cm: event.target.value })} required /></label>
      <label>Weight <span>kg</span><input type="number" min="10.1" max="500" step="0.1" value={form.weight_kg} onChange={(event) => setForm({ ...form, weight_kg: event.target.value })} required /></label>
      <label>Age <span>years</span><input type="number" min="10" max="120" value={form.age} onChange={(event) => setForm({ ...form, age: event.target.value })} required /></label>
      <label>Sex<select value={form.sex} onChange={(event) => setForm({ ...form, sex: event.target.value })}><option value="female">Female</option><option value="male">Male</option></select></label>
      <label>Activity level<select value={form.activity_level} onChange={(event) => setForm({ ...form, activity_level: event.target.value })}><option value="sedentary">Mostly sitting</option><option value="light">Light activity</option><option value="moderate">Moderately active</option><option value="active">Very active</option><option value="very_active">Highly active</option></select></label>
      <label>Your goal<select value={form.goal} onChange={(event) => setForm({ ...form, goal: event.target.value })}><option value="lose">Lose weight</option><option value="maintain">Maintain weight</option><option value="gain">Build muscle</option></select></label>
    </div>
    {error && <p className="form-error" role="alert">{error}</p>}
    <div className="profile-actions"><p>Targets are estimates for general wellness, not medical advice.</p><button className="primary-button" type="submit" disabled={saving}>{saving ? "Calculating…" : "Save my targets"}</button></div>
  </form>;
}
