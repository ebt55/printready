// Shared UI components: chips, badges, source tags, the threshold bar, dialogs, toasts, popovers.

import { h, clear, qs } from "./dom.js";
import { icon } from "./icons.js";
import { FIXER_ICON, FIXER_LABEL, OUTCOMES, STATUS_LABEL } from "./format.js";

export function chip(status, text, large) {
  return h("span", { class: "chip" + (large ? " chip-lg" : ""), "data-status": status }, text || STATUS_LABEL[status] || status);
}

export function outcomeChip(outcome, small, prefix) {
  const meta = OUTCOMES[outcome];
  if (!meta) return h("span", { class: "outcome" + (small ? " outcome-sm" : "") }, prefix ? prefix + " " : "", "–");
  return h(
    "span",
    { class: "outcome" + (small ? " outcome-sm" : ""), "data-outcome": outcome },
    icon(meta.icon, small ? 12 : 13),
    prefix ? h("span", { class: "muted" }, prefix) : null,
    meta.label
  );
}

export function fixerBadge(fixer) {
  if (!FIXER_LABEL[fixer]) return null;
  const tips = {
    auto: "printready can fix this automatically",
    customer: "The customer decides (for example, a smaller size)",
    person: "A person on the team has to look at it",
  };
  return h("span", { class: "fixer", "data-fixer": fixer, "data-tip": tips[fixer], "aria-label": `Fixer: ${FIXER_LABEL[fixer]}` }, icon(FIXER_ICON[fixer], 12), FIXER_LABEL[fixer]);
}

// Where a rule comes from: "SM" links to the Sticker Mule FAQ page it paraphrases; "conv" is ours.
export function srcTag(source) {
  if (!source) return null;
  if (source === "convention") {
    return h("span", { class: "src", "data-kind": "convention", "data-tip": "Our convention: the FAQ gives no number", tabindex: "0" }, "conv");
  }
  if (source === "derived") {
    return h("span", { class: "src", "data-kind": "convention", "data-tip": "Derived from the rules above" }, "derived");
  }
  return h("a", { class: "src", href: source, target: "_blank", rel: "noopener noreferrer", "data-tip": "Sticker Mule FAQ (paraphrased)", "aria-label": "Source: Sticker Mule FAQ" }, "SM");
}

export function kbd(text) {
  return h("kbd", { class: "kbd" }, text);
}

export function spinner() {
  return h("span", { class: "spinner", "aria-hidden": "true" });
}

export function dots() {
  return h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i"));
}

export function empty(iconName, title, text, actions) {
  return h(
    "div",
    { class: "empty" },
    h("div", { class: "empty-icon" }, icon(iconName, 20)),
    h("h3", null, title),
    text ? h("p", null, text) : null,
    actions && actions.length ? h("div", { class: "actions" }, actions) : null
  );
}

/* ---------------------------------------------------------------- threshold bar */
// m = { label, value, display, unit, status, domain: [lo, hi], marks: [{ value, display, label, source }],
//       zones: [{ from, to, level }], note }
export function thresholdBar(m) {
  const [lo, hi] = m.domain;
  const span = hi - lo || 1;
  const pos = (v) => Math.max(0, Math.min(100, ((v - lo) / span) * 100));
  const clamped = m.value > hi ? "hi" : m.value < lo ? "lo" : null;
  const marks = m.marks || [];
  const aria = [`${m.label}: ${m.display}${m.unit ? " " + m.unit : ""}.`]
    .concat(marks.map((mk) => `${mk.label} ${mk.display}${mk.source === "convention" ? " (our convention)" : mk.source ? " (Sticker Mule rule)" : ""}.`))
    .join(" ");
  return h(
    "div",
    { class: "tb", "data-status": m.status || "skip" },
    h("div", { class: "tb-head" }, h("span", { class: "tb-label" }, m.label), h("span", { class: "tb-value" }, m.display, m.unit ? h("small", null, m.unit) : null)),
    h(
      "div",
      { class: "tb-track", role: "img", "aria-label": aria },
      (m.zones || []).map((z) => h("i", { class: "tb-zone", "data-level": z.level || 1, style: { left: pos(z.from) + "%", width: Math.max(0, pos(z.to) - pos(z.from)) + "%" } })),
      marks.map((mk) => h("i", { class: "tb-mark", style: { left: pos(mk.value) + "%" } })),
      m.value === null || m.value === undefined ? null : h("i", { class: "tb-dot", "data-clamped": clamped, style: { left: pos(m.value) + "%" } })
    ),
    marks.length || m.note
      ? h(
          "div",
          { class: "tb-legend" },
          marks.map((mk) => h("span", null, h("i", { class: "tick" }), `${mk.label} ${mk.display}`, srcTag(mk.source))),
          m.note ? h("span", null, m.note) : null
        )
      : null
  );
}

export function fact(value, label) {
  return h("span", { class: "meas" }, h("b", null, value), label ? h("span", null, label) : null);
}

/* ---------------------------------------------------------------- JSON viewer */

