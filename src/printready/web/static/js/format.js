// Names, labels and number formatting. Everything user-facing about checks and fixes lives here.

export const CHECKS = {
  product_fit: { name: "Product fit", what: "Die-cut, or a whole-image sticker for scenes" },
  file: { name: "File", what: "Opens, under 20 MB, at least 64 px a side" },
  resolution: { name: "Resolution", what: "Pixels per inch at the ordered size" },
  background: { name: "Background", what: "Transparent, or one removable colour" },
  soft_alpha: { name: "Soft edges", what: "No shadow or glow band where the cut goes" },
  edge_crop: { name: "Edge crop", what: "Art does not run off the canvas" },
  islands: { name: "One piece", what: "The die-cut is a single outline" },
  text_garbled: { name: "Spelling", what: "Lettering reads as intended (vision)" },
  text_small: { name: "Text size", what: "Text is at least 6 pt when printed (vision)" },
};

export const CHECK_ORDER = ["product_fit", "file", "resolution", "background", "soft_alpha", "edge_crop", "islands", "text_garbled", "text_small"];

export const FIXES = {
  remove_background: "Remove background",
  pad_canvas: "Pad canvas",
  add_border: "Add border",
  bridge_islands: "Bridge parts",
  fit_shape: "Whole-image shape",
};

export const TOOLS = {
  check: { icon: "rules", label: "check" },
  look: { icon: "eye", label: "look" },
  remove_background: { icon: "wand", label: "remove_background" },
  pad_canvas: { icon: "fit", label: "pad_canvas" },
  add_border: { icon: "border", label: "add_border" },
  bridge_islands: { icon: "layers", label: "bridge_islands" },
  fit_shape: { icon: "image", label: "fit_shape" },
  read_text: { icon: "text", label: "read_text" },
  finish: { icon: "flag", label: "finish" },
  handoff: { icon: "handoff", label: "handoff" },
};

export const OUTCOMES = {
  ready: { label: "Ready", title: "Ready to print", icon: "check" },
  fixable: { label: "Fixable", title: "Fixable", icon: "wand" },
  needs_person: { label: "Needs a person", title: "Needs a person", icon: "user" },
};

export const STATUS_LABEL = { pass: "Pass", warn: "Warn", fail: "Fail", skip: "Skip", na: "n/a" };

// Ebin's pass-1 labels record a fact; PREREG maps them to outcomes (scene -> fixable: the tool
// offers a rounded-rectangle sticker). Older three-way labels map to themselves.
export const LABELS = {
  ready_diecut: { text: "Ready", outcome: "ready" },
  fixable_diecut: { text: "Fixable", outcome: "fixable" },
  scene: { text: "Scene", outcome: "fixable" },
  needs_person: { text: "Needs a person", outcome: "needs_person" },
  ready: { text: "Ready", outcome: "ready" },
  fixable: { text: "Fixable", outcome: "fixable" },
};

export function labelOutcome(label) {
  return LABELS[label] ? LABELS[label].outcome : null;
}

// A whole-image (rounded-rectangle) sticker instead of a die-cut: art.shape, or a product_fit finding.
export function isShapeProduct(result) {
  if (!result) return false;
  if (result.art && result.art.shape && result.art.shape !== "die_cut") return true;
  return ((result.after && result.after.findings) || []).some((f) => f.check === "product_fit" && f.status !== "pass");
}

export function notApplicable(f) {
  return Boolean(f && f.measured && f.measured.applies === false);
}
export const FIXER_LABEL = { auto: "Auto-fix", customer: "Customer", person: "Person" };
export const FIXER_ICON = { auto: "wand", customer: "user", person: "handoff" };
export const SEVERITY = { fail: 3, warn: 2, skip: 1, pass: 0 };

export function checkName(id) {
  return (CHECKS[id] && CHECKS[id].name) || humanize(id);
}

export function fixName(id) {
  return FIXES[id] || humanize(id);
}

export function humanize(key) {
  const s = String(key || "").replace(/_/g, " ").trim();
  return s ? s[0].toUpperCase() + s.slice(1) : "";
}

