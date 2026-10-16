// Keyboard shortcuts: one registry, one `?` overlay that lists them.
// A binding: { keys: "ctrl+enter" | "g w" | "?", label, group, when: () => bool, run: (e) => void,
//              inInputs: bool }. Two-key sequences ("g w") wait up to 1 s for the second key.

import { h } from "./dom.js";
import { dialogOpen, kbd, openDialog } from "./ui.js";

const bindings = [];
let pending = null; // first key of a sequence
let pendingTimer = null;

export function bind(def) {
  bindings.push(def);
}

function normalise(e) {
  const parts = [];
  if (e.ctrlKey || e.metaKey) parts.push("ctrl");
  if (e.altKey) parts.push("alt");
  let key = e.key;
  if (key === " ") key = "space";
  key = key.length === 1 ? key.toLowerCase() : key.toLowerCase();
  if (e.shiftKey && key.length > 1 && key !== "?") parts.push("shift");
  if (e.shiftKey && key.length === 1 && /[a-z]/.test(key)) parts.push("shift");
  parts.push(key);
  return parts.join("+");
}

function typing(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

export function installShortcuts() {
  document.addEventListener("keydown", (e) => {
    if (e.defaultPrevented || e.isComposing) return;
    if (dialogOpen() && e.key !== "?") return;
    const combo = normalise(e);
    const inInput = typing(e.target);
    const candidates = bindings.filter((b) => (!b.when || b.when()) && (!inInput || b.inInputs));
    if (pending) {
      const seq = `${pending} ${combo}`;
      pending = null;
      clearTimeout(pendingTimer);
      const hit = candidates.find((b) => b.keys === seq);
      if (hit) {
        e.preventDefault();
        hit.run(e);
        return;
      }
    }
    const hit = candidates.find((b) => b.keys === combo || (b.alt && b.alt.includes(combo)));
    if (hit) {
      e.preventDefault();
      hit.run(e);
      return;
    }
    if (!inInput && candidates.some((b) => b.keys.startsWith(combo + " "))) {
      pending = combo;
      pendingTimer = setTimeout(() => (pending = null), 1000);
    }
  });
}

function keyCaps(keys) {
  return keys.split(" ").map((chord, i) =>
    h(
      "span",
      { style: { display: "inline-flex", gap: "3px", alignItems: "center" } },
      i ? h("span", { class: "muted", style: { margin: "0 4px", fontSize: "11px" } }, "then") : null,
      chord.split("+").map((k) => kbd(k === "ctrl" ? (navigator.platform.includes("Mac") ? "⌘" : "Ctrl") : k === "enter" ? "↵" : k === "shift" ? "Shift" : k === "backspace" ? "⌫" : k === "escape" ? "Esc" : k === "arrowleft" ? "←" : k === "arrowright" ? "→" : k.length === 1 ? k.toUpperCase() : k))
    )
  );
}

export function showShortcuts() {
  const groups = new Map();
  for (const b of bindings) {
    if (!b.label || (b.when && b.helpWhen === false)) continue;
    if (!groups.has(b.group)) groups.set(b.group, []);
    const list = groups.get(b.group);
    if (!list.some((x) => x.label === b.label)) list.push(b);
  }
  const body = h(
    "div",
    { style: { display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "8px 32px" } },
    Array.from(groups.entries()).map(([group, list]) =>
      h(
        "div",
        null,
        h("div", { class: "section-title", style: { margin: "8px 0 6px" } }, group),
        list.map((b) =>
          h(
            "div",
            { style: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px", padding: "5px 0", borderBottom: "1px solid var(--line)", fontSize: "13px" } },
            h("span", null, b.label),
            h("span", { style: { display: "inline-flex", gap: "3px", flex: "none" } }, keyCaps(b.display || b.keys))
          )
        )
      )
    )
  );
  openDialog({ title: "Keyboard shortcuts", body, wide: true });
}
