import { useState } from "react";
import { api } from "../api.js";
import { useAction } from "../hooks.js";

export default function Login({ onSignedIn }) {
  const [mode, setMode] = useState("signin");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run, clearError } = useAction();

  const registering = mode === "register";

  async function submit(e) {
    e.preventDefault();
    const result = await run(() =>
      registering
        ? api.post("/auth/register", { name, email, password })
        : api.post("/auth/login", { email, password })
    );
    if (result) onSignedIn(result.access_token);
  }

  function switchMode() {
    clearError();
    setMode(registering ? "signin" : "register");
  }

  return (
    <div className="center-page">
      <div className="login">
        <p className="brand brand-large">Smart Vision</p>
        <h1 className="display">{registering ? "Create a caregiver account" : "Welcome back"}</h1>
        <p className="muted">
          {registering
            ? "You will see alerts, medicines and the glasses' status for the person you look after."
            : "Sign in to see how things are going."}
        </p>

        <form onSubmit={submit} className="stack">
          {registering && (
            <div className="field">
              <label htmlFor="name">Your name</label>
              <input id="name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required />
            </div>
          )}
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={registering ? "new-password" : "current-password"}
              minLength={registering ? 8 : undefined}
              required
            />
            {registering && <span className="hint">At least 8 characters.</span>}
          </div>
          {error && (
            <div className="notice notice-error" role="alert">
              {error}
            </div>
          )}
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "One moment" : registering ? "Create account" : "Sign in"}
          </button>
        </form>

        <p className="switch muted">
          {registering ? "Already have an account? " : "New here? "}
          <button type="button" className="link-button" onClick={switchMode}>
            {registering ? "Sign in" : "Create an account"}
          </button>
        </p>
      </div>
    </div>
  );
}
