// Pure helpers for the ballot page: topics, the ballot-wide quiz, and private result links.
// No DOM access, so they run under `node --test`. Nothing here stores or sends anything.
import { scoreCandidate } from "./score.js";

const KEY = /^[a-z0-9-]+\/[a-z0-9-]+$/;
const ENTRY = /^([a-z0-9-]+\/[a-z0-9-]+)~(S-\d+)~([A-Z])~([123])$/;

// The part of a URL after "#": where you are (zip, precinct, or at=lat,lon), plus, in a
// private link, topics (t) and quiz answers (a). Browsers never send it to any server.
export function parseHash(hash) {
  const out = { zip: null, precinct: null, at: null, topics: [], answers: "" };
  for (const part of String(hash || "").replace(/^#/, "").split("&")) {
    const eq = part.indexOf("=");
    if (eq < 1) continue;
    const key = part.slice(0, eq);
    const value = part.slice(eq + 1);
    if (key === "zip" && /^\d{5}$/.test(value)) out.zip = value;
    else if (key === "precinct" && /^\d{1,6}$/.test(value)) out.precinct = value;
    else if (key === "at") {
      const m = /^(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)$/.exec(value);
      if (m) out.at = [Number(m[1]), Number(m[2])];
    } else if (key === "t") out.topics = value.split(".").filter((t) => /^[a-z-]+$/.test(t));
    else if (key === "a") out.answers = value;
  }
  return out;
}

export function buildHash({ zip = null, precinct = null, topics = [], answers = "" } = {}) {
  const parts = [];
  if (precinct) parts.push(`precinct=${precinct}`);
  else if (zip) parts.push(`zip=${zip}`);
  if (topics.length) parts.push(`t=${topics.join(".")}`);
  if (answers) parts.push(`a=${answers}`);
  return parts.length ? `#${parts.join("&")}` : "";
}

// answers: {raceKey: {questionId: {option, importance}}}; skipped questions are left out.
export function encodeAnswers(answers) {
  const entries = [];
  for (const [raceKey, byQuestion] of Object.entries(answers)) {
    if (!KEY.test(raceKey)) continue;
    for (const [qid, a] of Object.entries(byQuestion)) {
      const sid = qid.split("/").pop();
      if (a && a.option && /^S-\d+$/.test(sid) && /^[A-Z]$/.test(a.option) && [1, 2, 3].includes(a.importance)) {
        entries.push(`${raceKey}~${sid}~${a.option}~${a.importance}`);
      }
    }
  }
  return entries.join(".");
}

// Keeps only answers that match a question and option on this ballot.
export function decodeAnswers(text, quizRaces) {
  const out = {};
  const races = new Map(quizRaces.map((r) => [r.key, r]));
  for (const entry of String(text || "").split(".")) {
    const m = ENTRY.exec(entry);
    if (!m) continue;
    const race = races.get(m[1]);
    const question = race && race.questions.find((q) => q.id.split("/").pop() === m[2]);
    if (!question || !question.options.some((o) => o.id === m[3])) continue;
    (out[m[1]] ||= {})[question.id] = { option: m[3], importance: Number(m[4]) };
  }
  return out;
}

// Which races deal with any of the chosen topics, and which topics matched.
export function topicMatches(races, chosen) {
  const want = new Set(chosen);
  const out = new Map();
  if (!want.size) return out;
  for (const race of races) {
    const hit = (race.topics || []).filter((t) => want.has(t));
    if (hit.length) out.set(race.n, hit);
  }
  return out;
}

// Candidates with no record at all that we could find are set aside, with a note saying so;
// the comparison is among the rest. Comparable: at least two candidates with records, and
// every one of them has a percentage.
export function comparable(results) {
  const withRecords = results.filter((r) => r.result.hasRecords);
  return withRecords.length >= 2 && withRecords.every((r) => r.result.percent !== null);
}

// "Closest to your answers": only in a comparable race, and only when one percentage (as
// shown) is strictly highest.
export function closestCandidate(results) {
  if (!comparable(results)) return null;
  const withRecords = results.filter((r) => r.result.hasRecords);
  const top = Math.max(...withRecords.map((r) => r.result.percent));
  const best = withRecords.filter((r) => r.result.percent === top);
  return best.length === 1 ? best[0].candidate.id : null;
}

// Score every quiz race the visitor answered. Candidates stay in page (alphabetical) order.
export function scoreBallot(quizRaces, answers) {
  const out = [];
  for (const race of quizRaces) {
    const mine = answers[race.key] || {};
    const filled = Object.fromEntries(race.questions.map((q) => [q.id, mine[q.id] || { option: null, importance: 2 }]));
    if (!Object.values(filled).some((a) => a.option)) continue;
    const results = race.candidates.map((candidate) => ({
      candidate, result: scoreCandidate(candidate, race.questions, filled),
    }));
    out.push({ race, results, comparable: comparable(results), closest: closestCandidate(results) });
  }
  return out;
}

// "We could compare candidates in X of your Y races."
export function coverageText(scored, candidateRaces) {
  const x = scored.filter((s) => s.comparable).length;
  return `We could compare candidates in ${x} of your ${candidateRaces} ${candidateRaces === 1 ? "race" : "races"}.`;
}
