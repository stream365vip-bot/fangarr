// Kontodeling: finder tv, der aldrig har stået hos kunden, og den bedste blokering i Tracearr.
// ---------- kontodeling
let SH = null, shOpen = new Set(), shLast = null;
const SH_KIND = {tv: "Tv", mobil: "Mobil", ukendt: "Ukendt"};
const SH_ST = {kunde: "Kundens", tidligere: "Tidligere hos kunden", aldrig: "Aldrig hos kunden", uafklaret: "Uafklaret",
  godkendt: "Godkendt undtagelse", ikke: "Ikke kundens (valgt af dig)", "set hos kunden": "set hos kunden"};
const SH_CASE = ["", "blokeres", "blokeret", "undtagelse aftalt", "afsluttet"];
const SH_MSG = "Enheden er blokeret pga. kontodeling. Kontakt kontoejeren for at få din egen konto.";
const SH_BUCKET = [
  ["bloker", '<span class="dotc r"></span>Kan blokeres', "Tv, der aldrig har stået hos kunden, bruges samtidig med kundens tv. Åbn brugeren for at se den bedste blokering.", true],
  ["afgoer", '<span class="dotc y"></span>Afgør selv', "Fangarr kan ikke se, hvilket sted der er kundens. Åbn brugeren og vælg kundens sted – så får du en blokering.", true],
  ["igang", '<span class="dotc b"></span>I gang', "Brugere, du har sat en sag på (blokeres, blokeret eller undtagelse aftalt). Her kan du følge, om blokeringen virker.", true],
  ["skift", '<span class="dotc "></span>Fremmede tv uden samtidig brug', "Tv, der aldrig har stået hos kunden, men ikke kører samtidig med kundens. Efter kontoreglerne er det tilladt (ét tv ad gangen på forskellige adresser).", false],
  ["intet", '<span class="dotc g"></span>Ingen fremmede tv', "Brugere uden tv andre steder end hos kunden i perioden.", false]];
