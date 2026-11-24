// Oversættelser: status, venter (skjult for kunderne og på vej), problemer, oversæt en titel og indstillinger.
// ---------- Oversættelser
const TR_ST = {faerdig: "Færdig", fejlet: "Fejlet", mangler_engelsk: "Mangler engelsk tekst", forsoeg_igen: "Prøver igen",
  ikke_muligt: "Ikke muligt", venter_paa_dansk: "Venter på dansk", soeger: "Søger", soegt: "Søgt", i_gang: "I gang",
  sprunget_over: "Sprunget over"};
const TR_STATE = {i_gang: ["Oversætter", "var(--ok)"], venter: ["Venter på batch", "var(--info)"], pause: ["Pause", "var(--warn)"], ledig: ["Ledig", "var(--muted)"]};
let TR = null;
const lt = t => { if (!t) return "–"; const d = new Date(t); return isNaN(d) ? esc(t) : d.toLocaleString("da-DK", {day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"}); };
const kr = (usd, k) => Math.round((usd || 0) * k).toLocaleString("da-DK") + " kr.";
const kr1 = (usd, k) => ((usd || 0) * k).toLocaleString("da-DK", {minimumFractionDigits: 1, maximumFractionDigits: 1}) + " kr.";
let trAll = false;
const yesno = v => v === 1 || v === true ? '<span style="color:var(--ok)">✓</span>' : v === 0 || v === false ? '<span style="color:var(--bad)">✗</span>' : '<span class="small">–</span>';
async function loadTr(manual) {
  try { TR = await api("/api/translations"); } catch (e) { if (manual) toast(e.message, true); return; }
  if (!TR.enabled) {
    $("trWarn").innerHTML = '<div class="warn">Oversætteren er ikke forbundet. Tilføj OVERSAETTER_URL og OVERSAETTER_TOKEN i fangarr.env (se LÆSMIG).</div>';
    ["trKpis", "trMoney", "trConfig"].forEach(id => $(id).innerHTML = ""); return;
  }
  renderTr();
}
function renderTr() {
  const st = TR.status || {}, cfg = TR.config || {}, f = TR.forecast || {}, k = st.usd_to_dkk || cfg.usd_to_dkk || 6.7;
  const warn = [];
  (TR.errors || []).forEach(e => warn.push("Kunne ikke hente: " + esc(e)));
  if (st.new_warning) warn.push("<b>Nye titler:</b> " + esc(st.new_warning));
  if (st.state === "pause") warn.push("Oversætteren holder pause" + (st.pause_until ? " til " + lt(st.pause_until) : "") + " (fx udgiftsgrænse eller nøglefejl hos Anthropic).");
  if (cfg.dry_run) warn.push("Oversætteren står i prøvetilstand (DRY_RUN=true) – der oversættes ikke.");
  if (f.budget_usd && f.forecast_usd > f.budget_usd) warn.push(`Prognosen (${kr(f.forecast_usd, k)}) er over loftet (${kr(f.budget_usd, k)}). Når loftet er nået, oversættes der ikke mere i denne måned.`);
  $("trWarn").innerHTML = warn.map(w => `<div class="warn">${w}</div>`).join("");
  const [label, color] = TR_STATE[st.state] || ["Ukendt", "var(--muted)"];
  const today = new Date().toISOString().slice(0, 10), days = (TR.spend || {}).days || [];
  const since7 = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
  const sum = (rows, key) => rows.reduce((a, d) => a + d[key], 0);
  const t = days.filter(d => d.day === today), w = days.filter(d => d.day > since7);
  const probs = ((TR.problems || {}).items || []).filter(i => i.status !== "venter_paa_dansk" && i.status !== "ikke_muligt").length;
  $("trKpis").innerHTML = [
    ["Lige nu", `<span style="color:${color}">${label}</span>`, st.title ? esc(st.title) + (st.batch_wait_min != null ? ` · ${st.batch_wait_min} min` : "") : (st.last_round ? "Seneste runde " + lt(st.last_round) : "")],
    ["I kø", st.queue ?? 0, "valgt i denne runde"],
    ["I dag", sum(t, "titles"), kr(sum(t, "usd"), k)],
    ["Seneste 7 dage", sum(w, "titles"), kr(sum(w, "usd"), k) + " · " + (sum(w, "titles") ? kr(sum(w, "usd") / sum(w, "titles"), k) + " pr. stk." : "")],
    ["Problemer", probs, probs ? '<a href="#tr/problemer" onclick="go(&quot;tr&quot;,&quot;problemer&quot;);return false" style="color:var(--warn)">se listen</a>' : "ingen"],
    ...((TR.reveal || {}).enabled ? [["Skjult for kunderne", (TR.reveal.waiting || []).length, '<a href="#tr/skjult" onclick="go(&quot;tr&quot;,&quot;skjult&quot;);return false" style="color:var(--info)">se listen</a>']] : []),
  ].map(([l, v, sub]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="small">${sub}</div></div>`).join("");
  const b = f.budget_usd || 0, pct = x => b ? Math.min(100, x / b * 100) : 0, over = b && f.forecast_usd > b;
  $("trMoney").innerHTML = `<div class="row" style="justify-content:space-between;margin:0"><b>Månedens forbrug</b>
      <span>${kr(f.month_usd, k)} af ${kr(b, k)} <span class="small">(${(f.month_usd || 0).toFixed(2)} / ${b} USD)</span></span></div>
    <div class="money ${over ? "over" : ""}"><i class="fc" style="width:${pct(f.forecast_usd)}%"></i><i style="width:${pct(f.month_usd)}%"></i></div>
    <div class="small">Prognose for hele måneden: <b>${kr(f.forecast_usd, k)}</b> (${kr(f.per_day_usd, k)} pr. dag de seneste 7 dage, ${f.days_left} dage tilbage). Den lyse del af bjælken er prognosen.</div>`;
  renderReveal();
  const Pall = (TR.problems || {}).items || [], showAudio = $("trShowAudio").checked;
  const P = showAudio ? Pall : Pall.filter(i => i.status !== "ikke_muligt"), hidden = Pall.length - P.length;
  $("trProblems").innerHTML = (P.length ? P.map(i => `<tr><td><b>${esc(i.title)}</b><div class="small">${esc(i.file || i.key)}</div></td>
    <td class="st st-${esc(i.status)}">${TR_ST[i.status] || esc(i.status)}</td><td>${esc(i.reason || "")}</td><td style="white-space:nowrap">${lt(i.updated_at)}</td>
    <td class="num">${i.attempts ?? ""}</td>
    <td style="white-space:nowrap">${i.status === "ikke_muligt" ? "" : `<button class="b" onclick="trItem('${esc(i.key)}','retry')">Prøv igen</button> <button class="b danger" onclick="trItem('${esc(i.key)}','skip')">Opgiv</button>`}</td></tr>`).join("")
    : '<tr><td colspan="6" class="empty">Ingen problemer.</td></tr>')
    + (hidden ? `<tr><td colspan="6" class="small" style="text-align:center">${hidden} med dansk tale er skjult (ikke et problem)</td></tr>` : "");
  const Dall = (TR.done || {}).items || [], D = trAll ? Dall : Dall.slice(0, 25);
  $("trDone").innerHTML = D.length ? D.map(i => `<tr><td><b>${esc(i.title)}</b><div class="small">${esc(i.source || "")}${i.en_hi ? " · fra HI-tekst" : ""}</div></td>
    <td style="white-space:nowrap">${lt(i.updated_at)}</td><td class="num">${kr1(i.cost_usd, k)}</td>
    <td class="num">${i.flags_before ?? "–"} → ${i.flags_after ?? "–"}</td><td class="num">${i.fixes ?? "–"}</td>
    <td>${yesno(i.bazarr_sync)}</td><td>${yesno(i.plex_refresh)}</td></tr>`).join("")
    + (Dall.length > D.length ? `<tr><td colspan="7" style="text-align:center"><button class="b" onclick="trAll=true;renderTr()">Vis alle ${Dall.length}</button></td></tr>` : "")
    : '<tr><td colspan="7" class="empty">Ingen færdige oversættelser de seneste 30 dage.</td></tr>';
  const on = v => v ? "til" : "fra";
  const items = [
    ["Model", `${esc(cfg.translate_model)} (${esc(cfg.translate_effort)})`, `reserve: ${esc(cfg.fallback_model)} · batch ${on(cfg.batch_api)}`],
    ["Månedsloft", `${cfg.monthly_budget_usd} USD`, kr(cfg.monthly_budget_usd, k)],
    ["Alt nyt oversættes", cfg.translate_all_since ? "fra " + esc(cfg.translate_all_since) : "fra (kun Seerr og mærket)", cfg.translate_all_since ? `sprogprofil til nye titler: ${esc(cfg.bazarr_profile)}` : `mærket: ${esc(cfg.translate_tag)}`],
    ["Vent på dansk tjeneste (B9)", cfg.provider_wait ? `til (film ${cfg.provider_wait_days_movies} / serier ${cfg.provider_wait_days_series} dage)` : "fra", ""],
    ["Runder", `hvert ${cfg.poll_minutes}. minut`, `højst ${cfg.max_searches_per_round} søgninger pr. runde`],
    ["Prøvetilstand", cfg.dry_run ? "til" : "fra", `Bazarr-synk ${on(cfg.sync_after_upload)} · Plex-scanning ${on(cfg.plex_refresh)}`],
    ["Skjult indtil dansk", cfg.reveal ? "til" : "fra", cfg.reveal ? `vises senest efter ${cfg.reveal_safety_hours} timer` : "nyt vises med det samme (Autoscan)"],
  ];
  const dp = (TR.delay_profiles || []).map(d => d.error ? `<div class="small">${esc(d.instance)}: kunne ikke læses</div>` :
    `<div class="small"><b>${esc(d.instance)}</b>: ${d.torrent_min ? (d.torrent_min / 60).toLocaleString("da-DK") + " t" : "ingen ventetid"}${d.bypass ? " · straks ved score ≥ " + Number(d.min_score).toLocaleString("da-DK") : ""} · ${d.tags.length ? "mærker: " + esc(d.tags.join(", ")) : "alle andre"}</div>`).join("");
  $("trConfig").innerHTML = items.map(([l, v, sub]) => `<div class="kpi"><div class="l">${l}</div><div style="margin-top:4px"><b>${v}</b></div><div class="small">${sub}</div></div>`).join("")
    + `<div class="kpi" style="grid-column:1/-1"><div class="l">Ventetid i Sonarr/Radarr (Delay Profiles)</div>${dp || '<div class="small">–</div>'}</div>`;
}
// ---------- knapperne (Fase 4)
let TR_FOUND = [], TR_PICK = null, TR_EST = null;
async function trItem(key, action) {
  if (action === "skip" && !confirm("Opgiv titlen? Den oversættes ikke og vises i Plex uden dansk tekst efter sikkerhedsnettet.")) return;
  try { const r = await api("/api/translations/item", {method: "POST", body: JSON.stringify({key, action})});
        toast(action === "retry" ? `${r.title}: prøves igen i næste runde` : `${r.title}: opgivet`); loadTr(); }
  catch (e) { toast(e.message, true); }
}
async function trSearch() {
  const q = $("trQ").value.trim(); if (q.length < 2) return;
  $("trResults").innerHTML = '<div class="small">Søger …</div>'; $("trPick").innerHTML = "";
  try { TR_FOUND = await api("/api/translations/search?q=" + encodeURIComponent(q)); }
  catch (e) { $("trResults").innerHTML = `<div class="warn">${esc(e.message)}</div>`; return; }
  $("trResults").innerHTML = TR_FOUND.length ? `<div class="card" style="padding:6px">${TR_FOUND.map((x, i) =>
    `<button class="b" style="margin:4px" onclick="trChoose(${i})">${x.media === "movie" ? "🎬" : "📺"} ${esc(x.title)}${x.year ? " (" + x.year + ")" : ""}${x.straks ? ' <span class="tag" style="color:var(--ok)">straks</span>' : ""}</button>`).join("")}</div>`
    : '<div class="card empty">Ingen serier eller film fundet i Sonarr/Radarr.</div>';
}
async function trChoose(i) {
  TR_PICK = TR_FOUND[i]; $("trPick").innerHTML = '<div class="card empty">Tæller afsnit …</div>';
  try { TR_EST = await api(`/api/translations/estimate?media=${TR_PICK.media}&id=${TR_PICK.id}`); }
  catch (e) { $("trPick").innerHTML = `<div class="warn">${esc(e.message)}</div>`; return; }
  renderPick();
}
function trTotal() {
  const e = TR_EST; if (!e) return {n: 0, usd: 0};
  if (e.media === "movie") return {n: e.state === "mangler" ? 1 : 0, usd: e.est_usd};
  let n = 0; document.querySelectorAll(".trSeason:checked").forEach(c => { n += Number(c.dataset.n); });
  return {n, usd: n * e.price_per_item_usd};
}
function trUpdateTotal() {
  const e = TR_EST, k = e.usd_to_dkk || 6.7, t = trTotal(), left = (e.budget_usd || 0) - (e.month_usd || 0);
  $("trTotal").innerHTML = `<b>${t.n}</b> ${e.media === "movie" ? "film" : "afsnit"} · ca. <b>${kr(t.usd, k)}</b>`
    + (t.usd > left ? `<div class="warn" style="margin-top:8px">Det er mere end der er tilbage af månedens loft (${kr(Math.max(0, left), k)} af ${kr(e.budget_usd, k)}). Oversætteren stopper ved loftet, og resten venter til næste måned.</div>` : "");
  $("trGo").disabled = !t.n;
}
function renderPick() {
  const e = TR_EST, p = TR_PICK, k = e.usd_to_dkk || 6.7;
  const ST = {mangler: "mangler dansk", dansk: "har dansk", i_gang: "er i gang", ingen_fil: "ingen fil endnu"};
  let body;
  if (e.media === "movie") body = `<div>Status: <b>${ST[e.state] || esc(e.state)}</b></div>`;
  else body = e.seasons.length ? `<table><thead><tr><th></th><th>Sæson</th><th class="num">Afsnit</th><th class="num">Har dansk</th><th class="num">I gang</th><th class="num">Mangler</th><th class="num">Pris</th></tr></thead><tbody>${e.seasons.map(s =>
    `<tr><td><input type="checkbox" class="trSeason" data-n="${s.mangler}" data-s="${s.season}" ${s.mangler && s.season > 0 ? "checked" : ""} ${s.mangler ? "" : "disabled"} onchange="trUpdateTotal()" style="width:auto"></td>
     <td>${s.season === 0 ? "Specials" : "Sæson " + s.season}</td><td class="num">${s.episodes}</td><td class="num">${s.dansk}</td><td class="num">${s.i_gang}</td><td class="num"><b>${s.mangler}</b></td><td class="num">${kr(s.est_usd, k)}</td></tr>`).join("")}</tbody></table>`
    : '<div class="empty">Ingen afsnit med fil.</div>';
  $("trPick").innerHTML = `<div class="card" style="overflow-x:auto">
    <div class="row" style="justify-content:space-between;margin:0 0 8px"><b>${p.media === "movie" ? "🎬" : "📺"} ${esc(e.title)}${e.year ? " (" + e.year + ")" : ""}</b>
      <span class="small">ca. ${kr(e.price_per_item_usd, k)} pr. ${p.media === "movie" ? "film" : "afsnit"}</span></div>
    ${e.note ? `<div class="warn">${esc(e.note)}</div>` : ""}${body}
    <div id="trTotal" style="margin:10px 0"></div>
    <div class="row" style="margin:0"><button class="b pri" id="trGo" onclick="trGo()">Oversæt nu</button>
      <button class="b" onclick="trStraks(${!p.straks})">${p.straks ? "Slå ventetid til igen" : "Ingen ventetid fremover"}</button></div>
    <div class="small" style="margin-top:6px">${p.straks ? "Har mærket straks: nye afsnit hentes uden de 6 timer." : "Nye afsnit venter 6 timer på en NORDiC-udgave."}</div></div>`;
  trUpdateTotal();
}
async function trGo() {
  const e = TR_EST, t = trTotal(), k = e.usd_to_dkk || 6.7;
  if (!t.n || !confirm(`Oversæt ${t.n} ${e.media === "movie" ? "film" : "afsnit"} af ${e.title} for ca. ${kr(t.usd, k)}?`)) return;
  const seasons = [...document.querySelectorAll(".trSeason:checked")].map(c => Number(c.dataset.s));
  try { const r = await api("/api/translations/translate", {method: "POST", body: JSON.stringify({media: TR_PICK.media, id: TR_PICK.id, seasons})});
        toast(`${r.added} lagt i kø hos Oversætteren – den søger efter dansk først`); trChoose(TR_FOUND.indexOf(TR_PICK)); }
  catch (err) { toast(err.message, true); }
}
async function trStraks(on) {
  try { await api("/api/translations/straks", {method: "POST", body: JSON.stringify({media: TR_PICK.media, instance: TR_PICK.instance, id: TR_PICK.id, title: TR_PICK.title, on})});
        TR_PICK.straks = on; toast(on ? "Ingen ventetid fremover (mærket straks)" : "Normal ventetid igen"); renderPick(); }
  catch (e) { toast(e.message, true); }
}
const RV_WHY = {"dansk originalsprog": "dansk tale", "dansk tale": "dansk tale", "indlejret dansk tekst": "dansk tekst i filen", "dansk tekstfil": "dansk tekst"};
// 1.17.0: har Plex bekræftet filen? (Oversætterens trin C5 – feltet mangler på ældre rækker)
function RV_PLEX(i) {
  const n = i.plex_tries || 0;
  if (i.plex === "ok") return `<div class="small">i Plex${n ? ` efter ${n} ekstra scanning${n > 1 ? "er" : ""}` : ""}</div>`;
  if (i.plex === "tjekkes") return `<div class="small">${n ? `ikke i Plex endnu – ${n} ekstra scanning${n > 1 ? "er" : ""}` : "venter på bekræftelse fra Plex"}</div>`;
  if (i.plex === "mangler") return '<div class="small" style="color:var(--warn)">⚠ ikke kommet i Plex – prøver igen hver time</div>';
  if (i.plex === "opgivet") return '<div class="small" style="color:var(--warn)">⚠ ikke kommet i Plex – opgivet efter et døgn</div>';
  return "";
}
function renderReveal() {
  const R = TR.reveal, W = TR.on_the_way || [];
  if (!R || !R.enabled) {
    $("trRevealInfo").innerHTML = R ? '<div class="small" style="margin-bottom:8px">Slået fra – nye film og afsnit vises med det samme (REVEAL=false i oversætterens .env).</div>' : "";
    $("trHidden").innerHTML = '<tr><td colspan="5" class="empty">–</td></tr>'; $("trShown").innerHTML = '<tr><td colspan="3" class="empty">–</td></tr>';
  } else {
    $("trRevealInfo").innerHTML = (R.last_error ? `<div class="warn">Seneste kørsel fejlede: ${esc(R.last_error)}</div>` : "")
      + `<div class="small" style="margin-bottom:8px">Tjekkes hvert ${R.interval_seconds}. sekund (seneste ${lt(R.last_run)}). Sikkerhedsnet: ${R.safety_hours} timer.</div>`
      + ((R.plex_missing || []).length ? `<div class="warn">⚠ Vist, men ikke kommet i Plex: ${R.plex_missing.map(i => `<b>${esc(i.title)}</b> (${i.plex === "opgivet" ? "opgivet efter et døgn" : "prøver igen hver time"})`).join(", ")}</div>` : "");
    const H = R.waiting || [];
    $("trHidden").innerHTML = H.length ? H.map(i => { const left = i.reveal_by ? (new Date(i.reveal_by) - Date.now()) / 36e5 : null;
      return `<tr><td><b>${esc(i.title)}</b><div class="small">${esc(i.file || i.key)}</div></td><td>${esc(i.reason || "")}</td>
      <td>${i.translation ? `<span class="st st-${esc(i.translation)}">${TR_ST[i.translation] || esc(i.translation)}</span><div class="small">${esc(i.translation_reason || "")}</div>` : '<span class="small">ikke valgt</span>'}</td>
      <td style="white-space:nowrap">${lt(i.import_at)}</td>
      <td style="white-space:nowrap">${lt(i.reveal_by)}${left != null ? `<div class="small">om ${Math.max(0, left).toLocaleString("da-DK", {maximumFractionDigits: 1})} t</div>` : ""}</td></tr>`; }).join("")
      : '<tr><td colspan="5" class="empty">Intet er skjult lige nu 🎉</td></tr>';
    const S = R.shown || [];
    $("trShown").innerHTML = S.length ? S.slice(0, 50).map(i => `<tr><td><b>${esc(i.title)}</b><div class="small">${esc(i.file || i.key)}</div></td>
      <td>${i.shown_by === "sikkerhedsnet" ? `<span style="color:var(--warn)">⏰ uden dansk</span><div class="small">${esc(i.reason || "")}</div>` : `<span style="color:var(--ok)">✓ ${esc(RV_WHY[i.reason] || i.reason || "klar")}</span>`}${RV_PLEX(i)}</td>
      <td style="white-space:nowrap">${lt(i.shown_at)}</td></tr>`).join("") + (S.length > 50 ? `<tr><td colspan="3" class="small" style="text-align:center">… og ${S.length - 50} mere</td></tr>` : "")
      : '<tr><td colspan="3" class="empty">Intet vist endnu.</td></tr>';
  }
  $("trWay").innerHTML = W.length ? W.map(i => i.error ? `<tr><td colspan="4" class="small">${esc(i.instance)}: kunne ikke læses (${esc(i.error)})</td></tr>` :
    `<tr><td><b>${esc(i.title)}</b><div class="small">${esc(i.instance)}${i.quality ? " · " + esc(i.quality) : ""}</div></td>
     <td class="small" style="word-break:break-all">${esc(i.release)}${i.nordic ? ' <span class="tag" style="color:var(--ok)">NORDiC</span>' : ""}</td>
     <td class="num">${i.score != null ? Number(i.score).toLocaleString("da-DK") : "–"}</td><td style="white-space:nowrap">${lt(i.until)}</td></tr>`).join("")
    : '<tr><td colspan="4" class="empty">Intet venter på ventetiden lige nu.</td></tr>';
}
async function loadTrStats(refresh) {
  const days = $("trDays").value;
  $("trStats").innerHTML = '<div class="card empty">Beregner … (læser historikken i Sonarr/Radarr)</div>';
  let d; try { d = await api(`/api/translations/stats?days=${days}&refresh=${refresh ? 1 : 0}`); }
  catch (e) { $("trStats").innerHTML = `<div class="warn">${esc(e.message)}</div>`; return; }
  if (d.enabled === false) { $("trStats").innerHTML = ""; return; }
  const k = (TR && TR.status && TR.status.usd_to_dkk) || 6.7;
  const byDay = {}; (d.spend.days || []).forEach(x => { byDay[x.day] = byDay[x.day] || {usd: 0, n: 0}; byDay[x.day].usd += x.usd; byDay[x.day].n += x.titles; });
  const list = []; for (let i = d.days - 1; i >= 0; i--) { const day = new Date(Date.now() - i * 864e5).toISOString().slice(0, 10); list.push([day, byDay[day] || {usd: 0, n: 0}]); }
  const max = Math.max(0.01, ...list.map(([, v]) => v.usd));
  const chart = `<div class="cols">${list.map(([day, v]) => `<div title="${day}: ${v.n} oversat, ${kr(v.usd, k)}" style="height:${v.usd / max * 100}%"></div>`).join("")}</div>
    <div class="axis"><span>${list[0][0].slice(5)}</span><span>i dag</span></div>`;
  const C = ["var(--info)", "var(--ok)", "var(--warn)"], names = ["Dansk tale", "NORDiC / danske tekster", "Skal oversættes"];
  const split = ["series", "movie"].filter(m => d.imports[m]).map(m => { const c = d.imports[m].counts, tot = c.dansk_tale + c.nordic + c.oversaet || 1;
    const parts = [c.dansk_tale, c.nordic, c.oversaet];
    return `<div style="margin-bottom:10px"><b>${m === "series" ? "Afsnit" : "Film"}</b> <span class="small">(${tot} importeret)</span>
      <div class="stack">${parts.map((n, i) => `<i style="width:${n / tot * 100}%;background:${C[i]}"></i>`).join("")}</div>
      <div class="small">${parts.map((n, i) => `<span class="dot" style="background:${C[i]}"></span>${names[i]}: <b>${n}</b> (${Math.round(n / tot * 100)} %)`).join(" &nbsp; ")}</div></div>`; }).join("");
  const wasted = d.wasted.length ? `<table><thead><tr><th>Titel</th><th>Oversat</th><th>NORDiC kom</th><th class="num">Pris</th></tr></thead><tbody>${d.wasted.map(w => `<tr><td><b>${esc(w.title)}</b><div class="small">${esc(w.source)}</div></td><td>${lt(w.translated)}</td><td>${lt(w.nordic_at)}</td><td class="num">${kr(w.cost_usd, k)}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">Ingen – ingen oversatte afsnit er senere skiftet ud med NORDiC.</div>';
  const top = d.top.length ? `<table><thead><tr><th>Serie / film</th><th class="num">Oversat</th><th class="num">Pris</th></tr></thead><tbody>${d.top.map(t => `<tr><td>${esc(t.title)}</td><td class="num">${t.count}</td><td class="num">${kr(t.usd, k)}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">Ingen endnu.</div>';
  $("trStats").innerHTML = `<div class="card"><b>Pris pr. dag</b> <span class="small">(hold musen over en søjle)</span>${chart}</div>
    <div class="card"><b>Hvad der kom hjem</b> <span class="small">(fra historikken i Sonarr/Radarr)</span><div style="margin-top:8px">${split || '<div class="small">–</div>'}</div></div>
    <div class="card" style="overflow-x:auto"><b>"Spildte" oversættelser: ${d.wasted.length} (${kr(d.wasted_usd, k)})</b>
      <p class="hint" style="margin:4px 0 8px">Afsnit, vi betalte for at oversætte, som bagefter blev skiftet ud med en NORDiC-udgave. Mange her = overvej længere ventetid i Sonarr.</p>${wasted}</div>
    <div class="card" style="overflow-x:auto"><b>Dyreste serier og film</b> <span class="small">(30 dage)</span>${top}</div>
    <div class="small">Beregnet ${lt(d.computed)}</div>`;
}
