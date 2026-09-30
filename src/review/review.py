"""Local review page for the project owner: verify facts and mappings with one click.

Usage:  python src/review/review.py            (opens http://127.0.0.1:8765 in your browser)
        python src/review/review.py --no-browser --port 8765

Only the owner runs this (CLAUDE.md rule 3a). It serves on 127.0.0.1 only, requires a
per-session token on every change, edits nothing but the three verification lines of the
item you confirm, and runs the validator after every change (undoing the edit if it fails).
Your reviewer name is saved in .reviewer at the repo root, which is not committed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src" / "validate"))
import yaml  # noqa: E402
from validate import _NoDateLoader, classify, iter_facts, validate  # noqa: E402

VERIFY_KEYS = ("verification", "verified_on", "reviewer")


# ---------- reading ----------

def load_items(root: Path) -> list[dict]:
    """Every item that carries verification fields, in file order."""
    items = []
    for file in sorted((root / "data").rglob("*.yaml")):
        rel = file.relative_to(root).as_posix()
        kind = classify(rel)
        if kind not in ("candidate", "actions", "voter_essentials"):
            continue
        doc = yaml.load(file.read_text(encoding="utf-8"), Loader=_NoDateLoader) or {}
        who = doc.get("name") or doc.get("body") or f"{doc.get('state', '')} voter essentials"
        records = {r["id"]: r for r in doc.get("records") or []}
        for section, fact in iter_facts(kind, doc):
            items.append({
                "type": "fact", "file": rel, "who": who, "section": section, "key": fact["id"],
                "local_id": fact["id"].split("#")[-1],
                "text": fact.get("statement") or _essential_text(fact),
                "headline": fact.get("headline"),
                "label": fact.get("label"), "status": fact.get("claim_status"),
                "source_url": fact.get("source_url"), "source_title": fact.get("source_title"),
                "archive_url": fact.get("archive_url"),
                "verification": fact.get("verification"), "verified_on": fact.get("verified_on"),
                "reviewer": fact.get("reviewer"), "blocked": blocked_reason(fact),
            })
        for m in doc.get("mappings") or []:
            record = records.get(m["record"], {})
            items.append({
                "type": "mapping", "file": rel, "who": who, "section": "mappings",
                "key": f"{m['record']}|{m['question']}",
                "local_id": f"{m['record'].split('#')[-1]} -> {m['question']}",
                "text": record.get("statement", m["record"]),
                "question": m["question"], "options": m["options"], "rationale": m["rationale"],
                "source_url": record.get("source_url"), "source_title": record.get("source_title"),
                "archive_url": record.get("archive_url"),
                "verification": m.get("verification"), "verified_on": m.get("verified_on"),
                "reviewer": m.get("reviewer"), "blocked": None,
            })
    return items


def _essential_text(item: dict) -> str:
    when = item.get("date") or f"{item.get('start')} to {item.get('end')}"
    return f"{item.get('name')}: {when}"


def blocked_reason(fact: dict, today: str | None = None) -> str | None:
    """Why a fact can't be verified yet (mirrors the validator's rules), or None."""
    today = today or dt.date.today().isoformat()
    if not fact.get("archive_url"):
        return "No archived copy yet (archive_url is empty)."
    if fact.get("source_kind") == "document" and not fact.get("sha256"):
        return "Document has no SHA-256 fingerprint."
    if not fact.get("retrieved"):
        return "No retrieved date."
    if fact["retrieved"] > today:
        return f"Retrieved date {fact['retrieved']} is after today."
    return None


# ---------- writing ----------

def _block_span(lines: list[str], item_type: str, key: str) -> tuple[int, int, int]:
    """(start, end, key_indent) of the list item for this fact or mapping.

    Finds the item's identifying line (id: for facts, record: + question: for mappings),
    wherever it sits in the item, then walks up to the item's "- " line.
    """
    field, value = ("id", key) if item_type == "fact" else ("record", key.split("|")[0])
    question = None if item_type == "fact" else key.split("|")[1]
    pattern = re.compile(r"^(\s*)(-\s+)?" + field + r":\s*['\"]?" + re.escape(value) + r"['\"]?\s*$")
    # The same key with its value wrapped onto the next line ("id: >-" then the ID).
    wrapped = re.compile(r"^(\s*)(-\s+)?" + field + r":\s*[>|][-+]?\s*$")
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            m = wrapped.match(line)
            if not (m and i + 1 < len(lines) and lines[i + 1].strip().strip("'\"") == value):
                continue
        key_indent = len(m.group(1)) + (len(m.group(2)) if m.group(2) else 0)
        dash = key_indent - 2
        start = i
        while start >= 0 and not (lines[start][dash:dash + 2] == "- " and not lines[start][:dash].strip()):
            start -= 1
        if start < 0:
            continue
        end = start + 1
        while end < len(lines):
            nxt = lines[end]
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= dash:
                break
            end += 1
        if question and not any(re.match(r"^\s*question:\s*['\"]?" + re.escape(question) + r"['\"]?\s*$", l)
                                for l in lines[start:end]):
            continue
        return start, end, key_indent
    raise LookupError(f"Could not find {item_type} {key}")


def set_verification(path: Path, item_type: str, key: str, verified: bool,
                     reviewer: str | None = None, today: str | None = None) -> None:
    """Rewrite only the three verification lines of one item, in place."""
    today = today or dt.date.today().isoformat()
    lines = path.read_text(encoding="utf-8").split("\n")
    start, end, key_indent = _block_span(lines, item_type, key)
    values = {
        "verification": "verified" if verified else "unverified",
        "verified_on": json.dumps(today) if verified else "null",
        "reviewer": json.dumps(reviewer) if verified else "null",
    }
    found = set()
    for i in range(start, end):
        for k in VERIFY_KEYS:
            if re.match(rf"^\s{{{key_indent}}}{k}:", lines[i]) and not lines[i][key_indent].isspace():
                lines[i] = " " * key_indent + f"{k}: {values[k]}"
                found.add(k)
    if found != set(VERIFY_KEYS):
        raise ValueError(f"{key}: expected its own {', '.join(VERIFY_KEYS)} lines; found {sorted(found)}")
    path.write_text("\n".join(lines), encoding="utf-8")


def apply(root: Path, item_type: str, file: str, key: str, verified: bool, reviewer: str) -> str | None:
    """Change one item and validate the repo; restore the file if validation fails."""
    path = (root / file).resolve()
    if not path.is_relative_to((root / "data").resolve()):
        return "Only files under data/ can be changed."
    if verified and item_type == "fact":
        item = next((i for i in load_items(root) if i["key"] == key and i["file"] == file), None)
        if item is None:
            return "Item not found."
        if item["blocked"]:
            return item["blocked"]
    before = path.read_text(encoding="utf-8")
    try:
        set_verification(path, item_type, key, verified, reviewer)
    except (LookupError, ValueError) as exc:
        return str(exc)
    errors = [e for e in validate(root).errors if e.startswith(file)]
    if errors:
        path.write_text(before, encoding="utf-8")
        return "The checker rejected this change, so it was undone:\n" + "\n".join(errors)
    return None


# ---------- web page ----------

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Review · Vote the Record</title>
<style>
body{font:16px/1.5 system-ui,sans-serif;margin:0;background:#f2f5f4;color:#1b2a2f}
main{max-width:860px;margin:0 auto;padding:16px}
h1{font-size:1.5rem}h2{font-size:1.1rem;margin:1.6em 0 .4em}
.card{background:#fff;border:1px solid #c7d1cf;border-radius:6px;padding:12px 14px;margin:10px 0}
.card.verified{border-color:#2e7d32;background:#f1f8f1}
.meta{color:#4d5e63;font-size:.9rem}.why{color:#704800;font-size:.9rem}
.row{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-top:8px}
button{font:inherit;font-weight:600;border:0;border-radius:4px;padding:8px 14px;cursor:pointer}
.ok{background:#0f5c63;color:#fff}.undo{background:#fff;color:#0f5c63;border:1px solid #687a7f}
button:disabled{background:#c7d1cf;color:#4d5e63;cursor:not-allowed}
.badge{font-size:.8rem;font-weight:600;border:1px solid currentColor;border-radius:3px;padding:0 6px}
.u{color:#704800;background:#fff3d6}.v{color:#2e7d32}
.bar{position:sticky;top:0;background:#f2f5f4;padding:8px 0;border-bottom:1px solid #c7d1cf}
label{font-weight:600}input{font:inherit;padding:4px 8px}
</style></head><body><main>
<h1>Review and verify</h1>
<div class="bar"><label>Your name as reviewer: <input id="name" value="__NAME__"></label>
 <button class="undo" id="savename">Save name</button> <span id="count" class="meta"></span>
 <label class="meta"><input type="checkbox" id="hide"> Hide verified</label></div>
<div id="list"></div></main>
<script>
const TOKEN = "__TOKEN__";
let items = [];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function load(){ items = await (await fetch("/api/items")).json(); render(); }
function render(){
  const hide = document.getElementById("hide").checked;
  const todo = items.filter(i => i.verification !== "verified").length;
  document.getElementById("count").textContent = `${todo} of ${items.length} still unverified`;
  let out = "", last = "";
  items.forEach((it, n) => {
    const done = it.verification === "verified";
    if (hide && done) return;
    const group = it.who + " · " + it.file.split("/").slice(-1)[0];
    if (group !== last) { out += `<h2>${esc(group)}</h2>`; last = group; }
    out += `<div class="card ${done ? "verified" : ""}">
      <div class="meta">${esc(it.section)} · ${esc(it.local_id)} · ${done
        ? `<span class="badge v">Verified ${esc(it.verified_on)} by ${esc(it.reviewer)}</span>`
        : `<span class="badge u">Unverified</span>`}</div>
      ${it.headline ? `<p><strong>Short version shown first:</strong> ${esc(it.headline)}</p><p class="meta">Full statement:</p>` : ""}
      <p>${it.type === "mapping" ? "<strong>Question link.</strong> " : ""}${esc(it.text)}</p>
      ${it.type === "mapping" ? `<p class="meta">Question ${esc(it.question)} · supports option(s) ${esc(it.options.join(", "))}<br>Why: ${esc(it.rationale)}</p>` : `<p class="meta">${esc(it.label)} · ${esc(it.status)}</p>`}
      <div class="row">
        ${it.source_url ? `<a href="${esc(it.source_url)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>` : ""}
        ${it.archive_url ? `<a href="${esc(it.archive_url)}" target="_blank" rel="noopener noreferrer">Open archived copy ↗</a>` : ""}
        ${done ? `<button class="undo" data-n="${n}" data-v="0">Undo</button>`
               : `<button class="ok" data-n="${n}" data-v="1" ${it.blocked ? "disabled" : ""}>✓ Mark verified</button>`}
      </div>${!done && it.blocked ? `<p class="why">Can't verify yet: ${esc(it.blocked)}</p>` : ""}</div>`;
  });
  document.getElementById("list").innerHTML = out;
}
document.getElementById("list").addEventListener("click", async e => {
  const b = e.target.closest("button[data-n]"); if (!b) return;
  const it = items[+b.dataset.n], verify = b.dataset.v === "1";
  const name = document.getElementById("name").value.trim();
  if (verify && !name) { alert("Enter your name as reviewer first."); return; }
  const today = new Date().toLocaleDateString("en-CA");
  const msg = verify ? `Mark ${it.local_id} as verified by ${name} on ${today}?\\n\\nOnly confirm if you checked it against the source.`
                     : `Undo verification of ${it.local_id}? It will show as Unverified again.`;
  if (!confirm(msg)) return;
  b.disabled = true;
  const r = await fetch("/api/set", {method: "POST", headers: {"Content-Type": "application/json", "X-Review-Token": TOKEN},
    body: JSON.stringify({type: it.type, file: it.file, key: it.key, verified: verify, reviewer: name})});
  const res = await r.json();
  if (!res.ok) alert(res.error);
  await load();
});
document.getElementById("savename").addEventListener("click", async () => {
  await fetch("/api/reviewer", {method: "POST", headers: {"Content-Type": "application/json", "X-Review-Token": TOKEN},
    body: JSON.stringify({reviewer: document.getElementById("name").value.trim()})});
  alert("Saved.");
});
document.getElementById("hide").addEventListener("change", render);
load();
</script></body></html>"""


