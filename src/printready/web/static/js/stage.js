// The centre stage: the art in Before / After / Compare / Steps views (Trace is drawn by trace.js
// into the same column). One "world" in art pixels holds every layer; zoom and pan are a CSS
// transform on it, so boxes and the cut line stay aligned at any zoom.
//
// Coordinates: the world is the FINAL art's canvas (fixed.png). The original sits at
// result.art.offset inside it (pad_canvas shifts the art), before-report boxes are shifted by
// that offset, after-report boxes are already in world coordinates. The cut line comes from
// cutline.svg, whose viewBox spans the canvas in inches, so it maps onto the world exactly.

import { h, s, clear, cssVar } from "./dom.js";
import { icon } from "./icons.js";
import { api } from "./api.js";
import { checkName, fixName, num, sizeLabel } from "./format.js";
import { openMenu, segmented } from "./ui.js";

const PAD = 44;
const RULER = 22;
const MIN_SCALE = 0.02;
const MAX_SCALE = 32;
const MAX_FIT = 6; // tiny images are not blown up past 6x by "fit"

const VIEWS = [
  { value: "before", label: "Before", kbd: "1" },
  { value: "after", label: "After", kbd: "2" },
  { value: "compare", label: "Compare", kbd: "3" },
  { value: "steps", label: "Steps", kbd: "4" },
  { value: "trace", label: "Trace", kbd: "5", icon: "bot" },
];

const OVERLAYS = [
  { key: "cut", icon: "cut", label: "Cut line", kbd: "C" },
  { key: "boxes", icon: "boxes", label: "Finding boxes", kbd: "X" },
  { key: "border", icon: "border", label: "Border region", kbd: "B" },
  { key: "ruler", icon: "ruler", label: "Inch ruler at the ordered size", kbd: "R" },
];

const BACKDROPS = [
  { value: "checker", label: "Transparency checkerboard" },
  { value: "white", label: "White" },
  { value: "dark", label: "Dark" },
  { value: "kraft", label: "Kraft paper" },
];

const svgCache = new Map(); // url -> Promise<{ paths, vb }>
const cutReady = new Map(); // url -> { paths, vb } once loaded (drawn synchronously after that)

function loadCut(url) {
  if (!svgCache.has(url)) {
    svgCache.set(
      url,
      api.text(url).then((text) => {
        if (!text) return null;
        const doc = new DOMParser().parseFromString(text, "image/svg+xml");
        const root = doc.documentElement;
        const vbAttr = root.getAttribute("viewBox");
        const vb = vbAttr ? vbAttr.trim().split(/[\s,]+/).map(Number) : null;
        const paths = Array.from(doc.querySelectorAll("path"))
          .map((p) => p.getAttribute("d"))
          .filter(Boolean)
          .concat(Array.from(doc.querySelectorAll("rect")).map(rectPath));
        const cut = { paths, vb: vb && vb.length === 4 && vb[2] > 0 ? vb : null };
        cutReady.set(url, cut);
        return cut;
      }).catch(() => null)
    );
  }
  return svgCache.get(url);
}

// A rounded-rectangle cut line may come as <rect rx>; draw it as a path like the die-cut ones.
function rectPath(r) {
  const n = (k) => Number(r.getAttribute(k) || 0);
  const x = n("x");
  const y = n("y");
  const w = n("width");
  const hh = n("height");
  const rx = Math.min(n("rx") || n("ry"), w / 2, hh / 2);
  const ry = Math.min(n("ry") || rx, hh / 2);
  if (!rx) return `M ${x} ${y} H ${x + w} V ${y + hh} H ${x} Z`;
  return `M ${x + rx} ${y} H ${x + w - rx} A ${rx} ${ry} 0 0 1 ${x + w} ${y + ry} V ${y + hh - ry} A ${rx} ${ry} 0 0 1 ${x + w - rx} ${y + hh} H ${x + rx} A ${rx} ${ry} 0 0 1 ${x} ${y + hh - ry} V ${y + ry} A ${rx} ${ry} 0 0 1 ${x + rx} ${y} Z`;
}

function aspectClose(a, b) {
  return a.w && a.h && b.w && b.h && Math.abs(a.w / a.h - b.w / b.h) < 0.01;
}

function reportPPI(report) {
  const f = report && (report.findings || []).find((x) => x.check === "resolution");
  return f && f.measured && typeof f.measured.ppi === "number" ? f.measured.ppi : null;
}

