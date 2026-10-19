import { useCallback, useEffect, useRef, useState } from "react";

// Run `load` now and then every `ms` while the tab is visible. Keeps the last good
// data on screen if a refresh fails, and ignores answers that arrive out of order.
export function usePoll(load, ms, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const ticket = useRef(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  const run = useCallback(async () => {
    const mine = ++ticket.current;
    try {
      const data = await loadRef.current();
      if (mine === ticket.current) setState({ data, error: null, loading: false });
    } catch (error) {
      if (mine === ticket.current) setState((prev) => ({ data: prev.data, error, loading: false }));
    }
  }, []);

  useEffect(() => {
    setState({ data: null, error: null, loading: true });
    run();
    const timer = ms
      ? setInterval(() => {
          if (!document.hidden) run();
        }, ms)
      : null;
    const onVisible = () => {
      if (!document.hidden) run();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      ticket.current++;
      if (timer) clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ...state, reload: run };
}

// Tiny hash router: "#/medication" -> "medication", "" -> "".
export function useHashRoute() {
  const read = () => window.location.hash.replace(/^#\/?/, "");
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

// For buttons that call the API: tracks busy and error so forms can show both.
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const run = useCallback(async (fn) => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e.message || "Something went wrong.");
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, run, clearError: () => setError(null) };
}
