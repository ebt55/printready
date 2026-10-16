// The right panel: outcome banner, findings (one row per check, numbers against rules), fix
// timeline (with the damage guard), the customer's proof-approval card (a mock), person notes,
// downloads and run details. Pure render from the model; events go back through `actions`.

import { h, clear } from "./dom.js";
import { icon, logoMark } from "./icons.js";
import { CHECKS, CHECK_ORDER, OUTCOMES, SEVERITY, bytes, checkName, fixName, isShapeProduct, ms, notApplicable, num, outcomeReason, sizeLabel, timeAgo, usd } from "./format.js";
import { guardBar, headline, measurementsFor } from "./rules.js";
import { chip, fact, fixerBadge, lightbox, segmented, spinner, thresholdBar } from "./ui.js";

const expanded = new Set(); // check ids the user expanded (passing rows start collapsed)

function section(title, extra, ...children) {
  return h("section", { class: "section" }, h("div", { class: "section-head" }, h("h2", { class: "section-title" }, title), extra || null), children);
}

/* ---------------------------------------------------------------- banner */

function banner(m, actions) {
  const run = m.run;
  const res = run && run.result;
  const meta = [];
  const push = (iconName, text, tip) => meta.push(h("span", { class: "meta", "data-tip": tip || null }, icon(iconName, 12), text));
  if (run) {
    push(run.mode === "agent" ? "bot" : "rules", run.mode === "agent" ? `Agent · ${(run.model || "").replace(/^xai:/, "")}` : run.vision ? "Rules + text check" : "Rules", "Mode");
    push("ruler", sizeLabel(run.spec.size_in) + (isShapeProduct(res) ? " rounded rectangle" : " die-cut"), "Ordered size (longest side, border included)");
    if (res && res.cost_usd)
      push(
        "coin",
        usd(res.cost_usd) + (run.demo && !run.real ? " sim." : ""),
        run.real ? "What the saved live run cost; nothing is charged by the replay" : run.demo ? "Simulated cost; nothing is charged in demo mode" : "Model cost of this run"
      );
    if (res && res.elapsed_s) push("clock", ms(res.elapsed_s * 1000), "Time the run took (the saved run's own timing when replayed)");
    else if (run.duration_ms && !run.demo) push("clock", ms(run.duration_ms), "Wall-clock time");
  }
  const notices = run && run.notices && run.notices.length ? h("div", { class: "banner-notices" }, run.notices.map((n) => h("span", null, n))) : null;

  if (!run && m.runError) {
    return h(
      "div",
      { class: "banner", "data-outcome": "error", role: "alert" },
      h(
        "div",
        { class: "banner-top" },
        h("div", { class: "banner-icon" }, icon("alert", 18)),
        h("div", { class: "grow" }, h("div", { class: "banner-kicker" }, "Not found"), h("div", { class: "banner-title" }, "Could not open this run"), h("p", { class: "banner-reason" }, m.runError))
      ),
      h("div", { class: "row", style: { marginTop: "12px" } }, h("a", { class: "btn btn-sm", href: "#/workbench" }, icon("chevronLeft", 14), "Back to the workbench"))
    );
  }
  if (!run && !m.draft) {
    return h(
      "div",
      { class: "banner", "data-outcome": "empty" },
      h(
        "div",
        { class: "banner-top" },
        h("div", { class: "banner-icon" }, logoMark(22)),
        h("div", null, h("div", { class: "banner-kicker" }, "No artwork yet"), h("div", { class: "banner-title" }, "Check a sticker"), h("p", { class: "banner-reason" }, "Drop art on the stage or pick a sample. The verdict appears here: Ready, Fixable, or Needs a person."))
      )
    );
  }
  if (!run) {
    return h(
      "div",
      { class: "banner", "data-outcome": "draft" },
      h(
        "div",
        { class: "banner-top" },
        h("div", { class: "banner-icon" }, icon("image", 18)),
        h(
          "div",
          { class: "grow" },
          h("div", { class: "banner-kicker" }, "Not checked yet"),
          h("div", { class: "banner-title ellipsis", title: m.draft.name }, m.draft.name),
          h("p", { class: "banner-reason" }, `Ready to check as a ${sizeLabel(m.order.size)} die-cut sticker in ${m.order.mode} mode. Press Run or Ctrl+Enter.`)
        )
      )
    );
  }
  if (run.status === "error") {
    return h(
      "div",
      { class: "banner", "data-outcome": "error" },
      h(
        "div",
        { class: "banner-top" },
        h("div", { class: "banner-icon" }, icon("alert", 18)),
        h("div", { class: "grow" }, h("div", { class: "banner-kicker" }, "Run failed"), h("div", { class: "banner-title" }, "Something went wrong"), h("p", { class: "banner-reason" }, run.error || "The run stopped without a result."))
      ),
      run.readonly ? null : h("div", { class: "row", style: { marginTop: "12px" } }, h("button", { class: "btn btn-sm", type: "button", onClick: actions.retry }, icon("refresh", 14), "Try again"))
    );
  }
  if (!res) {
    const steps = run.steps.length;
    const turns = run.turns.length;
    return h(
      "div",
      { class: "banner", "data-outcome": "running", "aria-live": "polite" },
      h(
        "div",
        { class: "banner-top" },
        h("div", { class: "banner-icon" }, spinner()),
        h(
          "div",
          { class: "grow" },
          h("div", { class: "banner-kicker" }, run.mode === "agent" ? "Agent running" : "Checking"),
          h("div", { class: "banner-title" }, run.mode === "agent" ? (turns ? `Turn ${turns + 1}` : "Thinking") : steps ? `Fixing · ${steps} ${steps === 1 ? "step" : "steps"}` : "Running checks"),
          h("p", { class: "banner-reason" }, run.mode === "agent" ? "The model picks tools; every turn streams into the Trace tab." : "Deterministic checks, then fixes in a fixed order.")
        )
      ),
      h("div", { class: "banner-meta" }, meta),
      notices
    );
  }
  const o = OUTCOMES[res.outcome] || { label: res.outcome, title: res.outcome, icon: "info" };
  const shape = isShapeProduct(res);
  return h(
    "div",
    { class: "banner", "data-outcome": res.outcome, role: "status" },
    h(
      "div",
      { class: "banner-top" },
      h("div", { class: "banner-icon" }, icon(o.icon, 20)),
      h("div", { class: "grow" }, h("div", { class: "banner-kicker" }, "Outcome"), h("div", { class: "banner-title" }, o.title), h("p", { class: "banner-reason" }, outcomeReason(res)))
    ),
    shape
      ? h(
          "div",
          { class: "product-change", role: "note" },
          icon("image", 16),
          h("span", { class: "grow" }, h("b", null, "Rounded-rectangle sticker (suggested)"), h("small", null, "The art is a scene with no clean edge, so the whole image prints as a rounded rectangle instead of a die-cut. The customer can still ask a person to cut out part of it."))
        )
      : null,
    h("div", { class: "banner-meta" }, meta),
    notices
  );
}