const TOKEN = /("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false|null)\b/g;

export function codeJSON(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const pre = h("pre", { class: "code" });
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    if (m.index > last) pre.append(document.createTextNode(text.slice(last, m.index)));
    if (m[1]) {
      pre.append(h("span", { class: m[2] ? "k" : "s" }, m[1]));
      if (m[2]) pre.append(document.createTextNode(m[2]));
    } else if (m[3]) {
      pre.append(h("span", { class: "n" }, m[3]));
    } else {
      pre.append(h("span", { class: "n" }, m[4]));
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) pre.append(document.createTextNode(text.slice(last)));
  return pre;
}

/* ---------------------------------------------------------------- toasts */

let toastHost = null;

export function toast(message, kind = "info", timeout = 4200) {
  if (!toastHost) {
    toastHost = h("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(toastHost);
  }
  const iconName = kind === "error" ? "alert" : kind === "ok" ? "check" : "info";
  const el = h("div", { class: "toast", "data-kind": kind }, icon(iconName, 16), h("span", null, message));
  toastHost.append(el);
  setTimeout(() => el.remove(), timeout);
}

/* ---------------------------------------------------------------- dialogs */

let openDialogs = 0;

export function dialogOpen() {
  return openDialogs > 0;
}

export function openDialog({ title, body, actions, wide, label, onClose }) {
  const previous = document.activeElement;
  let closed = false;
  const close = (value) => {
    if (closed) return;
    closed = true;
    openDialogs -= 1;
    scrim.remove();
    document.removeEventListener("keydown", onKey, true);
    if (previous && previous.focus) previous.focus();
    if (onClose) onClose(value);
  };
  const onKey = (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close(false);
    } else if (e.key === "Tab") {
      // keep focus inside the dialog
      const items = Array.from(dialog.querySelectorAll("button, a[href], input, select, [tabindex='0']")).filter((x) => !x.disabled);
      if (!items.length) return;
      const first = items[0];
      const lastItem = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        lastItem.focus();
      } else if (!e.shiftKey && document.activeElement === lastItem) {
        e.preventDefault();
        first.focus();
      }
    }
  };
  const footer = actions && actions.length
    ? h(
        "div",
        { class: "dialog-foot" },
        actions.map((a) =>
          h("button", { class: "btn" + (a.primary ? " btn-primary" : ""), type: "button", onClick: () => (a.onClick ? a.onClick(close) : close(a.value)) }, a.icon ? icon(a.icon, 15) : null, a.label)
        )
      )
    : null;
  const dialog = h(
    "div",
    { class: "dialog" + (wide ? " dialog-wide" : ""), role: "dialog", "aria-modal": "true", "aria-label": label || title },
    title
      ? h("div", { class: "dialog-head" }, h("h2", null, title), h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onClick: () => close(false) }, icon("x", 16)))
      : null,
    h("div", { class: "dialog-body" }, body),
    footer
  );
  const scrim = h("div", { class: "scrim", onMousedown: (e) => e.target === scrim && close(false) }, dialog);
  document.body.append(scrim);
  openDialogs += 1;
  document.addEventListener("keydown", onKey, true);
  const focusTarget = qs(".btn-primary", dialog) || qs("button", dialog);
  if (focusTarget) focusTarget.focus();
  return close;
}

export function confirmDialog({ title, body, confirm, cancel = "Cancel" }) {
  return new Promise((resolve) => {
    openDialog({
      title,
      body,
      onClose: (v) => resolve(Boolean(v)),
      actions: [
        { label: cancel, value: false },
        { label: confirm, primary: true, value: true },
      ],
    });
  });
}

export function lightbox(src, alt) {
  const img = h("img", { src, alt: alt || "" });
  openDialog({ title: alt || "Image", body: h("div", { class: "lightbox checker" }, img), wide: true });
}

/* ---------------------------------------------------------------- popover */

let activePopover = null;

export function closePopover() {
  if (activePopover) activePopover();
}

export function openPopover(anchor, content, label) {
  closePopover();
  const pop = h("div", { class: "popover", role: "dialog", "aria-label": label || "Details" }, content);
  document.body.append(pop);
  const r = anchor.getBoundingClientRect();
  const width = pop.offsetWidth;
  const left = Math.max(16, Math.min(window.innerWidth - width - 16, r.right - width));
  pop.style.left = left + "px";
  pop.style.top = r.bottom + 8 + "px";
  anchor.setAttribute("aria-expanded", "true");
  const onDown = (e) => {
    if (!pop.contains(e.target) && !anchor.contains(e.target)) close();
  };
  const onKey = (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
      anchor.focus();
    }
  };
  function close() {
    pop.remove();
    anchor.setAttribute("aria-expanded", "false");
    document.removeEventListener("mousedown", onDown, true);
    document.removeEventListener("keydown", onKey, true);
    activePopover = null;
  }
  setTimeout(() => {
    document.addEventListener("mousedown", onDown, true);
    document.addEventListener("keydown", onKey, true);
  });
  activePopover = close;
  return close;
}

export function segmented(options, value, onChange, opts = {}) {
  return h(
    "div",
    { class: "seg" + (opts.block ? " seg-block" : "") + (opts.small ? " seg-sm" : ""), role: "group", "aria-label": opts.label || "" },
    options.map((o) =>
      h(
        "button",
        {
          type: "button",
          "aria-pressed": String(o.value === value),
          disabled: o.disabled || false,
          "data-tip": o.tip || null,
          "data-tip-pos": o.tip ? "below" : null,
          onClick: () => o.value !== value && onChange(o.value),
        },
        o.icon ? icon(o.icon, 14) : null,
        o.label,
        o.kbd ? h("span", { class: "sr-only" }, ` (${o.kbd})`) : null
      )
    )
  );
}

export function replaceChildren(el, ...children) {
  clear(el);
  for (const c of children.flat(Infinity)) if (c) el.append(c);
}
