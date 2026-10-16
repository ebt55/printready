"""Static report.html per image: one self-contained page (images inline as data URLs) with
before | after, findings table, fix timeline with the damage-guard numbers, customer message and
person notes. The workbench is the real UI; this page is the file you can email or archive."""

from __future__ import annotations

import base64
import io
from html import escape

from PIL import Image

from printready.types import RunResult

MAX_IMAGE_PX = 760
OUTCOME_LABELS = {"ready": "Ready", "fixable": "Fixable", "needs_person": "Needs a person"}

CSS = """
:root{--paper:#fbfaf7;--ink:#17161a;--muted:#6b6873;--line:#e4e1da;--card:#fff;--accent:#c4006b;
--pass:#1f7a3f;--warn:#a35f00;--fail:#b3261e;--skip:#7a7780;--ready:#1f7a3f;--fixable:#c4006b;--needs_person:#a35f00}
@media (prefers-color-scheme:dark){:root{--paper:#141318;--ink:#ecebef;--muted:#a19fa8;--line:#2c2a33;--card:#1c1b21;
--accent:#ff5cae;--pass:#5cc785;--warn:#f0a43a;--fail:#ff7b70;--skip:#a19fa8;--ready:#5cc785;--fixable:#ff5cae;--needs_person:#f0a43a}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:15px/1.5 "Segoe UI Variable","Segoe UI",-apple-system,BlinkMacSystemFont,Inter,Roboto,system-ui,sans-serif}
main{max-width:1120px;margin:0 auto;padding:32px 24px 48px}
header{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;border-bottom:1px solid var(--line);padding-bottom:16px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:32px 0 12px}
.sub{color:var(--muted)}.brand{color:var(--accent);font-weight:600;letter-spacing:.02em}
.outcome{padding:8px 16px;border-radius:999px;color:#fff;font-weight:600;white-space:nowrap}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:24px}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
figure img{width:100%;height:auto;display:block;border-radius:6px}figcaption{color:var(--muted);font-size:13px;margin-top:8px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.05em}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}code{font:13px ui-monospace,Consolas,monospace}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid currentColor}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px}
ol.timeline{list-style:none;margin:0;padding:0}ol.timeline li{display:grid;grid-template-columns:150px 90px 1fr;gap:12px;
padding:10px 0;border-bottom:1px solid var(--line)}ol.timeline li:last-child{border-bottom:0}
.bar{height:6px;border-radius:3px;background:var(--line);margin-top:6px;max-width:260px;position:relative}
.bar span{position:absolute;left:0;top:0;bottom:0;border-radius:3px}
footer{margin-top:40px;color:var(--muted);font-size:12px}
@media (max-width:760px){.pair{grid-template-columns:1fr}ol.timeline li{grid-template-columns:1fr}}
"""


def _data_url(img: Image.Image) -> str:
    img = img.copy()
    img.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _chip(status: str) -> str:
    return f'<span class="chip" style="color:var(--{escape(status)})">{escape(status)}</span>'


def _figure(img: Image.Image | None, caption: str) -> str:
    if img is None:
        return f'<figure><figcaption>{escape(caption)}: not available</figcaption></figure>'
    return f'<figure><img alt="{escape(caption)}" src="{_data_url(img)}"><figcaption>{escape(caption)}</figcaption></figure>'


def _guard(guard: dict) -> str:
    if not guard:
        return ""
    value, limit = float(guard.get("value", 0)), float(guard.get("limit", 0))
    colour = "var(--pass)" if guard.get("passed") else "var(--fail)"
    width = 100.0 if limit <= 0 and value > 0 else (0.0 if limit <= 0 else min(100.0, 100.0 * value / (2 * limit)))
    return (
        f'<div class="sub">guard: {escape(str(guard.get("label", "")))} {value:g} (limit {limit:g})</div>'
        f'<div class="bar" title="limit at the midpoint"><span style="width:{width:.1f}%;background:{colour}"></span></div>'
    )


def report_html(run: RunResult, images: dict[str, Image.Image]) -> str:
    """One self-contained HTML page for a RunResult; `images` may hold "before" and "after"."""
    name = run.art.meta.get("path", "") if run.art is not None else ""
    name = escape(name.replace("\\", "/").rsplit("/", 1)[-1]) if name else "artwork"
    spec = run.spec
    title = f"{spec.size_in:g} in die-cut sticker" if spec else "die-cut sticker"
    outcome = run.outcome
    before = {f.check: f for f in run.before.findings}
    rows = []
    for f in run.after.findings:
        b = before.get(f.check)
        fixer = escape(f.fixer) if f.status in ("warn", "fail") else ""
        rows.append(
            f"<tr><td><code>{escape(f.check)}</code></td><td>{_chip(b.status) if b else ''}</td>"
            f"<td>{_chip(f.status)}</td><td>{escape(f.message)}</td><td>{fixer}</td></tr>"
        )
    steps = []
    for s in run.art.history if run.art is not None else []:
        state = "reverted" if s.damaged else ("applied" if s.ok else "refused")
        colour = {"applied": "pass", "refused": "warn", "reverted": "fail"}[state]
        steps.append(
            f'<li><code>{escape(s.fix)}</code><span class="chip" style="color:var(--{colour})">{state}</span>'
            f"<div>{escape(s.note)}{_guard(s.guard)}</div></li>"
        )
    notes = "".join(f"<li>{escape(n)}</li>" for n in run.person_notes)
    cost = f" &middot; ${run.cost_usd:.4f}" if run.cost_usd else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}: {escape(OUTCOME_LABELS[outcome])}</title><style>{CSS}</style></head>
<body><main>
<header><div><div class="brand">printready</div><h1>{name}</h1>
<div class="sub">{escape(title)} &middot; {escape(run.mode)} mode &middot; {run.elapsed_s:.1f} s{cost}</div></div>
<div class="outcome" style="background:var(--{outcome})">{escape(OUTCOME_LABELS[outcome])}</div></header>
<div class="pair">{_figure(images.get("before"), "Before, with findings")}{_figure(images.get("after"), "After: proof with cut line")}</div>
<h2>Findings</h2>
<table><thead><tr><th>Check</th><th>Before</th><th>After</th><th>Finding</th><th>Fixer</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<h2>Fix timeline</h2>
<div class="card">{'<ol class="timeline">' + ''.join(steps) + '</ol>' if steps else '<span class="sub">No fixes were applied.</span>'}</div>
<h2>Message to the customer</h2>
<div class="card">{escape(run.customer_message)}</div>
{f'<h2>Notes for a person</h2><div class="card"><ul>{notes}</ul></div>' if notes else ''}
<footer>Rules paraphrased from Sticker Mule's public FAQ. Not affiliated with Sticker Mule.</footer>
</main></body></html>
"""
