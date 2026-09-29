// Unit tests for site/static/js/score.js. Run: node --test tests/js
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  scoreCandidate, recordWeight, isScorable, MIN_SCORED_QUESTIONS,
} from "../../site/static/js/score.js";

const Q = (n) => ({
  id: `office/S-0${n}`,
  text: `Question ${n}`,
  options: [{ id: "A", text: "A" }, { id: "B", text: "B" }, { id: "C", text: "C" }],
});
const QUESTIONS = [Q(1), Q(2), Q(3), Q(4)];

let seq = 0;
function rec(fields = {}) {
  seq += 1;
  return {
    id: `tx/x/candidates/pat#R-${String(seq).padStart(3, "0")}`,
    record_type: "vote",
    label: "official_record",
    claim_status: "documented",
    verification: "verified",
    same_event: null,
    ...fields,
  };
}
function map(record, question, options, fields = {}) {
  return { record: record.id, question: `office/S-0${question}`, options, rationale: "r",
           verification: "verified", ...fields };
}
function candidate(pairs) {
  return { records: pairs.map(([r]) => r), mappings: pairs.map(([, m]) => m) };
}
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} != ${expected}`);

// ---- The worked example in docs/METHODOLOGY.md ----
function workedExample({ withS03 = true } = {}) {
  const vote = rec({ record_type: "vote", label: "official_record", same_event: "tx/x#event-1" });
  const news = rec({ record_type: "vote", label: "news_report", same_event: "tx/x#event-1" });
  const claim = rec({ record_type: "statement", label: "candidate_claim" });
  const s02 = rec();
  const s03 = rec();
  const pairs = [
    [vote, map(vote, 1, ["B"])],
    [news, map(news, 1, ["A"])],   // same event, lower weight: dropped whatever it maps to
    [claim, map(claim, 1, ["A"])],
    [s02, map(s02, 2, ["A"])],
  ];
  if (withS03) pairs.push([s03, map(s03, 3, ["A"])]);
  const answers = {
    "office/S-01": { option: "B", importance: 3 },
    "office/S-02": { option: "A", importance: 2 },
    "office/S-03": { option: "A", importance: 2 },
    "office/S-04": { option: "A", importance: 2 },
  };
  return scoreCandidate(candidate(pairs), QUESTIONS, answers);
}

test("worked example: S-01 alignment is 3.0 / 3.4 (88%) and the same-event news record is dropped", () => {
  const result = workedExample();
  const s01 = result.questions.find((q) => q.id === "office/S-01");
  close(s01.alignment, 3.0 / 3.4);
  assert.equal(Math.round(s01.alignment * 100), 88);
  const news = s01.items.find((i) => i.record.label === "news_report");
  close(news.weight, 2.1);
  assert.equal(news.counted, false);
  assert.match(news.reason, /Same event/);
});

test("worked example: based on 3 of 4 questions, S-04 excluded rather than scored zero", () => {
  const result = workedExample();
  assert.equal(result.answered, 4);
  assert.equal(result.scored, 3);
  assert.equal(result.questions.find((q) => q.id === "office/S-04").alignment, null);
  // Σ(importance × alignment) ÷ Σ importance over S-01..S-03 only
  close(result.score, (3 * (3 / 3.4) + 2 * 1 + 2 * 1) / (3 + 2 + 2));
  assert.equal(result.percent, Math.round(100 * (3 * (3 / 3.4) + 4) / 7));
});

test("worked example variant: records on only 2 questions gives no percentage", () => {
  const result = workedExample({ withS03: false });
  assert.equal(result.scored, 2);
  assert.equal(result.answered, 4);
  assert.equal(result.percent, null);
  assert.equal(result.score, null);
});

// ---- Weights ----
test("record weight = type weight × evidence factor", () => {
  close(recordWeight(rec({ record_type: "vote", label: "official_record" })), 3);
  close(recordWeight(rec({ record_type: "sponsored", label: "news_report" })), 1.4);
  close(recordWeight(rec({ record_type: "promise_kept", label: "official_record" })), 2);
  close(recordWeight(rec({ record_type: "promise_broken", label: "candidate_claim" })), 0.8);
  close(recordWeight(rec({ record_type: "statement", label: "candidate_claim" })), 0.4);
});

// ---- What counts ----
const threeScored = (extra) => {
  const [a, b, c] = [rec(), rec(), rec()];
  return [[a, map(a, 1, ["A"])], [b, map(b, 2, ["A"])], [c, map(c, 3, ["A"])], ...extra];
};
const allA = {
  "office/S-01": { option: "A", importance: 2 },
  "office/S-02": { option: "A", importance: 2 },
  "office/S-03": { option: "A", importance: 2 },
  "office/S-04": { option: "A", importance: 2 },
};

for (const [name, recordFields, mappingFields] of [
  ["unverified record", { verification: "unverified" }, {}],
  ["unverified mapping", {}, { verification: "unverified" }],
  ["allegation", { claim_status: "allegation" }, {}],
  ["disputed", { claim_status: "disputed" }, {}],
  ["contradicted", { claim_status: "contradicted" }, {}],
]) {
  test(`${name} is shown but never scored`, () => {
    const r = rec(recordFields);
    const m = map(r, 4, ["B"], mappingFields);
    assert.equal(isScorable(r, m), false);
    const result = scoreCandidate(candidate(threeScored([[r, m]])), QUESTIONS, allA);
    const s04 = result.questions.find((q) => q.id === "office/S-04");
    assert.equal(s04.alignment, null);
    assert.equal(s04.items.length, 1);
    assert.equal(s04.items[0].scorable, false);
    assert.ok(s04.items[0].reason);
    assert.equal(result.scored, 3);
    assert.equal(result.percent, 100);
  });
}

test("a mapping can support several options", () => {
  const r = rec();
  const result = scoreCandidate(candidate([[r, map(r, 1, ["A", "C"])]]), QUESTIONS,
    { "office/S-01": { option: "C", importance: 2 } });
  assert.equal(result.questions[0].alignment, 1);
  assert.equal(result.questions[0].items[0].supportsChoice, true);
});

test("importance weights questions: match = Σ(importance × alignment) ÷ Σ importance", () => {
  const result = scoreCandidate(candidate(threeScored([])), QUESTIONS, {
    "office/S-01": { option: "A", importance: 3 },  // alignment 1
    "office/S-02": { option: "B", importance: 1 },  // alignment 0
    "office/S-03": { option: "B", importance: 1 },  // alignment 0
  });
  close(result.score, 3 / 5);
  assert.equal(result.percent, 60);
});

test("unanswered questions are not counted in X or Y", () => {
  const result = scoreCandidate(candidate(threeScored([])), QUESTIONS, {
    "office/S-01": { option: "A", importance: 2 },
    "office/S-02": { option: null, importance: 2 },
  });
  assert.equal(result.answered, 1);
  assert.equal(result.scored, 1);
});

// ---- same_event ----
test("same_event tie on weight: the alphabetically first ID is counted", () => {
  const first = rec({ id: "tx/x#R-A", same_event: "tx/x#e" });
  const second = rec({ id: "tx/x#R-B", same_event: "tx/x#e" });
  const result = scoreCandidate(
    candidate([[second, map(second, 1, ["B"])], [first, map(first, 1, ["A"])]]),
    QUESTIONS, { "office/S-01": { option: "A", importance: 2 } });
  const [a, b] = result.questions[0].items;
  assert.equal(a.record.id, "tx/x#R-A");
  assert.equal(a.counted, true);
  assert.equal(b.counted, false);
  assert.equal(result.questions[0].alignment, 1);
});

test("records in different same_event groups both count", () => {
  const r1 = rec({ same_event: "tx/x#e1" });
  const r2 = rec({ same_event: "tx/x#e2", record_type: "statement" });
  const result = scoreCandidate(candidate([[r1, map(r1, 1, ["A"])], [r2, map(r2, 1, ["B"])]]),
    QUESTIONS, { "office/S-01": { option: "A", importance: 2 } });
  assert.deepEqual(result.questions[0].items.map((i) => i.counted), [true, true]);
  close(result.questions[0].alignment, 3 / 4);
});

test("same_event groups are per question: one event can count on two questions", () => {
  const r = rec({ same_event: "tx/x#e" });
  const result = scoreCandidate(candidate([[r, map(r, 1, ["A"])], [r, map(r, 2, ["A"])]]),
    QUESTIONS, { "office/S-01": { option: "A", importance: 2 }, "office/S-02": { option: "A", importance: 2 } });
  assert.equal(result.scored, 2);
});

test("an unscorable record in a group never displaces a scorable one", () => {
  const official = rec({ same_event: "tx/x#e", verification: "unverified" });
  const news = rec({ same_event: "tx/x#e", label: "news_report" });
  const result = scoreCandidate(candidate([[official, map(official, 1, ["B"])], [news, map(news, 1, ["A"])]]),
    QUESTIONS, { "office/S-01": { option: "A", importance: 2 } });
  assert.equal(result.questions[0].alignment, 1);
});

// ---- Threshold ----
test(`exactly ${MIN_SCORED_QUESTIONS} scored questions shows a percent; ${MIN_SCORED_QUESTIONS - 1} does not`, () => {
  assert.equal(MIN_SCORED_QUESTIONS, 3);
  const three = scoreCandidate(candidate(threeScored([])), QUESTIONS, allA);
  assert.equal(three.percent, 100);
  const pairs = threeScored([]).slice(0, 2);
  const two = scoreCandidate(candidate(pairs), QUESTIONS, allA);
  assert.equal(two.percent, null);
  assert.equal(two.scored, 2);
});

test("a candidate with no mapped records reports hasRecords = false", () => {
  const result = scoreCandidate({ records: [rec()], mappings: [] }, QUESTIONS, allA);
  assert.equal(result.hasRecords, false);
  assert.equal(result.scored, 0);
  assert.equal(result.percent, null);
});