def make_handler(root: Path, token: str, name_file: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            if self.path == "/":
                name = name_file.read_text(encoding="utf-8").strip() if name_file.exists() else ""
                page = PAGE.replace("__TOKEN__", token).replace("__NAME__", html.escape(name, quote=True))
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if self.path == "/api/items":
                return self._send(200, json.dumps(load_items(root)).encode("utf-8"), "application/json")
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-Review-Token") != token:
                return self._send(403, b'{"ok":false,"error":"forbidden"}', "application/json")
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/api/reviewer":
                name_file.write_text(body.get("reviewer", "").strip() + "\n", encoding="utf-8")
                return self._send(200, b'{"ok":true}', "application/json")
            if self.path == "/api/set":
                reviewer = (body.get("reviewer") or "").strip()
                if body.get("verified") and not reviewer:
                    error = "Enter your name as reviewer first."
                else:
                    error = apply(root, body["type"], body["file"], body["key"], bool(body["verified"]), reviewer)
                if not error and reviewer:
                    name_file.write_text(reviewer + "\n", encoding="utf-8")
                result = {"ok": error is None, "error": error}
                return self._send(200, json.dumps(result).encode("utf-8"), "application/json")
            self._send(404, b'{"ok":false}', "application/json")

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local review page for verifying facts.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--root", type=Path, default=REPO)
    args = parser.parse_args(argv)
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                 make_handler(args.root.resolve(), token, REPO / ".reviewer"))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Review page: {url}\nPress Ctrl+C here to stop.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