export function num(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "–";
  return Number(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

// Significant-ish formatting for measurements: 321, 2.31, 0.084, 0.0042.
export function smart(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "–";
  const v = Number(value);
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a >= 100) return num(v, 0);
  if (a >= 10) return num(v, 1);
  if (a >= 1) return num(v, 2);
  if (a >= 0.01) return num(v, 3);
  return num(v, 4);
}

export function usd(value, opts = {}) {
  if (value === null || value === undefined) return "–";
  const v = Number(value);
  if (opts.cents || v >= 1) return "$" + v.toFixed(2);
  if (v === 0) return "$0.00";
  if (v < 0.0001) return "<$0.0001";
  return "$" + v.toFixed(4);
}

export function pct(value, digits = 0) {
  if (value === null || value === undefined) return "–";
  return (Number(value) * 100).toFixed(digits) + "%";
}

export function bytes(n) {
  if (n === null || n === undefined) return "–";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + " MB";
  if (n >= 1e3) return Math.max(1, Math.round(n / 1e3)) + " KB";
  return n + " B";
}

export function ms(n) {
  if (n === null || n === undefined) return "–";
  if (n >= 10000) return (n / 1000).toFixed(0) + " s";
  if (n >= 1000) return (n / 1000).toFixed(1) + " s";
  return Math.round(n) + " ms";
}

export function tokens(n) {
  if (n === null || n === undefined) return "–";
  if (n >= 100000) return Math.round(n / 1000) + "k";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

export function inches(v, digits = 2) {
  if (v === null || v === undefined) return "–";
  return Number(v).toFixed(digits) + " in";
}

export function sizeLabel(size) {
  return `${Number(size).toLocaleString("en-US", { maximumFractionDigits: 2 })} in`;
}

export function timeAgo(iso) {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const sec = Math.max(0, (Date.now() - t) / 1000);
  if (sec < 45) return "just now";
  if (sec < 3600) return Math.round(sec / 60) + " min ago";
  if (sec < 86400) return Math.round(sec / 3600) + " h ago";
  const d = new Date(t);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function shortId(id, n = 10) {
  return String(id || "").slice(0, n);
}

export function plural(n, word, many) {
  return `${n} ${n === 1 ? word : many || word + "s"}`;
}

// The one-line reason under the outcome banner, from the RunResult alone.
export function outcomeReason(result) {
  if (!result) return "";
  const after = (result.after && result.after.findings) || [];
  const history = result.history || (result.art && result.art.history) || [];
  const size = result.spec && result.spec.size_in ? sizeLabel(result.spec.size_in) : "the ordered size";
  if (result.handoff_reason) {
    const auto = ["turn limit", "error", "budget"].includes(result.handoff_reason);
    return auto ? `The agent run stopped (${result.handoff_reason}), so a person takes over.` : `The agent handed off: ${result.handoff_reason}.`;
  }
  const damaged = history.find((s) => s.damaged);
  if (damaged) return `${fixName(damaged.fix)} damaged the art and was reverted.`;
  const flagged = after.filter((f) => f.status === "warn" || f.status === "fail");
  const person = flagged.find((f) => ["person", "none", "auto"].includes(f.fixer));
  if (result.outcome === "needs_person") {
    if (person) return person.message;
    const skipped = after.find((f) => f.status === "skip");
    if (skipped) return `${checkName(skipped.check)} could not be verified.`;
    return "Something needs a closer look before printing.";
  }
  if (result.outcome === "ready") return `Passes every rule at ${size} with no corrections.`;
  if (isShapeProduct(result)) return "A scene with no clean edge: it fits a whole-image rounded-rectangle sticker; the customer confirms the product.";
  const applied = history.filter((s) => s.ok && s.fix !== "add_border").map((s) => fixName(s.fix).toLowerCase());
  const customer = flagged.find((f) => f.fixer === "customer");
  const parts = [];
  if (applied.length) parts.push(applied.join(", ") + " applied automatically");
  if (customer) parts.push("the customer should " + (customer.check === "resolution" ? "pick a smaller size" : "review: " + checkName(customer.check).toLowerCase()));
  const text = parts.join("; ");
  return text ? text[0].toUpperCase() + text.slice(1) + "." : "Mechanical fixes only.";
}
