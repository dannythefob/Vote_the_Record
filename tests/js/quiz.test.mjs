import { test } from "node:test";
import assert from "node:assert/strict";
import { parseHash, buildHash, encodeAnswers, decodeAnswers, topicMatches, closestCandidate, scoreBallot,
         coverageText, comparable } from "../../site/static/js/quiz.js";

const Q1 = { id: "county-judge/S-01", text: "Q1", options: [{ id: "A", text: "a" }, { id: "B", text: "b" }] };
const Q2 = { id: "county-judge/S-02", text: "Q2", options: [{ id: "A", text: "a" }, { id: "B", text: "b" }] };
const Q3 = { id: "county-judge/S-03", text: "Q3", options: [{ id: "A", text: "a" }, { id: "B", text: "b" }] };

function candidate(id, supports) {
  // One verified official vote per question, supporting the given option.
  const records = [], mappings = [];
  supports.forEach((opt, i) => {
    const rid = `${id}#R-${i}`;
    records.push({ id: rid, record_type: "vote", label: "official_record", claim_status: "documented",
                   verification: "verified", same_event: null });
    mappings.push({ record: rid, question: [Q1, Q2, Q3][i].id, options: [opt], verification: "verified" });
  });
  return { id, name: id, records, mappings };
}

const RACE = { n: 4, key: "harris-county/county-judge", name: "County Judge", url: "/r/", questions: [Q1, Q2, Q3],
               candidates: [candidate("ann", ["A", "A", "A"]), candidate("bob", ["B", "B", "A"])] };
const ALL_A = { [Q1.id]: { option: "A", importance: 2 }, [Q2.id]: { option: "A", importance: 2 },
                [Q3.id]: { option: "A", importance: 3 } };

test("parseHash reads location, topics, and answers, ignoring junk", () => {
  assert.deepEqual(parseHash("#zip=77002"), { zip: "77002", precinct: null, at: null, topics: [], answers: "" });
  const h = parseHash("#precinct=123&t=schools.taxes-budget&a=x~S-01~A~2&evil=<b>");
  assert.equal(h.precinct, "123");
  assert.deepEqual(h.topics, ["schools", "taxes-budget"]);
  assert.equal(h.answers, "x~S-01~A~2");
  assert.deepEqual(parseHash("#at=29.76,-95.36").at, [29.76, -95.36]);
  assert.equal(parseHash("#zip=7700").zip, null);
});

test("buildHash prefers the precinct and round-trips through parseHash", () => {
  const hash = buildHash({ zip: "77002", precinct: "123", topics: ["schools"], answers: "k/x~S-01~A~2" });
  assert.equal(hash, "#precinct=123&t=schools&a=k/x~S-01~A~2");
  assert.equal(buildHash({}), "");
  const back = parseHash(hash);
  assert.equal(back.precinct, "123");
  assert.deepEqual(back.topics, ["schools"]);
});

test("answers survive encode -> decode, and unknown or invalid entries are dropped", () => {
  const answers = { [RACE.key]: { [Q1.id]: { option: "B", importance: 3 }, [Q2.id]: { option: null, importance: 2 } } };
  const text = encodeAnswers(answers);
  assert.equal(text, "harris-county/county-judge~S-01~B~3");
  assert.deepEqual(decodeAnswers(text, [RACE]), { [RACE.key]: { [Q1.id]: { option: "B", importance: 3 } } });
  const junk = `${text}.harris-county/county-judge~S-09~A~2.harris-county/county-judge~S-02~Z~2.other/race~S-01~A~2.bad`;
  assert.deepEqual(decodeAnswers(junk, [RACE]), { [RACE.key]: { [Q1.id]: { option: "B", importance: 3 } } });
});

test("topicMatches lists only races touching a chosen topic", () => {
  const races = [{ n: 0, topics: ["schools", "taxes-budget"] }, { n: 1, topics: ["courts-justice"] }, { n: 2, topics: [] }];
  const m = topicMatches(races, ["taxes-budget", "elections"]);
  assert.deepEqual([...m.entries()], [[0, ["taxes-budget"]]]);
  assert.equal(topicMatches(races, []).size, 0);
});

test("closest is marked only when every candidate with records has a percentage and one is strictly highest", () => {
  const r = (id, percent, hasRecords = true) => ({ candidate: { id }, result: { percent, hasRecords } });
  assert.equal(closestCandidate([r("a", 80), r("b", 40)]), "a");
  assert.equal(closestCandidate([r("a", 80), r("b", null)]), null);   // has records, not enough checked: no mark
  assert.equal(closestCandidate([r("a", 60), r("b", 60)]), null);     // tie: no mark
  assert.equal(closestCandidate([r("a", 90)]), null);                 // one candidate: no comparison
  // No record found at all: set aside (and said so on the page); the rest are compared.
  assert.equal(closestCandidate([r("a", 80), r("b", 40), r("w", null, false)]), "a");
  assert.equal(comparable([r("a", 80), r("w", null, false)]), false); // only one candidate with records
});

test("scoreBallot scores answered races, keeps candidate order, and finds the closest", () => {
  const [entry] = scoreBallot([RACE], { [RACE.key]: ALL_A });
  assert.deepEqual(entry.results.map((x) => x.candidate.id), ["ann", "bob"]);
  assert.equal(entry.results[0].result.percent, 100);
  assert.equal(entry.comparable, true);
  assert.equal(entry.closest, "ann");
  assert.deepEqual(scoreBallot([RACE], {}), []);   // nothing answered: race left out
});

test("a race where only one candidate has records is not comparable and marks no one", () => {
  const thin = { ...RACE, candidates: [RACE.candidates[0], { id: "cy", name: "cy", records: [], mappings: [] }] };
  const [entry] = scoreBallot([thin], { [RACE.key]: ALL_A });
  assert.equal(entry.comparable, false);
  assert.equal(entry.closest, null);
  assert.equal(coverageText([entry], 12), "We could compare candidates in 0 of your 12 races.");
  assert.equal(coverageText(scoreBallot([RACE], { [RACE.key]: ALL_A }), 1), "We could compare candidates in 1 of your 1 race.");
});

test("a candidate with no record found is set aside and the others are still compared", () => {
  const withWriteIn = { ...RACE, candidates: [...RACE.candidates, { id: "wren", name: "wren", records: [], mappings: [] }] };
  const [entry] = scoreBallot([withWriteIn], { [RACE.key]: ALL_A });
  assert.deepEqual(entry.results.map((x) => x.candidate.id), ["ann", "bob", "wren"]);  // still listed, in order
  assert.equal(entry.comparable, true);
  assert.equal(entry.closest, "ann");
});
