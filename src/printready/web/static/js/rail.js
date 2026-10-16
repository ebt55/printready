// The left rail: artwork (drop, click, paste), samples, the order (size, product), the mode
// (rules or agent, model, estimated cost), recent runs, and the Run button.

import { h, clear } from "./dom.js";
import { icon } from "./icons.js";
import { OUTCOMES, bytes, num, sizeLabel, timeAgo, usd } from "./format.js";
import { kbd, segmented } from "./ui.js";

const MAX_BYTES = 20_000_000;
const TYPES = ["image/png", "image/jpeg", "image/webp"];

export function validateFile(file) {
  const okType = TYPES.includes(file.type) || /\.(png|jpe?g|webp)$/i.test(file.name || "");
  if (!okType) return "Only PNG, JPG and WebP images are supported.";
  if (file.size > MAX_BYTES) return `This file is ${(file.size / 1e6).toFixed(1)} MB; the upload limit is 20 MB.`;
  if (file.size === 0) return "This file is empty.";
  return null;
}

function sectionHead(title, extra) {
  return h("div", { class: "section-head" }, h("h2", { class: "section-title" }, title), extra || null);
}

function artworkSection(m, a) {
  const d = m.draft;
  let body;
  if (d) {
    body = h(
      "div",
      { class: "file-card" },
      h("span", { class: "thumb checker checker-sm" }, h("img", { src: d.thumb || d.url, alt: "" })),
      h(
        "div",
        { class: "grow" },
        h("div", { class: "file-name ellipsis", title: d.name }, d.name),
        h("div", { class: "file-meta ellipsis" }, [d.w && d.h ? `${d.w}×${d.h} px` : null, d.bytes ? bytes(d.bytes) : null, d.kind === "sample" ? "sample" : d.kind === "run" ? "from a run" : null].filter(Boolean).join(" · "))
      ),
      h("button", { class: "icon-btn icon-btn-sm", type: "button", "aria-label": "Choose another file", "data-tip": "Replace (O)", onClick: a.pickFile }, icon("upload", 15)),
      h("button", { class: "icon-btn icon-btn-sm", type: "button", "aria-label": "Clear the artwork", "data-tip": "Clear", "data-tip-pos": "left", onClick: a.clearDraft }, icon("x", 15))
    );
  } else {
    body = h(
      "div",
      {
        class: "drop",
        role: "button",
        tabindex: "0",
        "aria-label": "Choose an image, or drop one here",
        onClick: a.pickFile,
        onKeydown: (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), a.pickFile()),
        onDragover: (e) => {
          e.preventDefault();
          e.currentTarget.dataset.over = "true";
        },
        onDragleave: (e) => (e.currentTarget.dataset.over = "false"),
        onDrop: (e) => {
          e.preventDefault();
          e.stopPropagation();
          e.currentTarget.dataset.over = "false";
          if (e.dataTransfer.files.length) a.onFiles(e.dataTransfer.files);
        },
      },
      h("span", { class: "drop-icon" }, icon("upload", 18)),
      h("span", { class: "drop-title" }, "Drop art or click to choose"),
      h("span", { class: "drop-sub" }, "PNG, JPG, WebP · up to 20 MB · or paste")
    );
  }
  return h("section", { class: "section" }, sectionHead("Artwork"), body, m.fileError ? h("div", { class: "drop-error", role: "alert" }, m.fileError) : null);
}

// One group of sample tiles with a caption line that describes the hovered (or chosen) tile.
function sampleGroup(m, a, list, title, hint, idle) {
  const selected = list.find((x) => m.draft && m.draft.sampleId === x.id);
  const caption = h("p", { class: "samples-caption" });
  const describe = (x) => {
    clear(caption);
    if (!x) return caption.append(idle);
    caption.append(h("b", null, x.title), " · ", x.blurb);
    if (x.prompt) caption.append(h("span", { class: "samples-prompt" }, `Prompt: "${x.prompt}"`));
  };
  describe(selected);
  return h(
    "section",
    { class: "section" },
    sectionHead(title, h("span", { class: "hint" }, hint)),
    h(
      "div",
      { class: "samples", onMouseleave: () => describe(selected) },
      list.map((x) =>
        h(
          "button",
          {
            class: "sample" + (x.group === "real" ? " real" : ""),
            type: "button",
            "aria-pressed": String(selected === x),
            "aria-label": `${x.title}: ${x.blurb}${x.note ? " (" + x.note + ")" : ""}`,
            onClick: () => a.onSample(x.id),
            onMouseenter: () => describe(x),
            onFocus: () => describe(x),
          },
          h("span", { class: "thumb checker checker-sm" }, h("img", { src: x.thumb, alt: "", loading: "lazy" }))
        )
      )
    ),
    caption
  );
}

