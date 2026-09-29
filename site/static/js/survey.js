// Survey wiring for race pages. Scoring lives in score.js; this file only reads the form
// and renders results. It builds DOM nodes with textContent (never innerHTML), sets no
// inline styles, stores nothing, and makes no network requests.
import { scoreCandidate, recordWeight } from "./score.js";

const LABELS = { official_record: "Official record", news_report: "News report", candidate_claim: "Candidate's claim" };
const RECORD_TYPES = { vote: "Vote", sponsored: "Sponsored measure", promise_kept: "Promise kept",
                       promise_broken: "Promise broken", statement: "Statement" };
const IMPORTANCE = { 1: "A little", 2: "Somewhat", 3: "A lot" };
const STATUSES = { documented: "Documented", allegation: "Allegation", disputed: "Disputed", contradicted: "Contradicted" };

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined && child !== false) {
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
  }
  return node;
}

function badge(verified, text = verified ? "Verified" : "Unverified") {
  return el("span", { class: `badge ${verified ? "badge-verified" : "badge-unverified"}`, text });
}

function reportLink(template, itemId) {
  if (!template) return el("span", { class: "report", text: "Corrections form coming soon" });
  return el("a", { class: "report", href: template.replace("{id}", encodeURIComponent(itemId)),
                   rel: "noopener noreferrer" }, "Report a problem");
}

function readAnswers(form, questions) {
  const answers = {};
  for (const q of questions) {
    const choice = form.querySelector(`input[name="${CSS.escape(`answer-${q.id}`)}"]:checked`);
    const importance = form.querySelector(`input[name="${CSS.escape(`importance-${q.id}`)}"]:checked`);
    answers[q.id] = {
      option: choice && choice.value ? choice.value : null,
      importance: importance ? Number(importance.value) : 2,
    };
  }
  return answers;
}

function optionText(question, optionId) {
  const option = question.options.find((o) => o.id === optionId);
  return option ? `${option.id}. ${option.text}` : optionId;
}

function renderItem(item, question, template) {
  const { record, mapping } = item;
  const supported = mapping.options.map((id) => optionText(question, id)).join("; ");
  let status;
  if (item.counted) status = item.supportsChoice ? "Counted: supports your choice" : "Counted: supports a different option";
  else status = `Not counted: ${item.reason}`;
  return el("li", { class: "card item" },
    el("p", { class: "item-main" },
      el("strong", {}, `${RECORD_TYPES[record.record_type] || "Record"}: `), record.statement),
    el("p", { class: "item-meta" },
      el("span", { class: "chip", text: LABELS[record.label] || record.label }), " ",
      el("span", { class: "chip", text: STATUSES[record.claim_status] || record.claim_status }), " ",
      badge(record.verification === "verified"), " ",
      el("a", { href: record.source_url, rel: "noopener noreferrer" }, `Source: ${record.source_title}`),
      " · ", reportLink(template, record.id)),
    el("p", { class: "item-meta" },
      `Supports: ${supported}. `, "Why: ", mapping.rationale, " ",
      el("span", { class: "visually-hidden", text: "Link to this question:" }), " ",
      badge(mapping.verification === "verified",
            mapping.verification === "verified" ? "Link verified" : "Unverified")),
    el("p", { class: `item-meta ${item.counted ? "" : "not-counted"}`.trim() },
      status, item.counted ? ` (weight ${recordWeight(record).toFixed(1)})` : ""));
}

function renderBreakdown(result, questionsById, template) {
  const list = el("ol", { class: "breakdown" });
  for (const q of result.questions) {
    const question = questionsById.get(q.id);
    const block = el("li", {},
      el("p", { class: "item-main" }, el("strong", {}, q.text)),
      el("p", { class: "item-meta" },
        `You chose ${optionText(question, q.choice)} · Importance: ${IMPORTANCE[q.importance]}`,
        q.alignment === null ? " · Not scored for this candidate" : ` · Alignment ${Math.round(q.alignment * 100)}%`));
    if (q.items.length === 0) {
      block.append(el("p", { class: "empty", text: "No record on this question." }));
    } else {
      block.append(el("ul", { class: "item-list" }, ...q.items.map((item) => renderItem(item, question, template))));
    }
    list.append(block);
  }
  return list;
}

function renderCandidate(candidate, result, questionsById, template) {
  const card = el("section", { class: "card result", "aria-labelledby": `result-${candidate.id}` },
    el("h3", { id: `result-${candidate.id}`, text: candidate.name }));
  if (!result.hasRecords) {
    card.append(el("p", { class: "empty", text: "No record on file for this candidate." }));
    return card;
  }
  const basedOn = `Based on ${result.scored} of ${result.answered} question${result.answered === 1 ? "" : "s"}.`;
  if (result.percent !== null) {
    card.append(
      el("p", { class: "match" }, el("span", { class: "match-value", text: `${result.percent}% match` })),
      el("meter", { min: "0", max: "100", value: String(result.percent), "aria-label": `${result.percent}% match` }),
      el("p", { class: "muted", text: basedOn }),
      el("details", {}, el("summary", {}, "See how this was calculated"),
        renderBreakdown(result, questionsById, template)));
  } else {
    card.append(
      el("p", { class: "match", text: "Not enough record to compare." }),
      el("p", { class: "muted", text: `${basedOn} A percentage appears once at least 3 of your answered questions have verified records for this candidate.` }),
      el("details", { open: "" }, el("summary", {}, "What is on record for your answers"),
        renderBreakdown(result, questionsById, template)));
  }
  return card;
}

function init() {
  const dataNode = document.getElementById("race-data");
  const form = document.getElementById("survey-form");
  const output = document.getElementById("results");
  if (!dataNode || !form || !output) return;
  const data = JSON.parse(dataNode.textContent);
  const questionsById = new Map(data.questions.map((q) => [q.id, q]));

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const answers = readAnswers(form, data.questions);
    const heading = el("h2", { id: "results-heading", tabindex: "-1", text: "Your results" });
    output.replaceChildren(heading);
    const answered = Object.values(answers).filter((a) => a.option).length;
    if (answered === 0) {
      output.append(el("p", { text: "Answer at least one question to see results." }));
    } else {
      output.append(el("p", { class: "muted",
        text: "How your answers line up with each candidate's verified record. Candidates are listed alphabetically. This is not a recommendation." }));
      for (const candidate of data.candidates) {  // already alphabetical; never re-sorted by score
        const result = scoreCandidate(candidate, data.questions, answers);
        output.append(renderCandidate(candidate, result, questionsById, data.corrections_form_url));
      }
    }
    output.hidden = false;
    heading.focus();
  });

  form.addEventListener("reset", () => {
    output.replaceChildren();
    output.hidden = true;
  });
}

init();