/* ---------------------------------------------------------------- findings */

function sortFindings(list) {
  // flagged first, then passes, then checks that do not apply to this product
  const rank = (f) => (notApplicable(f) ? -1 : SEVERITY[f.status]);
  return [...list].sort((a, b) => rank(b) - rank(a) || CHECK_ORDER.indexOf(a.check) - CHECK_ORDER.indexOf(b.check));
}

function naRow(f) {
  return h(
    "div",
    { class: "finding na", "data-status": "na", "data-check": f.check, "aria-label": `${checkName(f.check)}: not applicable. ${f.message}` },
    h("div", { class: "finding-head" }, h("span", { class: "chip", "data-status": "na" }, "n/a"), h("span", { class: "finding-name" }, checkName(f.check)), h("span", { class: "muted", style: { marginLeft: "auto", fontSize: "12px" } }, "whole-image sticker"))
  );
}

function findingRow(f, before, m, actions, ctx) {
  if (notApplicable(f)) return naRow(f);
  const pinned = m.focusCheck && m.focusCheck.pinned && m.focusCheck.check === f.check;
  const open = f.status !== "pass" || expanded.has(f.check) || pinned;
  const was = before && before.status !== f.status ? before : null;
  const meas = measurementsFor(f, ctx);
  const textBoxes = ((m.run && m.run.text_boxes) || []).filter((b) => b.check === f.check).length;
  const boxes = (f.boxes || []).length || textBoxes;
  const row = h(
    "div",
    {
      class: "finding",
      "data-status": f.status,
      "data-check": f.check,
      role: "button",
      tabindex: "0",
      "aria-pressed": String(Boolean(pinned)),
      "aria-label": `${checkName(f.check)}: ${f.status}. ${f.message}`,
      onMouseenter: () => actions.hoverCheck(f.check),
      onMouseleave: () => actions.hoverCheck(null),
      onFocus: () => actions.hoverCheck(f.check),
      onBlur: () => actions.hoverCheck(null),
      onClick: () => {
        if (f.status === "pass") {
          if (expanded.has(f.check)) expanded.delete(f.check);
          else expanded.add(f.check);
        }
        actions.pinCheck(f.check);
      },
      onKeydown: (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          e.currentTarget.click();
        }
      },
    },
    h(
      "div",
      { class: "finding-head" },
      chip(f.status),
      h("span", { class: "finding-name" }, checkName(f.check)),
      was ? h("span", { class: "finding-was", "data-tip": "Status before the fixes" }, "was ", h("s", null, was.status)) : null,
      !open ? h("span", { class: "muted num", style: { marginLeft: "auto", fontSize: "12px" } }, headline(f)) : null,
      open && f.status !== "pass" ? fixerBadge(f.fixer) : null,
      open && boxes ? h("span", { class: "boxes-hint", "data-tip": "Regions marked on the stage" }, icon("boxes", 12), boxes) : null
    ),
    // collapsed (passing) rows still read as rules: one compact bar, value against the rule
    !open && meas.bars.length ? thresholdBar(meas.bars[0], { compact: true }) : null,
    open ? h("p", { class: "finding-msg" }, f.message) : null,
    open && meas && (meas.bars.length || meas.facts.length)
      ? h(
          "div",
          { class: "finding-meas" },
          meas.bars.map((b) => thresholdBar(b)),
          meas.facts.length
            ? h(
                "div",
                { class: "finding-facts" },
                meas.facts.map(([v, label, colour, tone]) =>
                  h(
                    "span",
                    { class: "meas" },
                    colour ? h("i", { style: { width: "10px", height: "10px", borderRadius: "3px", background: colour, boxShadow: "inset 0 0 0 1px rgba(0,0,0,.15)", alignSelf: "center" } }) : null,
                    h("b", { style: tone === "bad" ? { color: "var(--fail-ink)" } : null }, v),
                    label ? h("span", null, label) : null
                  )
                )
              )
            : null
        )
      : null
  );
  return row;
}