function samplesSection(m, a) {
  const samples = (m.app && m.app.samples) || [];
  if (!samples.length) return null;
  const drawn = samples.filter((x) => x.group !== "real");
  const real = samples.filter((x) => x.group === "real");
  return [
    real.length
      ? sampleGroup(m, a, real, "Real Grok output", "dev set", "Real grok-imagine images from the dev set, with their saved rules and agent runs (real grok-4.3 turns).")
      : null,
    drawn.length ? sampleGroup(m, a, drawn, "Samples", "drawn in code, not AI", "Each one trips a different rule. Hover to see which.") : null,
  ];
}

function orderSection(m, a) {
  const sizes = (m.app && m.app.sizes) || [2, 3, 4, 5];
  const limits = (m.app && m.app.size_limits) || { min: 0.5, max: 20 };
  const custom = !sizes.includes(m.order.size) || m.customSize;
  const options = sizes.map((x) => ({ value: x, label: `${x}"` })).concat([{ value: "custom", label: "Custom" }]);
  return h(
    "section",
    { class: "section" },
    sectionHead("Order"),
    h(
      "div",
      { class: "field" },
      h("span", { class: "label" }, "Product"),
      h("div", { class: "product" }, icon("cut", 15), "Die-cut sticker", h("span", { class: "muted" }, "v1 only"))
    ),
    h(
      "div",
      { class: "field" },
      h("span", { class: "label", id: "size-label" }, "Size"),
      segmented(options, custom ? "custom" : m.order.size, (v) => (v === "custom" ? a.setCustomSize(true) : a.setSize(v)), { block: true, label: "Size in inches" }),
      custom
        ? h(
            "div",
            { class: "input-wrap", style: { marginTop: "8px" } },
            h("input", {
              class: "input num",
              type: "number",
              min: String(limits.min),
              max: String(limits.max),
              step: "0.25",
              value: String(m.order.size),
              "aria-labelledby": "size-label",
              onChange: (e) => {
                const v = Number(e.target.value);
                if (v >= limits.min && v <= limits.max) a.setSize(v, true);
                else e.target.value = String(m.order.size);
              },
            }),
            h("span", { class: "suffix" }, "in")
          )
        : null,
      h("p", { class: "hint", style: { marginTop: "6px" } }, "Longest side of the finished sticker, border included.")
    )
  );
}

function modeSection(m, a) {
  const app = m.app || {};
  const models = app.models || [];
  const mode = m.order.mode;
  const model = models.find((x) => x.id === m.order.model) || models[0];
  const paid = mode === "agent" || m.order.vision;
  const est = !paid || !model ? 0 : mode === "agent" ? model.est_agent_usd : model.est_vision_usd;
  const runner = app.runner || {};
  const ready = app.demo || (runner[mode] && runner[mode].ready);
  return h(
    "section",
    { class: "section" },
    sectionHead("Mode", h("span", { class: "hint" }, h("kbd", { class: "kbd" }, "M"), " toggles")),
    segmented(
      [
        { value: "rules", label: "Rules", icon: "rules" },
        { value: "agent", label: "Agent", icon: "bot" },
      ],
      mode,
      (v) => a.setMode(v),
      { block: true, label: "Mode" }
    ),
    h(
      "p",
      { class: "hint mode-desc" },
      mode === "rules" ? "Deterministic checks and fixes in a fixed order. Same input, same output." : "A model chooses the tools, turn by turn; the outcome is still computed by the rules."
    ),
    mode === "rules"
      ? h(
          "label",
          { class: "switch", style: { marginTop: "12px" } },
          h("input", { type: "checkbox", checked: Boolean(m.order.vision), onChange: (e) => a.setVision(e.target.checked) }),
          h("span", { class: "switch-track", "aria-hidden": "true" }),
          h("span", { class: "switch-text" }, "Read text with a model", h("br"), h("span", { class: "hint" }, "Spelling and text size: one vision call"))
        )
      : null,
    paid && models.length
      ? h(
          "div",
          { class: "field", style: { marginTop: "12px" } },
          h("label", { class: "label", for: "model-select" }, "Model"),
          h(
            "select",
            { class: "input", id: "model-select", onChange: (e) => a.setModel(e.target.value) },
            models.map((x) => h("option", { value: x.id, selected: x.id === m.order.model }, `${x.label} · $${x.price_in}/$${x.price_out} per 1M`))
          )
        )
      : null,
    h(
      "div",
      { class: "estimate" },
      h("span", null, paid ? "Estimated cost" : "Cost"),
      app.demo
        ? h("span", null, h("b", null, "$0.00"), " demo")
        : paid
          ? h("span", null, "≤ ", h("b", null, usd(est)), " per image")
          : h("span", null, h("b", null, "free"), " · no model calls")
    ),
    !ready ? h("p", { class: "hint", style: { marginTop: "8px", color: "var(--warn-ink)" } }, (runner[mode] && runner[mode].reason) || "This mode is not wired yet.") : null
  );
}

