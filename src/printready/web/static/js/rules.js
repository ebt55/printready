// Turns a finding's `measured` numbers into threshold bars bound to the profile's rules, so each
// row reads as "value vs rule (source)". Key names follow src/printready/checks/*.py; unknown
// keys fall back to plain facts. One place to update when a check changes its measurements.

import { inches, num, pct, smart } from "./format.js";

// ctx = { rules: { key: { value, source } }, size }
function rule(ctx, key, fallback) {
  const r = ctx.rules[key];
  return r ? r : { value: fallback, source: "convention" };
}

function niceMax(v) {
  if (!(v > 0)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const k of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (k * p >= v) return k * p;
  return 10 * p;
}

const EDGE = { top: "top", bottom: "bottom", left: "left", right: "right" };

export function measurementsFor(f, ctx) {
  const m = f.measured || {};
  const out = { bars: [], facts: [] };
  const size = ctx.size;

  if (f.status === "skip") {
    if (m.reason) out.facts.push([m.reason, ""]);
    return out;
  }

  switch (f.check) {
    case "resolution": {
      if (typeof m.ppi === "number") {
        const target = rule(ctx, "ppi_target", 300);
        const floor = rule(ctx, "ppi_floor", 150);
        const hi = niceMax(Math.max(m.ppi, target.value) * 1.18);
        out.bars.push({
          label: `Print resolution at ${num(size, size % 1 ? 2 : 0)} in`,
          value: m.ppi,
          display: num(m.ppi, 0),
          unit: "PPI",
          status: f.status,
          domain: [0, hi],
          zones: [
            { from: 0, to: floor.value, level: 2 },
            { from: floor.value, to: target.value, level: 1 },
          ],
          marks: [
            { value: target.value, display: num(target.value), label: "target", source: target.source },
            { value: floor.value, display: num(floor.value), label: "floor", source: floor.source },
          ],
        });
      }
      if (m.max_size_in_at_target) out.facts.push([inches(m.max_size_in_at_target, 1), "sharp up to"]);
      if (m.max_size_in_at_floor) out.facts.push([inches(m.max_size_in_at_floor, 1), "acceptable up to"]);
      if (m.one_pt_px) out.facts.push([`${num(m.one_pt_px, 1)} px`, "= a 1 pt line"]);
      if (m.basis === "canvas") out.facts.push(["whole canvas", "measured on"]);
      break;
    }
    case "background": {
      if (m.real_alpha === false && typeof m.ring_uniform_frac === "number") {
        const r = rule(ctx, "bg_ring_uniform_frac", 0.95);
        out.bars.push({
          label: "Edge ring within tolerance of one colour",
          value: m.ring_uniform_frac * 100,
          display: num(m.ring_uniform_frac * 100, 1),
          unit: "%",
          status: f.status,
          domain: [0, 100],
          zones: [{ from: 0, to: r.value * 100, level: 1 }],
          marks: [{ value: r.value * 100, display: pct(r.value, 0), label: "solid at", source: r.source }],
        });
        if (m.colour_hex) out.facts.push([m.colour_hex.toUpperCase(), "colour", m.colour_hex]);
        const de = ctx.rules.bg_delta_e;
        if (de) out.facts.push([`ΔE ${num(de.value, 0)}`, "tolerance"]);
      } else if (m.real_alpha) {
        out.facts.push([m.removed ? "removed" : "transparent", "background"]);
      }
      break;
    }
    case "soft_alpha": {
      const lim = rule(ctx, "soft_alpha_max_in", m.limit_in || 0.03);
      if (typeof m.band_p95_in === "number") {
        const hi = niceMax(Math.max(m.band_p95_in, lim.value) * 1.6);
        out.bars.push({
          label: "Soft edge band (95th percentile)",
          value: m.band_p95_in,
          display: smart(m.band_p95_in),
          unit: "in",
          status: f.status,
          domain: [0, hi],
          zones: [{ from: lim.value, to: hi, level: 1 }],
          marks: [{ value: lim.value, display: `${lim.value} in`, label: "max", source: lim.source }],
        });
      } else if (m.band_p95_in === null) {
        out.facts.push(["no opaque pixels", ""]);
      }
      if (m.partial_px) out.facts.push([num(m.partial_px), "see-through px"]);
      break;
    }
    case "edge_crop": {
      const lim = rule(ctx, "edge_cut_min_run_in", m.limit_in || 0.1);
      if (typeof m.longest_run_in === "number") {
        const hi = niceMax(Math.max(m.longest_run_in, lim.value) * 1.6);
        out.bars.push({
          label: m.edge ? `Art along the ${EDGE[m.edge] || m.edge} edge` : "Art along a canvas edge",
          value: m.longest_run_in,
          display: smart(m.longest_run_in),
          unit: "in",
          status: f.status,
          domain: [0, hi],
          zones: [{ from: lim.value, to: hi, level: 2 }],
          marks: [{ value: lim.value, display: `${lim.value} in`, label: "cut off above", source: lim.source }],
        });
      }
      if (typeof m.min_margin_in === "number") {
        const border = rule(ctx, "border_in", 0.1);
        out.facts.push([inches(m.min_margin_in, 2), `margin (border needs ${border.value} in)`]);
      }
      if (m.cut_on_edge) out.facts.push(["border clipped", "at the canvas edge"]);
      break;
    }
    case "islands": {
      if (typeof m.components === "number") out.facts.push([String(m.components), m.components === 1 ? "piece" : "pieces"]);
      if (typeof m.border_in === "number") out.facts.push([inches(m.border_in, 2), m.basis === "cut" ? "border (cut)" : "border"]);
      if (m.specks) out.facts.push([String(m.specks), m.specks === 1 ? "speck dropped" : "specks dropped"]);
      if (m.joins_at_max_bridge !== null && m.joins_at_max_bridge !== undefined) {
        const r = rule(ctx, "max_bridge_border_in", 0.25);
        out.facts.push([m.joins_at_max_bridge ? "yes" : "no", `joins with a ${r.value} in border`]);
      }
      break;
    }
    case "file": {
      const max = rule(ctx, "max_upload_mb", 20);
      if (typeof m.bytes === "number") {
        const mb = m.bytes / 1e6;
        out.bars.push({
          label: "File size",
          value: mb,
          display: mb >= 1 ? num(mb, 1) : num(mb, 2),
          unit: "MB",
          status: f.status,
          domain: [0, max.value * 1.15],
          zones: [{ from: max.value, to: max.value * 1.15, level: 2 }],
          marks: [{ value: max.value, display: `${max.value} MB`, label: "limit", source: max.source }],
        });
      }
      if (m.width_px) out.facts.push([`${num(m.width_px)} × ${num(m.height_px)} px`, m.format || ""]);
      if (m.error) out.facts.push([m.error, ""]);
      break;
    }
    case "text_small": {
      if (typeof m.min_cap_height_pt === "number") {
        const ratio = rule(ctx, "cap_height_ratio", 0.7);
        const minText = rule(ctx, "min_text_pt", 6);
        const threshold = m.threshold_cap_pt || ratio.value * minText.value;
        const hi = niceMax(Math.max(m.min_cap_height_pt, threshold) * 1.5);
        out.bars.push({
          label: "Smallest capital letters",
          value: m.min_cap_height_pt,
          display: num(m.min_cap_height_pt, 1),
          unit: "pt",
          status: f.status,
          domain: [0, hi],
          zones: [{ from: 0, to: threshold, level: 1 }],
          marks: [{ value: threshold, display: `${num(threshold, 1)} pt`, label: `${minText.value} pt text`, source: minText.source }],
        });
      }
      if (m.min_text_pt_equiv) out.facts.push([`≈ ${num(m.min_text_pt_equiv, 1)} pt`, "text"]);
      if (m.min_size_in_for_text && f.status !== "pass") out.facts.push([inches(m.min_size_in_for_text, 1), "big enough from"]);
      break;
    }
    case "product_fit": {
      if (typeof m.finished_w_in === "number") out.facts.push([`${num(m.finished_w_in, 2)} × ${num(m.finished_h_in, 2)} in`, "rounded rectangle"]);
      if (typeof m.bleed_in === "number") out.facts.push([inches(m.bleed_in, 3), "bleed"]);
      if (typeof m.corner_radius_in === "number") out.facts.push([inches(m.corner_radius_in, 2), "corner radius"]);
      break;
    }
    case "text_garbled": {
      const items = m.items || [];
      for (const it of items.slice(0, 4)) {
        // the model spells each line letter by letter, so a dropped or doubled letter is visible
        const why = it.broken ? "broken letters" : it.misspelled ? `→ ${it.intended}` : it.garbled ? `→ ${it.intended}` : "reads fine";
        out.facts.push([it.letters && it.garbled ? it.letters : it.seen, why, null, it.garbled ? "bad" : "ok"]);
      }
      if (!items.length && m.reason) out.facts.push([m.reason, ""]);
      break;
    }
    default: {
      for (const [k, v] of Object.entries(m)) {
        if (typeof v === "number") out.facts.push([smart(v), k.replace(/_/g, " ")]);
        if (out.facts.length >= 4) break;
      }
    }
  }
  return out;
}

// One short number for a collapsed (passing) row, e.g. "321 PPI".
export function headline(f) {
  const m = f.measured || {};
  switch (f.check) {
    case "resolution":
      return typeof m.ppi === "number" ? `${num(m.ppi)} PPI` : "";
    case "file":
      return m.width_px ? `${m.width_px} × ${m.height_px}` : "";
    case "background":
      return m.real_alpha ? (m.removed ? "removed" : "transparent") : m.colour_hex ? m.colour_hex.toUpperCase() : "";
    case "soft_alpha":
      return typeof m.band_p95_in === "number" ? `${smart(m.band_p95_in)} in` : "";
    case "edge_crop":
      return typeof m.min_margin_in === "number" ? `${smart(m.min_margin_in)} in margin` : "";
    case "islands":
      return typeof m.components === "number" ? (m.components === 1 ? "1 piece" : `${m.components} pieces`) : "";
    case "text_garbled":
      return m.items ? (m.items.length ? `${m.items.length} text` : "no text") : "";
    case "text_small":
      return typeof m.min_cap_height_pt === "number" ? `${num(m.min_cap_height_pt, 1)} pt caps` : "";
    case "product_fit":
      return m.product === "rounded_rect" ? "rounded rectangle" : "die-cut";
    default:
      return "";
  }
}

// The damage guard result of a Step: {metric, label, value, limit, passed}.
export function guardBar(guard, ctx) {
  if (!guard || guard.value === undefined) return null;
  if (guard.metric === "damage_frac") {
    const lim = rule(ctx, "damage_max_frac", guard.limit);
    const limit = typeof guard.limit === "number" ? guard.limit : lim.value;
    const hi = niceMax(Math.max(guard.value, limit) * 1.6);
    return {
      label: `Damage guard: ${guard.label || "removed subject colour"}`,
      value: guard.value * 100,
      display: num(guard.value * 100, 2),
      unit: "%",
      status: guard.passed ? "pass" : "fail",
      domain: [0, hi * 100],
      zones: [{ from: limit * 100, to: hi * 100, level: 2 }],
      marks: [{ value: limit * 100, display: `${num(limit * 100, 0)}%`, label: "limit", source: lim.source }],
    };
  }
  return null;
}

export function rulesIndex(app) {
  const out = {};
  for (const r of (app && app.profile && app.profile.rules) || []) out[r.key] = r;
  return out;
}
