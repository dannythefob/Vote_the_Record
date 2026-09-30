// ZIP lookup logic for ballot pages (site/static/js/ballot.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import { cleanZip, racesForZip } from "../../site/static/js/ballot.js";

const payload = {
  name: "Demo County ballot",
  implied: ["tx", "demo-county"],
  zips: {
    "11111": ["us-house-1", "demo-county/jp-1"],
    "22222": [["us-house-1", "us-house-2"], "demo-county/jp-2"],
  },
  races: [
    { n: 0, area: "demo-county/jp-1", office: "justice-of-the-peace" },
    { n: 1, area: "demo-county/jp-2", office: "justice-of-the-peace" },
    { n: 2, area: "demo-county", office: "county-judge" },
    { n: 3, area: "tx", office: "governor" },
    { n: 4, area: "us-house-1", office: "us-representative" },
    { n: 5, area: "us-house-2", office: "us-representative" },
  ],
};

test("cleanZip accepts 5 digits or ZIP+4 and rejects the rest", () => {
  assert.equal(cleanZip("77002"), "77002");
  assert.equal(cleanZip(" 77002-1234 "), "77002");
  for (const bad of ["7700", "770022", "abcde", "", null, "77002 1234"]) assert.equal(cleanZip(bad), null, String(bad));
});

test("a ZIP gets its own areas plus statewide and county-wide races, in ballot order", () => {
  assert.deepEqual(racesForZip(payload, "11111"), [
    { n: 0, split: false }, { n: 2, split: false }, { n: 3, split: false }, { n: 4, split: false },
  ]);
});

test("a split ZIP shows every possible race, flagged as depending on the address", () => {
  assert.deepEqual(racesForZip(payload, "22222"), [
    { n: 1, split: false }, { n: 2, split: false }, { n: 3, split: false },
    { n: 4, split: true }, { n: 5, split: true },
  ]);
});

test("an unknown ZIP returns null so the page can show everything", () => {
  assert.equal(racesForZip(payload, "99999"), null);
});

import { cleanPrecinct, racesForPrecinct } from "../../site/static/js/ballot.js";

const withPrecincts = {
  ...payload,
  zipEverywhere: ["coa-1"],
  areas: ["demo-county/jp-1", "demo-county/jp-2", "us-house-1", "us-house-2"],
  precincts: { "101": [2, 0], "102": [3, 1] },
  precinctEverywhere: ["coa-1"],
  races: [...payload.races, { n: 6, area: "coa-1", office: "court-of-appeals-justice" }],
};

test("cleanPrecinct strips leading zeros and rejects non-numbers", () => {
  assert.equal(cleanPrecinct("0123"), "123");
  assert.equal(cleanPrecinct(" 7 "), "7");
  for (const bad of ["", "0", "12a", "1234567", null]) assert.equal(cleanPrecinct(bad), null, String(bad));
});

test("a precinct gets exactly its areas plus implied and everywhere areas, never split", () => {
  assert.deepEqual(racesForPrecinct(withPrecincts, "102"), [
    { n: 1, split: false }, { n: 2, split: false }, { n: 3, split: false }, { n: 5, split: false }, { n: 6, split: false },
  ]);
  assert.equal(racesForPrecinct(withPrecincts, "999"), null);
});

test("zipEverywhere areas are added to every ZIP", () => {
  assert.ok(racesForZip(withPrecincts, "11111").some((r) => r.n === 6));
});
