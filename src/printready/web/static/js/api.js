// The backend, behind one interface. Live: fetch + Server-Sent Events against the local server.
// Static export: the same calls answered from window.PRINTREADY_STATIC (data.js), no network.

const STATIC = window.PRINTREADY_STATIC || null;
export const isStatic = Boolean(STATIC);

export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (e) {
    throw new ApiError("Cannot reach the printready server. Is `printready serve` still running?", 0, "offline");
  }
  let data = null;
  try {
    data = await response.json();
  } catch (e) {
    data = null;
  }
  if (!response.ok) {
    const message = (data && data.message) || `Request failed (${response.status})`;
    throw new ApiError(message, response.status, data && data.error);
  }
  return data;
}

function getJSON(url) {
  return request(url, { headers: { Accept: "application/json" } });
}

function postJSON(url, body) {
  return request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
}

function fromStatic(value, what) {
  if (value === undefined || value === null) return Promise.reject(new ApiError(`${what} is not part of this export`, 404, "not_found"));
  return Promise.resolve(value);
}

export const api = {
  state: () => (STATIC ? Promise.resolve(STATIC.state) : getJSON("/api/state")),
  runs: () => (STATIC ? Promise.resolve({ runs: STATIC.examples || [] }) : getJSON("/api/runs")),
  run: (id) => (STATIC ? fromStatic(STATIC.runs[id], "This run") : getJSON(`/api/runs/${encodeURIComponent(id)}`)),
  createRun: (payload) => (STATIC ? Promise.reject(new ApiError("Read-only demo", 403, "static")) : postJSON("/api/runs", payload)),
  bench: (split) =>
    STATIC ? Promise.resolve((STATIC.bench || {})[split] || { available: false, split, reason: "Not included in this export." }) : getJSON(`/api/results/bench/${split}`),
  realsets: () => (STATIC ? Promise.resolve({ runs: STATIC.realsets || [] }) : getJSON("/api/results/realset")),
  realset: (run) => (STATIC ? fromStatic((STATIC.realset || {})[run], "This real-set run") : getJSON(`/api/results/realset/${encodeURIComponent(run)}`)),
  realsetItem: (run, sha, mode) =>
    STATIC
      ? fromStatic((STATIC.items || {})[`${run}/${sha}/${mode}`], "This item")
      : getJSON(`/api/results/realset/${encodeURIComponent(run)}/items/${sha}/${mode}`),
  labelSession: (pass) => getJSON(`/api/label/session${pass ? `?pass=${pass}` : ""}`),
  label: (body) => postJSON("/api/label", body),
  // Text files (the cut line SVG). The export embeds them, because file:// pages cannot fetch.
  text: async (url) => {
    if (STATIC) return (STATIC.texts || {})[url] || null;
    const r = await fetch(url);
    if (!r.ok) throw new ApiError(`Could not load ${url}`, r.status);
    return r.text();
  },
};

// Stream a run's events. Returns a function that closes the stream.
export function subscribe(runId, from, onEvent, onDrop) {
  if (STATIC) return () => {};
  const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events?from=${from || 0}`);
  let closed = false;
  const close = () => {
    if (!closed) {
      closed = true;
      source.close();
    }
  };
  for (const type of ["findings", "step", "turn", "done", "error"]) {
    source.addEventListener(type, (e) => {
      let data = null;
      try {
        data = JSON.parse(e.data);
      } catch (err) {
        return;
      }
      onEvent(data);
      if (type === "done" || type === "error") close();
    });
  }
  source.addEventListener("end", close);
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED && !closed) {
      closed = true;
      if (onDrop) onDrop();
    }
  };
  return close;
}

export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error("Could not read the file"));
    reader.readAsDataURL(file);
  });
}

export async function urlToBase64(url) {
  const r = await fetch(url);
  if (!r.ok) throw new ApiError("Could not load the image", r.status);
  return fileToBase64(await r.blob());
}
