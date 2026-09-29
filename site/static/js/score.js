// Scoring for Vote the Record. Implements docs/METHODOLOGY.md exactly.
// Pure functions with no DOM access, so they run in the browser and under `node --test`.

export const TYPE_WEIGHTS = Object.freeze({
  vote: 3,
  sponsored: 2,
  promise_kept: 2,
  promise_broken: 2,
  statement: 1,
});

export const EVIDENCE_FACTORS = Object.freeze({
  official_record: 1.0,
  news_report: 0.7,
  candidate_claim: 0.4,
});

// A percentage is shown only when at least this many answered questions have scorable records.
export const MIN_SCORED_QUESTIONS = 3;

// record weight = type weight × evidence factor
export function recordWeight(record) {
  return (TYPE_WEIGHTS[record.record_type] ?? 0) * (EVIDENCE_FACTORS[record.label] ?? 0);
}

// Why a mapped record does not count, or null if it is scorable.
export function exclusionReason(record, mapping) {
  if (record.verification !== "verified") return "Record not yet verified";
  if (mapping.verification !== "verified") return "Link to this question not yet verified";
  if (record.claim_status !== "documented") return `Status is ${record.claim_status}, so it is not scored`;
  return null;
}

export function isScorable(record, mapping) {
  return exclusionReason(record, mapping) === null;
}

// Plain code-unit comparison, so tie-breaks never depend on the viewer's locale.
function compareIds(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * Score one candidate against the user's answers.
 *
 * @param candidate {records: [...], mappings: [...]} as embedded in the race page
 * @param questions [{id, text, options: [{id, text}]}] in survey order
 * @param answers   {questionId: {option: "B", importance: 1|2|3}}; missing or null option = skipped
 * @returns {answered, scored, percent, score, hasRecords, questions: [...]}
 */
export function scoreCandidate(candidate, questions, answers) {
  const records = new Map(candidate.records.map((r) => [r.id, r]));
  const hasRecords = candidate.mappings.some((m) => records.has(m.record));
  const results = [];
  let answered = 0;
  let scored = 0;
  let weightedSum = 0;
  let importanceSum = 0;

  for (const question of questions) {
    const answer = answers[question.id];
    if (!answer || !answer.option) continue;
    answered += 1;
    const importance = answer.importance;

    const items = candidate.mappings
      .filter((m) => m.question === question.id && records.has(m.record))
      .map((mapping) => {
        const record = records.get(mapping.record);
        const reason = exclusionReason(record, mapping);
        return {
          record,
          mapping,
          weight: recordWeight(record),
          scorable: reason === null,
          counted: false,
          supportsChoice: mapping.options.includes(answer.option),
          reason,
        };
      })
      .sort((a, b) => compareIds(a.record.id, b.record.id));

    // Records describing the same event count once: keep the highest weight, ties to the first ID.
    // A record without a same_event group is its own group, so a record mapped twice counts once.
    const groups = new Map();
    for (const item of items) {
      if (!item.scorable) continue;
      const key = item.record.same_event ? `event:${item.record.same_event}` : `record:${item.record.id}`;
      const best = groups.get(key);
      if (!best || item.weight > best.weight ||
          (item.weight === best.weight && compareIds(item.record.id, best.record.id) < 0)) {
        groups.set(key, item);
      }
    }
    for (const item of items) {
      if (!item.scorable) continue;
      if (groups.get(item.record.same_event ? `event:${item.record.same_event}` : `record:${item.record.id}`) === item) {
        item.counted = true;
      } else {
        item.reason = "Same event as a higher-weight record, which is counted instead";
      }
    }

    const counted = items.filter((i) => i.counted);
    const total = counted.reduce((sum, i) => sum + i.weight, 0);
    let alignment = null;
    if (total > 0) {
      const matched = counted.filter((i) => i.supportsChoice).reduce((sum, i) => sum + i.weight, 0);
      alignment = matched / total;
      scored += 1;
      weightedSum += importance * alignment;
      importanceSum += importance;
    }

    results.push({
      id: question.id,
      text: question.text,
      options: question.options,
      choice: answer.option,
      importance,
      alignment,
      items,
    });
  }

  const enough = scored >= MIN_SCORED_QUESTIONS;
  const score = enough ? weightedSum / importanceSum : null;
  return {
    answered,
    scored,
    score,
    percent: score === null ? null : Math.round(score * 100),
    hasRecords,
    questions: results,
  };
}