export function createStage(root, actions) {
  const st = {
    model: null,
    t: { s: 1, tx: 0, ty: 0 },
    W: 1,
    H: 1,
    fitKey: null,
    userZoomed: false,
    interacted: false,
    compare: 0.5,
    scene: null,
    cut: null, // { paths, k, ox, oy, unitsPerIn }
    cutBox: null, // world-px bbox of the cut, for the ruler origin
    colors: null,
  };

  // ------------------------------------------------------------ DOM (built once)
  const bar = h("div", { class: "stage-bar" });
  const imgUnder = h("img", { class: "layer", alt: "", draggable: "false", decoding: "async" });
  const imgOver = h("img", { class: "layer", alt: "", draggable: "false", decoding: "async" });
  const overlay = s("svg", { class: "overlay", "aria-hidden": "true" });
  const world = h("div", { class: "world" }, imgUnder, imgOver, overlay);
  const artboard = h("div", { class: "artboard checker" });
  const labels = h("div", { class: "box-labels" });
  const rulerX = h("canvas", { class: "ruler ruler-x", "aria-hidden": "true" });
  const rulerY = h("canvas", { class: "ruler ruler-y", "aria-hidden": "true" });
  const corner = h("div", { class: "ruler-corner", "aria-hidden": "true" }, "in");
  const hudTL = h("div", { class: "hud hud-tl" });
  const hudTR = h("div", { class: "hud hud-tr" });
  const hudBL = h("div", { class: "hud hud-bl" });
  const hudBR = h("div", { class: "hud hud-br" });
  const progress = h("div", { class: "stage-progress", hidden: true }, h("i"));
  // While a run has produced no fix yet, the art is shown dimmed with this in the middle.
  const waitPill = h("div", { class: "stage-wait", hidden: true, role: "status" }, h("span", { class: "spinner" }), "Checking the art; fixes appear here");
  const grip = h(
    "button",
    { class: "compare-grip", type: "button", role: "slider", "aria-label": "Compare divider", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "50" },
    icon("arrows", 16)
  );
  const compareEl = h("div", { class: "compare", hidden: true }, h("div", { class: "compare-line" }), grip);
  const emptyEl = h("div", { class: "stage-empty", hidden: true });
  const viewport = h(
    "div",
    { class: "viewport", tabindex: "0", "aria-label": "Artwork. Scroll to zoom, drag to pan, arrow keys to move." },
    artboard,
    world,
    labels,
    rulerX,
    rulerY,
    corner,
    compareEl,
    hudTL,
    hudTR,
    hudBL,
    hudBR,
    progress,
    waitPill,
    emptyEl
  );
  const stepsEl = h("div", { class: "steps-strip", hidden: true });
  const traceEl = h("div", { class: "trace", hidden: true, tabindex: "-1" });
  root.append(bar, viewport, stepsEl, traceEl);

  // ------------------------------------------------------------ scene: what to draw for the model
  function computeScene(m) {
    const run = m.run;
    const draft = m.draft;
    const sc = { W: 1, H: 1, under: null, over: null, boxes: [], ppi: null, ppiApprox: false, size: m.order.size, key: "none", steps: [], label: "", running: false };
    if (run) {
      const res = run.result;
      const art = res && res.art;
      const orig = run.images.original;
      const fixed = run.images.fixed;
      const off = (art && art.offset) || [0, 0];
      sc.size = (run.spec && run.spec.size_in) || sc.size;
      sc.running = run.status === "running" || run.status === "queued";
      sc.W = (art && art.width) || (fixed && fixed.w) || (orig && orig.w) || 1;
      sc.H = (art && art.height) || (fixed && fixed.h) || (orig && orig.h) || 1;
      sc.ppi = (art && art.ppi) || reportPPI(run.reports.latest) || reportPPI(run.reports.first);
      sc.key = `run:${run.id}:${sc.W}x${sc.H}`;
      const world = { w: sc.W, h: sc.H };
      const place = (img) => {
        if (!img) return null;
        if (img === orig) return { url: img.url, x: off[0], y: off[1], w: orig.w || sc.W, h: orig.h || sc.H };
        if (img.w === sc.W && img.h === sc.H) return { url: img.url, x: 0, y: 0, w: sc.W, h: sc.H };
        if (aspectClose(img, world)) return { url: img.url, x: 0, y: 0, w: sc.W, h: sc.H }; // a downscaled preview
        if (orig && img.w === orig.w && img.h === orig.h) return { url: img.url, x: off[0], y: off[1], w: orig.w, h: orig.h };
        const k = Math.min(sc.W / img.w, sc.H / img.h);
        return { url: img.url, x: (sc.W - img.w * k) / 2, y: (sc.H - img.h * k) / 2, w: img.w * k, h: img.h * k };
      };
      const lastPreview = [...run.steps].reverse().find((x) => x.preview);
      const afterImg = fixed || (lastPreview && lastPreview.preview) || null;
      sc.steps = [{ label: "Original", sub: "as uploaded", img: orig, state: "ok", note: "The file as uploaded, before any fix." }].concat(
        run.steps.map((x) => ({
          label: fixName(x.step.fix),
          sub: x.step.damaged ? "reverted" : x.step.ok ? "applied" : "refused",
          img: x.preview,
          state: x.step.damaged ? "damaged" : x.step.ok ? "ok" : "refused",
          note: x.step.note,
        }))
      );
      const v = m.view;
      if (v === "before") {
        sc.under = place(orig);
        sc.label = "Original, as uploaded";
      } else if (v === "after") {
        sc.over = place(afterImg || orig);
        sc.label = fixed ? "Print file · fixed.png" : afterImg ? "Working copy" : "No fixes yet";
        sc.dimOver = !afterImg && sc.running;
      } else if (v === "compare") {
        sc.under = place(orig);
        sc.over = place(afterImg);
        sc.label = "Compare";
        if (!afterImg) {
          sc.under = place(orig);
          sc.dimUnder = sc.running;
        }
      } else if (v === "steps") {
        const i = Math.min(m.stepIndex ?? sc.steps.length - 1, sc.steps.length - 1);
        const stp = sc.steps[Math.max(0, i)];
        sc.over = place(stp.img);
        sc.stepIdx = Math.max(0, i);
        sc.label = stp.label;
      }
      // boxes
      if (v !== "steps") {
        const before = (res && res.before) || run.reports.first;
        const after = (res && res.after) || run.reports.latest;
        const report = v === "before" ? before : after;
        const shift = v === "before" ? off : [0, 0];
        for (const f of (report && report.findings) || []) {
          if (f.status !== "warn" && f.status !== "fail") continue;
          for (const b of f.boxes || []) {
            sc.boxes.push({ check: f.check, status: f.status, x: b[0] + shift[0], y: b[1] + shift[1], w: b[2] - b[0], h: b[3] - b[1] });
          }
        }
      }
      sc.cutUrl = run.cutline && v !== "steps" ? run.cutline.url : null;
      sc.textBoxes = v !== "steps" ? run.text_boxes || [] : [];
      sc.borderIn = art && art.border_in;
      sc.dims = `${num(sc.W)} × ${num(sc.H)} px`;
    } else if (draft) {
      sc.W = draft.w || 1;
      sc.H = draft.h || 1;
      sc.key = `draft:${draft.key}`;
      sc.under = { url: draft.url, x: 0, y: 0, w: sc.W, h: sc.H };
      sc.label = "Not checked yet";
      sc.dims = `${num(sc.W)} × ${num(sc.H)} px`;
      const long = Math.max(sc.W, sc.H);
      const printable = sc.size - 0.2;
      sc.ppi = printable > 0 ? long / printable : null;
      sc.ppiApprox = true;
    }
    return sc;
  }

  // ------------------------------------------------------------ toolbar
  let barKey = null;
  function renderBar(m) {
    const run = m.run;
    const hasRun = Boolean(run);
    const isAgent = run && run.mode === "agent";
    const hasAfter = Boolean(run && (run.images.fixed || run.steps.some((x) => x.preview)));
    // Rebuild only when something the toolbar shows changed (not on every streamed event).
    const hasArt = Boolean(run || m.draft);
    const key = JSON.stringify([m.view, m.overlays, m.backdrop, hasRun, isAgent, hasAfter, hasArt]);
    if (key === barKey) return;
    barKey = key;
    clear(bar);
    if (!hasArt) return; // the empty stage is a drop target, nothing to switch or zoom
    const views = VIEWS.filter((v) => v.value !== "trace" || isAgent).map((v) => ({
      ...v,
      label: v.label,
      disabled: (!hasRun && v.value !== "before") || (v.value === "compare" && !hasAfter) || (v.value === "steps" && !hasRun),
      tip: `${v.label} (${v.kbd})`,
    }));
    bar.append(segmented(views, m.view, (v) => actions.setView(v), { label: "View" }));
    if (m.view === "trace") return;
    const tools = h("div", { class: "stage-tools" });
    tools.append(
      h(
        "div",
        { class: "toolgroup tg-overlays", role: "group", "aria-label": "Overlays" },
        OVERLAYS.map((o) =>
          h(
            "button",
            {
              class: "icon-btn",
              type: "button",
              "aria-pressed": String(Boolean(m.overlays[o.key])),
              "aria-label": `${o.label} (${o.kbd})`,
              "data-tip": `${o.label} (${o.kbd})`,
              "data-tip-pos": "below",
              onClick: () => actions.setOverlay(o.key, !m.overlays[o.key]),
            },
            icon(o.icon, 16)
          )
        )
      ),
      h(
        "div",
        { class: "toolgroup tg-backdrop", role: "group", "aria-label": "Background" },
        BACKDROPS.map((b) =>
          h(
            "button",
            {
              class: "swatch",
              type: "button",
              "aria-pressed": String(m.backdrop === b.value),
              "aria-label": `Background: ${b.label}`,
              "data-tip": `${b.label} (D cycles)`,
              "data-tip-pos": "below",
              onClick: () => actions.setBackdrop(b.value),
            },
            h("i", { "data-bg": b.value })
          )
        )
      ),
    );
    // narrow columns (1024 px screens): overlays and backgrounds fold into one menu (CSS @container)
    tools.append(
      h(
        "div",
        { class: "toolgroup tg-more" },
        h(
          "button",
          {
            class: "icon-btn",
            type: "button",
            "aria-label": "Overlays and background",
            "aria-haspopup": "menu",
            "data-tip": "Overlays and background",
            "data-tip-pos": "left",
            onClick: (e) =>
              openMenu(
                e.currentTarget,
                [{ section: "Overlays" }]
                  .concat(OVERLAYS.map((o) => ({ label: o.label, icon: o.icon, kbd: o.kbd, checked: Boolean(m.overlays[o.key]), onSelect: () => actions.setOverlay(o.key, !m.overlays[o.key]) })))
                  .concat([{ section: "Background" }])
                  .concat(BACKDROPS.map((b) => ({ label: b.label, checked: m.backdrop === b.value, onSelect: () => actions.setBackdrop(b.value) }))),
                "Overlays and background"
              ),
          },
          icon("layers", 16)
        )
      )
    );
    bar.append(tools);
    updateZoomLabel();
  }

  // Zoom controls float on the canvas, bottom-right (built once; hidden with no art).
  const zoomLabel = h(
    "button",
    { class: "zoom-readout", type: "button", "aria-label": "Zoom level. Click to cycle 100 %, actual size and fit.", "data-tip": "Scroll to zoom · F fit · 0 100% · I actual size", "data-tip-pos": "left", onClick: cycleZoom },
    "100%"
  );
  const zoomBox = h(
    "div",
    { class: "toolgroup zoom-float", role: "group", "aria-label": "Zoom" },
    h("button", { class: "icon-btn", type: "button", "aria-label": "Zoom out (-)", "data-tip": "Zoom out (−)", onClick: () => zoomBy(1 / 1.25) }, icon("zoomOut", 16)),
    zoomLabel,
    h("button", { class: "icon-btn", type: "button", "aria-label": "Zoom in (+)", "data-tip": "Zoom in (+)", onClick: () => zoomBy(1.25) }, icon("zoomIn", 16)),
    h("button", { class: "icon-btn", type: "button", "aria-label": "Fit to screen (F)", "data-tip": "Fit (F)", "data-tip-pos": "left", onClick: () => fit(true) }, icon("fit", 16))
  );
  hudBR.append(zoomBox);

  // ------------------------------------------------------------ images, overlay, hud
  function setImg(img, layer) {
    if (!layer) {
      img.hidden = true;
      return;
    }
    img.hidden = false;
    if (img.getAttribute("src") !== layer.url) img.setAttribute("src", layer.url);
    img.style.left = layer.x + "px";
    img.style.top = layer.y + "px";
    img.style.width = layer.w + "px";
    img.style.height = layer.h + "px";
  }

  function renderOverlay(m, sc) {
    clear(overlay);
    overlay.setAttribute("width", sc.W);
    overlay.setAttribute("height", sc.H);
    overlay.setAttribute("viewBox", `0 0 ${sc.W} ${sc.H}`);
    const focus = m.focusCheck && m.focusCheck.check;
    if (focus) overlay.setAttribute("data-focus", focus);
    else overlay.removeAttribute("data-focus");
    // cut line and border band
    const wantCut = (m.overlays.cut || m.overlays.border) && sc.cutUrl;
    st.cut = null;
    if (wantCut) {
      const url = sc.cutUrl;
      if (cutReady.has(url)) drawCut(cutReady.get(url), m, sc, true);
      else
        loadCut(url).then((cut) => {
          if (!cut || !st.scene || st.scene.cutUrl !== url) return;
          drawCut(cut, m, sc);
        });
    }
    // boxes
    const g = s("g", { class: "ov-boxes" });
    for (const b of sc.boxes) {
      const show = m.overlays.boxes || b.check === focus;
      if (!show) continue;
      g.append(
        s(
          "g",
          { class: "ov-box" + (b.check === focus ? " focused" : ""), "data-status": b.status, "data-check": b.check },
          s("rect", { class: "fill", x: b.x, y: b.y, width: Math.max(1, b.w), height: Math.max(1, b.h) }),
          s("rect", { x: b.x, y: b.y, width: Math.max(1, b.w), height: Math.max(1, b.h) })
        )
      );
    }
    for (const t of sc.textBoxes || []) {
      if (!(m.overlays.boxes || t.check === focus)) continue;
      const [x0, y0, x1, y1] = t.box;
      g.append(
        s(
          "g",
          { class: "ov-box ov-text" + (t.check === focus ? " focused" : ""), "data-status": t.status, "data-check": t.check },
          s("rect", { class: "fill", x: x0, y: y0, width: Math.max(1, x1 - x0), height: Math.max(1, y1 - y0) }),
          s("rect", { x: x0, y: y0, width: Math.max(1, x1 - x0), height: Math.max(1, y1 - y0) })
        )
      );
    }
    overlay.append(g);
  }

  function drawCut(cut, m, sc, sync) {
    const ppi = sc.ppi || 300;
    let k, ox, oy, unitsPerIn;
    if (cut.vb) {
      k = sc.W / cut.vb[2]; // the viewBox spans the canvas
      ox = -cut.vb[0] * k;
      oy = -cut.vb[1] * k;
      unitsPerIn = cut.vb[2] / (sc.W / ppi);
    } else {
      k = ppi; // no viewBox: assume inches from the canvas origin
      ox = 0;
      oy = 0;
      unitsPerIn = 1;
    }
    const tf = `matrix(${k} 0 0 ${k} ${ox} ${oy})`;
    const old = overlay.querySelector(".ov-cutwrap");
    if (old) old.remove();
    const wrap = s("g", { class: "ov-cutwrap" });
    if (m.overlays.border && sc.borderIn) {
      const id = "cutclip" + Math.random().toString(36).slice(2, 8);
      wrap.append(
        s("defs", null, s("clipPath", { id }, cut.paths.map((d) => s("path", { d, transform: tf })))),
        s("g", { class: "ov-band", "clip-path": `url(#${id})` }, s("g", { transform: tf }, cut.paths.map((d) => s("path", { d, "stroke-width": 2 * sc.borderIn * unitsPerIn }))))
      );
    }
    if (m.overlays.cut) {
      wrap.append(s("g", { class: "ov-cut", transform: tf }, cut.paths.map((d) => s("path", { d, class: "halo" })), cut.paths.map((d) => s("path", { d }))));
    }
    overlay.insertBefore(wrap, overlay.firstChild);
    // world-px bounding box of the cut: the ruler measures the sticker from its edge
    try {
      const probe = s("path", { d: cut.paths.join(" "), transform: tf });
      overlay.append(probe);
      const bb = probe.getBBox();
      probe.remove();
      st.cutBox = { x: bb.x * k + ox, y: bb.y * k + oy, w: bb.width * k, h: bb.height * k };
    } catch (e) {
      st.cutBox = null;
    }
    if (!sync) layout();
  }

  function pill(content, cls) {
    return h("span", { class: "hud-pill" + (cls ? " " + cls : "") }, content);
  }

  function renderHud(m, sc) {
    clear(hudTL);
    clear(hudTR);
    clear(hudBL);
    zoomBox.hidden = !m.run && !m.draft;
    if (!m.run && !m.draft) return;
    if (m.view === "compare") {
      hudTL.append(pill("Before"));
      hudTR.append(pill("After"));
    } else if (sc.running) {
      hudTL.append(pill([h("span", { class: "spinner", style: { width: "11px", height: "11px" } }), h("b", null, "Running"), m.run.steps.length ? `· ${m.run.steps.length} ${m.run.steps.length === 1 ? "fix" : "fixes"} so far` : "· checking"], "accent"));
    } else if (sc.label) {
      hudTL.append(pill(h("b", null, sc.label)));
    }
    const bits = [];
    if (sc.dims) bits.push(sc.dims);
    if (sc.ppi) bits.push(h("span", null, sc.ppiApprox ? "≈ " : "", h("b", null, num(sc.ppi)), ` PPI at ${sizeLabel(sc.size)}`));
    if (bits.length) hudBL.append(pill(bits.flatMap((b, i) => (i ? [h("span", { class: "muted" }, "·"), b] : [b]))));
  }

  function renderSteps(m, sc) {
    clear(stepsEl);
    const show = m.view === "steps" && sc.steps.length;
    stepsEl.hidden = !show;
    if (!show) return;
    const i = sc.stepIdx ?? sc.steps.length - 1;
    const cur = sc.steps[i];
    const range = h("input", {
      class: "scrub",
      type: "range",
      min: "0",
      max: String(sc.steps.length - 1),
      value: String(i),
      "aria-label": "Scrub through the fixes",
      onInput: (e) => actions.setStep(Number(e.target.value)),
    });
    stepsEl.append(
      h(
        "div",
        { class: "steps-caption" },
        h("span", { class: "chip", "data-status": cur.state === "ok" ? "pass" : cur.state === "damaged" ? "fail" : "skip" }, i === 0 ? "start" : cur.sub),
        h("b", null, i === 0 ? "Original" : `Step ${i} of ${sc.steps.length - 1} · ${cur.label}`),
        h("span", { class: "note ellipsis", title: cur.note || "" }, cur.note || "")
      ),
      h(
        "div",
        { class: "steps-thumbs", role: "group", "aria-label": "Steps" },
        sc.steps.map((x, j) =>
          h(
            "button",
            { class: "step-thumb", type: "button", "aria-pressed": String(j === i), "data-state": x.state, onClick: () => actions.setStep(j), "aria-label": `${x.label}, ${x.sub}` },
            h("span", { class: "thumb checker checker-sm" }, x.img ? h("img", { src: x.img.url, alt: "", loading: "lazy" }) : icon("image", 18)),
            h("span", null, j === 0 ? "Original" : `${j}. ${x.label}`)
          )
        )
      ),
      sc.steps.length > 2 ? range : null
    );
  }

  function renderEmpty(m) {
    const show = !m.run && !m.draft && !m.loading;
    emptyEl.hidden = !show;
    if (!show) return;
    clear(emptyEl);
    const samples = actions.samples();
    emptyEl.append(
      h(
        "div",
        { class: "stage-empty-card" },
        h("div", { class: "hero-mark" }, actions.heroMark()),
        h("h2", null, m.readonly ? "Pick a saved run" : "Drop sticker art to check it"),
        h(
          "p",
          null,
          m.readonly
            ? "This is a read-only copy. Open a saved run from the list or from Results."
            : "PNG, JPG or WebP up to 20 MB. printready checks it against die-cut rules at the size you order, fixes what it can and draws the cut line."
        ),
        m.readonly
          ? null
          : h(
              "div",
              { class: "row", style: { gap: "8px", marginTop: "4px" } },
              h("button", { class: "btn btn-primary", type: "button", onClick: () => actions.pickFile() }, icon("upload", 15), "Choose a file"),
              h("span", { class: "hint" }, "or paste with Ctrl+V")
            ),
        samples.length
          ? h(
              "div",
              { style: { marginTop: "12px" } },
              h("div", { class: "hint", style: { marginBottom: "6px" } }, m.readonly ? "Saved runs" : "Or try a sample"),
              h(
                "div",
                { class: "samples-row" },
                samples.map((x) => h("button", { type: "button", "data-tip": x.title, "aria-label": `Sample: ${x.title}`, onClick: () => actions.onSample(x.id) }, h("img", { src: x.thumb, alt: "" })))
              )
            )
          : null
      )
    );
  }

  // ------------------------------------------------------------ transform
  function viewportSize() {
    return { w: viewport.clientWidth, h: viewport.clientHeight };
  }

  function insets() {
    return st.model && st.model.overlays.ruler ? RULER : 0;
  }

  function fit(explicit) {
    const { w, h: hh } = viewportSize();
    if (!w || !hh) return;
    const r = insets();
    const sc = Math.max(MIN_SCALE, Math.min(MAX_FIT, (w - r - 2 * PAD) / st.W, (hh - r - 2 * PAD) / st.H));
    st.t = { s: sc, tx: r + (w - r - st.W * sc) / 2, ty: r + (hh - r - st.H * sc) / 2 };
    if (explicit) st.userZoomed = false;
    layout();
  }

  function zoomAt(factor, px, py) {
    const { s: sc, tx, ty } = st.t;
    const ns = Math.max(MIN_SCALE, Math.min(MAX_SCALE, sc * factor));
    const wx = (px - tx) / sc;
    const wy = (py - ty) / sc;
    st.t = { s: ns, tx: px - wx * ns, ty: py - wy * ns };
    st.userZoomed = true;
    markInteracted();
    layout();
  }

  function zoomBy(factor) {
    const { w, h: hh } = viewportSize();
    zoomAt(factor, w / 2, hh / 2);
  }

  function zoomTo(scale) {
    zoomBy(scale / st.t.s);
  }

  function actualSize() {
    const ppi = st.scene && st.scene.ppi;
    if (ppi) zoomTo(96 / ppi); // CSS inches: 96 px per inch
  }

  function cycleZoom() {
    const ppi = st.scene && st.scene.ppi;
    const actual = ppi ? 96 / ppi : null;
    if (!st.userZoomed) zoomTo(1);
    else if (Math.abs(st.t.s - 1) < 0.001 && actual) zoomTo(actual);
    else fit(true);
  }

  function markInteracted() {
    st.interacted = true;
  }

  function updateZoomLabel() {
    const ppi = st.scene && st.scene.ppi;
    const actual = ppi && Math.abs(st.t.s - 96 / ppi) < 0.002;
    zoomLabel.textContent = actual ? "Actual" : `${Math.round(st.t.s * 100)}%`;
  }

  function layout() {
    const { s: sc, tx, ty } = st.t;
    world.style.transform = `translate(${tx}px, ${ty}px) scale(${sc})`;
    world.style.width = st.W + "px";
    world.style.height = st.H + "px";
    world.classList.toggle("pixelated", sc >= 2.5);
    overlay.style.setProperty("--px", String(1 / sc)); // constant on-screen stroke widths
    artboard.style.left = tx + "px";
    artboard.style.top = ty + "px";
    artboard.style.width = st.W * sc + "px";
    artboard.style.height = st.H * sc + "px";
    // box labels in screen space
    clear(labels);
    const m = st.model;
    const sc0 = st.scene;
    if (m && sc0 && m.view !== "steps") {
      const focus = m.focusCheck && m.focusCheck.check;
      if (focus) labels.setAttribute("data-focus", focus);
      else labels.removeAttribute("data-focus");
      const seen = new Set();
      for (const b of sc0.boxes) {
        if (!(m.overlays.boxes || b.check === focus) || seen.has(b.check + b.x + b.y)) continue;
        seen.add(b.check + b.x + b.y);
        labels.append(
          h(
            "div",
            { class: "box-label" + (b.check === focus ? " focused" : ""), "data-status": b.status, style: { left: tx + b.x * sc + "px", top: ty + b.y * sc + "px" } },
            checkName(b.check)
          )
        );
      }
      for (const t of sc0.textBoxes || []) {
        if (!(m.overlays.boxes || t.check === focus)) continue;
        labels.append(
          h(
            "div",
            { class: "box-label" + (t.check === focus ? " focused" : ""), "data-status": t.status, "data-kind": "text", style: { left: tx + t.box[0] * sc + "px", top: ty + t.box[1] * sc + "px" } },
            t.label
          )
        );
      }
    }
    // compare divider
    if (m && m.view === "compare" && sc0 && sc0.over) {
      const { w } = viewportSize();
      const x = st.compare * w;
      compareEl.hidden = false;
      compareEl.style.left = x + "px";
      grip.setAttribute("aria-valuenow", String(Math.round(st.compare * 100)));
      const worldX = (x - tx) / sc;
      const local = Math.max(0, Math.min(sc0.over.w, worldX - sc0.over.x));
      imgOver.style.clipPath = `inset(0 0 0 ${local}px)`;
      if (sc0.under) {
        // the before layer only left of the divider, so it never shows through transparent "after" pixels
        const left = Math.max(0, Math.min(sc0.under.w, worldX - sc0.under.x));
        imgUnder.style.clipPath = `inset(0 ${sc0.under.w - left}px 0 0)`;
      }
    } else {
      compareEl.hidden = true;
      imgOver.style.clipPath = "";
      imgUnder.style.clipPath = "";
    }
    drawRulers();
    updateZoomLabel();
  }

  // ------------------------------------------------------------ rulers (inches at the ordered size)
  function drawRulers() {
    const m = st.model;
    const sc0 = st.scene;
    const on = m && m.overlays.ruler && sc0 && sc0.ppi && (m.run || m.draft) && m.view !== "trace";
    rulerX.hidden = rulerY.hidden = corner.hidden = !on;
    viewport.dataset.ruler = on ? "on" : "off";
    if (!on) return;
    const colors = st.colors || (st.colors = { bg: cssVar("--surface"), line: cssVar("--line"), ink: cssVar("--ink-3"), ink2: cssVar("--ink-2"), accent: cssVar("--accent-ink"), band: cssVar("--accent-soft") });
    const dpr = window.devicePixelRatio || 1;
    const { w, h: hh } = viewportSize();
    const { s: scale, tx, ty } = st.t;
    const pxPerIn = sc0.ppi * scale;
    const box = st.cutBox || { x: 0, y: 0, w: st.W, h: st.H };
    const n = pxPerIn >= 160 ? 16 : pxPerIn >= 80 ? 8 : pxPerIn >= 40 ? 4 : pxPerIn >= 20 ? 2 : 1;
    const labelEvery = pxPerIn >= 30 ? 1 : pxPerIn >= 14 ? 2 : 5;
    const draw = (canvas, length, origin, extentPx, horizontal) => {
      canvas.width = Math.round((horizontal ? length : RULER) * dpr);
      canvas.height = Math.round((horizontal ? RULER : length) * dpr);
      canvas.style.width = (horizontal ? length : RULER) + "px";
      canvas.style.height = (horizontal ? RULER : length) + "px";
      const c = canvas.getContext("2d");
      c.scale(dpr, dpr);
      c.fillStyle = colors.bg;
      c.fillRect(0, 0, horizontal ? length : RULER, horizontal ? RULER : length);
      // the sticker's extent, measured from its cut edge
      c.fillStyle = colors.band;
      if (horizontal) c.fillRect(origin, 0, extentPx, RULER);
      else c.fillRect(0, origin, RULER, extentPx);
      c.strokeStyle = colors.line;
      c.beginPath();
      if (horizontal) {
        c.moveTo(0, RULER - 0.5);
        c.lineTo(length, RULER - 0.5);
      } else {
        c.moveTo(RULER - 0.5, 0);
        c.lineTo(RULER - 0.5, length);
      }
      c.stroke();
      c.font = "600 9.5px " + getComputedStyle(document.body).fontFamily;
      const start = Math.ceil(((RULER - origin) / pxPerIn) * n);
      const end = Math.floor(((length - origin) / pxPerIn) * n);
      for (let k = start; k <= end; k++) {
        const pos = Math.round(origin + (k / n) * pxPerIn) + 0.5;
        const whole = k % n === 0;
        const half = !whole && (k * 2) % n === 0;
        const quarter = !whole && !half && (k * 4) % n === 0;
        const len = whole ? 10 : half ? 7 : quarter ? 5 : 3;
        c.strokeStyle = whole ? colors.ink2 : colors.ink;
        c.globalAlpha = whole ? 1 : 0.7;
        c.beginPath();
        if (horizontal) {
          c.moveTo(pos, RULER);
          c.lineTo(pos, RULER - len);
        } else {
          c.moveTo(RULER, pos);
          c.lineTo(RULER - len, pos);
        }
        c.stroke();
        c.globalAlpha = 1;
        if (whole && (k / n) % labelEvery === 0) {
          c.fillStyle = colors.ink2;
          if (horizontal) c.fillText(String(k / n), pos + 3, 10);
          else {
            c.save();
            c.translate(10, pos + 3);
            c.rotate(-Math.PI / 2);
            c.textAlign = "right";
            c.fillText(String(k / n), 0, 0);
            c.restore();
          }
        }
      }
      const inchesLong = extentPx / pxPerIn;
      const label = `${inchesLong.toFixed(2)} in`;
      c.fillStyle = colors.accent;
      c.font = "700 10px " + getComputedStyle(document.body).fontFamily;
      if (horizontal) {
        const tw = c.measureText(label).width;
        const x = Math.min(length - tw - 4, origin + extentPx - tw - 4);
        if (x > RULER + 24) c.fillText(label, x, RULER - 12);
      } else {
        c.save();
        const y = Math.min(length - 4, origin + extentPx - 4);
        c.translate(RULER - 12, y);
        c.rotate(-Math.PI / 2);
        if (y > RULER + 40) c.fillText(label, 0, 0);
        c.restore();
      }
    };
    draw(rulerX, w, tx + box.x * scale, box.w * scale, true);
    draw(rulerY, hh, ty + box.y * scale, box.h * scale, false);
  }

  // ------------------------------------------------------------ interaction
  let pan = null;
  viewport.addEventListener("wheel", (e) => {
    if (!st.model || (!st.model.run && !st.model.draft)) return;
    e.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const dy = e.deltaY * (e.deltaMode === 1 ? 33 : e.deltaMode === 2 ? 400 : 1);
    zoomAt(Math.exp(-dy * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX - rect.left, e.clientY - rect.top);
  }, { passive: false });

  viewport.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest(".compare-grip, .stage-empty, .zoom-float")) return;
    pan = { x: e.clientX, y: e.clientY, tx: st.t.tx, ty: st.t.ty, moved: false };
    viewport.setPointerCapture(e.pointerId);
  });
  viewport.addEventListener("pointermove", (e) => {
    if (!pan) return;
    const dx = e.clientX - pan.x;
    const dy = e.clientY - pan.y;
    if (!pan.moved && Math.hypot(dx, dy) < 3) return;
    if (!pan.moved) {
      pan.moved = true;
      viewport.classList.add("panning");
      markInteracted();
    }
    st.t = { ...st.t, tx: pan.tx + dx, ty: pan.ty + dy };
    st.userZoomed = true;
    layout();
  });
  const endPan = () => {
    pan = null;
    viewport.classList.remove("panning");
  };
  viewport.addEventListener("pointerup", endPan);
  viewport.addEventListener("pointercancel", endPan);
  viewport.addEventListener("dblclick", (e) => {
    if (e.target.closest(".stage-empty, .compare-grip, .zoom-float")) return;
    const rect = viewport.getBoundingClientRect();
    if (st.userZoomed && Math.abs(st.t.s - 1) < 0.001) fit(true);
    else zoomAt(1 / st.t.s, e.clientX - rect.left, e.clientY - rect.top);
  });
  viewport.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 160 : 40;
    const moves = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
    if (moves[e.key] && e.target === viewport) {
      e.preventDefault();
      st.t = { ...st.t, tx: st.t.tx + moves[e.key][0], ty: st.t.ty + moves[e.key][1] };
      st.userZoomed = true;
      markInteracted();
      layout();
    }
  });

  // compare divider: drag or arrow keys
  let dragging = false;
  grip.addEventListener("pointerdown", (e) => {
    dragging = true;
    grip.setPointerCapture(e.pointerId);
    e.stopPropagation();
  });
  grip.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const rect = viewport.getBoundingClientRect();
    st.compare = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    markInteracted();
    layout();
  });
  grip.addEventListener("pointerup", () => (dragging = false));
  grip.addEventListener("keydown", (e) => {
    const d = e.shiftKey ? 0.1 : 0.02;
    const map = { ArrowLeft: -d, ArrowRight: d, Home: -1, End: 1 };
    if (e.key in map) {
      e.preventDefault();
      e.stopPropagation();
      st.compare = Math.max(0, Math.min(1, st.compare + map[e.key]));
      layout();
    }
  });

  // drag and drop anywhere on the stage
  let dragDepth = 0;
  const setOver = (v) => {
    emptyEl.dataset.over = String(v);
  };
  root.addEventListener("dragenter", (e) => {
    if (!actions.canDrop() || !e.dataTransfer || !Array.from(e.dataTransfer.types).includes("Files")) return;
    e.preventDefault();
    dragDepth += 1;
    setOver(true);
  });
  root.addEventListener("dragover", (e) => {
    if (!actions.canDrop()) return;
    e.preventDefault();
  });
  root.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) setOver(false);
  });
  root.addEventListener("drop", (e) => {
    if (!actions.canDrop()) return;
    e.preventDefault();
    dragDepth = 0;
    setOver(false);
    if (e.dataTransfer && e.dataTransfer.files.length) actions.onFiles(e.dataTransfer.files);
  });

  new ResizeObserver(() => {
    if (!st.userZoomed) fit();
    else layout();
  }).observe(viewport);

  // ------------------------------------------------------------ public
  function render(m) {
    st.model = m;
    st.colors = null; // theme may have changed
    renderBar(m);
    const isTrace = m.view === "trace" && m.run && m.run.mode === "agent";
    viewport.hidden = isTrace;
    traceEl.hidden = !isTrace;
    if (isTrace) {
      stepsEl.hidden = true;
      actions.renderTrace(traceEl);
      return;
    }
    const sc = computeScene(m);
    const prevCut = st.scene && st.scene.cutUrl;
    st.scene = sc;
    if (prevCut !== sc.cutUrl) st.cutBox = null;
    st.W = sc.W;
    st.H = sc.H;
    artboard.dataset.bg = m.backdrop;
    artboard.classList.toggle("checker", m.backdrop === "checker");
    artboard.hidden = !(m.run || m.draft);
    setImg(imgUnder, sc.under);
    setImg(imgOver, sc.over);
    imgOver.classList.toggle("dimmed", Boolean(sc.dimOver));
    imgUnder.classList.toggle("dimmed", Boolean(sc.dimUnder));
    waitPill.hidden = !(sc.dimOver || sc.dimUnder);
    progress.hidden = !sc.running;
    renderOverlay(m, sc);
    renderHud(m, sc);
    renderSteps(m, sc);
    renderEmpty(m);
    if (sc.key !== st.fitKey) {
      st.fitKey = sc.key;
      st.userZoomed = false;
      requestAnimationFrame(() => fit());
    } else {
      layout();
    }
  }

  // Hovering a finding only re-draws the overlay and labels, never the toolbar.
  function updateFocus(m) {
    st.model = m;
    if (!st.scene || m.view === "trace") return;
    renderOverlay(m, st.scene);
    layout();
  }

  return {
    render,
    updateFocus,
    fit: () => fit(true),
    zoomIn: () => zoomBy(1.25),
    zoomOut: () => zoomBy(1 / 1.25),
    zoom100: () => zoomTo(1),
    actualSize,
    focusViewport: () => viewport.focus(),
    traceEl,
  };
}
