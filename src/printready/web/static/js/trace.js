// The agent trace: one card per model turn, streaming live. Each turn shows the model's text, its
// tool calls with arguments, each tool's result (summary plus the full JSON the model got back),
// any image the model was shown, and tokens, cost and latency. Totals and a latency waterfall sit
// on top. The outcome is never the model's: the header says so, because that is the design.

import { h, clear } from "./dom.js";
import { icon } from "./icons.js";
import { OUTCOMES, TOOLS, ms, tokens, usd } from "./format.js";
import { codeJSON, dots, lightbox, outcomeChip } from "./ui.js";

const open = new Set(); // "turn:call" keys whose JSON is expanded (survives re-renders)

function callKind(call) {
  const r = String(call.result || "").toLowerCase();
  if (call.name === "handoff") return "handoff";
  if (call.name === "finish" && r.startsWith("finished")) return "ok";
  if (r.startsWith("refused") || r.startsWith("error") || r.includes("refused") || r.startsWith("bad") || r.startsWith("unknown") || r.includes("damaged")) return "refused";
  if (call.name === "check" || call.name === "look" || call.name === "read_text") return "neutral";
  return "ok";
}

function argsInline(args) {
  if (!args || typeof args !== "object") return args ? String(args) : "()";
  const keys = Object.keys(args);
  if (!keys.length) return "()";
  if (keys.length === 1 && typeof args[keys[0]] === "string" && args[keys[0]].length < 24) return `(${keys[0]}="${args[keys[0]]}")`;
  return `(${keys.join(", ")})`;
}

function renderCall(turn, call, idx, run) {
  const kind = callKind(call);
  const meta = TOOLS[call.name] || { icon: "tool" };
  const key = `${turn.n}:${idx}`;
  const statusText = { ok: "ok", refused: "refused", handoff: "handoff", neutral: "done" }[kind];
  const statusIcon = { ok: "check", refused: "x", handoff: "handoff", neutral: "check" }[kind];
  const args = call.arguments && typeof call.arguments === "object" ? call.arguments : null;
  const quote =
    call.name === "finish" && args && args.customer_message
      ? h("blockquote", { class: "message-quote" }, args.customer_message)
      : call.name === "handoff" && args
        ? h("blockquote", { class: "message-quote handoff" }, h("b", null, args.reason || "handoff"), args.person_notes ? h("div", { style: { marginTop: "4px" } }, Array.isArray(args.person_notes) ? args.person_notes.join(" ") : args.person_notes) : null)
        : null;
  const details = call.content !== undefined ? call.content : null;
  const expanded = open.has(key);
  const toggle = details
    ? h(
        "button",
        {
          class: "link-btn",
          type: "button",
          "aria-expanded": String(expanded),
          onClick: (e) => {
            if (open.has(key)) open.delete(key);
            else open.add(key);
            const body = e.currentTarget.closest(".call").querySelector(".call-args");
            const now = open.has(key);
            e.currentTarget.setAttribute("aria-expanded", String(now));
            e.currentTarget.textContent = now ? "Hide JSON" : "JSON";
            if (body) body.hidden = !now;
          },
        },
        expanded ? "Hide JSON" : "JSON"
      )
    : null;
  return h(
    "div",
    { class: "call" },
    h(
      "div",
      { class: "call-head" },
      h("span", { class: "call-icon" }, icon(meta.icon, 13)),
      h("code", { class: "call-name" }, call.name),
      call.name === "finish" || call.name === "handoff" ? null : h("span", { class: "call-args-inline", title: args ? JSON.stringify(args) : "" }, argsInline(args)),
      call.ms !== undefined ? h("span", { class: "muted", style: { fontSize: "11px" } }, ms(call.ms)) : null,
      h("span", { class: "call-status", "data-kind": kind }, icon(statusIcon, 12), statusText)
    ),
    quote ? h("div", { style: { padding: "0 12px 10px" } }, quote) : null,
    h(
      "div",
      { class: "call-result" },
      h("span", { class: "arrow" }, "→"),
      h("span", { class: "grow" }, call.result || "(no result)"),
      toggle
    ),
    details ? h("div", { class: "call-args", hidden: !expanded }, h("div", { class: "hint", style: { margin: "6px 0 4px" } }, "Tool result as the model received it"), codeJSON(details)) : null
  );
}

function endKind(turn) {
  const names = (turn.tool_calls || []).map((c) => c.name);
  if (names.includes("handoff")) return "handoff";
  if (names.includes("finish") && (turn.tool_calls || []).some((c) => c.name === "finish" && callKind(c) === "ok")) return "finish";
  return null;
}

