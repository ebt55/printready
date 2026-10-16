// A minimal observable store. Screens subscribe and re-render the parts whose keys changed.

export function createStore(initial) {
  let state = { ...initial };
  const subscribers = new Set();
  return {
    get() {
      return state;
    },
    set(patch) {
      const changed = new Set();
      for (const [k, v] of Object.entries(patch)) {
        if (state[k] !== v) changed.add(k);
      }
      if (!changed.size) return;
      state = { ...state, ...patch };
      for (const fn of subscribers) fn(state, changed);
    },
    subscribe(fn) {
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },
  };
}

export const store = createStore({
  app: null, // GET /api/state (or the static export's copy)
  screen: "workbench",
  route: { screen: "workbench" },
  theme: "auto",
  runs: [], // recent runs (out/workbench only)
  draft: null, // the artwork chosen but not yet run
  order: { size: 3, mode: "rules", model: "xai:grok-4.3", vision: false },
  run: null, // the RunView on stage (live-updating while it streams)
  runError: null,
  busy: false, // creating a run
  view: "after",
  overlays: { cut: true, boxes: true, border: false, ruler: false },
  backdrop: "checker",
  side: "after", // which report the findings list shows
  focusCheck: null, // { check, pinned }
  stepIndex: null,
});
