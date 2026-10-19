import { useState } from "react";
import { api } from "../api.js";
import { useAction, usePoll } from "../hooks.js";
import { LANGUAGE_NAMES, agoLabel, languageName } from "../format.js";

const TIERS = {
  1: "Called first",
  2: "Called if no one answers",
  3: "Called last",
};

export default function Setup({ patient, onPatientChanged, onPatientAdded }) {
  return (
    <div className="stack-lg">
      <div>
        <h1 className="display">Setup</h1>
        <p className="muted">
          {patient.name} speaks {languageName(patient.language)} and is in the {patient.timezone} time zone.
        </p>
      </div>
      <Contacts patient={patient} onChanged={onPatientChanged} />
      <Devices patient={patient} />
      <section className="stack" aria-labelledby="another-h">
        <div>
          <h2 id="another-h" className="section-title">
            Add another person
          </h2>
          <p className="muted">
            For someone else you look after, or to try a prompt in a different language. Each person has their own
            medicines, contacts, glasses and prompts, and you switch between them at the top of the page.
          </p>
        </div>
        <div className="panel">
          <PatientForm onCreated={onPatientAdded} />
        </div>
      </section>
    </div>
  );
}

function Contacts({ patient, onChanged }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [priority, setPriority] = useState(1);
  const { busy, error, run } = useAction();

  const contacts = [...patient.contacts].sort((a, b) => a.priority - b.priority || a.id - b.id);

  async function add(e) {
    e.preventDefault();
    const created = await run(() =>
      api.post(`/patients/${patient.id}/contacts`, { name: name.trim(), phone: phone.trim(), priority: Number(priority) })
    );
    if (created) {
      setName("");
      setPhone("");
      onChanged();
    }
  }

  async function remove(c) {
    if (!window.confirm(`Remove ${c.name}?`)) return;
    await run(() => api.del(`/patients/${patient.id}/contacts/${c.id}`));
    onChanged();
  }

  return (
    <section className="stack" aria-labelledby="contacts-h">
      <div>
        <h2 id="contacts-h" className="section-title">
          Who gets contacted
        </h2>
        <p className="muted">
          When a fall or SOS is not acknowledged, the next group is contacted every couple of minutes, until someone says
          they are on it.
        </p>
      </div>

      {contacts.length === 0 ? (
        <div className="notice notice-warning">Nobody will be contacted yet. Add at least one person.</div>
      ) : (
        <ul className="rows">
          {contacts.map((c) => (
            <li key={c.id} className="row">
              <span className="row-main">
                <span className="row-title">{c.name}</span>
                <span className="row-sub mono">{c.phone}</span>
              </span>
              <span className="row-time">{TIERS[c.priority]}</span>
              <span className="row-actions">
                <button className="btn btn-quiet btn-danger-text" onClick={() => remove(c)} disabled={busy}>
                  Remove
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={add} className="panel stack">
        <h3 className="subtitle">Add a contact</h3>
        <div className="grid-form">
          <div className="field">
            <label htmlFor="c-name">Name</label>
            <input id="c-name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="c-phone">Phone, with country code</label>
            <input
              id="c-phone"
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+91 98765 43210"
              required
              minLength={5}
            />
          </div>
          <div className="field">
            <label htmlFor="c-priority">When</label>
            <select id="c-priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
              {Object.entries(TIERS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>
        {error && <div className="notice notice-error" role="alert">{error}</div>}
        <div>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            Add contact
          </button>
        </div>
      </form>
    </section>
  );
}

function Devices({ patient }) {
  const devices = usePoll(() => api.get(`/patients/${patient.id}/devices`), 10000, [patient.id]);
  const [name, setName] = useState("Smart Vision frame");
  const [created, setCreated] = useState(null);
  const [copied, setCopied] = useState(false);
  const { busy, error, run } = useAction();

  async function add(e) {
    e.preventDefault();
    const result = await run(() => api.post(`/patients/${patient.id}/devices`, { name: name.trim() }));
    if (result) {
      setCreated(result);
      setCopied(false);
      devices.reload();
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(created.api_key);
      setCopied(true);
    } catch {
      /* clipboard can be blocked; the key is selectable on screen */
    }
  }

  const list = devices.data || [];

  return (
    <section className="stack" aria-labelledby="devices-h">
      <div>
        <h2 id="devices-h" className="section-title">
          Glasses
        </h2>
        <p className="muted">Each pair of glasses has its own key. The key is how the glasses prove who they are.</p>
      </div>

      {list.length === 0 ? (
        <p className="muted">No glasses added yet.</p>
      ) : (
        <ul className="rows">
          {list.map((d) => (
            <li key={d.id} className="row">
              <span className="row-main">
                <span className="row-title">{d.name}</span>
                <span className="row-sub">
                  {d.last_seen ? `Last heard from ${agoLabel(d.last_seen)}` : "Never connected"}
                </span>
              </span>
              <span className="row-time">{d.battery_pct != null ? `${d.battery_pct}% battery` : ""}</span>
            </li>
          ))}
        </ul>
      )}

      {created && (
        <div className="notice notice-ok key-box" role="status">
          <p>
            <strong>Key for {created.name}.</strong> Copy it now. It is shown only this once and cannot be looked up later.
            If it is lost, add the device again.
          </p>
          <code className="key">{created.api_key}</code>
          <div>
            <button className="btn" type="button" onClick={copy}>
              {copied ? "Copied" : "Copy key"}
            </button>{" "}
            <button className="btn btn-quiet" type="button" onClick={() => setCreated(null)}>
              I have saved it
            </button>
          </div>
        </div>
      )}

      <form onSubmit={add} className="panel stack">
        <h3 className="subtitle">Add glasses</h3>
        <div className="field field-short">
          <label htmlFor="d-name">Name</label>
          <input id="d-name" value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        {error && <div className="notice notice-error" role="alert">{error}</div>}
        <div>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            Create key
          </button>
        </div>
      </form>
    </section>
  );
}

// Used on first run (no patient yet) and from the app shell.
export function PatientForm({ onCreated }) {
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("en");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const { busy, error, run } = useAction();

  async function submit(e) {
    e.preventDefault();
    const created = await run(() => api.post("/patients", { name: name.trim(), language, timezone: timezone.trim() }));
    if (created) {
      setName("");
      onCreated(created);
    }
  }

  return (
    <form onSubmit={submit} className="stack">
      <div className="field">
        <label htmlFor="p-name">Their name</label>
        <input id="p-name" value={name} onChange={(e) => setName(e.target.value)} required />
      </div>
      <div className="field">
        <label htmlFor="p-lang">Language they hear prompts in</label>
        <select id="p-lang" value={language} onChange={(e) => setLanguage(e.target.value)}>
          {Object.entries(LANGUAGE_NAMES).map(([code, label]) => (
            <option key={code} value={code}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="p-tz">Time zone</label>
        <input id="p-tz" value={timezone} onChange={(e) => setTimezone(e.target.value)} required />
        <span className="hint">For example Asia/Kolkata. Medicine times are set in this zone.</span>
      </div>
      {error && <div className="notice notice-error" role="alert">{error}</div>}
      <div>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Adding" : "Add person"}
        </button>
      </div>
    </form>
  );
}
