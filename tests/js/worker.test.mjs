// Unit tests for the corrections-form Worker (src/worker/index.js). Uses Node's built-in
// Request/FormData and an in-memory stand-in for the KV namespace.
import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { handleReport, validate } from "../../src/worker/index.js";

const ITEM = "tx/localities/harris-county/elections/2026-11-03/county-judge/candidates/letitia-plummer#R-01";
function kv() {
  const store = new Map();
  return { store, put: async (k, v) => { store.set(k, v); } };
}
function post(fields, headers = {}) {
  const body = new URLSearchParams(fields).toString();
  return new Request("https://example.org/api/report", {
    method: "POST", body,
    headers: { "Content-Type": "application/x-www-form-urlencoded", "Content-Length": String(body.length), ...headers },
  });
}

test("a valid report is stored privately with only the submitted fields and a timestamp", async () => {
  const env = { REPORTS: kv() };
  const res = await handleReport(post({ item: ITEM, problem: "The vote count here looks wrong.", source: "https://example.gov/minutes.pdf", contact: "me@example.com", website: "" }), env, new Date("2026-09-30T12:00:00Z"));
  assert.equal(res.status, 303);
  assert.equal(res.headers.get("Location"), "/report/thanks/");
  const [[key, value]] = [...env.REPORTS.store];
  assert.match(key, /^report:2026-09-30T12:00:00\.000Z:[0-9a-f]{8}$/);
  assert.deepEqual(JSON.parse(value), { received: "2026-09-30T12:00:00.000Z", item: ITEM,
    problem: "The vote count here looks wrong.", source: "https://example.gov/minutes.pdf", contact: "me@example.com" });
});

test("contact, source, and item are optional", async () => {
  const env = { REPORTS: kv() };
  const res = await handleReport(post({ problem: "A date on the home page is wrong." }), env);
  assert.equal(res.headers.get("Location"), "/report/thanks/");
  assert.equal(env.REPORTS.store.size, 1);
});

test("rejects missing or oversized text, bad IDs and bad links, without storing", async () => {
  for (const [fields, reason] of [
    [{ problem: "short" }, "missing-problem"],
    [{ problem: "x".repeat(3001) }, "too-long"],
    [{ problem: "Something is wrong here.", item: "not-an-id" }, "bad-item"],
    [{ problem: "Something is wrong here.", source: "javascript:alert(1)" }, "bad-source"],
  ]) {
    const env = { REPORTS: kv() };
    const res = await handleReport(post(fields), env);
    assert.equal(res.headers.get("Location"), `/report/error/?reason=${reason}`, reason);
    assert.equal(env.REPORTS.store.size, 0, reason);
  }
});

test("honeypot submissions look successful but are not stored", async () => {
  const env = { REPORTS: kv() };
  const res = await handleReport(post({ problem: "Buy cheap watches now!!!", website: "http://spam.example" }), env);
  assert.equal(res.headers.get("Location"), "/report/thanks/");
  assert.equal(env.REPORTS.store.size, 0);
});

test("only accepts form posts under 8 KB", async () => {
  const env = { REPORTS: kv() };
  const json = new Request("https://example.org/api/report", { method: "POST", body: "{}", headers: { "Content-Type": "application/json" } });
  assert.equal((await handleReport(json, env)).headers.get("Location"), "/report/error/?reason=format");
  const big = post({ problem: "x".repeat(20) }, { "Content-Length": "9000" });
  assert.equal((await handleReport(big, env)).headers.get("Location"), "/report/error/?reason=too-long");
});

test("routes: GET /api/report is refused; everything else goes to the static site", async () => {
  const env = { REPORTS: kv(), ASSETS: { fetch: async (req) => new Response("static:" + new URL(req.url).pathname) } };
  assert.equal((await worker.fetch(new Request("https://example.org/api/report"), env)).status, 405);
  assert.equal(await (await worker.fetch(new Request("https://example.org/report/"), env)).text(), "static:/report/");
});

test("validate never reads fields other than the form's own", () => {
  const form = new URLSearchParams({ problem: "A long enough problem.", extra: "ignored" });
  assert.deepEqual(Object.keys(validate(form).report).sort(), ["contact", "item", "problem", "source"]);
});

test("without the REPORTS binding, reports go to the 'unavailable' error page", async () => {
  const body = new URLSearchParams({ problem: "This vote count looks wrong." });
  const req = new Request("https://x.test/api/report", { method: "POST", body,
    headers: { "Content-Type": "application/x-www-form-urlencoded" } });
  const res = await handleReport(req, {});
  assert.equal(res.status, 303);
  assert.equal(res.headers.get("Location"), "/report/error/?reason=unavailable");
});
