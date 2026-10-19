import { useEffect, useRef, useState } from "react";
import { fetchAudio } from "./api.js";

// Sounds already made, by key, so pressing Listen again is instant and costs nothing.
const cache = new Map();
function remember(key, url) {
  cache.set(key, url);
  if (cache.size > 24) {
    const oldest = cache.keys().next().value;
    URL.revokeObjectURL(cache.get(oldest));
    cache.delete(oldest);
  }
}

// Only one clip plays at a time.
let playing = null;

// A button that fetches a spoken version from the backend and plays it.
// onMade runs after a sound was newly fetched from the server (not when it came from the cache).
export default function Listen({ method = "GET", path, body, cacheKey, label = "Listen", disabled = false, onMade }) {
  const [state, setState] = useState("idle"); // idle | loading | playing
  const [error, setError] = useState("");
  const audioRef = useRef(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (audioRef.current) audioRef.current.pause();
    };
  }, []);

  async function press() {
    if (state === "playing") {
      audioRef.current.pause();
      return;
    }
    if (state === "loading") return;
    setError("");
    setState("loading");
    try {
      let url = cacheKey ? cache.get(cacheKey) : null;
      if (!url) {
        url = await fetchAudio(method, path, body);
        if (cacheKey) remember(cacheKey, url);
        if (onMade) onMade();
      }
      if (!mounted.current) return;
      if (playing) playing.pause();
      const audio = new Audio(url);
      audioRef.current = audio;
      playing = audio;
      // "pause" also fires when a clip ends, so this covers finishing and stopping.
      audio.addEventListener("pause", () => mounted.current && setState("idle"));
      await audio.play();
      if (mounted.current && !audio.paused) setState("playing");
    } catch (e) {
      if (!mounted.current) return;
      setState("idle");
      setError(e && e.name === "NotAllowedError" ? "The browser blocked playback. Press Listen again." : (e && e.message) || "Could not play the voice.");
    }
  }

  return (
    <span className="listen">
      <button className="btn" type="button" onClick={press} disabled={disabled || state === "loading"}>
        {state === "loading" ? "Making voice" : state === "playing" ? "Stop" : label}
      </button>
      {error && (
        <span className="listen-error" role="alert">
          {error}
        </span>
      )}
    </span>
  );
}
