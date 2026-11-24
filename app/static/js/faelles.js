// Fælles for alle sider: hjælpefunktioner, menuen, øverste linje og søgning efter en titel.
const LANGS = ["Danish","Swedish","Norwegian","Finnish","Icelandic","English","German","French","Spanish","Italian","Dutch","Polish","Japanese","Korean"];
const LANG_DA = {Danish:"Dansk",Swedish:"Svensk",Norwegian:"Norsk",Finnish:"Finsk",Icelandic:"Islandsk",English:"Engelsk",German:"Tysk",French:"Fransk",Spanish:"Spansk",Italian:"Italiensk",Dutch:"Hollandsk",Polish:"Polsk",Japanese:"Japansk",Korean:"Koreansk"};
const GENRES = {
  series: ["Drama","Crime","Thriller","Mystery","Comedy","Documentary","Reality","Mini-Series","Action","Adventure","Science Fiction","Fantasy","Family","Children","Animation","Romance","Horror","War","Western","Soap","Talk Show","Game Show","News","Sport","Food","Travel","Home and Garden"],
  movie: ["Drama","Crime","Thriller","Mystery","Comedy","Documentary","Action","Adventure","Science Fiction","Fantasy","Family","Animation","Romance","Horror","War","History","Music","Western","TV Movie"]
};
const GENRE_DA = {"Drama":"Drama","Crime":"Krimi","Thriller":"Thriller","Mystery":"Mysterie","Comedy":"Komedie","Documentary":"Dokumentar","Reality":"Reality","Mini-Series":"Miniserie","Action":"Action","Adventure":"Eventyr","Science Fiction":"Science fiction","Fantasy":"Fantasy","Family":"Familie","Children":"Børn","Animation":"Animation","Romance":"Romantik","Horror":"Gys","War":"Krig","Western":"Western","Soap":"Sæbeopera","Talk Show":"Talkshow","Game Show":"Quiz/gameshow","News":"Nyheder","Sport":"Sport","Food":"Mad","Travel":"Rejser","Home and Garden":"Hus og have","History":"Historie","Music":"Musik","TV Movie":"Tv-film"};
const MONITOR_DA = {latestSeason:"nyeste sæson + nye",future:"kun fremtidige afsnit",firstSeason:"første sæson + nye",all:"alle sæsoner + nye",none:"intet"};

let S = null, editing = null, logRows = [], AB = null;
const SET_NUM = ["max_series_per_day", "max_movies_per_day", "max_disk_pct", "summary_hour", "wait_hours", "wait_days", "refresh_hours", "refresh_days", "backup_hour", "backup_keep", "huske_hour"];
const $ = id => document.getElementById(id);
const dlg = $("dlg");
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function toast(msg, bad) {
  const t = $("toast"); t.textContent = msg; t.style.color = bad ? "var(--bad)" : "var(--text)";
  t.style.display = "block"; clearTimeout(t._h); t._h = setTimeout(() => t.style.display = "none", 3500);
}

async function api(path, opts = {}) {
  const r = await fetch(path, {headers: {"Content-Type": "application/json"}, ...opts});
  let data = null; try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error((data && data.detail) || ("Fejl " + r.status));
  return data;
}

async function load() {
  try { S = await api("/api/state"); } catch (e) { toast(e.message, true); return; }
  renderStatus(); renderRules(); renderSettings();
}
function list(a) { return (a && a.length) ? a.join(", ") : null; }

function dcls(d) {
  if (d === "tilføjet") return "d-tilføjet"; if (d === "ville tilføje") return "d-ville"; if (d === "fejl") return "d-fejl";
  if (d === "venteliste") return "d-ville"; if (d === "udløbet") return "d-loft";
  if (d === "loft nået") return "d-loft"; if (d === "for lidt plads") return "d-plads"; if (d === "findes allerede") return "d-findes"; return "d-afvist";
}

const fmt = t => t ? esc(t.replace("T", " ").slice(0, 16)) : "–";
const WAIT_CLS = {venter: "d-ville", klar: "d-tilføjet", afvist: "d-afvist", "udløbet": "d-loft"};