function recentSection(m, a) {
  const runs = m.runs || [];
  const current = m.run && m.run.id;
  return h(
    "section",
    { class: "section" },
    sectionHead(m.app && m.app.static ? "Saved runs" : "Recent runs", runs.length ? h("span", { class: "hint num" }, String(runs.length)) : null),
    runs.length
      ? h(
          "div",
          { class: "runs-list" },
          runs.slice(0, 40).map((r) =>
            h(
              "button",
              { class: "run-item", type: "button", "aria-current": String(r.id === current), onClick: () => a.openRun(r.id) },
              h("span", { class: "thumb checker checker-sm" }, r.thumb ? h("img", { src: r.thumb, alt: "", loading: "lazy" }) : icon("image", 16)),
              h(
                "span",
                { class: "grow" },
                h("div", { class: "run-name ellipsis", title: r.filename }, r.title || r.filename || r.id),
                h("div", { class: "run-meta ellipsis" }, [r.size_in ? sizeLabel(r.size_in) : null, r.mode === "agent" ? "Agent" : "Rules", r.created ? timeAgo(r.created) : r.note].filter(Boolean).join(" · "))
              ),
              h("span", {
                class: "outcome-dot",
                "data-outcome": r.status === "error" ? "error" : r.status === "running" || r.status === "queued" ? "running" : r.outcome || "",
                "aria-label": r.outcome ? OUTCOMES[r.outcome].label : r.status,
                title: r.outcome ? OUTCOMES[r.outcome].label : r.status,
              })
            )
          )
        )
      : h("p", { class: "hint" }, "Runs you start appear here. They are saved under out/workbench/.")
  );
}

function footer(m, a) {
  const app = m.app || {};
  if (app.static) return null;
  const mode = m.order.mode;
  const models = app.models || [];
  const model = models.find((x) => x.id === m.order.model) || models[0];
  const paid = mode === "agent" || m.order.vision;
  const est = paid && model ? (mode === "agent" ? model.est_agent_usd : model.est_vision_usd) : 0;
  const runner = app.runner || {};
  const ready = app.demo || (runner[mode] && runner[mode].ready);
  const has = Boolean(m.draft);
  const label = mode === "agent" ? "Run agent" : "Run check";
  return h(
    "div",
    { class: "rail-foot" },
    h(
      "button",
      {
        class: "btn btn-primary btn-lg btn-block",
        type: "button",
        disabled: !has || m.busy || !ready,
        onClick: a.run,
        "aria-keyshortcuts": "Control+Enter",
      },
      m.busy ? h("span", { class: "spinner" }) : icon(mode === "agent" ? "bot" : "play", 15),
      h("span", null, label, paid && !app.demo && est ? h("span", { style: { opacity: 0.8, fontWeight: 500 } }, ` · ≤ ${usd(est)}`) : null),
      kbd("Ctrl ↵")
    ),
    h("p", { class: "hint" }, !has ? "Choose artwork or a sample first." : app.demo ? "Demo mode: nothing is charged." : paid ? "You confirm the cost before anything is spent." : `${sizeLabel(m.order.size)} die-cut · ${mode}`)
  );
}

export function renderRail(host, m, a) {
  const scroller = host.querySelector(".rail-scroll");
  const top = scroller ? scroller.scrollTop : 0;
  clear(host);
  const scroll = h("div", { class: "rail-scroll" });
  if (m.app && m.app.static) {
    scroll.append(
      h(
        "section",
        { class: "section" },
        h("div", { class: "notice notice-accent" }, icon("lock", 14), h("span", null, h("b", null, "Read-only demo. "), "Run it locally for your own art: ", h("code", null, "printready serve")))
      ),
      recentSection(m, a)
    );
  } else {
    scroll.append(artworkSection(m, a));
    for (const sec of samplesSection(m, a) || []) if (sec) scroll.append(sec);
    scroll.append(orderSection(m, a), modeSection(m, a), recentSection(m, a));
  }
  host.append(scroll);
  const foot = footer(m, a);
  if (foot) host.append(foot);
  scroll.scrollTop = top;
}
