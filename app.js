(async function () {
  const $ = id => document.getElementById(id);
  const [fx, venues] = await Promise.all([
    fetch("fixtures.json", { cache: "no-cache" }).then(r => r.json()),
    fetch("venues.json", { cache: "no-cache" }).then(r => r.json()),
  ]);
  const fixtures = fx.fixtures;
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const day = d => d.toISOString().slice(0, 10);
  const fmtDate = s => new Date(s).toLocaleDateString("en-IE", { weekday: "short", day: "numeric", month: "short" });
  const fmtTime = f => f.tbc ? '<span class="tbc">time TBC</span>' : (f.time || "").slice(0, 5);
  const score = f => f.score && f.score.hg != null ? ` ${f.score.hg}-${f.score.hp} to ${f.score.ag}-${f.score.ap}` : "";

  // Defaults: the next six weeks, or the whole season if nothing is upcoming.
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const p = new URLSearchParams(location.search);
  const upcoming = fixtures.some(f => new Date(f.date) >= today);
  $("from").value = p.get("from") || (upcoming ? day(today) : fixtures[0].date.slice(0, 10));
  $("to").value = p.get("to") || (upcoming ? day(new Date(today.getTime() + 42 * 864e5)) : fixtures[fixtures.length - 1].date.slice(0, 10));
  if (!upcoming || p.has("results")) $("results").checked = true;

  const comps = [...new Set(fixtures.map(f => f.competition).filter(Boolean))].sort();
  for (const c of comps) $("comp").insertAdjacentHTML("beforeend", `<option value="${esc(c)}">${esc(c)}</option>`);
  if (p.get("comp")) $("comp").value = p.get("comp");
  if (p.has("sport")) for (const cb of document.querySelectorAll("input[name=sport]")) cb.checked = p.getAll("sport").includes(cb.value);

  const map = L.map("map", { scrollWheelZoom: false }).setView([53.4, -7.9], 7);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "&copy; OpenStreetMap contributors" }).addTo(map);
  const layer = L.layerGroup().addTo(map);

  function selected() {
    const from = $("from").value, to = $("to").value;
    const sports = [...document.querySelectorAll("input[name=sport]:checked")].map(cb => cb.value);
    const comp = $("comp").value, results = $("results").checked;
    return fixtures.filter(f => {
      const d = f.date.slice(0, 10);
      return (!from || d >= from) && (!to || d <= to) && sports.includes(f.sport) && (!comp || f.competition === comp) && (results || !f.result);
    });
  }

  function render() {
    const shown = selected();
    const u = new URL(location.href);
    u.searchParams.set("from", $("from").value); u.searchParams.set("to", $("to").value);
    $("comp").value ? u.searchParams.set("comp", $("comp").value) : u.searchParams.delete("comp");
    $("results").checked ? u.searchParams.set("results", "") : u.searchParams.delete("results");
    u.searchParams.delete("sport");
    const sports = [...document.querySelectorAll("input[name=sport]:checked")].map(cb => cb.value);
    if (sports.length !== 2) for (const s of sports) u.searchParams.append("sport", s);
    history.replaceState(null, "", u);

    layer.clearLayers();
    const byVenue = new Map();
    for (const f of shown) { if (!byVenue.has(f.venueId)) byVenue.set(f.venueId, []); byVenue.get(f.venueId).push(f); }
    let unplaced = 0;
    for (const [vid, list] of byVenue) {
      const v = venues[vid];
      if (!v || v.lat == null) { unplaced += list.length; continue; }
      const m = L.circleMarker([v.lat, v.lon], { radius: 6 + Math.min(list.length, 8), color: "#8a3b12", weight: 1, fillColor: "#e0864f", fillOpacity: .8 }).addTo(layer);
      m.bindPopup(`<div class="pop"><b>${esc(v.name)}</b>${list.map(f => `${fmtDate(f.date)} ${fmtTime(f)} · ${esc(f.home.name)} v ${esc(f.away.name)}<br><small>${esc(f.competition)}${f.round ? ", " + esc(f.round) : ""}</small>`).join("<br>")}</div>`, { maxWidth: 320 });
    }

    const byDay = new Map();
    for (const f of shown) { const d = f.date.slice(0, 10); if (!byDay.has(d)) byDay.set(d, []); byDay.get(d).push(f); }
    $("list").innerHTML = shown.length ? [...byDay.keys()].sort().map(d => `
      <h2>${fmtDate(d)}</h2>
      <table>${byDay.get(d).sort((a, b) => (a.time || "").localeCompare(b.time || "")).map(f => `
        <tr><td class="when">${fmtTime(f)}</td>
            <td>${esc(f.home.name)} v ${esc(f.away.name)}${score(f)}<br><small>${esc(f.competition)}${f.round ? ", " + esc(f.round) : ""}${f.tv ? " · " + esc(f.tv) : ""}${f.tickets ? ` · <a href="${esc(f.tickets)}" rel="noopener">tickets</a>` : ""}</small></td>
            <td class="venue">${venues[f.venueId] && venues[f.venueId].lat != null ? `<a href="#map" data-venue="${esc(f.venueId)}">${esc(f.venue)}</a>` : esc(f.venue)}</td></tr>`).join("")}
      </table>`).join("") : '<p class="none">No fixtures in this range. Widen the dates, or tick "include played matches".</p>';
    $("count").textContent = `${shown.length} fixture${shown.length === 1 ? "" : "s"} at ${byVenue.size} venue${byVenue.size === 1 ? "" : "s"}${unplaced ? ` (${unplaced} at venues not yet on the map)` : ""}.`;
  }

  $("list").addEventListener("click", ev => {
    const a = ev.target.closest("a[data-venue]"); if (!a) return;
    const v = venues[a.dataset.venue]; map.setView([v.lat, v.lon], 11);
    layer.eachLayer(m => { const ll = m.getLatLng(); if (ll.lat === v.lat && ll.lng === v.lon) m.openPopup(); });
  });
  for (const el of document.querySelectorAll("#f input, #f select")) el.addEventListener("change", render);
  $("meta").textContent = `Fixtures fetched from gaa.ie on ${fx.fetched.slice(0, 10)}. ${fixtures.length} fixtures, ${fixtures[0].date.slice(0, 10)} to ${fixtures[fixtures.length - 1].date.slice(0, 10)}.`;
  render();
})();
