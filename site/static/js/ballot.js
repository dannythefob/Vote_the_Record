// ZIP code lookup for ballot pages and the home page. Runs entirely in the browser:
// the ZIP code is never sent anywhere (the page data is embedded; no network requests).

/** "77002", " 77002-1234 " -> "77002"; anything else -> null. */
export function cleanZip(text) {
  const m = /^\s*(\d{5})(?:-\d{4})?\s*$/.exec(text || "");
  return m ? m[1] : null;
}

/**
 * Races on this ballot for a ZIP code, in ballot order, or null if the ZIP isn't covered.
 * payload.zips[zip] lists areas; a nested list means "one of these, depending on your
 * address", so those races are flagged split. Statewide and county-wide areas are implied.
 */
export function racesForZip(payload, zip) {
  const entries = payload.zips[zip];
  if (!entries) return null;
  const sure = new Set([...payload.implied, ...(payload.zipEverywhere || [])]);
  const maybe = new Set();
  for (const e of entries) {
    if (Array.isArray(e)) e.forEach((a) => maybe.add(a));
    else sure.add(e);
  }
  return payload.races
    .filter((r) => sure.has(r.area) || maybe.has(r.area))
    .map((r) => ({ n: r.n, split: maybe.has(r.area) && !sure.has(r.area) }));
}

/** "0123", " 123 " -> "123"; anything that isn't 1-6 digits -> null. */
export function cleanPrecinct(text) {
  const m = /^\s*0*(\d{1,6})\s*$/.exec(text || "");
  return m && m[1] !== "0" ? m[1] : null;
}

/** Races for a voting precinct (exact, never split), or null if the precinct isn't on this ballot. */
export function racesForPrecinct(payload, precinct) {
  const codes = (payload.precincts || {})[precinct];
  if (!codes) return null;
  const mine = new Set([...payload.implied, ...(payload.precinctEverywhere || []), ...codes.map((i) => payload.areas[i])]);
  return payload.races.filter((r) => mine.has(r.area)).map((r) => ({ n: r.n, split: false }));
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function readJson(id) {
  const el = document.getElementById(id);
  return el ? JSON.parse(el.textContent) : null;
}

function initBallotPage(payload) {
  const form = document.getElementById("zip-form");
  const input = document.getElementById("zip");
  const pctInput = document.getElementById("precinct");
  const status = document.getElementById("zip-status");
  const reset = document.getElementById("zip-reset");
  const rows = [...document.querySelectorAll("[data-race]")];
  const groups = [...document.querySelectorAll("[data-group]")];
  form.hidden = false;

  function showAll() {
    rows.forEach((row) => {
      row.hidden = false;
      row.querySelector(".split-chip").hidden = true;
    });
    groups.forEach((g) => { g.hidden = false; });
    reset.hidden = true;
  }

  function show(found) {
    const byN = new Map(found.map((r) => [r.n, r]));
    rows.forEach((row) => {
      const hit = byN.get(Number(row.dataset.race));
      row.hidden = !hit;
      row.querySelector(".split-chip").hidden = !(hit && hit.split);
    });
    groups.forEach((g) => { g.hidden = !g.querySelector("[data-race]:not([hidden])"); });
    reset.hidden = false;
  }

  function applyZip(zip, updateHash) {
    const clean = cleanZip(zip);
    if (!clean) {
      status.textContent = "Enter a 5-digit ZIP code.";
      return;
    }
    const found = racesForZip(payload, clean);
    if (!found) {
      showAll();
      status.textContent = `ZIP code ${clean} isn't in our ${payload.name} data. Showing every race on this ballot.`;
      return;
    }
    show(found);
    const split = found.filter((r) => r.split).length;
    status.textContent = `ZIP code ${clean}: ${plural(found.length, "race", "races")} on your ballot, closest to home first.` +
      (split ? ` ${plural(split, "race depends", "races depend")} on your exact address. Add your precinct number to be sure.` : "");
    if (updateHash) history.replaceState(null, "", `#zip=${clean}`);
  }

  function applyPrecinct(text, updateHash) {
    const clean = cleanPrecinct(text);
    if (!clean) {
      status.textContent = "Enter your precinct number (digits only), or leave it blank and use your ZIP code.";
      return;
    }
    const found = racesForPrecinct(payload, clean);
    if (!found) {
      showAll();
      status.textContent = `Precinct ${clean} isn't in our ${payload.name} data. Showing every race on this ballot.`;
      return;
    }
    show(found);
    status.textContent = `Precinct ${clean}: ${plural(found.length, "race", "races")} on your ballot, closest to home first.`;
    if (updateHash) history.replaceState(null, "", `#precinct=${clean}`);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (pctInput && pctInput.value.trim()) applyPrecinct(pctInput.value, true);
    else applyZip(input.value, true);
  });
  reset.addEventListener("click", () => {
    showAll();
    status.textContent = "Showing every race on this ballot.";
    history.replaceState(null, "", window.location.pathname);
    input.focus();
  });
  const zipHash = /^#zip=(\d{5})$/.exec(window.location.hash);
  const pctHash = /^#precinct=(\d{1,6})$/.exec(window.location.hash);
  if (pctHash && pctInput) {
    pctInput.value = pctHash[1];
    applyPrecinct(pctHash[1], false);
  } else if (zipHash) {
    input.value = zipHash[1];
    applyZip(zipHash[1], false);
  }
}

function initHomeFinder(index) {
  const form = document.getElementById("zip-find");
  const input = document.getElementById("zip-home");
  const status = document.getElementById("zip-home-status");
  const choices = document.getElementById("zip-home-choices");
  form.hidden = false;
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    choices.replaceChildren();
    const clean = cleanZip(input.value);
    if (!clean) {
      status.textContent = "Enter a 5-digit ZIP code.";
      return;
    }
    const ballots = index[clean] || [];
    if (ballots.length === 1) {
      window.location.href = `${ballots[0].url}#zip=${clean}`;
      return;
    }
    if (ballots.length === 0) {
      status.textContent = `We don't have ballot information for ZIP code ${clean} yet. See the official voting info below.`;
      return;
    }
    status.textContent = `ZIP code ${clean} crosses county lines. Which county do you live in?`;
    for (const b of ballots) {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = `${b.url}#zip=${clean}`;
      a.textContent = b.name;
      li.append(a);
      choices.append(li);
    }
  });
}

function init() {
  const ballot = readJson("ballot-data");
  if (ballot) initBallotPage(ballot);
  const index = readJson("zip-index");
  if (index) initHomeFinder(index);
}

if (typeof document !== "undefined") init();
