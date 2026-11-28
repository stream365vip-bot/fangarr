// Kontodeling › Blokeringer og Indstillinger (2.4.0): overtrædelser fra Tracearr samlet pr. kunde.
let BLK = null, blkOpenSet = new Set();
const BLK_ACT = {stopper: ["stopper afspilningen", "bad"], besked: ["kun besked", "warn"], test: ["test", ""], "": ["ukendt – vælg under Indstillinger", "info"]};

async function loadBlk() {
  const q = `?days=${$("blkDays").value}&rule=${encodeURIComponent($("blkRule").value)}&open=${$("blkOpen").checked ? 1 : 0}`;
  try { BLK = await api("/api/blokeringer" + q); } catch (e) { $("blkList").innerHTML = `<div class="warn">${esc(e.message)}</div>`; return; }
  renderBlk();
}
async function blkRefresh() {
  $("blkBtn").disabled = true;
  try { const r = await api("/api/blokeringer/hent", {method: "POST"}); toast(`Hentet ${r.count} overtrædelser fra Tracearr`); await loadBlk(); }
  catch (e) { toast(e.message, true); }
  $("blkBtn").disabled = false;
}
function blkActTag(a) { const x = BLK_ACT[a] || BLK_ACT[""]; return `<span class="pill ${x[1]}">${esc(x[0])}</span>`; }
function renderBlk() {
  const B = BLK;
  if (!B.enabled) { $("blkInfo").innerHTML = ""; $("blkList").innerHTML = '<div class="warn">Tracearr er ikke sat op. Tilføj TRACEARR_URL og TRACEARR_APIKEY i fangarr.env (se LÆSMIG).</div>'; return; }
  const sel = $("blkRule"), keep = sel.value;
  sel.innerHTML = '<option value="">Alle viste regler</option>' + B.rules.filter(r => r.show).map(r => `<option value="${esc(r.name)}">${esc(r.name)} (${r.count})</option>`).join("");
  if ([...sel.options].some(o => o.value === keep)) sel.value = keep;
  if (B.link) { $("blkLink").href = B.link; $("blkLink").style.display = ""; }
  setBadge("blk", B.new, true);
  const open = B.groups.reduce((n, g) => n + g.open, 0), total = B.groups.reduce((n, g) => n + g.count, 0);
  $("blkInfo").innerHTML = (B.error ? `<div class="warn">Seneste hentning fejlede: ${esc(B.error)}</div>` : "") +
    `Hentet fra Tracearr ${B.synced ? lt(B.synced) : "– endnu ikke"} (hvert 15. minut). ${total} overtrædelser hos ${B.groups.length} brugere${open ? ` · <b style="color:var(--bad)">${open} uafgjorte</b>` : ""}. ` +
    B.rules.filter(r => r.show && r.count).map(r => `<span class="chip">${esc(r.name)} <b>${r.count}</b> ${blkActTag(r.action)}</span>`).join(" ") +
    (B.rules.some(r => !r.show && r.count) ? ` <span class="small">· skjult: ${B.rules.filter(r => !r.show && r.count).map(r => `${esc(r.name)} (${r.count})`).join(", ")}</span>` : "");
  if (!B.groups.length) { $("blkList").innerHTML = '<div class="card empty">Ingen overtrædelser i perioden 🎉</div>'; return; }
  $("blkList").innerHTML = `<div class="card" style="padding:0;overflow-x:auto"><table><thead><tr><th>Kunde</th><th class="num">Uafgjorte</th><th class="num">I alt</th><th>Regler</th><th class="hs">Seneste</th><th>Sag</th></tr></thead><tbody>` +
    B.groups.map(g => `<tr class="shu" onclick="blkToggle('${esc(g.key)}')"><td><b>${esc(g.name)}</b>${g.username && g.username !== g.name ? `<div class="small">${esc(g.username)}</div>` : ""}${g.customer_id ? "" : '<div class="small" style="color:var(--info)">ikke koblet til en kunde</div>'}</td>
      <td class="num"${g.open ? ' style="color:var(--bad);font-weight:600"' : ""}>${g.open || "–"}</td><td class="num">${g.count}</td>
      <td class="small">${Object.entries(g.rules).map(([n, c]) => `${esc(n)} (${c})`).join(", ")}</td><td class="hs">${lt(g.last)}</td>
      <td class="small">${g.case && g.case.status ? `<b>${esc(g.case.status)}</b>${g.case.note ? " · " + esc(g.case.note) : ""}` : ""}</td></tr>` +
      (blkOpenSet.has(g.key) ? `<tr class="shd"><td colspan="6">${blkDetail(g)}</td></tr>` : "")).join("") + "</tbody></table></div>";
}
function blkToggle(k) { blkOpenSet.has(k) ? blkOpenSet.delete(k) : blkOpenSet.add(k); renderBlk(); }
function blkDetail(g) {
  const c = g.case || {}, uid = g.plex_user;
  const caseBox = uid != null ? `<div class="shbox" onclick="event.stopPropagation()"><b>Sag</b> <span class="small">– samme sag som under Analyse</span>
      <div class="row" style="margin:8px 0 0"><select id="blkc_s_${esc(g.key)}" style="width:auto">${SH_CASE.concat(SH_CASE.includes(c.status || "") ? [] : [c.status]).map(s => `<option value="${esc(s)}" ${(c.status || "") === s ? "selected" : ""}>${s ? esc(s[0].toUpperCase() + s.slice(1)) : "Ingen status"}</option>`).join("")}</select>
      <input type="text" id="blkc_n_${esc(g.key)}" value="${esc(c.note || "")}" placeholder="Note, fx: blokeret i Tracearr 28. nov." style="flex:1;min-width:160px">
      <button class="b" onclick="blkCase('${esc(g.key)}', ${uid})">Gem</button></div></div>` : "";
  const items = g.items.map(v => `<tr${v.acked || v.seen ? ' style="opacity:.6"' : ""}><td class="hs" style="white-space:nowrap">${lt(v.created)}</td>
      <td>${esc(v.rule)}<div>${blkActTag(v.action)}</div></td><td>${esc(v.title || "–")}${v.evidence.length ? `<div class="small">${v.evidence.map(esc).join("<br>")}</div>` : ""}</td>
      <td class="small mono">${esc(v.ip || "")}</td><td class="small">${v.acked ? "kvitteret i Tracearr" : v.seen ? "set i Fangarr" : '<span style="color:var(--bad)">uafgjort</span>'}</td></tr>`).join("");
  return `<div class="row" style="margin:0 0 8px;gap:6px" onclick="event.stopPropagation()">
      ${g.open ? `<button class="b sm" onclick="blkSeen('${esc(g.key)}')">Markér alle som set</button>` : `<button class="b sm" onclick="blkSeen('${esc(g.key)}', true)">Fortryd "set"</button>`}
      ${g.customer_id ? `<button class="b sm" onclick="kOpen(${g.customer_id})">Kundekort</button><button class="b sm" onclick="fsOpen(${g.customer_id})">Fejlsøg</button>` : ""}
      ${BLK.link ? `<a class="b sm" href="${esc(BLK.link)}" target="_blank" rel="noopener">Åbn Tracearr</a>` : ""}</div>
    ${caseBox}
    <div style="overflow-x:auto"><table><thead><tr><th>Tid</th><th>Regel</th><th>Titel og bevis</th><th>Adresse</th><th>Status</th></tr></thead><tbody>${items}</tbody></table></div>
    ${g.items.length < g.count ? `<div class="small">Viser de nyeste ${g.items.length} af ${g.count}.</div>` : ""}`;
}
async function blkSeen(key, undo) {
  try { await api("/api/blokeringer/set", {method: "PUT", body: JSON.stringify({key, undo: !!undo})}); toast(undo ? "Fortrudt" : "Markeret som set"); await loadBlk(); loadHome(); }
  catch (e) { toast(e.message, true); }
}
async function blkCase(key, uid) {
  try { await api("/api/sharing/user", {method: "PUT", body: JSON.stringify({user_id: String(uid), status: $("blkc_s_" + key).value, note: $("blkc_n_" + key).value})});
        toast("Sagen er gemt"); await loadBlk(); }
  catch (e) { toast(e.message, true); }
}

