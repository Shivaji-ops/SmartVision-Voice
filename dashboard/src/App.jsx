import { useCallback, useEffect, useState } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api.js";
import { useHashRoute, usePoll } from "./hooks.js";
import { prettyAlertTitle } from "./format.js";
import Login from "./pages/Login.jsx";
import Overview from "./pages/Overview.jsx";
import Medication from "./pages/Medication.jsx";
import Prompts from "./pages/Prompts.jsx";
import Alerts from "./pages/Alerts.jsx";
import Setup, { PatientForm } from "./pages/Setup.jsx";

const PAGES = [
  { path: "", label: "Overview" },
  { path: "medication", label: "Medication" },
  { path: "prompts", label: "Prompts" },
  { path: "alerts", label: "Alerts" },
  { path: "setup", label: "Setup" },
];

export default function App() {
  const [token, setTokenState] = useState(getToken());

  const signOut = useCallback(() => {
    setToken(null);
    setTokenState(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(signOut);
  }, [signOut]);

  if (!token) {
    return (
      <Login
        onSignedIn={(t) => {
          setToken(t);
          setTokenState(t);
        }}
      />
    );
  }
  return <Shell onSignOut={signOut} />;
}

function Shell({ onSignOut }) {
  const route = useHashRoute();
  const me = usePoll(() => api.get("/me"), 0, []);
  const patients = usePoll(() => api.get("/patients"), 0, []);
  // Remember who was selected, so a refresh does not jump back to the first person.
  const [patientId, setPatientIdState] = useState(() => {
    try {
      return Number(localStorage.getItem("sv_patient")) || null;
    } catch {
      return null;
    }
  });
  function setPatientId(id) {
    setPatientIdState(id);
    try {
      localStorage.setItem("sv_patient", String(id));
    } catch {
      /* storage can be blocked; the choice just will not survive a refresh */
    }
  }

  const list = patients.data || [];
  const patient = list.find((p) => p.id === patientId) || list[0] || null;

  // Open alerts for every patient this caregiver looks after, refreshed every 5 seconds.
  const alerts = usePoll(() => api.get("/alerts?state=open"), 5000, []);
  const openAlerts = alerts.data || [];
  const mine = patient ? openAlerts.filter((a) => a.patient_id === patient.id) : [];

  useEffect(() => {
    document.title = openAlerts.length ? `(${openAlerts.length}) Smart Vision` : "Smart Vision";
  }, [openAlerts.length]);

  if (patients.loading) {
    return (
      <div className="center-page">
        <p className="muted">Loading</p>
      </div>
    );
  }

  if (patients.error && !patients.data) {
    return (
      <div className="center-page">
        <div className="notice notice-error" role="alert">
          {patients.error.message}
        </div>
        <button className="btn" onClick={patients.reload}>
          Try again
        </button>
      </div>
    );
  }

  if (!patient) {
    return (
      <div className="center-page">
        <div className="panel narrow">
          <h1 className="display">Who are you looking after?</h1>
          <p className="muted">Add the person who will wear the glasses. You can add medicines, contacts and the device next.</p>
          <PatientForm onCreated={() => patients.reload()} />
        </div>
      </div>
    );
  }

  const critical = openAlerts.some((a) => a.level === "critical");
  const current = PAGES.find((p) => p.path === route) || PAGES[0];
  const nameOf = (id) => (list.find((p) => p.id === id) || {}).name || "Someone";

  // The Alerts page lists everything, and the Overview already says it in the big sentence
  // for the person shown, so the strip only appears where it adds something.
  const bannerAlerts =
    current.path === "alerts"
      ? []
      : current.path === ""
        ? openAlerts.filter((a) => a.patient_id !== patient.id)
        : openAlerts;
  const bannerCritical = bannerAlerts.some((a) => a.level === "critical");

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="#/">
            Smart Vision
          </a>
          {list.length > 1 ? (
            <label className="patient-pick">
              <span className="visually-hidden">Person</span>
              <select value={patient.id} onChange={(e) => setPatientId(Number(e.target.value))}>
                {list.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <span className="patient-name">{patient.name}</span>
          )}
          <span className="spacer" />
          <span className="who muted">{me.data ? me.data.name : ""}</span>
          <button className="btn btn-quiet" onClick={onSignOut}>
            Sign out
          </button>
        </div>
        <nav className="nav" aria-label="Sections">
          {PAGES.map((p) => (
            <a
              key={p.path}
              href={`#/${p.path}`}
              className={p === current ? "nav-link current" : "nav-link"}
              aria-current={p === current ? "page" : undefined}
            >
              {p.label}
              {p.path === "alerts" && openAlerts.length > 0 && (
                <span className={critical ? "count count-critical" : "count count-warning"}>{openAlerts.length}</span>
              )}
            </a>
          ))}
        </nav>
      </header>

      {bannerAlerts.length > 0 && (
        <div
          className={bannerCritical ? "banner banner-critical" : "banner banner-warning"}
          role={bannerCritical ? "alert" : "status"}
        >
          <div className="banner-inner">
            <span>
              <strong>{nameOf(bannerAlerts[0].patient_id)}:</strong> {prettyAlertTitle(bannerAlerts[0].title)}
              {bannerAlerts.length > 1 ? `, and ${bannerAlerts.length - 1} more` : ""}
            </span>
            <a href="#/alerts">Open alerts</a>
          </div>
        </div>
      )}

      <main className="page" id="main">
        {alerts.error && !alerts.data && <div className="notice notice-error">{alerts.error.message}</div>}
        {current.path === "" && <Overview patient={patient} openAlerts={mine} />}
        {current.path === "medication" && <Medication patient={patient} />}
        {current.path === "prompts" && <Prompts patient={patient} onPatientChanged={patients.reload} />}
        {current.path === "alerts" && (
          <Alerts patientNames={Object.fromEntries(list.map((p) => [p.id, p.name]))} onChanged={alerts.reload} />
        )}
        {current.path === "setup" && (
          <Setup
            patient={patient}
            onPatientChanged={patients.reload}
            onPatientAdded={(created) => {
              setPatientId(created.id);
              patients.reload();
            }}
          />
        )}
      </main>
    </div>
  );
}