function renderTurn(turn, run, isLast) {
  const t = turn.tokens || {};
  const end = endKind(turn);
  const image = turn.image;
  const imgFile = image && (image.name || image);
  const card = h(
    "li",
    { class: "turn", id: `turn-${turn.n}`, "data-end": end },
    h("div", { class: "turn-n", "aria-hidden": "true" }, turn.n),
    h(
      "article",
      { class: "turn-card", "aria-label": `Turn ${turn.n}` },
      h(
        "header",
        { class: "turn-head" },
        h("span", { class: "who" }, icon("bot", 14), `Turn ${turn.n}`),
        end === "finish" ? h("span", { class: "pill pill-accent" }, "finish") : end === "handoff" ? h("span", { class: "pill" }, "handoff") : null,
        h(
          "span",
          { class: "turn-meta" },
          turn.tokens
            ? h("span", { "data-tip": "Input tokens (cached) · output tokens", "data-tip-pos": "below" }, icon("tokens", 12), h("b", null, tokens(t.in)), t.cached ? h("span", null, `(${tokens(t.cached)} cached)`) : null, "·", h("b", null, tokens(t.out)))
            : null,
          turn.cost_usd !== undefined && turn.cost_usd !== null ? h("span", { "data-tip": "Cost of this call", "data-tip-pos": "below" }, icon("coin", 12), h("b", null, usd(turn.cost_usd))) : null,
          turn.latency_ms !== undefined && turn.latency_ms !== null ? h("span", { "data-tip": "Model latency", "data-tip-pos": "left" }, icon("clock", 12), h("b", null, ms(turn.latency_ms))) : null
        )
      ),
      h(
        "div",
        { class: "turn-body" },
        turn.error
          ? h("div", { class: "error-box" }, h("b", null, "The model call failed"), turn.error)
          : turn.text
            ? h("p", { class: "turn-text" }, turn.text)
            : h("p", { class: "turn-text notext" }, "No text: tool calls only."),
        (turn.tool_calls || []).map((c, i) => renderCall(turn, c, i, run)),
        image && image.url
          ? h(
              "figure",
              { class: "turn-image" },
              h("button", { class: "checker checker-sm", type: "button", "aria-label": "Enlarge the image the model saw", onClick: () => lightbox(image.url, `Shown to the model after turn ${turn.n}`) }, h("img", { src: image.url, alt: `Image shown to the model: ${imgFile}`, loading: "lazy" })),
              h(
                "figcaption",
                null,
                h("b", null, "Image shown to the model"),
                h("br"),
                "Sent as a user message after the tool results (tool messages cannot carry images), downscaled to 768 px.",
                h("br"),
                h("span", { class: "mono" }, imgFile)
              )
            )
          : null,
        turn.model || turn.request_sha256 || turn.finish_reason
          ? h(
              "div",
              { class: "turn-foot" },
              turn.model ? h("span", { class: "mono" }, turn.model) : null,
              turn.finish_reason ? h("span", null, "· " + turn.finish_reason) : null,
              turn.request_sha256 ? h("span", { class: "mono", title: turn.request_sha256 }, "· req " + String(turn.request_sha256).slice(0, 10)) : null
            )
          : null
      )
    )
  );
  return card;
}

function stat(label, value, unit, sub) {
  return h("div", { class: "stat" }, h("div", { class: "stat-label" }, label), h("div", { class: "stat-value" }, value, unit ? h("small", null, unit) : null), sub ? h("div", { class: "stat-sub" }, sub) : null);
}

let pendingTimer = null;

