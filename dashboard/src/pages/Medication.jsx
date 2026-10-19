import { useState } from "react";
import { api } from "../api.js";
import { useAction, usePoll } from "../hooks.js";
import { clock12 } from "../format.js";

export default function Medication({ patient }) {
  const schedules = usePoll(() => api.get(`/patients/${patient.id}/schedules`), 0, [patient.id]);
  const rowAction = useAction();

  async function toggle(s) {
    await rowAction.run(() => api.patch(`/schedules/${s.id}`, { active: !s.active }));
    schedules.reload();
  }

  async function remove(s) {
    if (!window.confirm(`Remove ${s.name} at ${clock12(s.time_of_day)}? Past records stay.`)) return;
    await rowAction.run(() => api.del(`/schedules/${s.id}`));
    schedules.reload();
  }

  const list = schedules.data || [];

  return (
    <div className="stack-lg">
      <div>
        <h1 className="display">Medication</h1>
        <p className="muted">
          The glasses remind {patient.name} at each time below and listen for the packaging. A dose counts as taken if it is
          confirmed from one hour before the time until the window closes. Times are in {patient.timezone}.
        </p>
      </div>

      {rowAction.error && <div className="notice notice-error" role="alert">{rowAction.error}</div>}

      {schedules.loading && !schedules.data ? (
        <p className="muted">Loading</p>
      ) : list.length === 0 ? (
        <p className="muted">No medicines yet. Add the first one below.</p>
      ) : (
        <ul className="rows">
          {list.map((s) => (
            <li key={s.id} className={s.active ? "row" : "row row-off"}>
              <span className="row-main">
                <span className="row-title">{s.name}</span>
                <span className="row-sub">
                  {s.dose_text || "No dose note"}
                  {!s.active && " (paused)"}
                </span>
              </span>
              <span className="row-time mono">
                {clock12(s.time_of_day)}
                <span className="row-sub">window {s.window_minutes} min</span>
              </span>
              <span className="row-actions">
                <button className="btn btn-quiet" onClick={() => toggle(s)} disabled={rowAction.busy}>
                  {s.active ? "Pause" : "Resume"}
                </button>
                <button className="btn btn-quiet btn-danger-text" onClick={() => remove(s)} disabled={rowAction.busy}>
                  Remove
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <AddSchedule patientId={patient.id} onAdded={schedules.reload} />
    </div>
  );
}

function AddSchedule({ patientId, onAdded }) {
  const [name, setName] = useState("");
  const [doseText, setDoseText] = useState("");
  const [time, setTime] = useState("08:00");
  const [windowMinutes, setWindowMinutes] = useState(30);
  const { busy, error, run } = useAction();

  async function submit(e) {
    e.preventDefault();
    const created = await run(() =>
      api.post(`/patients/${patientId}/schedules`, {
        name: name.trim(),
        dose_text: doseText.trim(),
        time_of_day: time,
        window_minutes: Number(windowMinutes),
      })
    );
    if (created) {
      setName("");
      setDoseText("");
      onAdded();
    }
  }

  return (
    <form onSubmit={submit} className="panel stack" aria-labelledby="add-med-h">
      <h2 id="add-med-h" className="section-title">
        Add a medicine
      </h2>
      <div className="grid-form">
        <div className="field">
          <label htmlFor="med-name">Medicine</label>
          <input id="med-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Metformin" required />
        </div>
        <div className="field">
          <label htmlFor="med-dose">Dose note</label>
          <input id="med-dose" value={doseText} onChange={(e) => setDoseText(e.target.value)} placeholder="500 mg with breakfast" />
        </div>
        <div className="field">
          <label htmlFor="med-time">Time</label>
          <input id="med-time" type="time" value={time} onChange={(e) => setTime(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="med-window">Window, minutes</label>
          <input
            id="med-window"
            type="number"
            min="5"
            max="240"
            step="5"
            value={windowMinutes}
            onChange={(e) => setWindowMinutes(e.target.value)}
            required
          />
          <span className="hint">How long after the time before it counts as missed.</span>
        </div>
      </div>
      {error && <div className="notice notice-error" role="alert">{error}</div>}
      <div>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Adding" : "Add medicine"}
        </button>
      </div>
    </form>
  );
}