function findingsSection(m, actions, ctx) {
  const run = m.run;
  if (!run) {
    // before a run: what will be checked, and the rule each check uses
    const rows = CHECK_ORDER.filter((c) => c !== "product_fit" && (m.order.mode === "agent" || m.order.vision ? true : !c.startsWith("text_"))).map((c) =>
      h("div", { class: "precheck-row" }, icon("dot", 14), h("span", null, h("b", null, CHECKS[c].name), h("span", { class: "muted" }, " · " + CHECKS[c].what)), h("span", null))
    );
    return section("Checks", h("span", { class: "hint" }, m.draft ? "will run" : ""), h("div", { class: "precheck" }, rows));
  }
  const res = run.result;
  const before = (res && res.before) || run.reports.first;
  const after = (res && res.after) || (run.reports.latest !== run.reports.first ? run.reports.latest : null);
  const side = res ? m.side : after ? "after" : "before";
  const report = side === "before" ? before : after || before;
  const toggle = res
    ? segmented(
        [
          { value: "before", label: "Before" },
          { value: "after", label: "After" },
        ],
        side,
        (v) => actions.setSide(v),
        { small: true, label: "Which report" }
      )
    : h("span", { class: "hint" }, run.status === "error" ? "" : h("span", { class: "row", style: { gap: "6px" } }, spinner(), side === "before" ? "first report" : "updating"));
  if (!report) {
    const skel = [0, 1, 2, 3].map(() => h("div", { style: { display: "grid", gap: "8px", padding: "12px" } }, h("div", { class: "skeleton", style: { height: "14px", width: "40%" } }), h("div", { class: "skeleton", style: { height: "12px", width: "90%" } })));
    return section("Checks", toggle, skel);
  }
  const beforeBy = {};
  for (const f of (before && before.findings) || []) beforeBy[f.check] = f;
  const list = sortFindings(report.findings || []);
  const applicable = list.filter((f) => !notApplicable(f));
  const flagged = applicable.filter((f) => f.status !== "pass").length;
  const na = list.length - applicable.length;
  const title = h("span", null, "Checks ", h("span", { class: "count" }, (flagged ? `${flagged} of ${applicable.length} flagged` : `all ${applicable.length} pass`) + (na ? ` · ${na} n/a` : "")));
  return section(title, toggle, h("div", { class: "findings" }, list.map((f) => findingRow(f, side === "after" ? beforeBy[f.check] : null, m, actions, ctx))));
}

