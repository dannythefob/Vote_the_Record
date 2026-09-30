// Browser check for the demo build: real CSP enforcement, survey behavior, dark mode,
// reduced motion, and phone width. Drives headless Chrome/Edge over the DevTools protocol
// using only Node built-ins (http, fetch, WebSocket). No npm packages.
//
// Usage: node tests/browser/survey_check.mjs <dist-dir> <browser-executable>
// Prints a JSON report; exits 1 if any check fails.
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";

const [distDir, browserPath] = process.argv.slice(2);
const RACE = "/races/tx/demo-county/2026-11-03/commissioner-precinct-9/";
const BALLOT = "/ballot/tx/demo-county/2026-11-03/";
const TYPES = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
                ".woff2": "font/woff2", ".txt": "text/plain" };

// Static server that applies the "/*" block of _headers, like Cloudflare Pages does.
function headersFromFile() {
  const lines = fs.readFileSync(path.join(distDir, "_headers"), "utf-8").split(/\r?\n/);
  const headers = {};
  let inRoot = false;
  for (const line of lines) {
    if (!line.trim()) continue;
    if (!/^\s/.test(line)) { inRoot = line.trim() === "/*"; continue; }
    if (inRoot) { const i = line.indexOf(":"); headers[line.slice(0, i).trim()] = line.slice(i + 1).trim(); }
  }
  return headers;
}

function startServer() {
  const extra = headersFromFile();
  const server = http.createServer((req, res) => {
    let file = path.join(distDir, decodeURIComponent(new URL(req.url, "http://x").pathname));
    if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, "index.html");
    if (!fs.existsSync(file)) { res.writeHead(404, extra); res.end("not found"); return; }
    res.writeHead(200, { ...extra, "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
    res.end(fs.readFileSync(file));
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

async function launchBrowser() {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "vtr-browser-"));
  const proc = spawn(browserPath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
    "--no-first-run", "--no-default-browser-check", "--disable-extensions", "about:blank"], { stdio: "ignore" });
  const portFile = path.join(profile, "DevToolsActivePort");
  for (let i = 0; i < 100 && !fs.existsSync(portFile); i++) await new Promise((r) => setTimeout(r, 100));
  const port = fs.readFileSync(portFile, "utf-8").split("\n")[0].trim();
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = targets.find((t) => t.type === "page");
  return { proc, profile, wsUrl: page.webSocketDebuggerUrl };
}

function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let id = 0;
  const pending = new Map();
  const listeners = [];
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    } else if (msg.method) {
      listeners.forEach((fn) => fn(msg));
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    id += 1;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
  return new Promise((resolve) => { ws.onopen = () => resolve({ ws, send, on: (fn) => listeners.push(fn) }); });
}

