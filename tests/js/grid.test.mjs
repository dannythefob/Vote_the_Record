// Unit tests for the quiz results grid cells (site/static/js/survey.js, cellFor).
import { test } from "node:test";
import assert from "node:assert/strict";
import { cellFor } from "../../site/static/js/survey.js";

const item = {};
test("no linked records -> No record", () => {
  assert.deepEqual(cellFor({ items: [], alignment: null }), { state: "none", text: "No record" });
  assert.equal(cellFor(undefined).state, "none");
});
test("linked but unscored records -> Record not counted", () => {
  assert.equal(cellFor({ items: [item], alignment: null }).state, "unscored");
});
test("full agreement, disagreement, and mixed", () => {
  assert.equal(cellFor({ items: [item], alignment: 1 }).text, "Same as you");
  assert.equal(cellFor({ items: [item], alignment: 0 }).text, "Different");
  assert.equal(cellFor({ items: [item], alignment: 3 / 3.4 }).text, "Mixed");
});
