import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useAction, usePoll } from "../hooks.js";
import { LANGUAGE_NAMES, agoLabel, languageName } from "../format.js";
import Listen from "../Listen.jsx";

const slug = (value) => value.toLowerCase().replace(/[^a-z0-9_]+/g, "_");

export default function Prompts({ patient, onPatientChanged }) {
  const prompts = usePoll(() => api.get(`/patients/${patient.id}/prompts`), 0, [patient.id]);
  const templates = usePoll(() => api.get("/dose-templates"), 0, []);
  const list = prompts.data || [];

  return (
    <div className="stack-lg">
      <div>
        <h1 className="display">Voice prompts</h1>
        <p className="muted">
          What the glasses say to {patient.name}, in {languageName(patient.language)}. Changes reach the glasses the next time
          they connect. Current version {patient.prompt_version}.
        </p>
      </div>

      {prompts.loading && !prompts.data ? (
        <p className="muted">Loading</p>
      ) : list.length === 0 ? (
        <p className="muted">No custom prompts yet. The glasses use their built-in wording until you add one.</p>
      ) : (
        <ul className="rows">
          {list.map((p) => (
            <li key={p.id} className="row row-top">
              <span className="row-main">
                <span className="row-title mono">{p.key}</span>
                <span className="prompt-text" lang={p.language}>
                  {p.text}
                </span>
                {p.source_language !== p.language && !p.is_dose_related && (
                  <span className="row-sub">
                    Written in {languageName(p.source_language)}: {p.source_text}
                  </span>
                )}
                {p.is_dose_related && <span className="row-sub">Reviewed medicine wording, not machine translated.</span>}
                <span className="row-listen">
                  <Listen
                    path={`/patients/${patient.id}/prompts/${p.key}/audio`}
                    cacheKey={`saved:${patient.id}:${p.key}:${p.version}:${p.language}:${p.text}`}
                    onMade={prompts.reload}
                  />
                  {!p.audio_ready && <span className="row-sub">The voice has not been made yet. Listen makes it.</span>}
                </span>
              </span>
              <span className="row-time">
                <span className="mono">v{p.version}</span>
                <span className="row-sub">{agoLabel(p.updated_at)}</span>
              </span>
            </li>
          ))}
        </ul>
      )}

      <PromptForm
        patient={patient}
        templates={templates.data || []}
        onSaved={() => {
          prompts.reload();
          onPatientChanged();
        }}
      />
    </div>
  );
}

