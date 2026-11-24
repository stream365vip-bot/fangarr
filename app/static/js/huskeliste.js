// 2.1: Huskeliste (Drift › Huskeliste), Udgifter (Opkrævning › Udgifter), Besked ved 0 streams (Overblik)
// og Telegram-knapperne (Indstillinger › Telegram).

// ---------- huskeliste
let HL = null, HL_DONE = false;
const HL_REP = {"": "Ingen", dag: "Hver dag", uge: "Hver uge", maaned: "Hver måned", kvartal: "Hvert kvartal", aar: "Hvert år"};
const HL_SRV = ["", "feeder", "Mediabox", "begge", "Chromebook", "telefon", "andet"];
const hlDay = d => { if (!d) return "–"; const t = new Date(d + "T12:00:00"); return t.toLocaleDateString("da-DK", {weekday: "short", day: "numeric", month: "short", year: "numeric"}); };
function hlCopy(t) {
  (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(() => toast("Kommandoen er kopieret"), () => {
    const a = document.createElement("textarea"); a.value = t; document.body.appendChild(a); a.select(); document.execCommand("copy"); a.remove(); toast("Kommandoen er kopieret"); });
}
async function loadHuske() {
  try { HL = await api("/api/huskeliste" + (HL_DONE ? "?done=1" : "")); } catch (e) { toast(e.message, true); return; }
  renderHuske();
}
function huskeToggleDone() { HL_DONE = !HL_DONE; $("huskeDoneBtn").textContent = HL_DONE ? "Vis det, der mangler" : "Vis udførte"; loadHuske(); }
function renderHuske() {
  const el = $("huskeList"); if (!HL) return;
  if (!HL.items.length) { el.innerHTML = `<div class="card"><div class="empty">${HL_DONE ? "Intet er markeret udført endnu." : "Intet på huskelisten. Tryk Ny opgave."}</div></div>`; return; }
  el.innerHTML = '<div class="card tp"><div class="kl">' + HL.items.map(h => {
    const state = h.done_at ? `<span class="pill ok">Udført ${kDay(h.done_at)}</span>` : h.overdue ? '<span class="pill bad">Overskredet</span>' : h.today ? '<span class="pill warn">I dag</span>' : "";
    return `<div class="kr"><div class="who" style="flex:1 1 320px"><b>${esc(h.title)}</b> ${state}
      <div class="small">${hlDay(h.due)}${h.server ? " · " + esc(h.server) : ""}${h.repeat ? " · " + esc(HL_REP[h.repeat] || h.repeat) : ""}${h.kind === "udgift" ? " · fra Udgifter" : ""}</div>
      ${h.command ? `<div class="hlcmd"><code>${esc(h.command)}</code><button class="b sm" onclick="hlCopy(${esc(JSON.stringify(h.command))})" title="Kopiér kommandoen">Kopiér</button></div>` : ""}
      ${h.note ? `<div class="small">${esc(h.note)}</div>` : ""}</div>
      <div class="btns">${h.done_at ? `<button class="b sm" onclick="huskeAct(${h.id},'reopen')">Fortryd udført</button>`
        : `<button class="b sm pri" onclick="huskeAct(${h.id},'done')">Udført</button><button class="b sm" onclick="huskeAct(${h.id},'snooze')">Udsæt en dag</button>
           <button class="b sm" onclick="huskeEdit(${h.id})">Ret</button><button class="b sm danger" onclick="huskeDel(${h.id})">Slet</button>`}</div></div>`;
  }).join("") + "</div></div>";
  tipAll(el);
}
async function huskeAct(id, a) {
  try { HL = await api(`/api/huskeliste/${id}/${a}`, {method: "POST"}); renderHuske(); loadHome();
        toast(a === "done" ? "Markeret udført" : a === "snooze" ? "Udsat til i morgen" : "Står på huskelisten igen"); }
  catch (e) { toast(e.message, true); }
}
async function huskeDel(id) {
  if (!confirm("Slet opgaven fra huskelisten?")) return;
  try { HL = await api("/api/huskeliste/" + id, {method: "DELETE"}); renderHuske(); loadHome(); } catch (e) { toast(e.message, true); }
}
function huskeEdit(id) {
  const h = id ? (HL.items.find(x => x.id === id) || {}) : {due: new Date().toISOString().slice(0, 10)};
  kForm(id ? "Ret opgave" : "Ny opgave", [
    {k: "title", label: "Hvad skal du huske?"},
    {k: "due", label: "Dato", type: "date"},
    {k: "server", label: "Hvor", type: "select", options: HL_SRV.map(s => [s, s || "(ingen)"])},
    {k: "command", label: "Kontrolkommando (valgfri)", ph: "fx df -h /mnt/local",
     hint: "Vises med en kopiknap. Kun kommandoer, der viser noget – skriv aldrig nøgler eller kodeord her."},
    {k: "repeat", label: "Gentag", type: "select", options: Object.entries(HL_REP)},
    {k: "note", label: "Note (valgfri)", type: "textarea"},
  ], h, async v => { HL = await api("/api/huskeliste", {method: "POST", body: JSON.stringify({...v, id: id || null})}); HL_DONE = false; renderHuske(); loadHome(); });
}

// ---------- udgifter
let UD = null;
async function loadUdg() { try { UD = await api("/api/udgifter"); } catch (e) { toast(e.message, true); return; } renderUdg(); }
function renderUdg() {
  if (!UD) return;
  $("udgKpis").innerHTML = [["Pr. måned", kkr(Math.round(UD.per_month)), "aktive udgifter"], ["Pr. år", kkr(Math.round(UD.per_year)), "bruges i Økonomi"],
    ["Fornyes snart", UD.items.filter(u => u.soon).length, "varslet er nået"]].map(([l, v, s]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${esc(s)}</div></div>`).join("");
  $("udgBody").innerHTML = UD.items.length ? UD.items.map(u => `<tr style="${u.active ? "" : "opacity:.55"}"><td><b>${esc(u.name)}</b>${u.active ? "" : ' <span class="pill">ikke aktiv</span>'}${u.note ? `<div class="small">${esc(u.note)}</div>` : ""}</td>
    <td class="num">${kkr(u.amount)} <span class="small">pr. ${u.per === "aar" ? "år" : "måned"}</span></td><td class="num hs">${kkr(Math.round(u.monthly))}</td>
    <td>${u.renews ? kDay(u.renews) + (u.soon ? ' <span class="pill warn">snart</span>' : "") + `<div class="small">varsel ${u.notice} dage</div>` : '<span class="small">ingen dato</span>'}</td>
    <td style="white-space:nowrap"><button class="b sm" onclick="udgEdit(${u.id})">Ret</button> <button class="b sm danger" onclick="udgDel(${u.id})">Slet</button></td></tr>`).join("")
    : '<tr><td colspan="5" class="empty">Ingen udgifter endnu. Tryk Ny udgift.</td></tr>';
  setBadge("udg", UD.items.filter(u => u.soon).length, false);
  tipAll($("udgBody"));
}
function udgEdit(id) {
  const u = id ? (UD.items.find(x => x.id === id) || {}) : {per: "maaned", notice: 14, active: true};
  kForm(id ? "Ret udgift" : "Ny udgift", [
    {k: "name", label: "Navn", ph: "fx Hetzner feeder"},
    {k: "amount", label: "Beløb i kr.", type: "money"},
    {k: "per", label: "Beløbet er pr.", type: "select", options: [["maaned", "måned"], ["aar", "år"]]},
    {k: "renews", label: "Næste fornyelse (valgfri)", type: "date", hint: "Når varslet nås, kommer \"Forny …\" på huskelisten."},
    {k: "notice", label: "Varsel i dage", type: "int"},
    {k: "note", label: "Note (valgfri)", type: "textarea"},
    {k: "active", label: "Aktiv (tæller med i Økonomi)", type: "check"},
  ], u, async v => { UD = await api("/api/udgifter", {method: "POST", body: JSON.stringify({...v, id: id || null})}); renderUdg(); });
}
async function udgDel(id) {
  if (!confirm("Slet udgiften? Den tæller så ikke længere med i Økonomi.")) return;
  try { UD = await api("/api/udgifter/" + id, {method: "DELETE"}); renderUdg(); } catch (e) { toast(e.message, true); }
}

// ---------- besked ved 0 streams (Overblik)
let STL = null;
async function loadStille() {
  try { STL = await api("/api/stille"); } catch (e) { return; }
  renderStille();
}
function renderStille() {
  const box = $("homeStille"); if (!box || !STL) return;
  if (!STL.enabled) { box.hidden = true; return; }
  box.hidden = false;
  const win = (STL.from != null && STL.from !== "" && STL.to != null && STL.to !== "") ? ` mellem kl. ${STL.from} og ${STL.to}` : "";
  $("stilleInfo").innerHTML = STL.armed
    ? `<b>Venter på 0 streams${win}.</b> Du får én besked i Stream365 Drift.${STL.last_count != null ? ` Seneste tjek: ${STL.last_count} ${STL.last_count === 1 ? "stream" : "streams"} (${fmt(STL.last_check)}).` : ""}`
    : "Fangarr sender én besked til Stream365 Drift, når ingen streamer – fx før en genstart eller opdatering af Plex." + (STL.fired_at ? ` Sidst: ${fmt(STL.fired_at)}.` : "");
  $("stilleBtns").innerHTML = STL.armed ? '<button class="b sm" onclick="stilleOff()">Stop</button>' : '<button class="b sm pri" onclick="stilleArm()">Sig til ved 0 streams</button>';
  $("stilleWin").style.display = STL.armed ? "none" : "";
  const q = STL.quiet;
  $("stilleQuiet").innerHTML = !q ? "" : q.error ? "Kunne ikke regne ud, hvornår der normalt er stille." :
    q.from ? `Normalt stille om natten: <b>kl. ${esc(q.from)}–${esc(q.to)}</b> (0 streams i mindst 9 af 10 nætter de sidste ${q.nights} nætter).`
           : `Ingen fast stille periode om natten de sidste ${q.nights} nætter.`;
  tipAll(box);
}
async function stilleArm() {
  try { STL = await api("/api/stille", {method: "POST", body: JSON.stringify({from: $("stilleFrom").value.trim(), to: $("stilleTo").value.trim()})});
        renderStille(); toast("Du får besked, når der er 0 streams"); } catch (e) { toast(e.message, true); }
}
async function stilleOff() { try { STL = await api("/api/stille", {method: "DELETE"}); renderStille(); } catch (e) { toast(e.message, true); } }

// ---------- Telegram-knapperne (Indstillinger › Telegram)
const TG_KIND = {huske_done: "Huskeliste: udført", huske_snooze: "Huskeliste: udsat", pay_paid: "Betaling: betalt", pay_snooze: "Betaling: udsat",
  stille_again: "0 streams: sig til igen", prem_add: "Premiere: tilføjet", prem_follow: "Premiere: følges", prem_no: "Premiere: ikke interesseret",
  wl_approve: "Venteliste: godkendt", wl_remove: "Venteliste: fjernet", tr_now: "Oversæt nu"};
async function loadTgStatus() {
  const el = $("tgRecent"); if (!el) return;
  try {
    const d = await api("/api/telegram/status");
    const head = !d.enabled ? "Telegram er ikke sat op." : !d.buttons ? "Knapperne er slået fra." :
      `Fangarr læser dine tryk${d.last_ok ? " – senest tjekket " + fmt(d.last_ok) : ""}.${d.last_error ? ` <span style="color:var(--bad)">Fejl: ${esc(d.last_error)}</span>` : ""}${d.rejected ? ` ${d.rejected} tryk fra andre chats er afvist siden start.` : ""}`;
    el.innerHTML = head + (d.recent.length ? '<table style="margin-top:10px"><tbody>' + d.recent.map(r => `<tr><td style="white-space:nowrap">${fmt(r.done_at)}</td>
      <td>${esc(TG_KIND[r.kind] || r.kind)}${r.undone_at ? ' <span class="pill">fortrudt</span>' : ""}</td><td class="small">${esc(r.result || "")}</td></tr>`).join("") + "</tbody></table>"
      : '<div style="margin-top:8px">Ingen tryk endnu.</div>');
  } catch (e) { el.textContent = "Kunne ikke hente status for knapperne."; }
}