export function renderTrace(host, run, opts = {}) {
  const nearBottom = host.scrollHeight - host.scrollTop - host.clientHeight < 80;
  const prevTop = host.scrollTop;
  clear(host);
  if (pendingTimer) {
    clearInterval(pendingTimer);
    pendingTimer = null;
  }
  const turns = run.turns || [];
  const live = run.status === "running" || run.status === "queued";
  const res = run.result;
  const totIn = turns.reduce((a, t) => a + ((t.tokens && t.tokens.in) || 0), 0);
  const totCached = turns.reduce((a, t) => a + ((t.tokens && t.tokens.cached) || 0), 0);
  const totOut = turns.reduce((a, t) => a + ((t.tokens && t.tokens.out) || 0), 0);
  const turnCost = turns.reduce((a, t) => a + (t.cost_usd || 0), 0);
  const totalCost = res ? res.cost_usd : turnCost;
  const totLatency = turns.reduce((a, t) => a + (t.latency_ms || 0), 0);
  const scripted = turns.some((t) => t.model === "demo-script");
  const modelName = (run.model || "").replace(/^xai:/, "");
  const ended = turns.length ? endKind(turns[turns.length - 1]) : null;

  const inner = h("div", { class: "trace-inner" });
  inner.append(
    h(
      "div",
      { class: "trace-head" },
      h(
        "div",
        null,
        h("h2", null, "Agent trace"),
        h(
          "p",
          null,
          scripted
            ? "Scripted demo model over the real tools: tool results, fixes and the outcome are real; tokens are scripted, cost is at grok-4.3 prices, and nothing is charged."
            : `${modelName || "Model"} with tools. Every call is logged to log.jsonl before its result is used.`
        )
      ),
      res ? h("div", { style: { display: "grid", justifyItems: "end", gap: "4px" } }, outcomeChip(res.outcome), h("span", { class: "hint" }, "computed by the rules, not the model")) : live ? h("span", { class: "pill pill-accent" }, h("span", { class: "spinner", style: { width: "10px", height: "10px" } }), "live") : null
    )
  );
  inner.append(
    h(
      "div",
      { class: "trace-stats" },
      stat("Turns", String(turns.length), live ? null : "of 8", ended === "handoff" ? "ended in handoff" : ended === "finish" ? "ended in finish" : live ? "streaming" : ""),
      stat("Input tokens", tokens(totIn), null, totCached ? `${tokens(totCached)} cached (${Math.round((totCached / Math.max(1, totIn)) * 100)}%)` : "no cache hits"),
      stat("Output tokens", tokens(totOut)),
      stat("Cost", usd(totalCost), null, res && Math.abs(totalCost - turnCost) > 1e-7 ? `turns ${usd(turnCost)} + text check` : scripted ? "simulated, not charged" : ""),
      stat("Model time", ms(totLatency), null, run.duration_ms ? `${ms(run.duration_ms)} wall clock` : "")
    )
  );
  if (turns.length) {
    const maxLatency = Math.max(...turns.map((t) => t.latency_ms || 0), 1);
    inner.append(
      h(
        "div",
        { class: "waterfall", role: "group", "aria-label": "Latency per turn" },
        turns.map((t) =>
          h(
            "button",
            {
              type: "button",
              style: { flexGrow: String(Math.max(t.latency_ms || 0, maxLatency * 0.04)) },
              "data-kind": endKind(t) ? "end" : null,
              "aria-label": `Turn ${t.n}: ${ms(t.latency_ms)}`,
              "data-tip": `Turn ${t.n} · ${ms(t.latency_ms)} · ${(t.tool_calls || []).map((c) => c.name).join(", ") || "no tools"}`,
              onClick: () => {
                const el = host.querySelector(`#turn-${t.n}`);
                if (el) {
                  el.scrollIntoView({ behavior: "smooth", block: "center" });
                  el.classList.add("highlight");
                  setTimeout(() => el.classList.remove("highlight"), 1200);
                }
              },
            },
            t.n
          )
        )
      ),
      h("div", { class: "waterfall-legend" }, h("span", null, "Latency per turn"), h("span", null, `${ms(totLatency)} total`))
    );
  }
  const list = h("ol", { class: "turns" });
  if (!turns.length && !live) {
    list.append(h("li", { class: "turn system" }, h("div", { class: "turn-n" }, "–"), h("div", { class: "turn-card" }, h("div", { class: "turn-body" }, h("p", { class: "turn-text notext" }, run.status === "error" ? "The run failed before the model answered." : "No turns were recorded for this run.")))));
  }
  turns.forEach((t, i) => list.append(renderTurn(t, run, i === turns.length - 1)));
  if (live) {
    const since = h("span", { class: "mono" }, "");
    const started = Date.now();
    list.append(
      h(
        "li",
        { class: "turn pending" },
        h("div", { class: "turn-n" }, turns.length + 1),
        h("div", { class: "turn-card" }, h("div", { class: "turn-body" }, dots(), h("span", null, turns.length ? "Running the tools and waiting for the model" : "Sending the order, the check report and the image to the model"), since))
      )
    );
    pendingTimer = setInterval(() => {
      if (!since.isConnected) {
        clearInterval(pendingTimer);
        pendingTimer = null;
        return;
      }
      since.textContent = `${((Date.now() - started) / 1000).toFixed(1)} s`;
    }, 200);
  } else if (res) {
    const meta = OUTCOMES[res.outcome];
    list.append(
      h(
        "li",
        { class: "turn system" },
        h("div", { class: "turn-n" }, icon("flag", 14)),
        h(
          "div",
          { class: "turn-card" },
          h(
            "div",
            { class: "turn-body" },
            h(
              "p",
              { class: "turn-text" },
              h("b", null, `Outcome: ${meta ? meta.label : res.outcome}. `),
              res.handoff_reason ? `The agent handed off (${res.handoff_reason}). ` : "",
              "The outcome rule ran on the final checks",
              (res.after && res.after.findings || []).some((f) => f.check === "text_garbled") ? ", the text check, " : " ",
              "and whether the run handed off."
            )
          )
        )
      )
    );
  }
  inner.append(list);
  host.append(inner);
  if (opts.live !== false && live && nearBottom) host.scrollTop = host.scrollHeight;
  else host.scrollTop = prevTop;
}