// ---------- fælles
function fillRuleSelect(id, media) {
  const el = $(id), keep = el.value;
  const rules = S.rules.filter(r => !media || r.media === media);
  el.innerHTML = rules.length ? rules.map(r => `<option value="${r.id}">${esc(r.name)} (${r.media === "series" ? "serier" : "film"})${r.active ? "" : " – slået fra"}</option>`).join("")
                              : '<option value="">(ingen regler)</option>';
  if (keep && rules.some(r => String(r.id) === keep)) el.value = keep;
}
async function poll(job, progId, onDone) {
  const tick = async () => {
    try { job = await api(`/api/jobs/${job.id}`); } catch (e) { $(progId).innerHTML = `<div class="small" style="color:var(--bad)">${esc(e.message)}</div>`; onDone(null); return; }
    const pct = job.total ? Math.round(100 * job.done / job.total) : 0;
    $(progId).innerHTML = `<div class="bar"><i style="width:${job.status === "færdig" ? 100 : pct}%"></i></div>
      <div class="small">${job.status === "kører" ? `Arbejder… ${job.done}/${job.total || "?"}` : esc(job.status)}${job.note ? " · " + esc(job.note) : ""}${job.error ? ` · <span style="color:var(--bad)">${esc(job.error)}</span>` : ""}</div>`;
    if (job.status === "kører") setTimeout(tick, 1200); else onDone(job);
  };
  tick();
}

// ====================================================================== menu og sider (2.0)
// Hvert menupunkt er en <section> i index.html. Underfanerne står i SUBDEF; den første er standard.
const SUBDEF = {log: "tilfoejet", wait: "venter", tr: "status", rules: "regler", cust: "liste", pay: "opkraevning",
                besk: "koe", guide: "besoeg", drift: "huskeliste", settings: "telegram"};
const TAB_IDS = ["home", "log", "wait", "tr", "bib", "rules", "cust", "pay", "besk", "oensker", "share", "guide", "drift", "settings", "hjaelp", "search"];
// Gamle adresser (bogmærker, widgetten) sendes videre til den nye plads: "gammel" eller "gammel/underfane" → [side, underfane]
const OLD_HASH = {
  setup: ["rules", "afproev"], "setup/test": ["rules", "afproev"], "setup/sim": ["rules", "historik"], "setup/autobrr": ["rules", "autobrr"],
  iptv: ["cust", "iptv"], eco: ["pay", "oekonomi"], prem: ["home"], stats: ["bib"], "cust/import": ["cust", "liste"],
  "settings/gen": ["rules", "indst"], "settings/vente": ["wait", "indst"], "settings/kob": ["wait", "koblinger"],
  "tr/skjult": ["tr", "venter"], "tr/paavej": ["tr", "venter"], "tr/faerdige": ["tr", "status"], "tr/stat": ["tr", "status"],
};
let TAB = "home", SUB = {...SUBDEF}, OV = null, CONN = null, APPS = null, VER = null, ADDED = null, ADDED_ROWS = null, logFirst = true;

