(async function () {
  const $ = id => document.getElementById(id);
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

  // ---- Seasons ----------------------------------------------------------------------
  // data/seasons.json indexes one file per source per season (see scripts/data.py). Only
  // the season being looked at is downloaded; the newest is the one that opens, because
  // that is the season anyone arriving here is asking about. An older season is fetched
  // when it is picked, and kept once fetched.
  const index = await fetch("data/seasons.json", { cache: "no-cache" }).then(r => r.json());
  const venues = await fetch("venues.json", { cache: "no-cache" }).then(r => r.json());
  const SEASONS = index.seasons;                       // newest first
  const loaded = new Map();
  async function seasonRows(year) {
    if (!loaded.has(year)) {
      const season = SEASONS.find(s => s.year === year);
      // One failed source must not empty the map: the others still draw.
      const parts = await Promise.all(season.sources.map(src =>
        fetch(src.file, { cache: "no-cache" }).then(r => r.ok ? r.json() : null).catch(() => null)));
      loaded.set(year, season.sources.map((src, i) => ({ src, rows: (parts[i] || { fixtures: [] }).fixtures })));
    }
    return loaded.get(year);
  }

  // ---- Making sense of the competition names ---------------------------------------
  // All three sites list every competition as a flat sponsor-prefixed name. The GAA's season has a
  // shape, though: senior inter-county championship (in tiers), the spring national league
  // (in divisions), the age grades, the All-Ireland stages of the club championship,
  // and the post-primary schools finals; and, from the county and provincial sites, the club
  // championships, which the site marks as such (f.club) because a county's "Senior Football
  // Championship" is named exactly like the county team's. Classify each fixture into a level and a tier so the
  // page can show that shape. Rules are by name, so a new competition next season still lands
  // somewhere sensible.
  const SPORTS = ["Football", "Hurling", "Camogie", "Ladies' Football"];
  const LEVELS = ["Senior championship", "National league", "Under-23", "Under-20", "Under-18", "Minor", "Under-16", "Under-14", "Third level", "Club", "Schools"];
  const LEVEL_NOTE = {
    "Senior championship": "the summer championship for county teams",
    "National league": "the spring league for county teams, with promotion and relegation between divisions",
    "Under-23": "county teams, under-23s (camogie's grade; the GAA's equivalent is under-20)",
    "Under-20": "county teams, under-20s",
    "Under-18": "county teams, under-18s (the LGFA's grade; the GAA's equivalent is minor)",
    Minor: "county teams, under-17s",
    "Under-16": "county teams, under-16s",
    "Under-14": "county teams, under-14s",
    "Third level": "the All-Ireland third-level championships, between universities and colleges; the cups below the Lynch Cup are not ranked here",
    Club: "the club championships: county rounds from the county boards that publish them (about half do, see the note at the foot of the page), the provincial series, and the All-Ireland stages from gaa.ie",
    Schools: "post-primary schools' All-Ireland finals",
  };
  const SPONSOR = /^(AIB|Allianz|Electric Ireland|Fulfil|Dalata Hotel Group|Masita|Beko|Bord Gáis Energy|EirGrid|Lidl|Glen Dimplex|Very)\s+(GAA\s+)?/i;
  const shortName = c => clean(c).replace(SPONSOR, "").replace(/\bGAA\s+/, "").replace(/\bRoinn\b/, "Division").replace(/\s+-\s+/, ", ")
    .replace(/^(Football|Hurling) All-Ireland (Senior|Intermediate|Junior|U20\w*) (Club )?Championship/, "All-Ireland $2 $3$1 Championship")
    .replace(/^(Connacht|Leinster|Munster|Ulster) (Football|Hurling) Senior Championship/, "$1 Senior $2 Championship");
  const graded = (level, g) => ({ level, tier: "ABC".indexOf(g) + 1 || 9, tierName: g === "A" ? "top grade" : "grade " + g });
  // Camogie's own ladder: senior down to junior in the championship, five league divisions,
  // and under-23/minor/under-16 grades lettered A to C, some with a Shield for teams knocked
  // out of the Cup. Named nothing like the GAA's competitions, so classified on its own terms.
  function classifyCamogie(c) {
    const m = x => x.test(c);
    const grade = (re, fallback = "A") => (c.match(re) || [])[1] || fallback;
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
  // Ladies' football's ladder: the same senior/intermediate/junior championship shape as the
  // men's game, four league divisions, age grades at under-20, under-18 (where the GAA says
  // minor), under-16 and under-14, and a set of third-level cups the other three sources have
  // no equivalent of. Only the senior cup is named here: the O'Connor Cup's place at the top of
  // the third-level ladder and the Giles and Lynch cups below it are settled, but the order of
  // the remaining four is not, so they are left unranked rather than guessed at.
  function classifyLadies(c) {
    const m = x => x.test(c);
    if (m(/National Football League/i)) { const d = (c.match(/Division (\d)/) || [])[1] || "?"; return { level: "National league", tier: Number(d) || 9, tierName: "division " + d }; }
    if (m(/^HEC/)) {
      const t = { "O'Connor": [1, "top tier"], Giles: [2, "second tier"], Lynch: [3, "third tier"] }[(c.match(/HEC ([\w']+)/) || [])[1]] || [9, ""];
      return { level: "Third level", tier: t[0], tierName: t[1] };
    }
    if (m(/Post Primary Schools/i)) {
      const [, age, g] = c.match(/(Senior|Junior) ([A-C])/) || [, "Senior", "?"];
      return { level: "Schools", tier: (age === "Senior" ? 0 : 3) + ("ABC".indexOf(g) + 1 || 9), tierName: `${age.toLowerCase()} ${g}` };
    }
    if (m(/U-20/)) return { level: "Under-20", tier: 1, tierName: "top grade" };
    if (m(/U-18/)) return graded("Under-18", (c.match(/U-18([A-C])/) || [])[1] || "A");
    if (m(/U-16/)) return graded("Under-16", (c.match(/U-16([A-C])/) || [])[1] || "A");
    if (m(/U-14/)) return { level: "Under-14", tier: 1, tierName: "" };
    if (m(/Senior/i)) return { level: "Senior championship", tier: 1, tierName: "tier 1, Brendan Martin Cup" };
    if (m(/Intermediate/i)) return { level: "Senior championship", tier: 2, tierName: "tier 2" };
    if (m(/Junior/i)) return { level: "Senior championship", tier: 3, tierName: "tier 3" };
    return { level: "Senior championship", tier: 9, tierName: "" };
  }
  function classify(f) {
    const c = clean(f.competition), s = f.sport, m = x => x.test(c);
    // Club first, whatever the code: a county's "Senior Camogie Championship" is a club
    // competition. The grade is read from the name before the site's filing, because a
    // county files its intermediate and junior championships under "senior" often enough.
    if (f.club || m(/Club Championship/i)) {
      const g = m(/\bSenior\b/i) && !m(/\bJunior\b/i) ? "senior" : m(/\bIntermediate\b/i) ? "intermediate" : m(/\bJunior\b/i) ? "junior" : f.grade || "senior";
      return { level: "Club", tier: { senior: 1, intermediate: 2, junior: 3 }[g] || 9, tierName: g };
    }
    if (s === "Camogie") return classifyCamogie(c);
    if (s === "Ladies' Football") return classifyLadies(c);
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

  // Scores: GAA convention is goals-points; a goal is three points, so give the total too.
  const total = (g, p) => g * 3 + p;
  const teamLine = f => {
    const h = esc(f.home.name), a = esc(f.away.name);
    if (!f.score || f.score.hg == null) return `${h} v ${a}`;
    const { hg, hp, ag, ap } = f.score, ht = total(hg, hp), at = total(ag, ap);
    const H = `${h} ${hg}-${hp}`, A = `${a} ${ag}-${ap}`;
    return `${ht > at ? `<b>${H}</b>` : H} <span class="tag">(${ht})</span> v ${ht < at ? `<b>${A}</b>` : A} <span class="tag">(${at})</span>`;
  };

  // "Tailteann Cup, Round 1, senior football championship, tier 2": the sport only when the name does not say it.
  const detail = f => {
    const sport = new RegExp(f.sport, "i").test(f.short) ? "" : f.sport.toLowerCase() + " ";
    const tier = f.level === "Senior championship" || f.level === "Minor" ? ", " + f.tierName.replace(/,.*/, "") : /^Under-/.test(f.level) && f.tier > 1 ? ", " + f.tierName : f.level === "Third level" && f.tierName ? ", " + f.tierName.replace(/,.*/, "") : "";
    // Camogie's top competition is called just "Senior Championship", so the usual phrasing
    // would read "Senior Championship, ..., senior camogie championship". Say it once.
    const level = f.level === "Senior championship"
      ? (f.sport === "Camogie" && /senior/i.test(f.short) ? "camogie championship" : `senior ${sport}championship`)
      : f.level === "Third level" ? `third-level ${f.sport.toLowerCase()}`
      : f.level === "Club" ? `${f.club === "county" ? "county" : f.club === "provincial" ? "provincial" : "All-Ireland"} club ${sport}`.trim() + `, ${f.tierName}`
      : `${sport}${f.level.toLowerCase()}`;
    return `${esc(f.short)}${f.group ? ", " + esc(f.group) : ""}${f.round ? ", " + esc(round(f)) : ""}, ${esc(level + tier)}`;
  };

  // gaa.ie gives the match page as a path, the other two a whole URL. Build the link from
  // whichever it is and name it after the site it actually goes to.
  const source = f => {
    if (!f.url) return "";
    const href = /^https?:/i.test(f.url) ? f.url : "https://www.gaa.ie" + f.url;
    let host; try { host = new URL(href).host.replace(/^www\./, ""); } catch { return ""; }
    return `, <a href="${esc(href)}" rel="noopener">${esc(host)}</a>`;
  };

  // ---- Map --------------------------------------------------------------------------
  const map = L.map("map").setView([53.4, -7.9], 7);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "&copy; OpenStreetMap contributors" }).addTo(map);
  const layer = L.layerGroup().addTo(map);
  // Colour says which game is played, size says the level (and, within the senior
  // championship, the tier). Camogie is the same game as hurling and ladies' football the
  // same game as football, so each takes its code's colour rather than a hue of its own:
  // grey then keeps meaning "more than one game here", and a ground with hurling and
  // camogie on it stays green, which is the truth.
  const CODE = { Football: "football", "Ladies' Football": "football", Hurling: "hurling", Camogie: "hurling" };
  const FILL = { football: "#e0864f", hurling: "#5aa06e", both: "#9a8a7a" };
  const RADIUS = { "Senior championship": 12, "National league": 9, "Under-23": 7, "Under-20": 7, Club: 7, "Third level": 7, "Under-18": 6, Minor: 6, "Under-16": 5, "Under-14": 5, Schools: 5 };
  // A county round of the club championship is a smaller dot than the provincial and All-Ireland stages.
  const radiusOf = f => f.level === "Senior championship" ? Math.max(7, RADIUS[f.level] - 1.5 * (Math.min(f.tier, 5) - 1)) : f.club === "county" ? 6 : RADIUS[f.level] || 5;
  const rankOf = f => LEVELS.indexOf(f.level) * 10 + f.tier;
  $("legend").innerHTML = `<span><i class="dot football"></i>football and ladies' football</span><span><i class="dot hurling"></i>hurling and camogie</span><span><i class="dot both"></i>both games</span>`
    + `<span class="key">size is the level:</span>` + [[12, "senior, tier 1"], [9, "lower tiers"], [9, "league"], [7, "under-23, under-20, provincial and All-Ireland club, third level"], [6, "county club, under-18, minor"], [5, "under-16, under-14, schools"]].map(([r, n]) => `<span><i class="size" style="width:${r * 1.3}px;height:${r * 1.3}px"></i>${n}</span>`).join("") + `<span class="key">click a dot for the matches there</span>`;
  let dots = [];  // { marker, base, radius, label, rank }
  // Dots grow a little as the map zooms in past the whole-island view, so the small ones stay visible.
  const grow = () => Math.min(5, Math.max(0, map.getZoom() - 7) * .8);
  map.on("zoomend", () => { const g = grow(); for (const d of dots) { d.radius = d.base + g; d.marker.setRadius(d.radius); } });
  // Map labels: the venue without its naming-rights sponsor, and without the town where the name stands alone.
  const VENUE_SPONSOR = /^(Hastings Insurance|SuperValu|FBD|Zimmer Biomet|Cedral|Laois Hire|BOX-IT|Glennon Brothers?'?s?|Heartland Credit Union|King & Moffatt|Kingspan|Netwatch|O'Neills|TEG|TUS|UPMC|Azzurri|Chadwicks|DEFY|Glenisk|Grant Heating|Cappoquin Logistics|Find Insurance|Integral|Protection & Prosperity|Manguard Plus|Cullen Auto Parts|MW Hire|Samaritans)\s+/i;
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

  // A dot's popup is a list of matches, not a paragraph of them: one block each, ruled off
  // from its neighbours, and a link down to the same match in the day-by-day list, where the
  // score, the television, the tickets and the link to the source page already are. Leaflet
  // scrolls the popup itself once it passes maxHeight, which busy grounds do quickly.
  const popup = (v, list) => `<div class="pop"><b>${esc(v.name)}</b>`
    + `<span class="tag">${list.length} match${list.length === 1 ? "" : "es"} here${list.length > 3 ? ", scroll for the rest" : ""}</span>`
    + `<ol>` + list.map(f => `<li>
        <span class="pop-when">${fmtDate(f.date)}, ${fmtTime(f)}</span>
        <span class="pop-teams">${teamLine(f)}</span>
        <span class="pop-detail">${detail(f)}</span>
        <a class="pop-jump" href="#${f.row}" data-jump="${f.row}">see it in the list below</a>
      </li>`).join("") + `</ol></div>`;

  // Sized from the map, not from a constant: a popup taller than the map cannot be panned
  // into it, and on a phone a fixed 300px one hangs off the top edge. The extra padding at
  // the top keeps it clear of the zoom buttons, which Leaflet always draws above a popup.
  const popupSize = () => ({
    maxWidth: Math.min(340, Math.max(200, map.getSize().x - 40)),
    minWidth: Math.min(240, Math.max(180, map.getSize().x - 60)),
    maxHeight: Math.max(150, Math.min(320, map.getSize().y - 190)),
    autoPanPaddingTopLeft: [10, 84],
    autoPanPaddingBottomRight: [10, 10],
  });

  function jumpTo(rowId) {
    const el = document.getElementById(rowId);
    if (!el) return;
    map.closePopup();
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    for (const old of document.querySelectorAll(".lit")) old.classList.remove("lit");
    el.classList.add("lit");
  }
  map.getContainer().addEventListener("click", ev => {
    const a = ev.target.closest("a[data-jump]");
    if (!a) return;
    ev.preventDefault();
    jumpTo(a.dataset.jump);
  });

  // ---- Per-season state -------------------------------------------------------------
  let fixtures = [], comps = new Map(), compList = [], sources = [];
  let first, last, upcoming, defaultFrom, defaultTo, year;

  const p = new URLSearchParams(location.search);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const plus = (s, n) => { const d = local(s); d.setDate(d.getDate() + n); return day(d); };

  function linkDates(changed) {
    const f = $("from"), t = $("to");
    if (f.value && t.value && t.value < f.value) { if (changed === "from") t.value = f.value; else f.value = t.value; }
    t.min = f.value || first; f.max = t.value || last;
  }
  const setDates = (f, t) => { $("from").value = f; $("to").value = t; linkDates(); render(); };
  $("from").addEventListener("change", () => { linkDates("from"); render(); });
  $("to").addEventListener("change", () => { linkDates("to"); render(); });
  $("clear-dates").addEventListener("click", () => setDates("", ""));
  $("earlier").addEventListener("click", () => shift(-1));
  $("later").addEventListener("click", () => shift(1));
  const shift = dir => {
    const f = $("from").value || first, t = $("to").value || last;
    const len = Math.round((local(t) - local(f)) / 864e5) + 1;
    setDates(plus(f, dir * len), plus(t, dir * len));
  };

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

  $("reset").addEventListener("click", () => {
    for (const cb of document.querySelectorAll("input[name=sport]")) cb.checked = true;
    $("level").value = ""; fillComps(); $("comp").value = ""; $("team").value = ""; $("results").checked = !upcoming;
    setDates(defaultFrom, defaultTo);
  });
  $("presets").addEventListener("click", ev => {
    const a = ev.target.closest("a[data-from]"); if (!a) return;
    ev.preventDefault(); setDates(a.dataset.from, a.dataset.to);
  });
  $("guide-body").addEventListener("click", ev => {
    const a = ev.target.closest("a[data-comp]"); if (!a) return;
    ev.preventDefault();
    const c = comps.get(a.dataset.comp);
    for (const cb of document.querySelectorAll("input[name=sport]")) cb.checked = cb.value === c.sport;
    $("level").value = c.level; fillComps(); $("comp").value = c.name;
    $("from").value = first; $("to").value = last; $("results").checked = true;
    render(); $("count").scrollIntoView({ behavior: "smooth" });
  });
  $("list").addEventListener("click", ev => {
    const a = ev.target.closest("a[data-venue]"); if (!a) return;
    // Without animate:false the popup opens mid-flight and Leaflet's auto-pan measures it
    // against a map that is still moving, leaving a tall popup hanging off the top edge.
    const v = venues[a.dataset.venue];
    map.setView([v.lat, v.lon], 11, { animate: false });
    layer.eachLayer(m => { const ll = m.getLatLng(); if (ll.lat === v.lat && ll.lng === v.lon) m.openPopup(); });
  });
  for (const el of document.querySelectorAll("#f input:not([type=date]), #f select:not(#seasonpick)"))
    el.addEventListener(el.id === "team" ? "input" : "change", () => { if (el.id === "level" || el.name === "sport") fillComps(); render(); });

  // Season picker: only worth showing once there is more than one season on file.
  if (SEASONS.length > 1) {
    $("season-row").hidden = false;
    $("seasonpick").innerHTML = SEASONS.map(s => `<option value="${s.year}">${s.year}</option>`).join("");
    $("seasonpick").addEventListener("change", () => useSeason(Number($("seasonpick").value)));
  }

  // Everything that depends on which season is being looked at, rebuilt when it changes.
  // The team and the sports carry over -- they are the same question asked of another season
  // -- while the dates, the level and the competition do not, because another season's
  // calendar and competition list are its own.
  async function useSeason(y, initial) {
    year = y;
    const parts = await seasonRows(y);
    sources = parts.filter(part => part.rows.length).map(part => part.src);
    fixtures = [].concat(...parts.map(part => part.rows))
      .map(f => Object.assign(f, classify(f), { short: shortName(f.competition), teams: fold(f.home.name + " " + f.away.name + " " + (f.county || "")) }));
    fixtures.sort((a, b) => a.date.localeCompare(b.date));
    first = fixtures[0].date.slice(0, 10);
    last = fixtures[fixtures.length - 1].date.slice(0, 10);
    upcoming = fixtures.some(f => new Date(f.date) >= today);
    defaultFrom = upcoming ? day(today) : first;
    defaultTo = upcoming ? plus(day(today), 42) : last;
    if (SEASONS.length > 1) $("seasonpick").value = String(y);

    $("from").min = $("to").min = first; $("from").max = $("to").max = last;
    $("from").value = initial && p.has("from") ? p.get("from") : defaultFrom;
    $("to").value = initial && p.has("to") ? p.get("to") : defaultTo;
    linkDates();
    $("results").checked = !upcoming || (initial && p.has("results"));

    const next = SEASONS[SEASONS.indexOf(SEASONS.find(s => s.year === y)) - 1];
    $("season").textContent = upcoming
      ? `The ${y} season runs ${fmtShort(first)} to ${fmtShort(last)}; ${fixtures.filter(f => new Date(f.date) >= today).length} fixtures still to play.`
      : next
        ? `The ${y} season, ${fixtures.length} matches from ${fmtShort(first)} to ${fmtShort(last)}.`
        : `The ${y} season is over (${fmtShort(first)} to ${fmtShort(last)}, ${fixtures.length} matches). ${y + 1} fixtures will appear here once published on ${sources.map(s => s.site).join(", ").replace(/, ([^,]*)$/, " and $1")}.`;

    // The level menu, the competition menu and the guide are this season's, not every season's.
    $("level").innerHTML = '<option value="">all</option>';
    for (const l of LEVELS) if (fixtures.some(f => f.level === l)) $("level").insertAdjacentHTML("beforeend", `<option value="${esc(l)}">${esc(l.toLowerCase())}</option>`);
    for (const cb of document.querySelectorAll("input[name=sport]")) {
      const has = fixtures.some(f => f.sport === cb.value);
      cb.closest("label").hidden = !has;
      if (initial && p.has("sport")) cb.checked = p.getAll("sport").includes(cb.value);
      else if (!has) cb.checked = true;   // a sport this season has none of filters nothing out
    }
    comps = new Map();
    for (const f of fixtures) if (f.competition && !comps.has(f.competition)) comps.set(f.competition, { name: f.competition, short: f.short, sport: f.sport, level: f.level, tier: f.tier, tierName: f.tierName, n: 0 });
    for (const f of fixtures) if (f.competition) comps.get(f.competition).n++;
    compList = [...comps.values()].sort((a, b) => SPORTS.indexOf(a.sport) - SPORTS.indexOf(b.sport) || LEVELS.indexOf(a.level) - LEVELS.indexOf(b.level) || a.tier - b.tier || a.short.localeCompare(b.short));
    if (initial && p.get("level")) $("level").value = p.get("level");
    fillComps();
    if (initial && p.get("comp")) { $("comp").value = p.get("comp"); if ($("comp").value !== p.get("comp")) { $("level").value = ""; fillComps(); $("comp").value = p.get("comp"); } }
    if (initial) $("team").value = p.get("team") || "";

    // Presets: quick ranges, and the months of the season for browsing back through it.
    const presets = [];
    if (upcoming) presets.push(["this week", day(today), day(new Date(today.getTime() + 7 * 864e5))], ["next 4 weeks", day(today), day(new Date(today.getTime() + 28 * 864e5))]);
    presets.push(["whole season", first, last]);
    for (const m of [...new Set(fixtures.map(f => irishDay(f.date).slice(0, 7)))].sort()) {
      const d = local(m + "-01");
      presets.push([d.toLocaleDateString("en-IE", { month: "short" }), m + "-01", day(new Date(d.getFullYear(), d.getMonth() + 1, 0))]);
    }
    $("presets").innerHTML = presets.map(([n, a, b]) => `<a href="#" data-from="${a}" data-to="${b}">${esc(n)}</a>`).join("");

    // The guide: the season's shape, with the whole season's fixture counts, every name a filter.
    $("guide-body").innerHTML = SPORTS.filter(sport => compList.some(c => c.sport === sport)).map(sport => `<h3>${sport.toLowerCase()}</h3><dl>` + LEVELS.filter(l => compList.some(c => c.sport === sport && c.level === l)).map(l => {
      const cs = compList.filter(c => c.sport === sport && c.level === l);
      const byTier = new Map(); for (const c of cs) { if (!byTier.has(c.tier)) byTier.set(c.tier, []); byTier.get(c.tier).push(c); }
      const line = c => `<a href="#" data-comp="${esc(c.name)}">${esc(c.short)}</a> <span class="tag">${c.n}</span>`;
      return `<dt>${esc(l)}<span class="tag">, ${esc(LEVEL_NOTE[l])}</span></dt>` + [...byTier.values()].map(list =>
        `<dd>${l !== "National league" ? `<span class="tier">${esc(list[0].tierName.replace(/,.*/, ""))}</span> ` : ""}${list.map(line).join(", ")}${/,/.test(list[0].tierName) ? ` <span class="tag">(${esc(list[0].tierName.replace(/^[^,]*, /, ""))})</span>` : ""}</dd>`).join("");
    }).join("") + "</dl>").join("");

    const clubSites = [...new Set(fixtures.filter(f => f.club).map(f => { try { return new URL(f.url).host.replace(/^www\./, ""); } catch { return null; } }).filter(Boolean))].sort();
    $("meta").innerHTML = `${y}: ` + sources.map(s => `${esc(s.count)} from ${esc(s.site)}, fetched ${esc(s.fetched.slice(0, 10))}`).join("; ")
      + `. Competition names are each site's with the sponsor dropped; the level and tier labels are this site's reading of them.`
      + (clubSites.length ? ` Club fixtures come from the boards whose sites can be read (${clubSites.map(esc).join(", ")}); the rest of the counties publish theirs elsewhere, so a county missing here is not a county with no matches. Club fixtures are published a few weeks ahead and refreshed weekly.` : "");
    render();
  }

  function selected() {
    const from = $("from").value, to = $("to").value;
    const sports = [...document.querySelectorAll("input[name=sport]:checked")].map(cb => cb.value);
    const level = $("level").value, comp = $("comp").value, results = $("results").checked, team = fold($("team").value);
    return fixtures.filter(f => {
      const d = irishDay(f.date);
      return (!from || d >= from) && (!to || d <= to) && sports.includes(f.sport) && (!level || f.level === level) && (!comp || f.competition === comp) && (!team || f.teams.includes(team)) && (results || !f.result);
    });
  }

  function render() {
    const shown = selected();
    const u = new URL(location.href);
    u.searchParams.set("from", $("from").value); u.searchParams.set("to", $("to").value);
    for (const k of ["level", "comp", "team"]) $(k).value.trim() ? u.searchParams.set(k, $(k).value.trim()) : u.searchParams.delete(k);
    $("results").checked ? u.searchParams.set("results", "") : u.searchParams.delete("results");
    year === index.latest ? u.searchParams.delete("season") : u.searchParams.set("season", year);
    u.searchParams.delete("sport");
    const sports = [...document.querySelectorAll("input[name=sport]:checked")].map(cb => cb.value);
    if (sports.length !== SPORTS.length) for (const s of sports) u.searchParams.append("sport", s);
    history.replaceState(null, "", u);

    // One id per shown match, so a dot's popup and the list below can point at each other.
    shown.sort((a, b) => a.date.localeCompare(b.date) || LEVELS.indexOf(a.level) - LEVELS.indexOf(b.level) || a.tier - b.tier);
    shown.forEach((f, i) => { f.row = "m" + i; });

    layer.clearLayers(); dots = [];
    const byVenue = new Map();  // keyed by the canonical venue id (see scripts/merge_venues.py)
    for (const f of shown) { const k = canon(f.venueId); if (!byVenue.has(k)) byVenue.set(k, []); byVenue.get(k).push(f); }
    // Two different kinds of absence, and saying so is the honest thing: ladiesgaelic.ie
    // leaves the venue out of some rows entirely, which no amount of geocoding will fix.
    let unplaced = 0, unnamed = 0, grounds = 0;
    for (const [vid, list] of byVenue) {
      const v = venues[vid];
      if (!v || !v.name) { unnamed += list.length; continue; }
      grounds++;
      if (v.lat == null) { unplaced += list.length; continue; }
      const kinds = new Set(list.map(f => CODE[f.sport])), fill = kinds.size > 1 ? FILL.both : FILL[[...kinds][0]];
      const best = list.slice().sort((a, b) => rankOf(a) - rankOf(b))[0], base = radiusOf(best), radius = base + grow();
      const m = L.circleMarker([v.lat, v.lon], { radius, color: "#333", weight: 1, fillColor: fill, fillOpacity: .85 }).addTo(layer);
      dots.push({ marker: m, base, radius, label: venueLabel(v.name), rank: rankOf(best) });
      m.bindPopup(popup(v, list), popupSize());
    }

    placeLabels();

    const byDay = new Map();
    for (const f of shown) { const d = irishDay(f.date); if (!byDay.has(d)) byDay.set(d, []); byDay.get(d).push(f); }
    $("list").innerHTML = shown.length ? [...byDay.keys()].sort().map(d => `
      <h2>${fmtDate(d)}</h2>
      <table>${byDay.get(d).map(f => `
        <tr id="${f.row}"><td class="when">${fmtTime(f)}</td>
            <td>${teamLine(f)}<br><small class="tag">${detail(f)}${tv(f) ? ", " + esc(tv(f)) : ""}${f.tickets ? `, <a href="${esc(f.tickets)}" rel="noopener">tickets</a>` : ""}${source(f)}</small></td>
            <td class="venue">${venues[canon(f.venueId)] && venues[canon(f.venueId)].lat != null ? `<a href="#map" data-venue="${esc(canon(f.venueId))}">${esc(f.venue)}</a>` : esc(f.venue) || '<span class="tag">venue TBC</span>'}</td></tr>`).join("")}
      </table>`).join("") : `<p class="none">No fixtures match. ${$("results").checked ? "Widen the dates or clear a filter." : 'Widen the dates, clear a filter, or tick "include played matches".'}</p>`;
    const fv = $("from").value, tvv = $("to").value;
    const range = fv && tvv ? `, ${fmtShort(fv)} to ${fmtShort(tvv)}` : fv ? `, from ${fmtShort(fv)}` : tvv ? `, to ${fmtShort(tvv)}` : ", whole season";
    $("count").textContent = `${shown.length} fixture${shown.length === 1 ? "" : "s"} at ${grounds} venue${grounds === 1 ? "" : "s"}${range}${unplaced || unnamed ? " (" + [unnamed && `${unnamed} with no venue listed`, unplaced && `${unplaced} at venues not yet on the map`].filter(Boolean).join(", ") + ")" : ""}.`;
  }

  const asked = Number(p.get("season"));
  await useSeason(SEASONS.some(s => s.year === asked) ? asked : index.latest, true);
})();
