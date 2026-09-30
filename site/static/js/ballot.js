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

/**
 * Races for a voting precinct, or null if the precinct isn't on this ballot. A nested entry
 * means the precinct is split (or, with one item, only partly in that area): those races are
 * flagged split, unless `atPoint` (the local areas containing the voter's exact location)
 * settles them.
 */
export function racesForPrecinct(payload, precinct, atPoint = null) {
  const codes = (payload.precincts || {})[precinct];
  if (!codes) return null;
  const known = new Set(payload.localAreas || []);
  const sure = new Set([...payload.implied, ...(payload.precinctEverywhere || [])]);
  const maybe = new Set();
  for (const code of codes) {
    if (!Array.isArray(code)) {
      sure.add(payload.areas[code]);
      continue;
    }
    for (const i of code) {
      const area = payload.areas[i];
      if (atPoint && known.has(area)) {
        if (atPoint.has(area)) sure.add(area);
      } else {
        maybe.add(area);
      }
    }
  }
  return payload.races
    .filter((r) => sure.has(r.area) || maybe.has(r.area))
    .map((r) => ({ n: r.n, split: maybe.has(r.area) && !sure.has(r.area) }));
}

/** Local areas (cities, districts) whose outlines contain the point. */
export function areasAt(areaShapes, lon, lat) {
  const inside = new Set();
  for (const [area, rings] of Object.entries(areaShapes.areas || {})) {
    if (pointInRings(rings, lon, lat)) inside.add(area);
  }
  return inside;
}

/** Even-odd point-in-polygon over all of a precinct's rings (holes included). */
export function pointInRings(rings, x, y) {
  let inside = false;
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i];
      const [xj, yj] = ring[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
  }
  return inside;
}

/** The precinct whose outline contains the point, or null. */
export function findPrecinct(shapes, lon, lat) {
  for (const [id, rings] of Object.entries(shapes.precincts)) {
    if (pointInRings(rings, lon, lat)) return id;
  }
  return null;
}

/** "Harris County" -> "harris-county" (matches locality folder names). */
export function countySlug(name) {
  return String(name || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

export const LOCATE_ERRORS = {
  "not-found": "We couldn't find that address. Check the house number and spelling, or use your ZIP code or precinct number.",
  "bad-address": "Enter a street address with a house number, like 1001 Preston St, Houston.",
  unavailable: "The address lookup isn't available right now. Use your ZIP code or precinct number instead.",
};

/** Ask our own Worker to find the address. Nothing is stored anywhere. */
export async function locate(address, fetchFn = fetch) {
  let res;
  try {
    res = await fetchFn("/api/locate", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ address }),
    });
  } catch {
    return { error: "unavailable" };
  }
  let data = {};
  try {
    data = await res.json();
  } catch {
    /* no body */
  }
  if (!res.ok) return { error: LOCATE_ERRORS[data.error] ? data.error : "unavailable" };
  return data;
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
  const addrInput = document.getElementById("address");
  let shapesPromise = null;
  let areaShapesPromise = null;
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

  function loadShapes() {
    if (!shapesPromise) {
      shapesPromise = fetch(payload.shapesUrl).then((r) => {
        if (!r.ok) throw new Error("shapes");
        return r.json();
      });
    }
    return shapesPromise;
  }

  async function placeAt(lat, lon, label) {
    status.textContent = "Finding your precinct...";
    let shapes;
    try {
      shapes = await loadShapes();
    } catch {
      shapesPromise = null;
      status.textContent = "We couldn't load the precinct map. Use your ZIP code or precinct number instead.";
      return;
    }
    let atPoint = null;
    if (payload.areaShapesUrl) {
      try {
        if (!areaShapesPromise) areaShapesPromise = fetch(payload.areaShapesUrl).then((r) => r.json());
        atPoint = areasAt(await areaShapesPromise, lon, lat);
      } catch {
        areaShapesPromise = null;  // local races then show as "depends on your address"
      }
    }
    const precinct = findPrecinct(shapes, lon, lat);
    if (!precinct) {
      showAll();
      status.textContent = `${label}: that spot isn't inside a precinct in our ${payload.name} data. Showing every race.`;
      return;
    }
    if (pctInput) pctInput.value = precinct;
    applyPrecinct(precinct, true, label, atPoint);
  }

  async function applyAddress(text) {
    status.textContent = "Looking up your address...";
    const found = await locate(text);
    if (found.error) {
      status.textContent = LOCATE_ERRORS[found.error];
      return;
    }
    if (countySlug(found.county) !== payload.locality) {
      status.textContent = `That address is in ${found.county || "another county"}, which isn't on this ballot.`;
      return;
    }
    await placeAt(found.lat, found.lon, `Found ${found.matched}`);
  }

  function applyPrecinct(text, updateHash, label = "", atPoint = null) {
    const clean = cleanPrecinct(text);
    if (!clean) {
      status.textContent = "Enter your precinct number (digits only), or leave it blank and use your ZIP code.";
      return;
    }
    const found = racesForPrecinct(payload, clean, atPoint);
    if (!found) {
      showAll();
      status.textContent = `Precinct ${clean} isn't in our ${payload.name} data. Showing every race on this ballot.`;
      return;
    }
    show(found);
    const split = found.filter((r) => r.split).length;
    status.textContent = `${label ? label + ". " : ""}Precinct ${clean}: ${plural(found.length, "race", "races")} on your ballot, closest to home first.` +
      (split ? ` ${plural(split, "race depends", "races depend")} on your exact address.` : "");
    if (updateHash) history.replaceState(null, "", `#precinct=${clean}`);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (addrInput && addrInput.value.trim()) applyAddress(addrInput.value);
    else if (pctInput && pctInput.value.trim()) applyPrecinct(pctInput.value, true);
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
  const atHash = /^#at=(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)$/.exec(window.location.hash);
  if (atHash && payload.shapesUrl) {
    // From the home page's address box. The map location is dropped from the URL right
    // away; placeAt then records only the precinct number.
    history.replaceState(null, "", window.location.pathname);
    placeAt(Number(atHash[1]), Number(atHash[2]), "Found your address");
  } else if (pctHash && pctInput) {
    pctInput.value = pctHash[1];
    applyPrecinct(pctHash[1], false);
  } else if (zipHash) {
    input.value = zipHash[1];
    applyZip(zipHash[1], false);
  }
}

function initHomeFinder(index, counties) {
  const form = document.getElementById("zip-find");
  const input = document.getElementById("zip-home");
  const addrInput = document.getElementById("address-home");
  const status = document.getElementById("zip-home-status");
  const choices = document.getElementById("zip-home-choices");
  form.hidden = false;

  async function findByAddress(text) {
    status.textContent = "Looking up your address...";
    const found = await locate(text);
    if (found.error) {
      status.textContent = LOCATE_ERRORS[found.error];
      return;
    }
    const ballots = counties[countySlug(found.county)] || [];
    if (!ballots.length) {
      status.textContent = `Found ${found.matched}, in ${found.county || "a county"} we don't cover yet. See the official voting info below.`;
      return;
    }
    // The location goes in the # part of the link, which browsers never send to a server.
    window.location.href = `${ballots[0].url}#at=${found.lat.toFixed(6)},${found.lon.toFixed(6)}`;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    choices.replaceChildren();
    if (addrInput && addrInput.value.trim()) {
      findByAddress(addrInput.value);
      return;
    }
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
  if (index) initHomeFinder(index, readJson("county-index") || {});
}

if (typeof document !== "undefined") init();
