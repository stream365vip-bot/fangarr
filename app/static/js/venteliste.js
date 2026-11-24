// Venteliste: titler, der venter på TheTVDB/TMDb, godkendte koblinger og fjernede titler ("Fjern og husk").
async function loadWait() {
  try { renderWait(await api("/api/waitlist")); } catch (e) { toast(e.message, true); }
}
function renderWait(rows) {
  $("waitBody").innerHTML = rows.length ? rows.map(w => `<tr>
    <td><b>${esc(w.title)}</b> <span class="small">${w.media === "movie" ? "Film" : "Serie"}</span><div class="small">${esc(w.release)}</div>
      <div class="small">Regel: ${esc(w.rule)} · sat på ${fmt(w.created)}</div></td>
    <td class="d ${WAIT_CLS[w.status] || ""}">${esc(w.status)}</td>
    <td>${w.attempts}</td>
    <td>${w.status === "venter" ? fmt(w.next_try) : "–"}</td>
    <td>${esc(w.reason)}${(w.suggestions || []).length && w.status === "venter" ? `<div class="sugg"><div class="small" style="margin:8px 0 4px">Muligt match – godkend det rigtige:</div>` +
      w.suggestions.map(sg => `<div class="row" style="margin:0 0 6px;gap:8px;flex-wrap:nowrap;align-items:flex-start">
        <button class="b pri" style="flex:none" onclick="approveWait(${w.id}, '${esc(String(sg.id))}', this)">Godkend</button>
        <span><b>${esc(sg.title)}</b>${/\(\d{4}\)$/.test(sg.title) ? "" : ` (${sg.year || "?"})`} · ${esc(LANG_DA[sg.language] || sg.language || "sprog ukendt")} · ${esc(sg.network || "kanal ukendt")}
        · ${esc((sg.genres || []).map(g => GENRE_DA[g] || g).join(", ") || "ingen genrer")}${sg.exists ? ' · <b>findes allerede</b>' : ""}${sg.note ? `<span class="small"> (${esc(sg.note)})</span>` : ""}</span></div>`).join("") + "</div>" : ""}</td>
    <td><div class="btns"><button class="b" onclick="retryWait(${w.id})">Prøv nu</button><button class="b danger" onclick="delWait(${w.id})">Fjern</button>${w.status === "venter" ? `<button class="b danger" onclick="delWait(${w.id}, 1)" title="Fjern titlen, og lad den ikke komme på ventelisten igen">Fjern og husk</button>` : ""}</div></td></tr>`).join("")
    : '<tr><td colspan="6" class="empty">Ventelisten er tom.</td></tr>';
}
async function approveWait(id, sid, btn) {
  const w = btn.closest("tr").querySelector("b").textContent;
  const sg = btn.nextElementSibling.querySelector("b").textContent;
  if (!confirm(`Er “${w}” det samme som “${sg}”? Den tilføjes med reglens mappe, profil og mærke.`)) return;
  btn.disabled = true;
  try { renderWait(await api(`/api/waitlist/${id}/approve`, {method: "POST", body: JSON.stringify({id: sid})})); toast("Godkendt"); load(); }
  catch (e) { btn.disabled = false; toast(e.message, true); }
}
async function retryWait(id) {
  try { renderWait(await api(`/api/waitlist/${id}/retry`, {method: "POST"})); toast("Prøvet igen"); load(); } catch (e) { toast(e.message, true); }
}


async function loadAliases() {
  try { renderAliases(await api("/api/aliases")); } catch (e) {}
}
function renderAliases(rows) {
  $("aliasBody").innerHTML = rows.length ? rows.map(a => `<tr><td><b>${esc(a.release_title)}</b></td><td>${esc(a.title)} <span class="small">(${a.media === "movie" ? "TMDb" : "TheTVDB"} ${a.ext_id})</span></td>
    <td>${a.media === "movie" ? "Film" : "Serie"}</td><td style="white-space:nowrap">${fmt(a.created)}</td>
    <td><button class="b danger" onclick="delAlias(${a.id})">Fjern</button></td></tr>`).join("")
    : '<tr><td colspan="5" class="empty">Ingen koblinger endnu.</td></tr>';
}
async function delAlias(id) {
  if (!confirm("Fjern koblingen? Fremtidige udgivelser med den titel bliver så ikke længere matchet automatisk.")) return;
  try { renderAliases(await api(`/api/aliases/${id}`, {method: "DELETE"})); toast("Koblingen er fjernet"); } catch (e) { toast(e.message, true); }
}

// ---------- fjernede titler (Fjern og husk)
async function delWait(id, remember) {
  if (remember && !confirm("Fjern titlen og husk den? Så kommer den ikke på ventelisten igen, når der kommer en ny udgivelse. Du kan fortryde under Venteliste › Fjernede titler.")) return;
  try { renderWait(await api(`/api/waitlist/${id}${remember ? "?remember=1" : ""}`, {method: "DELETE"})); toast(remember ? "Fjernet og husket" : "Fjernet fra ventelisten"); load(); } catch (e) { toast(e.message, true); }
}
async function loadIgnored() { try { renderIgnored(await api("/api/ignored")); } catch (e) {} }
function renderIgnored(rows) {
  $("ignBody").innerHTML = rows.length ? rows.map(a => `<tr><td><b>${esc(a.title)}</b></td><td>${a.media === "movie" ? "Film" : "Serie"}</td><td>${fmt(a.created)}</td>
    <td><div class="btns"><button class="b danger" onclick="delIgnored(${a.id})">Glem</button></div></td></tr>`).join("")
    : '<tr><td colspan="4" class="empty">Ingen fjernede titler. Brug “Fjern og husk” på ventelisten.</td></tr>';
}
async function delIgnored(id) { try { renderIgnored(await api(`/api/ignored/${id}`, {method: "DELETE"})); toast("Glemt – titlen kan komme på ventelisten igen"); } catch (e) { toast(e.message, true); } }