async function main() {
  const server = await startServer();
  const origin = `http://127.0.0.1:${server.address().port}`;
  const { proc, profile, wsUrl } = await launchBrowser();
  const cdp = await connect(wsUrl);
  const problems = { cspViolations: [], consoleErrors: [], offsiteRequests: [] };
  cdp.on((msg) => {
    if (msg.method === "Log.entryAdded" && msg.params.entry.level === "error") {
      problems.consoleErrors.push(msg.params.entry.text);
    }
    if (msg.method === "Runtime.exceptionThrown") {
      problems.consoleErrors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
    }
    if (msg.method === "Network.requestWillBeSent") {
      const url = msg.params.request.url;
      if (!url.startsWith(origin) && !url.startsWith("data:") && url !== "about:blank") problems.offsiteRequests.push(url);
    }
  });
  await cdp.send("Log.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Network.enable");
  await cdp.send("Page.enable");
  // Runs before page scripts and outside the page's CSP, so it can record violations.
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source:
    "window.__csp=[];document.addEventListener('securitypolicyviolation',e=>window.__csp.push(e.violatedDirective+' '+e.blockedURI));" });

  const evaluate = async (expression) => {
    const r = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || "evaluate failed");
    return r.result.value;
  };
  const load = async (url) => {
    await cdp.send("Page.navigate", { url: origin + url });
    for (let i = 0; i < 100; i++) {
      if (await evaluate("document.readyState === 'complete' && document.fonts.status === 'loaded'")) break;
      await new Promise((r) => setTimeout(r, 50));
    }
    problems.cspViolations.push(...(await evaluate("window.__csp")).map((v) => `${url}: ${v}`));
  };

  const report = {};
  for (const url of ["/", "/methodology/", "/corrections/", "/about/"]) await load(url);

  await load(RACE);
  report.survey = await evaluate(`(async () => {
    const pick = (q, opt, imp) => {
      document.querySelector('input[name="answer-county-commissioner/' + q + '"][value="' + opt + '"]').click();
      document.querySelector('input[name="importance-county-commissioner/' + q + '"][value="' + imp + '"]').click();
    };
    pick('S-01', 'B', 3); pick('S-02', 'A', 2); pick('S-03', 'B', 2); pick('S-04', 'A', 2);
    document.querySelector('#survey-form button[type=submit]').click();
    await new Promise(r => setTimeout(r, 50));
    const cards = [...document.querySelectorAll('#results .result')];
    return {
      focusedId: document.activeElement.id,
      order: cards.map(c => c.querySelector('h3').textContent),
      text: Object.fromEntries(cards.map(c => [c.querySelector('h3').textContent, c.textContent])),
      meters: cards.map(c => c.querySelector('meter')?.value ?? null),
      unverifiedBadgesInResults: document.querySelectorAll('#results .badge-unverified').length,
      betaBreakdownOpen: cards.map(c => c.querySelector('details')?.open ?? null),
      gridHead: [...document.querySelectorAll('#results .compare-grid thead th')].map(th => th.textContent.trim()),
      gridRows: [...document.querySelectorAll('#results .compare-grid tbody tr')].map(tr =>
        [tr.querySelector('th').firstChild.textContent.trim(), ...[...tr.querySelectorAll('td')].map(td => td.innerText.trim())]),
    };
  })()`);

  // Ballot page ZIP lookup (runs in the page; nothing is sent).
  const visible = `(() => ({
    races: [...document.querySelectorAll('[data-race]:not([hidden]) .ballot-race-name')].map(h => h.textContent.trim()),
    split: [...document.querySelectorAll('[data-race]:not([hidden])')].filter(li => !li.querySelector('.split-chip').hidden)
      .map(li => li.querySelector('.ballot-race-name').textContent.trim()),
    groups: [...document.querySelectorAll('[data-group]:not([hidden]) h2')].map(h => h.textContent.trim()),
    status: document.getElementById('zip-status').textContent,
    formShown: !document.getElementById('zip-form').hidden,
    hash: location.hash,
  }))()`;
  await load(BALLOT);
  report.ballot = { initial: await evaluate(visible) };
  report.ballot.zip22222 = await evaluate(`(async () => {
    document.getElementById('zip').value = '22222';
    document.querySelector('#zip-form button[type=submit]').click();
    await new Promise(r => setTimeout(r, 50));
    return ${visible};
  })()`);
  report.ballot.precinct102 = await evaluate(`(async () => {
    document.getElementById('zip').value = '22222';
    document.getElementById('precinct').value = '0102';
    document.querySelector('#zip-form button[type=submit]').click();
    await new Promise(r => setTimeout(r, 50));
    const out = ${visible};
    document.getElementById('precinct').value = '';
    return out;
  })()`);
  report.ballot.reset = await evaluate(`(async () => {
    document.getElementById('zip-reset').click();
    await new Promise(r => setTimeout(r, 50));
    return ${visible};
  })()`);
  await load("/");
  await evaluate(`(() => {
    document.getElementById('zip-home').value = '11111';
    document.querySelector('#zip-find button[type=submit]').click();
  })()`);
  for (let i = 0; i < 100; i++) {
    if (await evaluate("location.pathname === '" + BALLOT + "' && document.readyState === 'complete'")) break;
    await new Promise((r) => setTimeout(r, 50));
  }
  await new Promise((r) => setTimeout(r, 100));
  problems.cspViolations.push(...(await evaluate("window.__csp")).map((v) => `${BALLOT}: ${v}`));
  report.ballot.fromHome11111 = await evaluate(visible);
  report.ballot.homeUnknown = await (async () => {
    await load("/");
    return evaluate(`(async () => {
      document.getElementById('zip-home').value = '99999';
      document.querySelector('#zip-find button[type=submit]').click();
      await new Promise(r => setTimeout(r, 50));
      return document.getElementById('zip-home-status').textContent;
    })()`);
  })();

  await cdp.send("Emulation.setEmulatedMedia", { features: [
    { name: "prefers-color-scheme", value: "dark" }, { name: "prefers-reduced-motion", value: "reduce" }] });
  report.dark = await evaluate("getComputedStyle(document.body).backgroundColor");
  report.scrollBehaviorReduced = await evaluate("getComputedStyle(document.documentElement).scrollBehavior");
  await cdp.send("Emulation.setEmulatedMedia", { features: [
    { name: "prefers-color-scheme", value: "light" }, { name: "prefers-reduced-motion", value: "no-preference" }] });
  report.light = await evaluate("getComputedStyle(document.body).backgroundColor");

  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 375, height: 800, deviceScaleFactor: 2, mobile: true });
  await load(RACE);
  report.phoneOverflow = await evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth");
  await load(BALLOT);
  report.phoneOverflowBallot = await evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth");

  report.problems = problems;
  cdp.ws.close();
  proc.kill();
  server.close();
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch { /* browser may still hold files */ }
  console.log(JSON.stringify(report, null, 2));
}

main().catch((err) => { console.error(err); process.exit(2); });
