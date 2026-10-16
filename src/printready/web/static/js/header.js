// The top bar (wordmark, nav, profile, spend meter, theme) and the footer.

import { append, h, clear } from "./dom.js";
import { icon, logoMark } from "./icons.js";
import { num, usd } from "./format.js";
import { openPopover, srcTag } from "./ui.js";
import { showShortcuts } from "./shortcuts.js";

const THEME_LABEL = { auto: "Theme: follows the OS", light: "Theme: light", dark: "Theme: dark" };
const THEME_ICON = { auto: "auto", light: "sun", dark: "moon" };

function ruleValue(r) {
  const v = r.value;
  if (r.key === "bg_ring_uniform_frac" || r.key === "damage_max_frac") return `${num(v * 100, 0)}%`;
  if (r.unit === "x") return `${v}×`;
  return `${Number(v).toLocaleString("en-US", { maximumFractionDigits: 4 })} ${r.unit}`.trim();
}

function profilePopover(app) {
  const profile = app.profile || {};
  return h(
    "div",
    { class: "rules-list" },
    h(
      "div",
      { class: "rules-head" },
      h("h3", null, profile.label || "Profile"),
      h("p", null, "Paraphrased from Sticker Mule's public FAQ pages (SM links to the page). Numbers marked conv are our own conventions where the FAQ gives none. printready is not affiliated with Sticker Mule.")
    ),
    (profile.rules || []).map((r) =>
      h("div", { class: "rule" }, h("span", { class: "rule-name" }, r.label), h("span", { class: "rule-value" }, ruleValue(r), srcTag(r.source)), h("span", { class: "rule-why" }, r.why))
    ),
    profile.error ? h("div", { class: "rule" }, h("span", { class: "rule-why" }, "Profile could not be loaded: " + profile.error)) : null
  );
}

export function renderHeader(host, app, screen, theme, actions) {
  clear(host);
  const isStatic = app && app.static;
  const nav = [
    { id: "workbench", label: "Workbench", href: "#/workbench" },
    { id: "results", label: "Results", href: "#/results" },
    isStatic ? null : { id: "label", label: "Label", href: "#/label" },
  ].filter(Boolean);
  const right = h("div", { class: "topbar-right" });
  if (app && app.demo) right.append(h("span", { class: "pill pill-accent", "data-tip": "Saved runs replayed from examples/samples/demo; scripted model; nothing is charged", "data-tip-pos": "below" }, "Demo"));
  if (isStatic) right.append(h("span", { class: "pill", "data-tip": "A static copy: no server, no runs", "data-tip-pos": "below" }, icon("lock", 11), "Read-only"));
  if (app && app.profile) {
    const btn = h(
      "button",
      { class: "profile-btn", type: "button", "aria-haspopup": "dialog", "aria-expanded": "false", onClick: (e) => openPopover(e.currentTarget, profilePopover(app), "Profile rules") },
      icon("book", 15),
      h("span", { class: "ellipsis" }, "Sticker Mule die-cut rules ", h("span", { class: "paren" }, "(paraphrased from public FAQ)")),
      icon("chevronDown", 13)
    );
    right.append(btn);
  }
  if (app && app.spend && !isStatic) {
    const sp = app.spend;
    const frac = sp.cap_usd > 0 ? sp.total_usd / sp.cap_usd : 0;
    const level = sp.total_usd >= sp.cap_usd ? "over" : sp.total_usd >= (sp.stop_at_usd || 8) ? "high" : "ok";
    const tip = `Spend ledger (${sp.ledger}${sp.ledger_exists ? "" : ", none yet"}) against PRINTREADY_SPEND_CAP_USD.${app.demo ? " Demo runs are never charged." : ""}`;
    right.append(
      h("div", { class: "vsep", "aria-hidden": "true" }),
      h(
        "div",
        { class: "spend", "data-level": level, "data-tip": tip, "data-tip-pos": "left", tabindex: "0", role: "img", "aria-label": `Spent ${usd(sp.total_usd, { cents: true })} of ${usd(sp.cap_usd, { cents: true })}` },
        h("div", { class: "spend-text" }, h("span", null, h("b", null, usd(sp.total_usd, { cents: true })), " of ", usd(sp.cap_usd, { cents: true }))),
        h("div", { class: "spend-bar" }, h("i", { style: { width: Math.min(100, frac * 100) + "%" } }))
      )
    );
  }
  right.append(
    h("div", { class: "vsep", "aria-hidden": "true" }),
    h("button", { class: "icon-btn", type: "button", "aria-label": `${THEME_LABEL[theme]}. Click to change (Shift+T).`, "data-tip": THEME_LABEL[theme], "data-tip-pos": "left", onClick: actions.cycleTheme }, icon(THEME_ICON[theme], 17)),
    h("button", { class: "icon-btn", type: "button", "aria-label": "Keyboard shortcuts (?)", "data-tip": "Shortcuts (?)", "data-tip-pos": "left", onClick: showShortcuts }, icon("keyboard", 17))
  );
  host.append(
    h("a", { class: "brand", href: "#/workbench", "aria-label": "printready, home" }, logoMark(24), "printready"),
    h(
      "nav",
      { class: "nav", "aria-label": "Screens" },
      nav.map((n) => h("a", { href: n.href, "aria-current": screen === n.id ? "page" : null }, n.label))
    ),
    right
  );
}

export function renderFooter(host, app) {
  clear(host);
  append(host, [
    h("span", null, "Not affiliated with Sticker Mule."),
    h("span", { class: "muted fb-shrink" }, "Rules paraphrased from public FAQ pages; conv marks our own thresholds."),
    h("span", { class: "spacer" }),
    app && app.static ? h("span", { class: "fb-shrink fb-wide" }, "Read-only demo. Run it locally for your own art.") : null,
    h("span", { class: "num" }, app && app.version ? `printready ${app.version}` : "printready"),
    h("button", { type: "button", onClick: showShortcuts }, icon("keyboard", 13), "Press ? for shortcuts"),
  ]);
}