function PromptForm({ patient, templates, onSaved }) {
  const [kind, setKind] = useState("message"); // "message" or "dose"
  const [key, setKey] = useState("");
  const [text, setText] = useState("");
  const [sourceLanguage, setSourceLanguage] = useState("en");
  const [templateKey, setTemplateKey] = useState("");
  const [saved, setSaved] = useState(null);
  // The machine translation the caregiver is reviewing, and their possibly edited version of it.
  const [preview, setPreview] = useState(null);
  const [edited, setEdited] = useState("");
  const { busy, error, run, clearError } = useAction();

  useEffect(() => {
    if (!templateKey && templates.length) setTemplateKey(templates[0].key);
  }, [templates, templateKey]);

  const isDose = kind === "dose";
  const template = templates.find((t) => t.key === templateKey);
  const verified = !isDose || (template && template.verified_languages.includes(patient.language));
  const needsTranslation = !isDose && sourceLanguage !== patient.language;
  const dirty = preview !== null && edited.trim() !== preview.translated_text;

  // What the wearer would hear, when there is something to play: the reviewed translation,
  // or the text itself when it is already in their language. Medicine wording is fixed, so not here.
  const listenText = isDose ? "" : needsTranslation ? (preview ? edited.trim() : "") : text.trim();

  const sourceName = languageName(sourceLanguage);
  const targetName = languageName(patient.language);

  function resetReview() {
    setPreview(null);
    setEdited("");
  }

  async function fetchPreview(translatedText) {
    const result = await run(() =>
      api.post(`/patients/${patient.id}/prompts/preview`, {
        text,
        source_language: sourceLanguage,
        ...(translatedText ? { translated_text: translatedText } : {}),
      })
    );
    if (result) {
      setPreview(result);
      setEdited(result.translated_text);
    }
  }

  async function submit(e) {
    e.preventDefault();
    setSaved(null);

    // Step one for another language: translate and show the result. Nothing is saved yet.
    if (needsTranslation && !preview) {
      await fetchPreview();
      return;
    }

    const body = isDose
      ? { key, is_dose_related: true, template_key: templateKey }
      : needsTranslation
        ? { key, text, source_language: sourceLanguage, translated_text: edited.trim() }
        : { key, text, source_language: sourceLanguage };

    const result = await run(() => api.post(`/patients/${patient.id}/prompts`, body));
    if (result) {
      setSaved(result);
      setKey("");
      setText("");
      resetReview();
      onSaved();
    }
  }

  function changeKind(next) {
    clearError();
    setSaved(null);
    resetReview();
    setKind(next);
  }

  const submitLabel = busy
    ? needsTranslation && !preview
      ? "Translating"
      : "Saving"
    : needsTranslation && !preview
      ? "Translate and check"
      : needsTranslation
        ? "Save this wording"
        : "Save prompt";

  return (
    <form onSubmit={submit} className="panel stack" aria-labelledby="prompt-form-h">
      <h2 id="prompt-form-h" className="section-title">
        Add or change a prompt
      </h2>

      <fieldset className="choice">
        <legend className="visually-hidden">Kind of prompt</legend>
        <label className={!isDose ? "choice-item current" : "choice-item"}>
          <input type="radio" name="kind" checked={!isDose} onChange={() => changeKind("message")} />
          <span>
            <strong>A message</strong>
            <span className="hint">Greetings, encouragement, anything that is not about taking medicine.</span>
          </span>
        </label>
        <label className={isDose ? "choice-item current" : "choice-item"}>
          <input type="radio" name="kind" checked={isDose} onChange={() => changeKind("dose")} />
          <span>
            <strong>About taking medicine</strong>
            <span className="hint">Uses wording that has been checked by a person. Never machine translated.</span>
          </span>
        </label>
      </fieldset>

      <div className="field">
        <label htmlFor="prompt-key">Name for this prompt</label>
        <input
          id="prompt-key"
          value={key}
          onChange={(e) => {
            setSaved(null);
            setKey(slug(e.target.value));
          }}
          placeholder={isDose ? "morning_dose" : "greeting"}
          maxLength={64}
          required
        />
        <span className="hint">
          Using the same name again replaces the earlier wording. Lowercase letters, digits and underscores.
        </span>
      </div>

      {isDose ? (
        <div className="field">
          <label htmlFor="prompt-template">Wording</label>
          <select id="prompt-template" value={templateKey} onChange={(e) => setTemplateKey(e.target.value)}>
            {templates.map((t) => (
              <option key={t.key} value={t.key}>
                {t.description}
              </option>
            ))}
          </select>
          {!verified && (
            <div className="notice notice-warning" role="status">
              There is no reviewed wording in {targetName} yet, so this cannot be saved. Reviewed wording exists in:{" "}
              {template ? template.verified_languages.map(languageName).join(", ") : "none"}. A medicine prompt with a wrong
              word is worse than no prompt, so these are not translated by machine.
            </div>
          )}
        </div>
      ) : (
        <>
          <div className="field">
            <label htmlFor="prompt-text">What should it say?</label>
            <textarea
              id="prompt-text"
              rows={3}
              maxLength={500}
              value={text}
              onChange={(e) => {
                setSaved(null);
                resetReview();
                setText(e.target.value);
              }}
              required
            />
          </div>
          <div className="field field-short">
            <label htmlFor="prompt-lang">I am writing this in</label>
            <select
              id="prompt-lang"
              value={sourceLanguage}
              onChange={(e) => {
                setSaved(null);
                resetReview();
                setSourceLanguage(e.target.value);
              }}
            >
              {Object.entries(LANGUAGE_NAMES).map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
            <span className="hint">
              {needsTranslation
                ? `It is translated into ${targetName} for you to check. Nothing is saved until you approve it.`
                : `${patient.name} hears it exactly as written.`}
            </span>
          </div>

          {needsTranslation && preview && (
            <div className="review" aria-live="polite">
              <div className="field">
                <label htmlFor="prompt-translated">What {patient.name} will hear, in {targetName}</label>
                <textarea
                  id="prompt-translated"
                  lang={patient.language}
                  rows={3}
                  maxLength={1000}
                  value={edited}
                  onChange={(e) => setEdited(e.target.value)}
                  required
                />
                <span className="hint">You can fix any word here. Change it and press Check my edit to see it translated back.</span>
              </div>
              <div className="stack-sm">
                <p className="review-label">
                  Translated back to {sourceName}
                  {dirty ? ", for the earlier wording" : ""}
                </p>
                <p className="prompt-text" lang={sourceLanguage}>
                  {preview.back_translation}
                </p>
              </div>
              <div className="notice notice-warning" role="note">
                Machine translation can be wrong. If the line above is not what you meant, change your message or edit the
                wording. If you can read {targetName}, read it before saving.
              </div>
            </div>
          )}
        </>
      )}

      {error && (
        <div className="notice notice-error" role="alert">
          {error}
        </div>
      )}
      {saved && (
        <div className="notice notice-ok" role="status">
          Saved as version {saved.version}. The glasses will say: <em lang={saved.language}>{saved.text}</em>
        </div>
      )}
      {saved && saved.audio_error && (
        <div className="notice notice-warning" role="status">
          The words are saved, but the voice could not be made: {saved.audio_error} The glasses will have no sound for this
          prompt until it is made. Press Listen on the prompt above to try again.
        </div>
      )}

      <div className="button-row">
        <button className="btn btn-primary" type="submit" disabled={busy || !verified || (needsTranslation && preview && !edited.trim())}>
          {submitLabel}
        </button>
        {needsTranslation && preview && dirty && (
          <button className="btn" type="button" disabled={busy || !edited.trim()} onClick={() => fetchPreview(edited.trim())}>
            Check my edit
          </button>
        )}
        {listenText && (
          <Listen
            method="POST"
            path={`/patients/${patient.id}/speech/preview`}
            body={{ text: listenText }}
            cacheKey={`preview:${patient.id}:${patient.language}:${listenText}`}
            label={`Listen in ${targetName}`}
            disabled={busy}
          />
        )}
        {needsTranslation && preview && (
          <button className="btn btn-quiet" type="button" onClick={resetReview} disabled={busy}>
            Discard translation
          </button>
        )}
      </div>
    </form>
  );
}