function shPeriod() { const own = $("shDays").value === "0"; $("shFromBox").style.display = $("shToBox").style.display = own ? "" : "none"; }
async function loadShare() {
  $("shNote").innerHTML = S.features.tautulli ? "" : '<div class="warn">Tautulli er ikke forbundet. Tilføj TAUTULLI_URL og TAUTULLI_APIKEY i fangarr.env (se LÆSMIG).</div>';
  $("shBtn").disabled = $("shFull").disabled = !S.features.tautulli;
  if (SH) return;
  try { const d = await api("/api/sharing"); if (d && d.results && d.results.users) { SH = d; renderShare(); } } catch (e) { toast(e.message, true); }
}
function shParams() {
  const body = {min_minutes: Number($("shMin").value) || 10, red_days: Number($("shRed").value) || 5};
  if ($("shDays").value === "0") {
    if (!$("shFrom").value) { toast("Vælg en startdato", true); return null; }
    body.from = $("shFrom").value; if ($("shTo").value) body.to = $("shTo").value;
  } else body.days = Number($("shDays").value);
  if ($("shCut").value) body.cut = $("shCut").value;
  return body;
}
async function runShare(full, again) {
  const body = again && shLast ? {...shLast} : shParams();
  if (!body) return;
  if (full && !confirm("Glem den huskede historik og hent alt fra Tautulli igen? Det kan tage et par minutter.")) return;
  body.refresh = !!full; shLast = {...body, refresh: false};
  $("shBtn").disabled = $("shFull").disabled = true;
  try { const job = await api("/api/sharing/run", {method: "POST", body: JSON.stringify(body)});
        poll(job, "shProg", j => { $("shBtn").disabled = $("shFull").disabled = false; if (j && j.results && j.results.users) { SH = j; if (!again) shOpen = new Set(); renderShare(); } }); }
  catch (e) { $("shBtn").disabled = $("shFull").disabled = false; toast(e.message, true); }
}
function shToggle(id) { shOpen.has(id) ? shOpen.delete(id) : shOpen.add(id); renderShare(); }
const shDay = t => { const d = new Date(t); return isNaN(d) ? esc(t) : d.toLocaleDateString("da-DK", {day: "numeric", month: "short", year: "numeric"}); };
const shPlace = x => x.status === "kunde" ? "Kunden" : (x.status === "godkendt" ? "Godkendt sted" : "Sted " + (x.place + 1));
const shUser = id => SH.results.users.find(u => u.user_id === id);
const shTag = st => st ? `<span class="tag st-${esc(st.replace(/ /g, "-"))}">${esc(SH_ST[st] || st)}</span>` : "";
async function shMark(uid, pi, mark) {
  const p = shUser(uid).places[pi]; let note = "";
  if (mark === "godkendt") { note = prompt("Hvorfor er stedet godkendt? (fx sommerhus i Blokhus)", p.mark_note || ""); if (note === null) return; }
  try { await api("/api/sharing/mark", {method: "PUT", body: JSON.stringify({user_id: uid, mids: p.mids, mark, note})});
        toast(mark ? "Gemt – regner igen" : "Valget er fjernet – regner igen"); runShare(false, true); }
  catch (e) { toast(e.message, true); }
}
async function shCase(uid) {
  try { await api("/api/sharing/user", {method: "PUT", body: JSON.stringify({user_id: uid, status: $("shc_s_" + uid).value, note: $("shc_n_" + uid).value})});
        toast("Sagen er gemt – regner igen"); runShare(false, true); }
  catch (e) { toast(e.message, true); }
}
function shCopyText(t) {
  (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(() => toast("Kopieret"), () => {
    const a = document.createElement("textarea"); a.value = t; document.body.appendChild(a); a.select(); document.execCommand("copy"); a.remove(); toast("Kopieret"); });
}
function shRule(r, main) {
  const conds = r.conds.map(c => `<li>Betingelse: <code>${esc(c.field)}</code> ${esc(c.op)} <code>${c.value.map(esc).join("</code>, <code>")}</code>${c.value.length === 1 && c.field !== "User" && c.field !== "Device Type" ? ` <button class="b sm" onclick="event.stopPropagation();shCopyText('${esc(c.value[0])}')">Kopiér</button>` : ""}</li>`).join("");
  const ok = r.own_hit === 0;
  return `<div class="shrule${main ? " main" : ""}">
    <div><b>${esc(r.title)}</b>${main && r.recommended ? ' <span class="tag st-kunde">anbefalet</span>' : ""}</div>
    <div class="shsim ${ok ? "ok" : "bad"}">Prøvet på de seneste 90 dage: stopper <b>${r.blk_hit} af ${r.blk_total}</b> fremmede afspilninger (${r.cover} %) og <b>${r.own_hit} af kundens ${r.own_total}</b>.${r.oth_hit ? ` Rammer også ${r.oth_hit} afspilninger på tv, du ikke har afgjort.` : ""}</div>
    <div class="small">Rammer: ${esc(r.devices.join(", "))}${r.missed.length ? ` · <span style="color:var(--warn)">rammer ikke: ${esc(r.missed.join(", "))}</span>` : ""}</div>
    <ol><li>Trigger: <code>A stream starts</code></li>${conds}
      <li>Handling: <code>Kill Stream</code>, Target <code>Triggering session</code></li>
      <li>Besked: <code>${esc(SH_MSG)}</code> <button class="b sm" onclick="event.stopPropagation();shCopyText(SH_MSG)">Kopiér</button></li></ol>
    <div class="small"><b>Hvorfor:</b> ${esc(r.why)}</div><div class="small"><b>Pas på:</b> ${esc(r.risk)}</div></div>`;
}
function shBlock(u) {
  const can = u.places.some(p => ["aldrig", "ikke"].includes(p.status) && p.active);
  if (!u.rules.length || u.bucket === "afgoer") {
    if (u.bucket === "afgoer") return `<div class="shbox"><b>Blokering</b><div class="small" style="margin-top:6px">Vælg først kundens sted nedenfor. Når Fangarr ved, hvad der er kundens, regner den den bedste blokering ud.</div></div>`;
    if (can) return `<div class="shbox"><b>Blokering</b><div class="small" style="margin-top:6px">De fremmede tv har ingen afspilninger de seneste 90 dage fra en offentlig adresse, så der er intet at prøve en regel af på.</div></div>`;
    return "";
  }
  const [r0, ...rest] = u.rules;
  return `<div class="shbox"><b>Bedste blokering</b> <span class="small">– laves i Tracearr under Automations. Fangarr opretter ikke reglen.</span>
    ${r0.own_hit ? '<div class="warn" style="margin:8px 0">Ingen regel kan stoppe de fremmede tv uden også at ramme kundens egne. Se tallene, før du bruger den.</div>' : ""}
    ${shRule(r0, true)}
    ${rest.length ? `<details style="margin-top:8px"><summary class="small" style="cursor:pointer">Andre muligheder (${rest.length}) – prøvet på samme måde</summary>${rest.map(r => shRule(r, false)).join("")}</details>` : ""}
    <div class="small" style="margin-top:8px">Feltnavnene er fra Tracearrs engelske udgave. Tracearr afgør selv, hvad der er et tv, og kan tælle enkelte enheder anderledes end Fangarr – hold øje med brugeren de første dage, efter reglen er lavet.</div></div>`;
}
function shDevice(d) {
  return `<div class="shc${d.in_period ? "" : " old"}">
    <div><b>${esc(d.player)}</b>${d.ids > 1 ? ` <span class="tag" title="${esc(d.ids_why)}">${d.ids} id'er – samme tv</span>` : ""}${d.in_overlap ? ' <span class="tag" style="color:var(--bad)">i overlap</span>' : ""}</div>
    ${d.why ? `<div class="small"><b>Bevis:</b> ${esc(d.why)}</div>` : ""}${d.ids > 1 ? `<div class="small">Regnes som ét tv: ${esc(d.ids_why)}.</div>` : ""}
    <div class="small">${esc(d.product || d.platform || "–")} · ${d.in_period ? `${d.plays} afspilninger på ${d.period_days} ${d.period_days === 1 ? "dag" : "dage"} i perioden` : "ikke brugt i perioden"} · brugt ${shDay(d.first)} – ${shDay(d.last)}</div>
    ${d.ip_count ? `<div class="small">${d.ip_count} ${d.ip_count === 1 ? "adresse" : "adresser"}: <span class="mono">${d.ips.map(x => `${esc(x.ip)} (${x.plays})`).join(", ")}${d.ip_count > d.ips.length ? " …" : ""}</span></div>` : ""}
    <div class="small mono" style="word-break:break-all">${esc(d.mid)}</div></div>`;
}
function shPlaceCard(u, p, pi) {
  const btn = (m, l) => `<button class="b sm" onclick="event.stopPropagation();shMark('${esc(u.user_id)}',${pi},'${m}')">${l}</button>`;
  const devs = u.devices.filter(d => d.kind === "tv" && d.place === p.place);
  const st = p.status;
  return `<div class="shc shp st-b-${esc(st)}">
    <div><b>${shPlace(p)}</b> ${shTag(st)} <span class="small">${p.tv_count} tv: ${esc(p.names.join(", "))}</span></div>
    <div class="small">${p.active ? `${esc(p.net)} · ${p.plays} afspilninger på ${p.days} ${p.days === 1 ? "dag" : "dage"} i perioden` : "ikke brugt i perioden"} · brugt ${shDay(p.first)} – ${shDay(p.last)}${p.evenings ? ` · <span style="color:var(--bad)">${p.evenings} ${p.evenings === 1 ? "aften" : "aftener"} samtidig med et andet sted</span>` : ""}</div>
    ${p.why ? `<div class="small"><b>Bevis:</b> ${esc(p.why)}${p.mark_note ? " – " + esc(p.mark_note) : ""}</div>` : ""}
    <div class="row" style="margin:8px 0 0;gap:6px">${p.mark ? btn("", "Fjern valg") : ""}${st !== "kunde" ? btn("kunde", "Dette er kundens") : ""}${p.mark !== "ikke" && st !== "aldrig" ? btn("ikke", "Ikke kundens") : ""}${st !== "kunde" && st !== "godkendt" ? btn("godkendt", "Godkend undtagelse") : ""}
      <details style="flex-basis:100%"><summary class="small" style="cursor:pointer">Enheder, adresser og id'er (${devs.length})</summary><div style="margin-top:6px">${devs.map(shDevice).join("")}</div></details></div></div>`;
}
function shDetail(u) {
  const side = x => `<div class="small"><b>${shPlace(x)}:</b> ${esc(x.player)} <span class="mono">${esc(x.ip)}</span>${x.titles.length ? " – " + esc(x.titles.join(" · ")) : ""}</div>`;
  const ev = u.events.map(e => `<div class="shc${e.approved ? " old" : ""}"><div><b>${lt(e.start)}</b> · ${e.minutes} min. samtidig${e.approved ? ' <span class="tag st-godkendt">godkendt – tæller ikke</span>' : ""}</div>${side(e.home)}${side(e.other)}</div>`).join("");
  const c = u.case || {}, mob = u.devices.filter(d => d.kind !== "tv" && d.in_period);
  const col = {bloker: "bad", afgoer: "meh", igang: "", skift: "", intet: "good"}[u.bucket] || "";
  return `<div class="card result ${col}" style="margin-bottom:8px"><b>${esc(u.conclusion)}</b></div>
    ${u.notes.map(n => `<div class="warn" style="margin-bottom:8px">${esc(n)}</div>`).join("")}${(u.info || []).map(n => `<div class="small" style="margin-bottom:8px">ℹ ${esc(n)}</div>`).join("")}
    ${shBlock(u)}
    <h4>Steder, kontoen bruges på tv (${u.places.filter(p => p.active).length})</h4>
    ${u.places.map((p, i) => shPlaceCard(u, p, i)).join("")}
    <div class="shbox"><b>Sag</b> <span class="small">– hvad har du gjort ved denne bruger?</span>
      <div class="row" style="margin:8px 0 0"><select id="shc_s_${esc(u.user_id)}" style="width:auto" onclick="event.stopPropagation()">${SH_CASE.concat(SH_CASE.includes(c.status || "") ? [] : [c.status]).map(s => `<option value="${esc(s)}" ${(c.status || "") === s ? "selected" : ""}>${s ? esc(s[0].toUpperCase() + s.slice(1)) : "Ingen status"}</option>`).join("")}</select>
      <input type="text" id="shc_n_${esc(u.user_id)}" value="${esc(c.note || "")}" placeholder="Note, fx: regel lavet i Tracearr 11. nov." style="flex:1;min-width:160px">
      <button class="b" onclick="shCase('${esc(u.user_id)}')">Gem</button></div></div>
    ${u.events.length ? `<details class="shbox"><summary><b>Samtidig afspilning</b> <span class="small">– ${u.overlaps} gange på ${u.evenings} aftener${u.approved_overlaps ? ` (+ ${u.approved_overlaps} godkendte)` : ""}, seneste først</span></summary><div style="margin-top:8px">${ev}</div></details>` : ""}
    ${mob.length ? `<details class="shbox"><summary><b>Mobile enheder</b> <span class="small">– ${mob.length} telefoner, tablets og computere. Tæller ikke som tv og må bruges alle steder</span></summary><div style="margin-top:8px">${mob.map(shDevice).join("")}</div></details>` : ""}`;
}
function renderShare() {
  const R = SH.results, cut = !!R.cut, H = R.history || {}, B = R.buckets || {};
  const showAll = $("shAll") ? $("shAll").checked : false;
  $("shHist").textContent = H.rows ? `Husket historik: ${H.rows.toLocaleString("da-DK")} afspilninger fra ${shDay(H.oldest)}, hentet ${fmt(H.fetched)}` : "";
  $("shSum").innerHTML = `<div class="row" style="margin:14px 0 6px">${SH_BUCKET.map(([k, l]) => `<span class="chip">${l} <b>${B[k] || 0}</b></span>`).join("")}</div>
    <div class="small" style="margin-bottom:10px">${shDay(R.from)} – ${shDay(R.to)}${cut ? ` · skæringsdato ${shDay(R.cut)}` : ""} · ${R.sessions.toLocaleString("da-DK")} afspilninger · mindst ${R.min_minutes} min. samtidig · beregnet ${fmt(SH.started)}. Tryk på en bruger for at se steder og den bedste blokering.
    <label style="display:inline-flex;gap:6px;align-items:center;margin:0 0 0 10px"><input type="checkbox" id="shAll" onchange="renderShare()" style="width:auto" ${showAll ? "checked" : ""}> Vis alle grupper</label></div>`;
  const n = cut ? 7 : 5;
  const row = u => { const r = u.rules[0]; return `<tr class="shu" onclick="shToggle('${esc(u.user_id)}')">
      <td><b>${esc(u.name)}</b>${u.username && u.username !== u.name ? `<div class="small">${esc(u.username)}</div>` : ""}</td>
      <td class="num">${u.foreign_tv || "–"}</td><td class="num">${u.evenings || "–"}</td>
      ${cut ? `<td class="num">${u.before || "–"}</td><td class="num"${u.after ? ' style="color:var(--bad);font-weight:600"' : ""}>${u.after || "–"}</td>` : ""}
      <td class="hs">${u.last_overlap ? lt(u.last_overlap) : "–"}</td>
      <td class="small">${(u.case || {}).status ? `<b>${esc(u.case.status)}</b>${u.case.note ? " · " + esc(u.case.note) : ""}` : (u.bucket === "afgoer" ? "vælg kundens sted først" : (r ? `${esc(r.title)} <span style="color:${r.own_hit ? "var(--bad)" : "var(--ok)"}">(${r.cover} %)</span>` : ""))}</td></tr>` +
      (shOpen.has(u.user_id) ? `<tr class="shd"><td colspan="${n}">${shDetail(u)}</td></tr>` : ""); };
  $("shGroups").innerHTML = SH_BUCKET.map(([k, label, hint, open]) => {
    const us = R.users.filter(u => u.bucket === k);
    if (!us.length || !(open || showAll || us.some(u => shOpen.has(u.user_id)))) return "";
    return `<h3 class="shg">${label} (${us.length})</h3><p class="hint" style="margin:0 0 8px">${hint}</p>
      <div class="card" style="padding:0; overflow-x:auto"><table><thead><tr><th>Bruger</th><th class="num">Fremmede tv</th><th class="num">Aftener</th>${cut ? '<th class="num">Før</th><th class="num">Efter</th>' : ""}<th class="hs">Seneste</th><th>${k === "igang" ? "Sag" : "Bedste blokering"}</th></tr></thead>
      <tbody>${us.map(row).join("")}</tbody></table></div>`; }).join("") || '<div class="card empty">Ingen brugere at vise. Slå "Vis alle grupper" til for at se resten.</div>';
  $("shKinds").innerHTML = `<details style="margin-top:14px"><summary class="small" style="cursor:pointer">Enhedstyper – sådan er enhederne talt (tv / mobil)</summary>
    <div class="card" style="padding:0; overflow-x:auto; margin-top:8px"><table><thead><tr><th>Platform</th><th>App</th><th>Tælles som</th><th class="num">Enheder</th><th class="num">Afspilninger</th></tr></thead><tbody>` +
    R.kinds.map(k => `<tr><td>${esc(k.platform || "–")}</td><td>${esc(k.product || "–")}</td><td${k.kind === "ukendt" ? ' style="color:var(--warn)"' : ""}>${SH_KIND[k.kind]}</td><td class="num">${k.devices}</td><td class="num">${k.plays}</td></tr>`).join("") + "</tbody></table></div></details>";
}