/* ---------------------------------------------------------------- fix timeline */

function timelineSection(m, actions, ctx) {
  const run = m.run;
  if (!run) return null;
  const steps = run.steps || [];
  const live = run.status === "running" || run.status === "queued";
  if (!steps.length && !live) {
    if (!run.result) return null;
    return section("Fixes", null, h("p", { class: "hint" }, run.mode === "agent" && run.result.handoff_reason ? "The agent handed off before changing any pixels." : "No fixes were needed or applied."));
  }
  const items = steps.map((x, i) => {
    const st = x.step;
    const state = st.damaged ? "damaged" : st.ok ? "ok" : "refused";
    const guard = st.guard || {};
    const bar = guardBar(guard, ctx);
    let guardLine = null;
    if (st.damaged) {
      guardLine = h("div", { class: "guard-line", "data-ok": "false" }, icon("shield", 14), "Damage guard: damaged, reverted");
    } else if (guard.metric === "subject_px_changed" || guard.metric === "image_px_changed") {
      const what = guard.metric === "image_px_changed" ? "image" : "subject";
      guardLine = h("div", { class: "guard-line", "data-ok": String(guard.passed !== false) }, icon("shield", 14), guard.passed !== false ? `Damage guard: ${what} unchanged (0 pixels changed)` : `Damage guard: ${num(guard.value)} ${what} pixels changed`);
    } else if (guard.metric === "damage_frac") {
      guardLine = h("div", { class: "guard-line", "data-ok": String(guard.passed !== false) }, icon("shield", 14), guard.passed !== false ? "Damage guard: within the limit" : "Damage guard: over the limit, reverted");
    } else if (st.ok) {
      guardLine = h("div", { class: "guard-line" }, icon("shield", 14), /bit-identical|unchanged/i.test(st.note || "") ? "Damage guard: subject unchanged" : "Damage guard passed");
    }
    const measured = st.measured || {};
    const facts = [];
    if (typeof measured.border_in === "number") facts.push(fact(`${num(measured.border_in, 2)} in`, "border"));
    if (typeof measured.removed_frac === "number") facts.push(fact(`${Math.round(measured.removed_frac * 100)}%`, "of the canvas removed"));
    if (measured.bg_hex) facts.push(fact(String(measured.bg_hex).toUpperCase(), "background"));
    if (typeof measured.margin_in === "number") facts.push(fact(`${num(measured.margin_in, 2)} in`, "margin added"));
    if (measured.clipped_at_edge) facts.push(fact("clipped", "at the canvas edge"));
    if (measured.shape === "rounded_rect" || st.fix === "fit_shape") {
      if (typeof measured.corner_radius_in === "number") facts.push(fact(`${num(measured.corner_radius_in, 2)} in`, "corners"));
      if (typeof measured.ppi === "number") facts.push(fact(`${num(measured.ppi)} PPI`, "at the new size"));
    }
    return h(
      "li",
      { class: "tl-item", "data-state": state },
      h("span", { class: "tl-node" }, icon(state === "ok" ? "check" : state === "damaged" ? "alert" : "minus", 13)),
      h(
        "div",
        { class: "tl-body" },
        h(
          "div",
          { class: "tl-head" },
          h("span", { class: "tl-name" }, fixName(st.fix)),
          h("span", { class: "tl-state" }, state === "ok" ? "applied" : state === "damaged" ? "reverted" : "refused"),
          x.preview ? h("button", { class: "link-btn", type: "button", onClick: () => actions.showStep(i + 1) }, "View") : null
        ),
        st.note ? h("p", { class: "tl-note" }, st.note) : null,
        facts.length ? h("div", { class: "finding-facts" }, facts) : null,
        guardLine || bar ? h("div", { class: "tl-guard" }, guardLine, bar ? thresholdBar(bar, { compact: true }) : null) : null
      )
    );
  });
  if (live) {
    items.push(h("li", { class: "tl-item", "data-state": "pending" }, h("span", { class: "tl-node" }, spinner()), h("div", { class: "tl-body" }, h("div", { class: "tl-head" }, h("span", { class: "tl-name muted" }, run.mode === "agent" ? "Waiting for the agent" : "Working")))));
  }
  return section(h("span", null, "Fixes ", h("span", { class: "count" }, steps.length ? String(steps.length) : "")), null, h("ol", { class: "timeline" }, items));
}

/* ---------------------------------------------------------------- customer proof card (mock) */

