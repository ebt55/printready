// The Workbench screen: left rail, centre stage, right panel. Owns the run lifecycle:
// choose art -> POST /api/runs -> stream events (SSE) into the RunView -> fetch the final view.

import { h, storageGet, storageSet } from "./dom.js";
import { icon, logoMark } from "./icons.js";
import { api, fileToBase64, isStatic, subscribe, urlToBase64 } from "./api.js";
import { store } from "./store.js";
import { createStage } from "./stage.js";
import { renderTrace } from "./trace.js";
import { renderPanel } from "./panel.js";
import { renderRail, validateFile } from "./rail.js";
import { rulesIndex } from "./rules.js";
import { bind } from "./shortcuts.js";
import { usd } from "./format.js";
import { confirmDialog, segmented, toast } from "./ui.js";

const BACKDROP_ORDER = ["checker", "white", "dark", "kraft"];
const VIEW_KEYS = ["before", "after", "compare", "steps", "trace"];

// ---------------------------------------------------------------- event reducer (SSE -> RunView)
export function applyEvent(run, ev) {
  const next = { ...run, steps: [...run.steps], turns: [...run.turns], reports: { ...run.reports }, event_count: (run.event_count || 0) + 1 };
  if (ev.type === "findings") {
    if (ev.stage === "read_text") next.reports.text = ev.report;
    else {
      // "before" is the report on the upload; later stages (check, after) update the latest one
      if (!next.reports.first || ev.stage === "before") next.reports.first = ev.report;
      next.reports.latest = ev.report;
    }
  } else if (ev.type === "step") {
    next.steps.push({ step: ev.step || {}, preview: ev.preview_info || null });
  } else if (ev.type === "turn") {
    const t = { ...ev };
    delete t.type;
    delete t.image_info;
    t.image = ev.image_info || null;
    next.turns.push(t);
  } else if (ev.type === "done") {
    next.status = "done";
    next.result = ev.result;
  } else if (ev.type === "error") {
    next.status = "error";
    next.error = ev.message;
  }
  return next;
}

