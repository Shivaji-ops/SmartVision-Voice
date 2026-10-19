import { useState } from "react";
import { api } from "../api.js";
import { useAction, usePoll } from "../hooks.js";
import { agoLabel, prettyAlertTitle } from "../format.js";

const CHANNEL_WORDS = { sms: "Text message", voice: "Phone call" };

export default function Alerts({ patientNames, onChanged }) {
  const [state, setState] = useState("open");
  const alerts = usePoll(() => api.get(`/alerts?state=${state}`), 5000, [state]);
  const { busy, error, run } = useAction();

  async function acknowledge(alert) {
    await run(() => api.post(`/alerts/${alert.id}/ack`));
    alerts.reload();
    onChanged();
  }

  const list = alerts.data || [];

  return (
    <div className="stack-lg">
      <div>
        <h1 className="display">Alerts</h1>
        <p className="muted">
          Acknowledging an alert tells the system someone is on it, and stops further calls to your contacts.
        </p>
      </div>

      <div className="tabs" role="tablist" aria-label="Alert state">
        {[
          ["open", "Open"],
          ["acknowledged", "Acknowledged"],
        ].map(([value, label]) => (
          <button
            key={value}
            role="tab"
            aria-selected={state === value}
            className={state === value ? "tab current" : "tab"}
            onClick={() => setState(value)}
          >
            {label}
          </button>
        ))}
      </div>

      {error && <div className="notice notice-error" role="alert">{error}</div>}
      {alerts.error && !alerts.data && <div className="notice notice-error">{alerts.error.message}</div>}

      {alerts.loading && !alerts.data ? (
        <p className="muted">Loading</p>
      ) : list.length === 0 ? (
        <p className="muted">{state === "open" ? "Nothing needs attention." : "No acknowledged alerts yet."}</p>
      ) : (
        <ul className="alert-list">
          {list.map((a) => (
            <li key={a.id} className={`alert alert-${a.level}`}>
              <div className="alert-head">
                <div>
                  <h2 className="alert-title">{prettyAlertTitle(a.title)}</h2>
                  <p className="muted">
                    {patientNames[a.patient_id] || "Someone"}, {agoLabel(a.created_at)}
                  </p>
                </div>
                {a.status === "open" ? (
                  <button className="btn btn-primary" onClick={() => acknowledge(a)} disabled={busy}>
                    I'm on it
                  </button>
                ) : (
                  <span className="state state-taken">Acknowledged {agoLabel(a.acknowledged_at)}</span>
                )}
              </div>
              <Trail alert={a} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Trail({ alert }) {
  if (!alert.notifications.length) {
    return <p className="trail muted">No one has been contacted yet.</p>;
  }
  return (
    <ul className="trail">
      {alert.notifications.map((n, i) => (
        <li key={i}>
          <span className="mono">Tier {n.tier}</span> {CHANNEL_WORDS[n.channel] || n.channel} to{" "}
          <span className="mono">{n.target}</span>
          <span className="muted">, {agoLabel(n.created_at)}</span>
        </li>
      ))}
    </ul>
  );
}
