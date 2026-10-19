// Display helpers. Times shown to the caregiver are in the patient's own time zone,
// because dose times are set in that zone.

export function hhmmToMinutes(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

// "14:00" -> "2:00 pm"
export function clock12(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  const suffix = h >= 12 ? "pm" : "am";
  const hour = h % 12 === 0 ? 12 : h % 12;
  return `${hour}:${String(m).padStart(2, "0")} ${suffix}`;
}

// Minutes since local midnight in the given zone, right now.
export function localMinutesNow(timeZone) {
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone,
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(new Date());
    const h = Number(parts.find((p) => p.type === "hour").value);
    const m = Number(parts.find((p) => p.type === "minute").value);
    return h * 60 + m;
  } catch {
    const d = new Date();
    return d.getHours() * 60 + d.getMinutes();
  }
}

function dayKey(date, timeZone) {
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(date); // YYYY-MM-DD
}

// "2:41 pm" for today, "Mon 2:41 pm" for within a week, otherwise "12 Oct, 2:41 pm".
export function whenLabel(iso, timeZone) {
  if (!iso) return "never";
  const date = new Date(iso);
  const opts = { timeZone, hour: "numeric", minute: "2-digit", hour12: true };
  const time = new Intl.DateTimeFormat("en-IN", opts).format(date).replace(/\s?([AP])M/i, (_, c) => ` ${c.toLowerCase()}m`);
  const now = new Date();
  if (dayKey(date, timeZone) === dayKey(now, timeZone)) return time;
  const days = (now - date) / 86400000;
  if (days < 6) {
    const weekday = new Intl.DateTimeFormat("en-IN", { timeZone, weekday: "short" }).format(date);
    return `${weekday} ${time}`;
  }
  const day = new Intl.DateTimeFormat("en-IN", { timeZone, day: "numeric", month: "short" }).format(date);
  return `${day}, ${time}`;
}

// "just now", "4 min ago", "3 h ago", "2 days ago"
export function agoLabel(iso) {
  if (!iso) return "never";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  const days = Math.round(seconds / 86400);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

// The server writes alert titles with 24-hour times ("Missed dose: Vitamin D at 17:10").
// Show them the way the rest of the page does.
export function prettyAlertTitle(title) {
  return title.replace(/\b([01]\d|2[0-3]):[0-5]\d\b/g, (match) => clock12(match));
}

export function mapsUrl(lat, lon) {
  return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=17/${lat}/${lon}`;
}

export const LANGUAGE_NAMES = {
  en: "English",
  hi: "Hindi",
  te: "Telugu",
  ta: "Tamil",
  kn: "Kannada",
  ml: "Malayalam",
  mr: "Marathi",
  bn: "Bengali",
  gu: "Gujarati",
  pa: "Punjabi",
  ur: "Urdu",
};

export function languageName(code) {
  return LANGUAGE_NAMES[code] || code;
}

// One plain line per event for the activity list.
export function describeEvent(event, scheduleNames = {}) {
  const p = event.payload || {};
  const medName = p.name || scheduleNames[event.schedule_id];
  switch (event.type) {
    case "fall_confirmed":
      return "Fall detected";
    case "fall_suppressed":
      return "Fall-like movement while the frames were off. No alert sent.";
    case "fall_cancelled":
      return "Fall alert cancelled on the frames";
    case "sos":
      return "SOS button pressed";
    case "med_taken":
      return medName ? `Took ${medName}` : "Took a dose";
    case "med_missed":
      return medName ? `Missed ${medName}${p.due ? ` at ${clock12(p.due)}` : ""}` : "Missed a dose";
    case "med_mismatch":
      return "Packaging did not match the schedule";
    case "obstacle":
      return "Obstacle warning given";
    case "location":
      return "Location updated";
    default:
      return event.type.replace(/_/g, " ");
  }
}

// How an event should be marked in the list.
export function eventTone(type) {
  if (type === "fall_confirmed" || type === "sos") return "critical";
  if (type === "med_missed" || type === "med_mismatch") return "warning";
  return "quiet";
}

// The sentence at the top of the overview. Returns {tone, text, detail}.
export function statusSentence(summary, openAlerts) {
  const name = summary.patient.name;
  const critical = openAlerts.find((a) => a.level === "critical");
  if (critical) {
    if (critical.title === "Fall detected") {
      return { tone: "critical", text: `${name} may have fallen.`, detail: "Reported by the glasses. Call to check." };
    }
    if (critical.title === "SOS button pressed") {
      return { tone: "critical", text: `${name} pressed the SOS button.`, detail: "Call to check." };
    }
    return { tone: "critical", text: `${name} may need help.`, detail: critical.title };
  }
  const warning = openAlerts.find((a) => a.level === "warning");
  if (warning) {
    return { tone: "warning", text: `${name} missed a dose.`, detail: prettyAlertTitle(warning.title).replace(/^Missed dose:\s*/, "") };
  }
  const device = summary.device;
  if (!device) {
    return { tone: "quiet", text: "No glasses are paired yet.", detail: "Add a device in Setup to start receiving updates." };
  }
  if (!device.online) {
    return {
      tone: "quiet",
      text: `${name}'s glasses are offline.`,
      detail: device.last_seen ? `Last heard from ${agoLabel(device.last_seen)}.` : "They have not connected yet.",
    };
  }
  const due = summary.doses.find((d) => d.status === "pending");
  if (due) {
    return { tone: "quiet", text: `${name} has a dose due now.`, detail: `${due.name} at ${clock12(due.due)}` };
  }
  return { tone: "ok", text: `${name} is doing fine.`, detail: "No open alerts." };
}