function proofSection(m) {
  const run = m.run;
  const res = run && run.result;
  if (!res) return null;
  const proof = run.images.proof;
  const needsPerson = res.outcome === "needs_person";
  return section(
    "Customer proof",
    h("span", { class: "hint" }, needsPerson ? "held for a person" : "what they would see"),
    h(
      "div",
      { class: "proofcard" },
      h("div", { class: "proofcard-ribbon" }, h("span", null, "Mock · customer view"), h("span", null, "not sent")),
      h(
        "div",
        { class: "proofcard-head" },
        h("div", { class: "proofcard-avatar" }, logoMark(18)),
        h("div", null, h("b", null, needsPerson ? "We're checking your artwork" : "Your proof is ready"), h("small", null, `${sizeLabel(run.spec.size_in)} ${isShapeProduct(res) ? "rounded-rectangle" : "die-cut"} sticker · 1 design`))
      ),
      proof
        ? h("button", { class: "proofcard-img checker", type: "button", "aria-label": "Enlarge the proof", onClick: () => lightbox(proof.url, "Proof") }, h("img", { src: proof.url, alt: "Proof: the sticker with its white border and magenta cut line" }))
        : h("div", { class: "proofcard-img checker" }, h("span", { class: "hint" }, "No proof was rendered.")),
      h("p", { class: "proofcard-msg" }, res.customer_message || "(no message)"),
      h(
        "div",
        { class: "proofcard-actions" },
        h("button", { class: "btn btn-primary", type: "button", disabled: true, "aria-disabled": "true", title: "Mock: disabled" }, icon("check", 14), "Approve proof"),
        h("button", { class: "btn", type: "button", disabled: true, "aria-disabled": "true", title: "Mock: disabled" }, "Request changes")
      )
    )
  );
}

function notesSection(m) {
  const res = m.run && m.run.result;
  const notes = (res && res.person_notes) || [];
  if (!notes.length) return null;
  return section("Notes for a person", null, h("div", { class: "notes" }, notes.map((n) => h("div", { class: "note-item" }, icon("handoff", 14), h("span", null, n)))));
}

function downloadsSection(m) {
  const run = m.run;
  if (!run || !run.downloads || !run.downloads.length) return null;
  const primary = run.downloads.filter((d) => d.primary);
  const extra = run.downloads.filter((d) => !d.primary);
  return section(
    "Downloads",
    null,
    h(
      "div",
      { class: "downloads" },
      primary.map((d) => {
        const ext = d.name.split(".").pop();
        return h("a", { class: "dl", href: d.url, download: d.name, "data-ext": ext }, h("span", { class: "dl-ext" }, ext), h("span", { class: "grow" }, h("div", { class: "dl-name ellipsis" }, d.name), h("div", { class: "dl-size" }, bytes(d.bytes))), icon("download", 15));
      })
    ),
    extra.length ? h("div", { class: "dl-extra" }, h("span", { class: "muted" }, "Also:"), extra.map((d) => h("a", { href: d.url, download: d.name }, d.name))) : null
  );
}

function detailsSection(m) {
  const run = m.run;
  if (!run || !run.result) return null;
  const res = run.result;
  const rows = [
    ["Run", h("span", { class: "mono" }, run.id)],
    ["File", run.filename],
    ["Created", run.created ? `${new Date(run.created).toLocaleString()} (${timeAgo(run.created)})` : null],
    ["Mode", run.mode === "agent" ? `agent · ${run.model}` : run.vision ? `rules + text check (${run.model})` : "rules"],
    ["Engine", run.real ? "saved live run (real Grok output, dev set), replayed" : run.demo ? "demo (real pipeline, scripted model)" : run.engine || "live"],
    ["Art", res.art ? `${num(res.art.width)} × ${num(res.art.height)} px · ${num(res.art.ppi, 1)} PPI · offset ${res.art.offset.join(", ")}` : null],
    ["Pipeline time", res.elapsed_s ? `${num(res.elapsed_s, 2)} s` : null],
  ].filter((r) => r[1]);
  return section("Run details", null, h("dl", { class: "details" }, rows.map(([k, v]) => [h("dt", null, k), h("dd", null, v)])));
}

export function renderPanel(host, m, actions, ctx) {
  const top = host.scrollTop;
  clear(host);
  host.append(banner(m, actions));
  for (const sec of [findingsSection(m, actions, ctx), timelineSection(m, actions, ctx), proofSection(m), notesSection(m), downloadsSection(m), detailsSection(m)]) {
    if (sec) host.append(sec);
  }
  host.scrollTop = top;
}