export function createWorkbench(root) {
  const rail = h("aside", { class: "rail", "aria-label": "Artwork and order" });
  const stageHost = h("section", { class: "stage", "aria-label": "Stage" });
  const panel = h("aside", { class: "panel", "aria-label": "Outcome and findings" });
  root.append(h("div", { class: "wb" }, rail, stageHost, panel));
  const fileInput = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", hidden: true, onChange: (e) => e.target.files.length && onFiles(e.target.files) });
  root.append(fileInput);

  let closeStream = null;
  let routeKey = null;
  let local = { fileError: null, customSize: false, loading: false };

  // restore preferences
  const savedOrder = storageGet("order", null);
  const savedOverlays = storageGet("overlays", null);
  const savedBackdrop = storageGet("backdrop", null);
  store.set({
    order: { ...store.get().order, ...(savedOrder || {}) },
    overlays: { ...store.get().overlays, ...(savedOverlays || {}) },
    backdrop: savedBackdrop || store.get().backdrop,
  });

  const st = () => store.get();
  const model = () => ({ ...st(), ...local, readonly: Boolean(isStatic || (st().run && st().run.readonly)) });

  // ---------------------------------------------------------------- actions
  const stageActions = {
    setView: (v) => store.set({ view: v }),
    setOverlay: (k, v) => {
      const overlays = { ...st().overlays, [k]: v };
      store.set({ overlays });
      storageSet("overlays", overlays);
    },
    setBackdrop: (b) => {
      store.set({ backdrop: b });
      storageSet("backdrop", b);
    },
    setStep: (i) => store.set({ stepIndex: i, view: "steps" }),
    onFiles: (files) => onFiles(files),
    onSample: (id) => (isStatic ? openRun(id) : pickSample(id)),
    pickFile: () => fileInput.click(),
    canDrop: () => !isStatic,
    samples: () => (isStatic ? (st().runs || []).slice(0, 8).map((r) => ({ id: r.id, title: r.title || r.filename, thumb: r.thumb })) : (st().app && st().app.samples) || []),
    heroMark: () => logoMark(64),
    renderTrace: (host) => st().run && renderTrace(host, st().run),
  };
  const stage = createStage(stageHost, stageActions);

  const panelActions = {
    hoverCheck: (check) => {
      const f = st().focusCheck;
      if (f && f.pinned) return;
      store.set({ focusCheck: check ? { check, pinned: false } : null });
    },
    pinCheck: (check) => {
      const f = st().focusCheck;
      store.set({ focusCheck: f && f.pinned && f.check === check ? { check, pinned: false } : { check, pinned: true } });
    },
    setSide: (side) => store.set({ side }),
    showStep: (i) => store.set({ view: "steps", stepIndex: i }),
    retry: () => runNow(),
  };

  const railActions = {
    pickFile: () => fileInput.click(),
    clearDraft: () => {
      local.fileError = null;
      store.set({ draft: null });
    },
    onFiles: (files) => onFiles(files),
    onSample: (id) => pickSample(id),
    setSize: (size, custom) => {
      local.customSize = Boolean(custom);
      setOrder({ size });
    },
    setCustomSize: (on) => {
      local.customSize = on;
      renderAll();
    },
    setMode: (mode) => setOrder({ mode }),
    setVision: (vision) => setOrder({ vision }),
    setModel: (m) => setOrder({ model: m }),
    openRun: (id) => (location.hash = `#/workbench/run/${encodeURIComponent(id)}`),
    run: () => runNow(),
  };

  function setOrder(patch) {
    const order = { ...st().order, ...patch };
    store.set({ order });
    storageSet("order", { size: order.size, mode: order.mode, model: order.model, vision: order.vision });
  }

  // ---------------------------------------------------------------- choosing art
  function onFiles(files) {
    const file = files[0];
    if (!file) return;
    const err = validateFile(file);
    if (err) {
      local.fileError = err;
      toast(err, "error");
      renderAll();
      return;
    }
    local.fileError = null;
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      setDraft({ kind: "file", file, name: file.name || "pasted image", url, w: img.naturalWidth, h: img.naturalHeight, bytes: file.size, key: url });
    };
    img.onerror = () => {
      local.fileError = "This file does not open as an image.";
      toast(local.fileError, "error");
      renderAll();
    };
    img.src = url;
  }

  function pickSample(id) {
    const sample = ((st().app && st().app.samples) || []).find((x) => x.id === id);
    if (!sample) return;
    local.fileError = null;
    setDraft({ kind: "sample", sampleId: id, name: sample.title, url: sample.image, thumb: sample.thumb, w: sample.width, h: sample.height, bytes: null, key: "sample:" + id });
  }

  function setDraft(draft) {
    const prev = st().draft;
    if (prev && prev.kind === "file" && prev.url !== draft.url) URL.revokeObjectURL(prev.url);
    if (st().route.runId || st().route.realset) {
      store.set({ draft });
      location.hash = "#/workbench";
    } else {
      store.set({ draft, view: "before" });
    }
  }

  // ---------------------------------------------------------------- running
  async function runNow() {
    const s0 = st();
    const app = s0.app || {};
    const draft = s0.draft;
    if (!draft || s0.busy || isStatic) return;
    const order = s0.order;
    const paid = order.mode === "agent" || order.vision;
    if (paid && !app.demo) {
      const m = (app.models || []).find((x) => x.id === order.model) || {};
      const est = order.mode === "agent" ? m.est_agent_usd : m.est_vision_usd;
      const spend = app.spend || { total_usd: 0, cap_usd: 10 };
      const ok = await confirmDialog({
        title: order.mode === "agent" ? "Run the agent?" : "Run the text check?",
        body: h(
          "div",
          { style: { display: "grid", gap: "12px" } },
          h("p", null, `This calls ${m.label || order.model} on ${draft.name}. The estimate is an upper end; the real cost comes from token usage and is recorded in the spend ledger.`),
          h(
            "dl",
            { class: "details", style: { fontSize: "13px" } },
            h("dt", null, "Estimated cost"),
            h("dd", null, h("b", null, `≤ ${usd(est)}`)),
            h("dt", null, "Ledger"),
            h("dd", null, `${usd(spend.total_usd, { cents: true })} of ${usd(spend.cap_usd, { cents: true })} cap`),
            h("dt", null, "After this run"),
            h("dd", null, `≤ ${usd(spend.total_usd + (est || 0), { cents: true })}`)
          )
        ),
        confirm: `Run · ≤ ${usd(est)}`,
      });
      if (!ok) return;
    }
    store.set({ busy: true });
    try {
      const payload = { size_in: order.size, mode: order.mode, model: order.model, vision: order.mode === "agent" ? true : order.vision, filename: draft.name };
      if (draft.kind === "sample") payload.sample_id = draft.sampleId;
      else if (draft.kind === "file") payload.image_b64 = await fileToBase64(draft.file);
      else payload.image_b64 = await urlToBase64(draft.url);
      if (draft.kind === "run") payload.filename = draft.name;
      const { run_id } = await api.createRun(payload);
      store.set({ view: order.mode === "agent" ? "trace" : "after", side: "after", stepIndex: null, focusCheck: null });
      location.hash = `#/workbench/run/${encodeURIComponent(run_id)}`;
      refreshRuns();
    } catch (e) {
      toast(e.message || String(e), "error", 7000);
    } finally {
      store.set({ busy: false });
    }
  }

  async function refreshRuns() {
    try {
      const { runs } = await api.runs();
      store.set({ runs });
    } catch (e) {
      /* the list is a convenience; the run itself still works */
    }
  }

  function stopStream() {
    if (closeStream) closeStream();
    closeStream = null;
  }

  async function openRun(id) {
    stopStream();
    local.loading = true;
    store.set({ runError: null });
    renderAll();
    try {
      const view = await api.run(id);
      local.loading = false;
      // Keep the current view when it makes sense for this run (continuity while browsing runs).
      let v = st().view;
      if (!VIEW_KEYS.includes(v)) v = "after";
      if (v === "trace" && view.mode !== "agent") v = "after";
      if (v === "before" && !st().run) v = "after";
      if ((view.status === "running" || view.status === "queued") && view.mode === "agent") v = "trace";
      // The run's art becomes the current artwork, so "run it again at another size" is one click.
      let draft = st().draft;
      if (!isStatic && view.images && view.images.original) {
        if (draft && draft.kind === "file" && draft.url.startsWith("blob:")) URL.revokeObjectURL(draft.url);
        draft = { kind: view.sample_id ? "sample" : "run", sampleId: view.sample_id, name: view.filename || "artwork", url: view.images.original.url, w: view.images.original.w, h: view.images.original.h, key: "run:" + view.id };
      }
      store.set({ run: view, view: v, stepIndex: null, draft });
      if ((view.status === "running" || view.status === "queued") && !isStatic) follow(view);
    } catch (e) {
      local.loading = false;
      store.set({ run: null, runError: e.message || String(e) });
      toast(e.message || String(e), "error");
    }
  }

  async function openRealset(run, sha, mode) {
    stopStream();
    local.loading = true;
    renderAll();
    try {
      const view = await api.realsetItem(run, sha, mode);
      local.loading = false;
      store.set({ run: view, view: st().view === "trace" && mode !== "agent" ? "after" : st().view || "after", stepIndex: null });
    } catch (e) {
      local.loading = false;
      store.set({ run: null, runError: e.message || String(e) });
      toast(e.message || String(e), "error");
    }
  }

  function follow(view) {
    const id = view.id;
    closeStream = subscribe(
      id,
      view.event_count || 0,
      async (ev) => {
        const cur = st().run;
        if (!cur || cur.id !== id) return;
        store.set({ run: applyEvent(cur, ev) });
        if (ev.type === "done" || ev.type === "error") {
          closeStream = null;
          try {
            const final = await api.run(id); // authoritative: images, downloads, cut line
            if (st().run && st().run.id === id) store.set({ run: final });
          } catch (e) {
            /* keep the streamed view */
          }
          refreshRuns();
          if (ev.type === "done") toast(`Done: ${(ev.result && ev.result.outcome || "").replace("_", " ")}`, "ok", 2600);
        }
      },
      async () => {
        // the stream dropped (server restarted?): reload the view once
        try {
          const v = await api.run(id);
          if (st().run && st().run.id === id) store.set({ run: v });
        } catch (e) {
          toast("Lost the connection to the server.", "error");
        }
      }
    );
  }

  // ---------------------------------------------------------------- rendering
  function renderAll(changed) {
    const m = model();
    const ctx = { rules: rulesIndex(m.app), size: (m.run && m.run.spec && m.run.spec.size_in) || m.order.size };
    const only = changed && changed.size === 1 && changed.has("focusCheck");
    if (only) {
      stage.updateFocus(m);
      renderPanel(panel, m, panelActions, ctx);
      return;
    }
    renderRail(rail, m, railActions);
    stage.render(m);
    if (m.run && m.run.readonly && m.run.realset) {
      renderPanel(panel, m, panelActions, ctx);
      panel.insertBefore(readonlyBar(m), panel.firstChild);
    } else {
      renderPanel(panel, m, panelActions, ctx);
    }
  }

  function readonlyBar(m) {
    const rs = m.run.realset;
    return h(
      "div",
      { class: "section", style: { paddingBottom: "4px" } },
      h(
        "div",
        { class: "notice" },
        icon("lock", 14),
        h("span", { class: "grow" }, h("b", null, "Saved real-set run, read-only. "), `${rs.run} · ${rs.image.slice(0, 10)}${rs.image_model ? " · " + rs.image_model : ""}`)
      ),
      rs.modes.length > 1
        ? h(
            "div",
            { style: { marginTop: "8px" } },
            segmented(
              rs.modes.map((x) => ({ value: x, label: x === "agent" ? "Agent run" : "Rules run" })),
              m.run.mode,
              (v) => (location.hash = `#/workbench/realset/${encodeURIComponent(rs.run)}/${rs.image}/${v}`),
              { block: true, small: true, label: "Mode" }
            )
          )
        : null
    );
  }

  store.subscribe((state, changed) => {
    if (state.screen !== "workbench") return;
    const keys = ["app", "draft", "order", "run", "runs", "busy", "view", "overlays", "backdrop", "side", "focusCheck", "stepIndex", "runError", "theme"];
    if (keys.some((k) => changed.has(k))) renderAll(changed);
  });

  // paste an image anywhere on the workbench
  document.addEventListener("paste", (e) => {
    if (st().screen !== "workbench" || isStatic) return;
    const items = Array.from((e.clipboardData && e.clipboardData.items) || []);
    const item = items.find((i) => i.kind === "file" && i.type.startsWith("image/"));
    if (!item) return;
    e.preventDefault();
    const f = item.getAsFile();
    if (f) onFiles([new File([f], f.name && f.name !== "image.png" ? f.name : "pasted.png", { type: f.type })]);
  });

  // ---------------------------------------------------------------- shortcuts
  const wb = () => st().screen === "workbench" && st().app && st().app.mode !== "label";
  const G = "Workbench";
  const S = "Stage";
  bind({ keys: "ctrl+enter", label: "Run", group: G, when: wb, run: runNow, inInputs: true });
  bind({ keys: "o", label: "Open a file", group: G, when: () => wb() && !isStatic, run: () => fileInput.click() });
  bind({ keys: "m", label: "Toggle rules / agent", group: G, when: () => wb() && !isStatic, run: () => setOrder({ mode: st().order.mode === "agent" ? "rules" : "agent" }) });
  VIEW_KEYS.forEach((v, i) =>
    bind({ keys: String(i + 1), label: i === 0 ? "Views: before, after, compare, steps, trace" : null, display: "1", group: S, when: wb, run: () => {
      const run = st().run;
      if (!run && v !== "before") return;
      if (v === "trace" && !(run && run.mode === "agent")) return;
      store.set({ view: v });
    } })
  );
  bind({ keys: "f", label: "Fit to screen", group: S, when: wb, run: () => stage.fit() });
  bind({ keys: "0", label: "Zoom to 100 %", group: S, when: wb, run: () => stage.zoom100() });
  bind({ keys: "i", label: "Actual size in inches", group: S, when: wb, run: () => stage.actualSize() });
  bind({ keys: "=", alt: ["+", "shift+="], label: "Zoom in", display: "+", group: S, when: wb, run: () => stage.zoomIn() });
  bind({ keys: "-", label: "Zoom out", group: S, when: wb, run: () => stage.zoomOut() });
  bind({ keys: "c", label: "Cut line", group: S, when: wb, run: () => stageActions.setOverlay("cut", !st().overlays.cut) });
  bind({ keys: "x", label: "Finding boxes", group: S, when: wb, run: () => stageActions.setOverlay("boxes", !st().overlays.boxes) });
  bind({ keys: "b", label: "Border region", group: S, when: wb, run: () => stageActions.setOverlay("border", !st().overlays.border) });
  bind({ keys: "r", label: "Inch ruler", group: S, when: wb, run: () => stageActions.setOverlay("ruler", !st().overlays.ruler) });
  bind({ keys: "d", label: "Cycle background", group: S, when: wb, run: () => stageActions.setBackdrop(BACKDROP_ORDER[(BACKDROP_ORDER.indexOf(st().backdrop) + 1) % BACKDROP_ORDER.length]) });
  bind({ keys: "[", label: "Previous step", group: S, when: wb, run: () => stepBy(-1) });
  bind({ keys: "]", label: "Next step", group: S, when: wb, run: () => stepBy(1) });
  bind({ keys: "escape", label: "Clear the highlighted finding", group: G, when: () => wb() && st().focusCheck, run: () => store.set({ focusCheck: null }) });

  function stepBy(d) {
    const run = st().run;
    if (!run) return;
    const n = run.steps.length;
    const cur = st().view === "steps" ? (st().stepIndex ?? n) : n;
    store.set({ view: "steps", stepIndex: Math.max(0, Math.min(n, cur + d)) });
  }

  // ---------------------------------------------------------------- routing
  function show(route) {
    const key = JSON.stringify(route);
    if (key === routeKey) {
      renderAll();
      return;
    }
    routeKey = key;
    store.set({ route });
    if (route.runId) openRun(route.runId);
    else if (route.realset) openRealset(route.realset.run, route.realset.sha, route.realset.mode);
    else {
      stopStream();
      store.set({ run: null, runError: null, view: st().draft ? "before" : st().view, stepIndex: null, focusCheck: null });
      renderAll();
    }
  }

  refreshRuns();
  return { show, refreshRuns };
}