function showSub(tab) {
  const sec = $(tab), cur = SUB[tab];
  sec.querySelectorAll(".subs button").forEach(b => b.classList.toggle("on", b.dataset.sub === cur));
  sec.querySelectorAll("[data-p]").forEach(p => p.classList.toggle("on", p.dataset.p.split(" ").includes(cur)));
}
function go(tab, sub) {
  const old = OLD_HASH[tab + "/" + sub] || (!TAB_IDS.includes(tab) && OLD_HASH[tab]);
  if (old) [tab, sub] = old;
  if (!TAB_IDS.includes(tab)) tab = "home";
  TAB = tab;
  if (SUBDEF[tab]) { if (sub && $(tab).querySelector(`.subs button[data-sub="${sub}"]`)) SUB[tab] = sub; showSub(tab); }
  document.body.classList.remove("nav-open");
  document.querySelectorAll("[data-tab]").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  document.querySelectorAll("main > section").forEach(s => s.classList.toggle("on", s.id === tab));
  if (tab !== "search") history.replaceState(null, "", "#" + tab + (SUBDEF[tab] ? "/" + SUB[tab] : ""));
  clearInterval(window._trTimer);
  window.scrollTo(0, 0);
  if (!S) return;
  const s = SUB[tab];
  if (tab === "home") { loadHome(); loadConn(0); loadApps(0); loadStille(); }
  if (tab === "log") loadLog();
  if (tab === "wait") { loadWait(); if (s === "koblinger") loadAliases(); if (s === "fjernede") loadIgnored(); }
  if (tab === "tr") { loadTr(); loadTrStats(0); window._trTimer = setInterval(() => loadTr(), 60000); }
  if (tab === "bib") loadStats();
  if (tab === "rules") { fillRuleSelect("sim_rule", null); if (s === "autobrr") loadAutobrr(); }
  if (tab === "cust") { loadCust().then(renderKSet); if (s === "logins") loadLogins(); if (s === "iptv") loadIptv(); }
  if (tab === "pay") { if (s === "oekonomi") loadEco(); else if (s === "udgifter") loadUdg(); else loadPay(); }
  if (tab === "besk") { if (s === "koe") loadQueues(); else if (s === "klar") loadReady(); else if (s === "aendring") loadPrices();
    else kState().then(() => { renderKSet(); renderNews(); if (s === "skabeloner") loadTemplates(); }).catch(e => toast(e.message, true)); }
  if (tab === "oensker") loadOensker();
  if (tab === "share") loadShare();
  if (tab === "guide") { if (s === "nyheder") nwLoad(); else if (s === "soegninger") loadSearches(); else loadGuide(); }
  if (tab === "drift") { loadConn(0); if (s === "trackere") loadGrab(); if (s === "huskeliste") loadHuske(); }
  if (tab === "settings") { loadBackups(); loadAppsCfg(); renderTelegram(); loadTgStatus(); }
  if (tab === "hjaelp") renderHelp();
}
document.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => go(b.dataset.tab));
document.querySelectorAll(".subs button").forEach(b => b.onclick = () => go(b.closest("section").id, b.dataset.sub));
document.querySelectorAll("[data-menu]").forEach(b => b.onclick = e => { e.stopPropagation(); document.body.classList.toggle("nav-open"); });
document.addEventListener("click", e => { if (document.body.classList.contains("nav-open") && !e.target.closest("#side")) document.body.classList.remove("nav-open"); });
document.addEventListener("keydown", e => { if (e.key === "Escape") document.body.classList.remove("nav-open"); });

function renderStatus() {
  const s = S.settings;
  $("status").innerHTML =
    (s.dry_run ? '<span class="chip dry">Prøvetilstand</span>' : '<span class="chip live">Tilføjer for alvor</span>') +
    `<span class="chip">Disk <b>${S.disk_pct ?? "?"} %</b> · grænse ${s.max_disk_pct} %</span>` +
    `<span class="chip">I dag <b>${S.today.series}</b> serier · <b>${S.today.movie}</b> film</span>`;
}

// ---------- links til Sonarr/Radarr og "kom den hjem?"
function arrBase(name) {
  const i = ((S && S.instances) || []).find(x => x.name === name);
  if (i && i.link) return i.link;
  const h = location.hostname.split(".");
  if (h.length < 3 || /^\d+$/.test(h[h.length - 1])) return "";
  h[0] = name; return location.protocol + "//" + h.join(".");
}
const HOME_ST = {hentet: "ok", delvist: "warn", henter: "info", venter: "info", mangler: "bad", fjernet: "", ukendt: ""};
function homePill(a) { return a ? `<span class="pill ${HOME_ST[a.state] || ""}" title="${esc(a.text)}">${esc(a.text)}</span>` : ""; }
function arrLink(a, label) {
  const base = a && a.path ? arrBase(a.instance) : "";
  return base ? `<a href="${esc(base + a.path)}" target="_blank" rel="noopener" style="color:inherit">${label}</a>` : label;
}
const addedKey = (media, title) => media + "|" + String(title || "").toLowerCase();
function addedFor(r) { return ADDED ? ADDED[addedKey(r.media, r.title)] : null; }
async function loadAdded() {
  try { const rows = await api("/api/added?limit=500"); ADDED_ROWS = rows; ADDED = {}; rows.slice().reverse().forEach(a => ADDED[addedKey(a.media, a.title)] = a); }
  catch (e) { ADDED = ADDED || {}; }
}

function setBadge(id, n, bad) { document.querySelectorAll(`[data-bdg="${id}"]`).forEach(el => { el.textContent = n ? String(n) : ""; el.classList.toggle("bad", !!bad); }); }

