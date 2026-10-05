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

test("cleanPrecinct strips leading zeros, allows letters after a digit, and rejects the rest", () => {
  assert.equal(cleanPrecinct("0123"), "123");
  assert.equal(cleanPrecinct(" 7 "), "7");
  assert.equal(cleanPrecinct("32a0"), "32A0");
  for (const bad of ["", "0", "a12", "12-3", "1234567", "<b>", null]) assert.equal(cleanPrecinct(bad), null, String(bad));
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

import { pointInRings, findPrecinct, countySlug, locate, LOCATE_ERRORS } from "../../site/static/js/ballot.js";

const SHAPES = { precincts: {
  "7": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]],
  "8": [[[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]],
} };

test("pointInRings respects holes", () => {
  assert.equal(pointInRings(SHAPES.precincts["7"], 1, 1), true);
  assert.equal(pointInRings(SHAPES.precincts["7"], 5, 5), false);
  assert.equal(pointInRings(SHAPES.precincts["7"], 11, 5), false);
});

test("findPrecinct returns the precinct containing the point", () => {
  assert.equal(findPrecinct(SHAPES, 5, 5), "8");
  assert.equal(findPrecinct(SHAPES, 2, 8), "7");
  assert.equal(findPrecinct(SHAPES, 20, 20), null);
});

test("countySlug matches locality folder names", () => {
  assert.equal(countySlug("Harris County"), "harris-county");
  assert.equal(countySlug("Fort Bend County"), "fort-bend-county");
  assert.equal(countySlug(null), "");
});

test("locate posts only the address to our own Worker and maps errors", async () => {
  let call;
  const ok = await locate("1001 Preston St", async (url, init) => {
    call = { url, init };
    return new Response(JSON.stringify({ matched: "X", lat: 1, lon: 2, county: "Harris County" }), { status: 200 });
  });
  assert.equal(call.url, "/api/locate");
  assert.deepEqual(JSON.parse(call.init.body), { address: "1001 Preston St" });
  assert.equal(ok.county, "Harris County");
  const nf = await locate("1 Nowhere", async () => new Response(JSON.stringify({ error: "not-found" }), { status: 404 }));
  assert.deepEqual(nf, { error: "not-found" });
  const odd = await locate("1 X", async () => new Response(JSON.stringify({ error: "weird" }), { status: 400 }));
  assert.deepEqual(odd, { error: "unavailable" });
  const down = await locate("1 X", async () => { throw new Error("offline"); });
  assert.deepEqual(down, { error: "unavailable" });
  assert.ok(LOCATE_ERRORS["not-found"].includes("couldn't find"));
});

import { areasAt } from "../../site/static/js/ballot.js";

const CITY = {
  implied: ["tx", "demo-county"],
  areas: ["city-a", "us-house-1"],
  localAreas: ["city-a"],
  precincts: { "5": [1, [0]], "6": [1, 0] },
  zips: {},
  races: [
    { n: 0, area: "city-a", office: "measure" },
    { n: 1, area: "us-house-1", office: "us-representative" },
    { n: 2, area: "tx", office: "governor" },
  ],
};

test("a precinct partly inside a city flags the city's contests as depending on the address", () => {
  assert.deepEqual(racesForPrecinct(CITY, "5"), [
    { n: 0, split: true }, { n: 1, split: false }, { n: 2, split: false }]);
  assert.deepEqual(racesForPrecinct(CITY, "6")[0], { n: 0, split: false });
});

test("an exact location settles city contests: inside keeps them, outside drops them", () => {
  assert.deepEqual(racesForPrecinct(CITY, "5", new Set(["city-a"])).map((r) => [r.n, r.split]), [[0, false], [1, false], [2, false]]);
  assert.deepEqual(racesForPrecinct(CITY, "5", new Set()).map((r) => r.n), [1, 2]);
});

test("areasAt lists every local area whose outline contains the point", () => {
  const shapes = { areas: { "city-a": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]], "city-b": [[[5, 5], [6, 5], [6, 6], [5, 6], [5, 5]]] } };
  assert.deepEqual([...areasAt(shapes, 1, 1)], ["city-a"]);
  assert.deepEqual([...areasAt(shapes, 9, 9)], []);
});
