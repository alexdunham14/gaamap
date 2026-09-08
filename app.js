(async function () {
  const $ = id => document.getElementById(id);
  // Two fixture files: gaa.ie's football and hurling, and camogie.ie's camogie
  // (scripts/fetch.py and scripts/fetch_camogie.py each own one). If the camogie file
  // is missing or unreadable the rest of the map still draws.
  const [fx, cam, venues] = await Promise.all([
    fetch("fixtures.json", { cache: "no-cache" }).then(r => r.json()),
    fetch("camogie.json", { cache: "no-cache" }).then(r => r.ok ? r.json() : { fixtures: [] }).catch(() => ({ fixtures: [] })),
    fetch("venues.json", { cache: "no-cache" }).then(r => r.json()),
  ]);
  const clean = s => String(s ?? "").replace(/[\x00-\x1f\x7f-\x9f]/g, "").replace(/\s+/g, " ").trim();
  const esc = s => clean(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fold = s => clean(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const day = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const local = s => { const [y, m, d] = s.slice(0, 10).split("-").map(Number); return new Date(y, m - 1, d); };
  const fmtDate = s => local(s).toLocaleDateString("en-IE", { weekday: "short", day: "numeric", month: "short" });
  const fmtShort = s => local(s).toLocaleDateString("en-IE", { day: "numeric", month: "short" });
  // gaa.ie gives true UTC instants (All-Ireland finals show as 14:30Z, i.e. 15:30 Irish time), so show Irish time.
  const irishDay = s => new Date(s).toLocaleDateString("en-CA", { timeZone: "Europe/Dublin" });
  const fmtTime = f => f.tbc ? '<span class="tbc">time TBC</span>' : new Date(f.date).toLocaleTimeString("en-IE", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Europe/Dublin" });

  // ---- Making sense of the competition names ---------------------------------------
  // Both sites list every competition as a flat sponsor-prefixed name. The GAA's season has a
  // shape, though: senior inter-county championship (in tiers), the spring national league
  // (in divisions), under-20 and minor grades, the All-Ireland stages of the club championship,
  // and the post-primary schools finals. Classify each fixture into a level and a tier so the
  // page can show that shape. Rules are by name, so a new competition next season still lands
  // somewhere sensible.
  const SPORTS = ["Football", "Hurling", "Camogie"];
  const LEVELS = ["Senior championship", "National league", "Under-23", "Under-20", "Minor", "Under-16", "Club", "Schools"];
  const LEVEL_NOTE = {
    "Senior championship": "the summer championship for county teams",
    "National league": "the spring league for county teams, with promotion and relegation between divisions",
    "Under-23": "county teams, under-23s (camogie's grade; the GAA's equivalent is under-20)",
    "Under-20": "county teams, under-20s",
    "Minor": "county teams, under-17s",
    "Under-16": "county teams, under-16s",
    "Club": "the All-Ireland stages of the club championships (provincial winners onward)",
    "Schools": "post-primary schools' All-Ireland finals",
  };
  const SPONSOR = /^(AIB|Allianz|Electric Ireland|Fulfil|Dalata Hotel Group|Masita|Beko|Bord Gáis Energy|EirGrid|Lidl|Glen Dimplex|Very)\s+(GAA\s+)?/i;
  const shortName = c => clean(c).replace(SPONSOR, "").replace(/\bGAA\s+/, "").replace(/\bRoinn\b/, "Division").replace(/\s+-\s+/, ", ")
    .replace(/^(Football|Hurling) All-Ireland (Senior|Intermediate|Junior|U20\w*) (Club )?Championship/, "All-Ireland $2 $3$1 Championship")
    .replace(/^(Connacht|Leinster|Munster|Ulster) (Football|Hurling) Senior Championship/, "$1 Senior $2 Championship");
  // Camogie's own ladder: senior down to junior in the championship, five league divisions,
  // and under-23/minor/under-16 grades lettered A to C, some with a Shield for teams knocked
  // out of the Cup. Named nothing like the GAA's competitions, so classified on its own terms.
  function classifyCamogie(c) {
    const m = x => x.test(c);
    const grade = (re, fallback = "A") => (c.match(re) || [])[1] || fallback;
    const graded = (level, g) => ({ level, tier: "ABC".indexOf(g) + 1 || 9, tierName: g === "A" ? "top grade" : "grade " + g });
    // "Minor A Shield" is a second competition for teams out of the Cup, half a tier below it.
    // "U16B Cup/Shield" is not: that is one competition whose name happens to say both.
    const shield = (t, g) => /Shield/i.test(c) && !/Cup\/Shield/i.test(c) ? { ...t, tier: t.tier + 0.5, tierName: `grade ${g} shield` } : t;
    if (m(/National League/i)) { const d = grade(/Div (\w+)/, "?"); return { level: "National league", tier: { "1A": 1, "1B": 2, "2A": 3, "2B": 4, "3A": 5, "3B": 6 }[d] || 9, tierName: "division " + d }; }
    if (m(/U23/)) return graded("Under-23", grade(/U23([A-C])/));
    if (m(/U16/)) { const g = grade(/U16([A-C])/); return shield(graded("Under-16", g), g); }
    if (m(/Minor/i)) { const g = grade(/Minor ([A-C])/); return shield(graded("Minor", g), g); }
    if (m(/Senior/i)) return { level: "Senior championship", tier: 1, tierName: "tier 1, O'Duffy Cup" };
    if (m(/Intermediate/i)) return { level: "Senior championship", tier: 2, tierName: "tier 2" };
    if (m(/Premier Junior/i)) return { level: "Senior championship", tier: 3, tierName: "tier 3" };
    if (m(/Junior/i)) return { level: "Senior championship", tier: 4, tierName: "tier 4" };
    return { level: "Senior championship", tier: 9, tierName: "" };
  }
  function classify(f) {
    const c = clean(f.competition), s = f.sport, m = x => x.test(c);
    if (s === "Camogie") return classifyCamogie(c);
    if (m(/Club Championship/i)) return { level: "Club", tier: m(/Senior/) ? 1 : m(/Intermediate/) ? 2 : 3, tierName: m(/Senior/) ? "senior" : m(/Intermediate/) ? "intermediate" : "junior" };
    if (m(/Post Primary|\bPPS\b|Schools/i)) { const g = (c.match(/Senior ([A-D])\b/) || [])[1] || "?"; return { level: "Schools", tier: "ABCD".indexOf(g) + 1 || 9, tierName: "senior " + g }; }
    if (m(/U20/i)) { const g = (c.match(/U20([A-C])?/) || [])[1] || "A"; return { level: "Under-20", tier: "ABC".indexOf(g) + 1, tierName: g === "A" ? "top grade" : "grade " + g }; }
    if (m(/Minor/i)) { const t = Number((c.match(/Tier (\d)/) || [])[1] || 1); return { level: "Minor", tier: t, tierName: "tier " + t }; }
    if (m(/League/i)) { const d = (c.match(/Roinn (\w+)/) || [])[1] || "?"; return { level: "National league", tier: { "1": 1, "1A": 1, "1B": 2, "2": 3, "3": 4, "4": 5 }[d] || 9, tierName: "division " + d }; }
    if (s === "Hurling") {
      if (m(/Senior Championship/)) return { level: "Senior championship", tier: 1, tierName: "tier 1, Liam MacCarthy Cup" };
      if (m(/Joe McDonagh/)) return { level: "Senior championship", tier: 2, tierName: "tier 2" };
      if (m(/Christy Ring/)) return { level: "Senior championship", tier: 3, tierName: "tier 3" };
      if (m(/Nickey Rackard/)) return { level: "Senior championship", tier: 4, tierName: "tier 4" };
      if (m(/Lory Meagher/)) return { level: "Senior championship", tier: 5, tierName: "tier 5" };
    } else {
      if (m(/Senior Championship/)) return { level: "Senior championship", tier: 1, tierName: "tier 1, Sam Maguire Cup" };
      if (m(/Tailteann/)) return { level: "Senior championship", tier: 2, tierName: "tier 2" };
      if (m(/Junior Championship/)) return { level: "Senior championship", tier: 3, tierName: "tier 3, junior counties" };
    }
    return { level: "Senior championship", tier: 9, tierName: "" };
  }
  const TV = { tg4: "TG4", "spórt tg4": "TG4", "spórt tg4 youtube": "TG4 YouTube", "tg4 (deferred)": "TG4, deferred", "tg4 player/app | deferred": "TG4 Player, deferred", "tg4 player": "TG4 Player", gaaplus: "GAA+", rte: "RTÉ", rtebbc: "RTÉ and BBC", rtenews: "RTÉ News", "bbc iplayer gaa plus": "BBC iPlayer and GAA+", "bbc iplayer & gaa+": "BBC iPlayer and GAA+", bbc: "BBC" };
  const tv = f => f.tv ? TV[clean(f.tv).toLowerCase()] || clean(f.tv) : "";
  const round = f => clean(f.round).replace(/FInal/, "Final");

  const fixtures = [...fx.fixtures, ...cam.fixtures].map(f => Object.assign(f, classify(f), { short: shortName(f.competition), teams: fold(f.home.name + " " + f.away.name) }));
  fixtures.sort((a, b) => a.date.localeCompare(b.date));
  const first = fixtures[0].date.slice(0, 10), last = fixtures[fixtures.length - 1].date.slice(0, 10);

  // Scores: GAA convention is goals-points; a goal is three points, so give the total too.
  const total = (g, p) => g * 3 + p;
  const teamLine = f => {
    const h = esc(f.home.name), a = esc(f.away.name);
    if (!f.score || f.score.hg == null) return `${h} v ${a}`;
    const { hg, hp, ag, ap } = f.score, ht = total(hg, hp), at = total(ag, ap);
    const H = `${h} ${hg}-${hp}`, A = `${a} ${ag}-${ap}`;
    return `${ht > at ? `<b>${H}</b>` : H} <span class="tag">(${ht})</span> v ${ht < at ? `<b>${A}</b>` : A} <span class="tag">(${at})</span>`;
  };

  // ---- Controls ---------------------------------------------------------------------
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const p = new URLSearchParams(location.search);
  const upcoming = fixtures.some(f => new Date(f.date) >= today);
  const plus = (s, n) => { const d = local(s); d.setDate(d.getDate() + n); return day(d); };
  const defaultFrom = upcoming ? day(today) : first, defaultTo = upcoming ? plus(day(today), 42) : last;
  // Both pickers are bounded to the season and to each other ("to" cannot precede "from");
  // fixing one side moves the other rather than leaving an empty range. Empty means unbounded.
  $("from").min = $("to").min = first; $("from").max = $("to").max = last;
  $("from").value = p.has("from") ? p.get("from") : defaultFrom;
  $("to").value = p.has("to") ? p.get("to") : defaultTo;
  function linkDates(changed) {
    const f = $("from"), t = $("to");
    if (f.value && t.value && t.value < f.value) { if (changed === "from") t.value = f.value; else f.value = t.value; }
    t.min = f.value || first; f.max = t.value || last;
  }
  const setDates = (f, t) => { $("from").value = f; $("to").value = t; linkDates(); render(); };
  $("from").addEventListener("change", () => { linkDates("from"); render(); });
  $("to").addEventListener("change", () => { linkDates("to"); render(); });
  $("clear-dates").addEventListener("click", () => setDates("", ""));
  const shift = dir => {
    const f = $("from").value || first, t = $("to").value || last;
    const len = Math.round((local(t) - local(f)) / 864e5) + 1;
    setDates(plus(f, dir * len), plus(t, dir * len));
  };
  $("earlier").addEventListener("click", () => shift(-1));
  $("later").addEventListener("click", () => shift(1));
  linkDates();
  if (!upcoming || p.has("results")) $("results").checked = true;
  $("season").textContent = upcoming
    ? `The ${first.slice(0, 4)} season runs ${fmtShort(first)} to ${fmtShort(last)}; ${fixtures.filter(f => new Date(f.date) >= today).length} fixtures still to play.`
    : `The ${first.slice(0, 4)} season is over (${fmtShort(first)} to ${fmtShort(last)}, ${fixtures.length} matches). ${Number(first.slice(0, 4)) + 1} fixtures will appear here once published on gaa.ie and camogie.ie.`;

  for (const l of LEVELS) if (fixtures.some(f => f.level === l)) $("level").insertAdjacentHTML("beforeend", `<option value="${esc(l)}">${esc(l.toLowerCase())}</option>`);
  if (p.get("level")) $("level").value = p.get("level");
  $("team").value = p.get("team") || "";
  if (p.has("sport")) for (const cb of document.querySelectorAll("input[name=sport]")) cb.checked = p.getAll("sport").includes(cb.value);

  // Competition select: grouped by sport and level, ordered by tier, sponsor names stripped.
  const comps = new Map();
  for (const f of fixtures) if (f.competition && !comps.has(f.competition)) comps.set(f.competition, { name: f.competition, short: f.short, sport: f.sport, level: f.level, tier: f.tier, tierName: f.tierName, n: 0 });
  for (const f of fixtures) if (f.competition) comps.get(f.competition).n++;
  const compList = [...comps.values()].sort((a, b) => a.sport.localeCompare(b.sport) || LEVELS.indexOf(a.level) - LEVELS.indexOf(b.level) || a.tier - b.tier || a.short.localeCompare(b.short));
  function fillComps() {
    const sports = [...document.querySelectorAll("input[name=sport]:checked")].map(cb => cb.value);
    const level = $("level").value, keep = $("comp").value;
    $("comp").innerHTML = '<option value="">all</option>';
    let group = null, el = null;
    for (const c of compList) {
      if (!sports.includes(c.sport) || (level && c.level !== level)) continue;
      const g = `${c.sport.toLowerCase()}: ${c.level.toLowerCase()}`;
      if (g !== group) { group = g; el = document.createElement("optgroup"); el.label = g; $("comp").appendChild(el); }
      el.insertAdjacentHTML("beforeend", `<option value="${esc(c.name)}">${esc(c.short)}${c.tierName && c.level !== "National league" ? ` (${esc(c.tierName.replace(/,.*/, ""))})` : ""}</option>`);
    }
    $("comp").value = keep; if ($("comp").value !== keep) $("comp").value = "";
  }
  fillComps();
  if (p.get("comp")) { $("comp").value = p.get("comp"); if ($("comp").value !== p.get("comp")) { $("level").value = ""; fillComps(); $("comp").value = p.get("comp"); } }

  // Presets: quick ranges, and the months of the season for browsing back through it.
  const presets = [];
  if (upcoming) presets.push(["this week", day(today), day(new Date(today.getTime() + 7 * 864e5))], ["next 4 weeks", day(today), day(new Date(today.getTime() + 28 * 864e5))]);
  presets.push(["whole season", first, last]);
  const months = [...new Set(fixtures.map(f => irishDay(f.date).slice(0, 7)))].sort();
  for (const m of months) { const d = local(m + "-01"); presets.push([d.toLocaleDateString("en-IE", { month: "short" }), m + "-01", day(new Date(d.getFullYear(), d.getMonth() + 1, 0))]); }
  $("presets").innerHTML = presets.map(([n, a, b]) => `<a href="#" data-from="${a}" data-to="${b}">${esc(n)}</a>`).join("");
  $("presets").addEventListener("click", ev => {
    const a = ev.target.closest("a[data-from]"); if (!a) return;
    ev.preventDefault(); setDates(a.dataset.from, a.dataset.to);
  });
  $("reset").addEventListener("click", () => {
    for (const cb of document.querySelectorAll("input[name=sport]")) cb.checked = true;
    $("level").value = ""; fillComps(); $("comp").value = ""; $("team").value = ""; $("results").checked = !upcoming;
    setDates(defaultFrom, defaultTo);
  });

  // The guide: the season's shape, with the whole season's fixture counts, every name a filter.
  $("guide-body").innerHTML = SPORTS.filter(sport => compList.some(c => c.sport === sport)).map(sport => `<h3>${sport}</h3><dl>` + LEVELS.filter(l => compList.some(c => c.sport === sport && c.level === l)).map(l => {
    const cs = compList.filter(c => c.sport === sport && c.level === l);
    const byTier = new Map(); for (const c of cs) { if (!byTier.has(c.tier)) byTier.set(c.tier, []); byTier.get(c.tier).push(c); }
    const line = c => `<a href="#" data-comp="${esc(c.name)}">${esc(c.short)}</a> <span class="tag">${c.n}</span>`;
    return `<dt>${esc(l)}<span class="tag">, ${esc(LEVEL_NOTE[l])}</span></dt>` + [...byTier.values()].map(list =>
      `<dd>${l !== "National league" ? `<span class="tier">${esc(list[0].tierName.replace(/,.*/, ""))}</span> ` : ""}${list.map(line).join(", ")}${/,/.test(list[0].tierName) ? ` <span class="tag">(${esc(list[0].tierName.replace(/^[^,]*, /, ""))})</span>` : ""}</dd>`).join("");
  }).join("") + "</dl>").join("");
  $("guide-body").addEventListener("click", ev => {
    const a = ev.target.closest("a[data-comp]"); if (!a) return;
    ev.preventDefault();
    const c = comps.get(a.dataset.comp);
    for (const cb of document.querySelectorAll("input[name=sport]")) cb.checked = cb.value === c.sport;
    $("level").value = c.level; fillComps(); $("comp").value = c.name;
    $("from").value = first; $("to").value = last; $("results").checked = true;
    render(); $("count").scrollIntoView({ behavior: "smooth" });
  });

  // ---- Map and list -----------------------------------------------------------------
  const map = L.map("map").setView([53.4, -7.9], 7);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "&copy; OpenStreetMap contributors" }).addTo(map);
  const layer = L.layerGroup().addTo(map);
  // Colour says which game is played, size says the level (and, within the senior
  // championship, the tier). Camogie is the same game as hurling, so it takes the same
  // colour rather than a fourth hue: grey then keeps meaning "more than one game here",
  // and a ground with hurling and camogie on it stays green, which is the truth.
  const CODE = { Football: "football", Hurling: "hurling", Camogie: "hurling" };
  const FILL = { football: "#e0864f", hurling: "#5aa06e", both: "#9a8a7a" };
  const RADIUS = { "Senior championship": 12, "National league": 9, "Under-23": 7, "Under-20": 7, Club: 7, Minor: 6, "Under-16": 5, Schools: 5 };
  const radiusOf = f => f.level === "Senior championship" ? Math.max(7, RADIUS[f.level] - 1.5 * (Math.min(f.tier, 5) - 1)) : RADIUS[f.level];
  const rankOf = f => LEVELS.indexOf(f.level) * 10 + f.tier;
  $("legend").innerHTML = `<span><i class="dot football"></i>football</span><span><i class="dot hurling"></i>hurling and camogie</span><span><i class="dot both"></i>both games</span>`
    + `<span class="key">size is the level:</span>` + [[12, "senior, tier 1"], [9, "lower tiers"], [9, "league"], [7, "under-23, under-20, club"], [6, "minor"], [5, "under-16, schools"]].map(([r, n]) => `<span><i class="size" style="width:${r * 1.3}px;height:${r * 1.3}px"></i>${n}</span>`).join("") + `<span class="key">click a dot for the list</span>`;
  let dots = [];  // { marker, base, radius, label, rank }
  // Dots grow a little as the map zooms in past the whole-island view, so the small ones stay visible.
  const grow = () => Math.min(5, Math.max(0, map.getZoom() - 7) * .8);
  map.on("zoomend", () => { const g = grow(); for (const d of dots) { d.radius = d.base + g; d.marker.setRadius(d.radius); } });
  // Map labels: the venue without its naming-rights sponsor, and without the town where the name stands alone.
  const VENUE_SPONSOR = /^(Hastings Insurance|SuperValu|FBD|Zimmer Biomet|Cedral|Laois Hire|BOX-IT|Glennon Brothers?'?s?|Heartland Credit Union|King & Moffatt|Kingspan|Netwatch|O'Neills|TEG|TUS|UPMC|Azzurri|Chadwicks|DEFY|Glenisk|Grant Heating|Cappoquin Logistics|Find Insurance|Integral|Protection & Prosperity)\s+/i;
  // gaa.ie gives one ground several ids; venues.json points the extras at a canonical one.
  const canon = id => (venues[id] && venues[id].same) || id;
  const venueLabel = name => clean(name).replace(VENUE_SPONSOR, "").replace(/^Breffni/, "Breffni Park").replace(/\s+-\s+/, ", ");

  // Label a dot with its venue where there is room: top-level dots first, a label goes to the
  // right of its dot, else left, above, or below, wherever the box overlaps no other label or dot.
  function placeLabels() {
    const size = map.getSize(), taken = [];
    const hit = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
    const pts = dots.map(d => ({ d, pt: map.latLngToContainerPoint(d.marker.getLatLng()) }));
    for (const { d, pt } of pts) taken.push({ x: pt.x - d.radius, y: pt.y - d.radius, w: 2 * d.radius, h: 2 * d.radius });
    const ordered = pts.slice().sort((a, b) => a.d.rank - b.d.rank || b.d.radius - a.d.radius);
    for (const { d, pt } of ordered) {
      d.marker.unbindTooltip();
      if (pt.x < -20 || pt.y < -20 || pt.x > size.x + 20 || pt.y > size.y + 20) continue;
      const w = d.label.length * 6.6 + 12, h = 17;
      const r = d.radius + 2;
      const spots = { right: [{ x: pt.x + r, y: pt.y - h / 2, w, h }, [r, 0]], left: [{ x: pt.x - r - w, y: pt.y - h / 2, w, h }, [-r, 0]],
        top: [{ x: pt.x - w / 2, y: pt.y - r - h, w, h }, [0, -r]], bottom: [{ x: pt.x - w / 2, y: pt.y + r, w, h }, [0, r]] };
      const fits = box => box.x >= 0 && box.x + box.w <= size.x && box.y >= 0 && box.y + box.h <= size.y && !taken.some(t => hit(box, t));
      const side = Object.keys(spots).find(k => fits(spots[k][0]));
      if (!side) continue;
      taken.push(spots[side][0]);
      d.marker.bindTooltip(d.label, { permanent: true, direction: side, className: "marker-label", offset: spots[side][1] });
    }
  }
  map.on("zoomend moveend", placeLabels);

  function selected() {
    const from = $("from").value, to = $("to").value;
    const sports = [...document.querySelectorAll("input[name=sport]:checked")].map(cb => cb.value);
    const level = $("level").value, comp = $("comp").value, results = $("results").checked, team = fold($("team").value);
    return fixtures.filter(f => {
      const d = irishDay(f.date);
      return (!from || d >= from) && (!to || d <= to) && sports.includes(f.sport) && (!level || f.level === level) && (!comp || f.competition === comp) && (!team || f.teams.includes(team)) && (results || !f.result);
    });
  }

  // "Tailteann Cup, Round 1, senior football championship, tier 2": the sport only when the name does not say it.
  const detail = f => {
    const sport = new RegExp(f.sport, "i").test(f.short) ? "" : f.sport.toLowerCase() + " ";
    const tier = f.level === "Senior championship" || f.level === "Minor" ? ", " + f.tierName.replace(/,.*/, "") : /^Under-/.test(f.level) && f.tier > 1 ? ", " + f.tierName : "";
    // Camogie's top competition is called just "Senior Championship", so the usual phrasing
    // would read "Senior Championship, ..., senior camogie championship". Say it once.
    const level = f.level === "Senior championship"
      ? (f.sport === "Camogie" && /senior/i.test(f.short) ? "camogie championship" : `senior ${sport}championship`)
      : `${sport}${f.level.toLowerCase()}`;
    return `${esc(f.short)}${f.round ? ", " + esc(round(f)) : ""}, ${esc(level + tier)}`;
  };

  // gaa.ie gives the match page as a path, camogie.ie as a whole URL. Build the link from
  // whichever it is and name it after the site it actually goes to.
  const source = f => {
    if (!f.url) return "";
    const href = /^https?:/i.test(f.url) ? f.url : "https://www.gaa.ie" + f.url;
    let host; try { host = new URL(href).host.replace(/^www\./, ""); } catch { return ""; }
    return `, <a href="${esc(href)}" rel="noopener">${esc(host)}</a>`;
  };

  function render() {
    const shown = selected();
    const u = new URL(location.href);
    u.searchParams.set("from", $("from").value); u.searchParams.set("to", $("to").value);
    for (const k of ["level", "comp", "team"]) $(k).value.trim() ? u.searchParams.set(k, $(k).value.trim()) : u.searchParams.delete(k);
    $("results").checked ? u.searchParams.set("results", "") : u.searchParams.delete("results");
    u.searchParams.delete("sport");
    const sports = [...document.querySelectorAll("input[name=sport]:checked")].map(cb => cb.value);
    if (sports.length !== SPORTS.length) for (const s of sports) u.searchParams.append("sport", s);
    history.replaceState(null, "", u);

    layer.clearLayers(); dots = [];
    const byVenue = new Map();  // keyed by the canonical venue id (see scripts/merge_venues.py)
    for (const f of shown) { const k = canon(f.venueId); if (!byVenue.has(k)) byVenue.set(k, []); byVenue.get(k).push(f); }
    let unplaced = 0;
    for (const [vid, list] of byVenue) {
      const v = venues[vid];
      if (!v || v.lat == null) { unplaced += list.length; continue; }
      const kinds = new Set(list.map(f => CODE[f.sport])), fill = kinds.size > 1 ? FILL.both : FILL[[...kinds][0]];
      const best = list.slice().sort((a, b) => rankOf(a) - rankOf(b))[0], base = radiusOf(best), radius = base + grow();
      const m = L.circleMarker([v.lat, v.lon], { radius, color: "#333", weight: 1, fillColor: fill, fillOpacity: .85 }).addTo(layer);
      dots.push({ marker: m, base, radius, label: venueLabel(v.name), rank: rankOf(best) });
      m.bindPopup(`<div class="pop"><b>${esc(v.name)}</b>${list.map(f => `${fmtDate(f.date)} ${fmtTime(f)}, ${esc(f.home.name)} v ${esc(f.away.name)}<br><small>${detail(f)}</small>`).join("<br>")}</div>`, { maxWidth: 320 });
    }

    placeLabels();

    const byDay = new Map();
    for (const f of shown) { const d = irishDay(f.date); if (!byDay.has(d)) byDay.set(d, []); byDay.get(d).push(f); }
    $("list").innerHTML = shown.length ? [...byDay.keys()].sort().map(d => `
      <h2>${fmtDate(d)}</h2>
      <table>${byDay.get(d).sort((a, b) => a.date.localeCompare(b.date) || LEVELS.indexOf(a.level) - LEVELS.indexOf(b.level) || a.tier - b.tier).map(f => `
        <tr><td class="when">${fmtTime(f)}</td>
            <td>${teamLine(f)}<br><small class="tag">${detail(f)}${tv(f) ? ", " + esc(tv(f)) : ""}${f.tickets ? `, <a href="${esc(f.tickets)}" rel="noopener">tickets</a>` : ""}${source(f)}</small></td>
            <td class="venue">${venues[canon(f.venueId)] && venues[canon(f.venueId)].lat != null ? `<a href="#map" data-venue="${esc(canon(f.venueId))}">${esc(f.venue)}</a>` : esc(f.venue) || '<span class="tag">venue TBC</span>'}</td></tr>`).join("")}
      </table>`).join("") : `<p class="none">No fixtures match. ${$("results").checked ? "Widen the dates or clear a filter." : 'Widen the dates, clear a filter, or tick "include played matches".'}</p>`;
    const fv = $("from").value, tvv = $("to").value;
    const range = fv && tvv ? `, ${fmtShort(fv)} to ${fmtShort(tvv)}` : fv ? `, from ${fmtShort(fv)}` : tvv ? `, to ${fmtShort(tvv)}` : ", whole season";
    $("count").textContent = `${shown.length} fixture${shown.length === 1 ? "" : "s"} at ${byVenue.size} venue${byVenue.size === 1 ? "" : "s"}${range}${unplaced ? ` (${unplaced} at venues not yet on the map)` : ""}.`;
  }

  $("list").addEventListener("click", ev => {
    const a = ev.target.closest("a[data-venue]"); if (!a) return;
    const v = venues[a.dataset.venue]; map.setView([v.lat, v.lon], 11);
    layer.eachLayer(m => { const ll = m.getLatLng(); if (ll.lat === v.lat && ll.lng === v.lon) m.openPopup(); });
  });
  for (const el of document.querySelectorAll("#f input:not([type=date]), #f select")) el.addEventListener(el.id === "team" ? "input" : "change", () => { if (el.id === "level" || el.name === "sport") fillComps(); render(); });
  $("meta").textContent = `Fixtures fetched from gaa.ie on ${fx.fetched.slice(0, 10)}: ${fixtures.length} matches, ${fmtShort(first)} to ${fmtShort(last)} ${first.slice(0, 4)}, ${comps.size} competitions. Competition names are gaa.ie's with the sponsor dropped; the level and tier labels are this site's reading of them.`;
  render();
})();
