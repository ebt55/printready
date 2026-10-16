// Boot, routing, theme and the global shortcuts. Screens live in their own modules.
// Routes: #/workbench, #/workbench/run/<id>, #/workbench/realset/<split>/<sha>/<mode>,
//         #/results, #/label, #/label/2

import { h, clear, qs, storageGet, storageSet } from "./dom.js";
import { api, isStatic } from "./api.js";
import { store } from "./store.js";
import { renderFooter, renderHeader } from "./header.js";
import { createWorkbench } from "./workbench.js";
import { createResults } from "./results.js";
import { createLabel } from "./label.js";
import { bind, installShortcuts, showShortcuts } from "./shortcuts.js";
import { empty, toast } from "./ui.js";

const THEMES = ["auto", "light", "dark"];

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

function parseRoute() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const screen = ["workbench", "results", "label"].includes(parts[0]) ? parts[0] : "workbench";
  if (screen === "workbench" && parts[1] === "run" && parts[2]) return { screen, runId: parts[2] };
  if (screen === "workbench" && parts[1] === "realset" && parts[4]) return { screen, realset: { run: parts[2], sha: parts[3], mode: parts[4] } };
  if (screen === "label") return { screen, pass: parts[1] === "2" ? 2 : parts[1] === "1" ? 1 : null };
  return { screen };
}

async function boot() {
  const appEl = qs("#app");
  const header = qs("#topbar");
  const footer = qs("#footbar");
  const main = qs("#main");
  const labelMode = (qs('meta[name="printready-mode"]') || {}).content === "label";
  appEl.dataset.mode = labelMode ? "label" : "app";

  const theme = storageGet("theme", "auto");
  applyTheme(theme);
  store.set({ theme });

  installShortcuts();
  const screens = {
    workbench: h("section", { class: "screen", "data-screen": "workbench", hidden: true }),
    results: h("section", { class: "screen", "data-screen": "results", hidden: true }),
    label: h("section", { class: "screen", "data-screen": "label", hidden: true }),
  };
  clear(main);
  main.append(screens.workbench, screens.results, screens.label);

  if (labelMode) {
    // Label mode: only the label screen exists (the server refuses every other route).
    store.set({ app: { mode: "label" }, screen: "label" });
    screens.label.hidden = false;
    const label = createLabel(screens.label);
    label.show({});
    bind({ keys: "?", label: "Show shortcuts", group: "General", run: showShortcuts });
    return;
  }

  let app;
  try {
    app = await api.state();
  } catch (e) {
    clear(main);
    main.append(h("div", { class: "boot" }, empty("alert", "Cannot reach the printready server", e.message)));
    return;
  }
  if (isStatic) app = { ...app, static: true };
  const order = store.get().order;
  const models = (app.models || []).map((m) => m.id);
  store.set({
    app,
    order: {
      ...order,
      model: models.includes(order.model) ? order.model : app.default_model || models[0],
      vision: storageGet("order", null) ? order.vision : Boolean(app.demo),
    },
  });

  const cycleTheme = () => {
    const next = THEMES[(THEMES.indexOf(store.get().theme) + 1) % THEMES.length];
    storageSet("theme", next);
    applyTheme(next);
    store.set({ theme: next });
  };
  const drawChrome = () => {
    const st = store.get();
    renderHeader(header, st.app, st.screen, st.theme, { cycleTheme });
    renderFooter(footer, st.app);
  };

  const workbench = createWorkbench(screens.workbench);
  const results = createResults(screens.results);
  const label = createLabel(screens.label);

  function route() {
    const r = parseRoute();
    if (isStatic && r.screen === "label") {
      location.hash = "#/workbench";
      return;
    }
    store.set({ screen: r.screen });
    for (const [name, el] of Object.entries(screens)) el.hidden = name !== r.screen;
    document.title = { workbench: "Workbench · printready", results: "Results · printready", label: "Label · printready" }[r.screen];
    if (r.screen === "workbench") workbench.show(r);
    else if (r.screen === "results") results.show(r);
    else label.show(r);
    drawChrome();
  }

  store.subscribe((st, changed) => {
    if (changed.has("app") || changed.has("theme") || changed.has("screen")) drawChrome();
    // A finished run may have moved the spend ledger: refresh the header's numbers.
    if (changed.has("run") && st.run && st.run.status === "done" && !isStatic && !st.run.readonly && st.run._counted !== true) {
      st.run._counted = true;
      api.state().then((fresh) => store.set({ app: { ...store.get().app, spend: fresh.spend, results: fresh.results } })).catch(() => {});
    }
  });

  const G = "General";
  bind({ keys: "?", label: "Show shortcuts", group: G, run: showShortcuts });
  bind({ keys: "g w", label: "Go to Workbench", group: G, run: () => (location.hash = "#/workbench") });
  bind({ keys: "g r", label: "Go to Results", group: G, run: () => (location.hash = "#/results") });
  if (!isStatic) bind({ keys: "g l", label: "Go to Label", group: G, run: () => (location.hash = "#/label") });
  bind({ keys: "shift+t", label: "Switch theme", group: G, run: cycleTheme });

  window.addEventListener("hashchange", route);
  if (!location.hash) history.replaceState(null, "", "#/workbench");
  route();
  if (app.demo && !storageGet("demo-hello", false)) {
    storageSet("demo-hello", true);
    toast("Demo mode: saved runs replay with a scripted model. Nothing is charged.", "info", 6000);
  }
}

boot();
