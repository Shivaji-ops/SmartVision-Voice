import { api } from "../api.js";
import { usePoll } from "../hooks.js";
import {
  agoLabel,
  clock12,
  describeEvent,
  eventTone,
  hhmmToMinutes,
  localMinutesNow,
  mapsUrl,
  statusSentence,
  whenLabel,
} from "../format.js";

const STATUS_WORDS = {
  upcoming: "Later today",
  pending: "Due now",
  taken: "Taken",
  missed: "Missed",
};

export default function Overview({ patient, openAlerts }) {
  const summary = usePoll(() => api.get(`/patients/${patient.id}/summary`), 5000, [patient.id]);
  const s = summary.data;

  if (summary.loading && !s) return <p className="muted">Loading</p>;
  if (!s) {
    return (
      <div className="notice notice-error" role="alert">
        {summary.error ? summary.error.message : "Could not load the summary."}
      </div>
    );
  }

  const status = statusSentence(s, openAlerts);
  const names = Object.fromEntries(s.doses.map((d) => [d.schedule_id, d.name]));
  const tz = s.patient.timezone;

  return (
    <div className="stack-lg">
      {summary.error && <div className="notice notice-error">Updates paused: {summary.error.message}</div>}

      <section className={`status status-${status.tone}`} aria-live="polite">
        <h1 className="status-text">{status.text}</h1>
        <p className="status-detail">{status.detail}</p>
      </section>

      <section aria-labelledby="today-h">
        <h2 id="today-h" className="section-title">
          Today
        </h2>
        {s.doses.length === 0 ? (
          <p className="muted">
            No medicines are scheduled. <a href="#/medication">Add one</a>.
          </p>
        ) : (
          <>
            <DayStrip doses={s.doses} timeZone={tz} />
            <ul className="rows">
              {s.doses.map((d) => (
                <li key={d.schedule_id} className="row">
                  <span className="row-main">
                    <span className="row-title">{d.name}</span>
                    {d.dose_text && <span className="row-sub">{d.dose_text}</span>}
                  </span>
                  <span className="row-time mono">{clock12(d.due)}</span>
                  <span className={`state state-${d.status}`}>{STATUS_WORDS[d.status]}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <div className="two-col">
        <section aria-labelledby="dev-h">
          <h2 id="dev-h" className="section-title">
            Glasses
          </h2>
          <DeviceBlock device={s.device} />
        </section>

        <section aria-labelledby="loc-h">
          <h2 id="loc-h" className="section-title">
            Last known location
          </h2>
          {s.last_location ? (
            <div className="stack-sm">
              <p className="mono">
                {s.last_location.lat.toFixed(4)}, {s.last_location.lon.toFixed(4)}
              </p>
              <p className="muted">{agoLabel(s.last_location.at)}</p>
              <a href={mapsUrl(s.last_location.lat, s.last_location.lon)} target="_blank" rel="noreferrer">
                Open in OpenStreetMap
              </a>
            </div>
          ) : (
            <p className="muted">No position has been reported yet.</p>
          )}
        </section>
      </div>

      <section aria-labelledby="act-h">
        <h2 id="act-h" className="section-title">
          Recent activity
        </h2>
        {s.recent_events.length === 0 ? (
          <p className="muted">Nothing yet. Events from the glasses will show up here.</p>
        ) : (
          <ul className="rows">
            {s.recent_events.map((e) => (
              <li key={e.id} className={`row row-${eventTone(e.type)}`}>
                <span className="row-main">
                  <span className="row-title">{describeEvent(e, names)}</span>
                </span>
                <span className="row-time mono">{whenLabel(e.occurred_at, tz)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function DeviceBlock({ device }) {
  if (!device) {
    return (
      <p className="muted">
        No glasses are paired. <a href="#/setup">Add a device</a>.
      </p>
    );
  }
  return (
    <dl className="facts">
      <div>
        <dt>Connection</dt>
        <dd>
          <span className={device.online ? "dot dot-ok" : "dot dot-off"} aria-hidden="true" />
          {device.online ? "Online" : "Offline"}
        </dd>
      </div>
      <div>
        <dt>Last heard from</dt>
        <dd>{agoLabel(device.last_seen)}</dd>
      </div>
      <div>
        <dt>Battery</dt>
        <dd className={device.battery_pct != null && device.battery_pct <= 20 ? "text-warn" : undefined}>
          {device.battery_pct != null ? `${device.battery_pct}%` : "Unknown"}
        </dd>
      </div>
      <div>
        <dt>Worn</dt>
        <dd>{device.worn ? "Yes, on the face" : "No, taken off"}</dd>
      </div>
    </dl>
  );
}

// A thin line for the day with a tick for each dose and a mark for the current time.
function DayStrip({ doses, timeZone }) {
  const nowMin = localMinutesNow(timeZone);
  const pct = (min) => `${(min / 1440) * 100}%`;
  const hours = [0, 6, 12, 18, 24];
  return (
    <figure className="strip" aria-label="Today's doses on a timeline">
      <div className="strip-track">
        <div className="strip-elapsed" style={{ width: pct(nowMin) }} />
        {doses.map((d) => (
          <span
            key={d.schedule_id}
            className={`strip-tick tick-${d.status}`}
            style={{ left: pct(hhmmToMinutes(d.due)) }}
            title={`${d.name}, ${clock12(d.due)}: ${STATUS_WORDS[d.status]}`}
          />
        ))}
        <span className="strip-now" style={{ left: pct(nowMin) }} title="Now" />
      </div>
      <div className="strip-scale mono" aria-hidden="true">
        {hours.map((h) => (
          <span key={h} style={{ left: pct(h * 60) }}>
            {h === 0 || h === 24 ? "12 am" : h === 12 ? "12 pm" : h < 12 ? `${h} am` : `${h - 12} pm`}
          </span>
        ))}
      </div>
    </figure>
  );
}