// ---------- søg efter en titel
let qTimer = null;
$("q").addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(runSearch, 350); });
$("q").addEventListener("keydown", e => { if (e.key === "Enter") { clearTimeout(qTimer); runSearch(); } });
async function runSearch() {
  const q = $("q").value.trim();
  if (q.length < 2) { if (TAB === "search") go("home"); return; }
  if (TAB !== "search") go("search");
  $("searchInfo").textContent = `Søger efter “${q}” …`;
  let d; try { d = await api("/api/search?q=" + encodeURIComponent(q)); } catch (e) { $("searchInfo").textContent = e.message; return; }
  if ($("q").value.trim() !== q) return;
  const n = d.added.length + d.waitlist.length + d.log.length + d.translations.length + d.aliases.length + d.ignored.length;
  $("searchInfo").textContent = n ? `Alt, hvad Fangarr har gjort med titler, der indeholder “${q}”.` : `Fangarr har intet om “${q}”. Søgningen kigger i loggen, ventelisten, tilføjelser, oversættelser, koblinger og fjernede titler.`;
  const box = (title, n, body) => n ? `<div class="card tp"><div class="tph"><h2>${title} <span class="small">${n}</span></h2></div>${body}</div>` : "";
  $("searchOut").innerHTML =
    box("Tilføjet til Sonarr og Radarr", d.added.length, `<table><thead><tr><th>Tilføjet</th><th>Titel</th><th>Sendt til</th><th>Regel</th><th>Hentet?</th></tr></thead><tbody>` +
      d.added.map(a => `<tr><td style="white-space:nowrap;color:var(--muted)">${fmt(a.ts)}</td><td><b>${arrLink(a, esc(a.title))}</b></td><td>${esc(a.instance)}</td><td>${esc(a.rule)}</td><td>${homePill(a)}</td></tr>`).join("") + "</tbody></table>") +
    box("På ventelisten", d.waitlist.length, `<table><thead><tr><th>Titel</th><th>Status</th><th>Forsøg</th><th>Seneste grund</th></tr></thead><tbody>` +
      d.waitlist.map(w => `<tr><td><b>${esc(w.title)}</b><div class="small">${esc(w.release)}</div></td><td class="d ${WAIT_CLS[w.status] || ""}">${esc(w.status)}</td><td>${w.attempts}</td><td>${esc(w.reason)}</td></tr>`).join("") + "</tbody></table>") +
    box("Oversættelser", d.translations.length, `<table><thead><tr><th>Titel</th><th>Status</th><th>Grund</th><th>Senest</th></tr></thead><tbody>` +
      d.translations.map(i => `<tr><td><b>${esc(i.title)}</b></td><td class="st st-${esc(i.status)}">${(typeof TR_ST !== "undefined" && TR_ST[i.status]) || esc(i.status)}</td><td>${esc(i.reason)}</td><td style="white-space:nowrap">${lt(i.updated_at)}</td></tr>`).join("") + "</tbody></table>") +
    box("Loggen", d.log.length, `<table><thead><tr><th>Tid</th><th>Titel</th><th>Beslutning</th><th>Regel</th><th>Detaljer</th></tr></thead><tbody>` +
      d.log.map(r => `<tr><td style="white-space:nowrap;color:var(--muted)">${esc(r.ts.replace("T", " ").slice(0, 16))}</td><td><b>${esc(r.title)}</b>${r.year ? " (" + r.year + ")" : ""}<div class="small">${esc(r.release)}</div></td>
        <td class="d ${dcls(r.decision)}">${esc(r.decision)}</td><td>${esc(r.rule)}</td><td>${esc(r.detail)}</td></tr>`).join("") + "</tbody></table>") +
    box("Godkendte koblinger", d.aliases.length, `<table><tbody>` + d.aliases.map(a => `<tr><td><b>${esc(a.release_title)}</b></td><td>kobles til ${esc(a.title)}</td></tr>`).join("") + "</tbody></table>") +
    box("Fjernede titler (huskes)", d.ignored.length, `<table><tbody>` + d.ignored.map(a => `<tr><td><b>${esc(a.title)}</b></td><td>fjernet ${fmt(a.created)} – kommer ikke på ventelisten igen</td></tr>`).join("") + "</tbody></table>");
}