// ---------- Indstillinger
async function loadShareCfg() {
  try { const a = await api("/api/sharing/auto"); $("shAutoOn").checked = a.enabled;
        $("shAutoInfo").textContent = a.last ? `Seneste automatiske kørsel: ${a.last}.` : "Har ikke kørt af sig selv endnu."; } catch (e) { toast(e.message, true); }
  try { BLK = await api("/api/blokeringer?days=180"); } catch (e) { $("blkRules").innerHTML = `<div class="warn">${esc(e.message)}</div>`; return; }
  $("blkRules").innerHTML = BLK.rules.length ? `<table><thead><tr><th>Regel i Tracearr</th><th>Hvad gør den?</th><th>Vis</th><th class="num">Seneste 180 dage</th></tr></thead><tbody>` +
    BLK.rules.map((r, i) => `<tr><td><b>${esc(r.name)}</b></td><td><select id="blkr_a_${i}" style="width:auto">${[["", "– vælg –"], ["stopper", "Stopper afspilningen"], ["besked", "Kun besked"], ["test", "Test"]].map(([v, l]) => `<option value="${v}" ${r.action === v ? "selected" : ""}>${l}</option>`).join("")}</select></td>
      <td><input type="checkbox" id="blkr_s_${i}" style="width:auto" ${r.show ? "checked" : ""}></td><td class="num">${r.count}</td></tr>`).join("") + "</tbody></table>"
    : '<div class="empty">Ingen regler fundet endnu.</div>';
}
async function blkRulesSave() {
  const rules = BLK.rules.map((r, i) => ({name: r.name, action: $("blkr_a_" + i).value, show: $("blkr_s_" + i).checked}));
  try { await api("/api/blokeringer/regler", {method: "PUT", body: JSON.stringify({rules})}); toast("Gemt"); loadHome(); } catch (e) { toast(e.message, true); }
}
async function shAutoSave() {
  try { await api("/api/sharing/auto", {method: "PUT", body: JSON.stringify({enabled: $("shAutoOn").checked})}); toast("Gemt"); } catch (e) { toast(e.message, true); }
}
// Nye konti fra den automatiske analyse – vises øverst under Analyse og ryddes, når du har set dem
async function shAutoShow() {
  let a; try { a = await api("/api/sharing/auto"); } catch (e) { return; }
  const n = a.new || [];
  $("shAutoNew").innerHTML = n.length ? `<div class="card result bad" style="margin-bottom:10px"><b>Nye siden mandag nats analyse</b>
    <div class="small" style="margin-top:6px">${n.map(u => `${esc(u.name || u.user_id)} – ${u.bucket === "bloker" ? "kan blokeres" : "afgør selv"}${u.evenings ? ` (${u.evenings} aftener)` : ""}`).join(" · ")}</div>
    <div class="small">Tryk Analysér for at se dem. Listen ryddes nu, så de ikke står under Kræver din handling igen.</div></div>` : "";
  if (n.length) { api("/api/sharing/auto", {method: "PUT", body: JSON.stringify({seen: true})}).then(() => { if (OV) { OV.sharing_new = 0; renderHome(); } }).catch(() => {}); }
}
