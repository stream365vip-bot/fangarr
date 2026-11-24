// 2.2: Beskeder › Send-kø, Ønsker klar, Ændring for alle og Skabeloner – Guide › Søgninger – tidslinjen på kundekortet.
// Fangarr skriver aldrig selv til kunderne: hver besked åbnes klar i Telegram eller Messenger, og du trykker selv send.

const bdlg = $("bdlg");
let BQ = null, BQ_ALL = false, BQ_OPEN = null, BR = null, BR_DONE = false, BT = null, BP = null, BSEND = null;

// ---------- fælles: send én besked (samme knapper som Opkrævning › Send besked)
function bSend(item, onDone) {
  BSEND = {item, onDone};
  $("bdTitle").textContent = "Send besked – " + item.name; $("bdErr").textContent = "";
  $("bdBody").innerHTML = `<div class="field"><label for="bd_text">Beskeden til kunden</label><textarea class="kta" id="bd_text" style="min-height:220px" oninput="bUpd()">${esc(item.text)}</textarea>
      <div class="small">Du kan rette teksten her – det gælder kun denne besked.</div></div><div class="small" id="bd_how" style="margin-top:10px"></div>`;
  const tg = item.tg && item.channel !== "messenger", fb = item.fb && item.channel !== "telegram";
  $("bdFoot").innerHTML = `<button class="b" onclick="bAct('skip')">Spring over</button><button class="b" onclick="bCopy()">Kopiér</button>`
    + (navigator.share ? `<button class="b" onclick="bShare()">Del …</button>` : "")
    + (fb ? `<a class="b pri" id="bd_fb" ${ANDROID ? "" : 'target="_blank" rel="noopener"'} onclick="return bGo('fb')">Kopiér + åbn Messenger</a>` : "")
    + (tg ? `<a class="b pri" id="bd_tg" ${ANDROID ? "" : 'target="_blank" rel="noopener"'} onclick="return bGo('tg')">Åbn i Telegram</a>` : "")
    + `<button class="b ${tg || fb ? "" : "pri"}" onclick="bAct('sent')">Markér sendt</button>`;
  $("bd_how").innerHTML = (tg ? "<b>Åbn i Telegram</b> åbner chatten med beskeden skrevet – du trykker bare send. " : "")
    + (fb ? "<b>Kopiér + åbn Messenger</b> kopierer beskeden og åbner chatten – sæt ind, og tryk send. " : "")
    + "Åbn/kopiér markerer beskeden som sendt. <b>Spring over</b> fjerner kunden fra listen uden besked."
    + (!tg && !fb ? ` <a href="#" onclick="bdlg.close();kOpen(${item.customer_id});return false">Skriv kundens Telegram- eller Messenger-brugernavn på kundekortet</a>, så kan chatten åbnes direkte.` : "");
  bUpd(); bdlg.showModal();
}
function bText() { return $("bd_text").value.trim(); }
function bUpd() {
  const it = BSEND.item;
  if ($("bd_tg")) $("bd_tg").href = tgUrl(it.tg, bText());
  if ($("bd_fb")) $("bd_fb").href = fbUrl(it.fb);
}
function bGo(kind) {
  if (!bText()) { $("bdErr").textContent = "Beskeden er tom."; return false; }
  if (kind === "fb") sCopyNow(bText());
  setTimeout(() => bAct("sent", true), 300);
  return true;
}
function bCopy() { sCopyNow(bText()); toast("Kopieret"); bAct("sent"); }
async function bShare() { try { await navigator.share({text: bText()}); bAct("sent"); } catch (e) {} }
async function bAct(action, quiet) {
  try { await BSEND.onDone(action); bdlg.close(); loadHome(); }
  catch (e) { $("bdErr").textContent = e.message; }
}

// ---------- send-kø
async function loadQueues() {
  try { BQ = await api("/api/beskeder/koe" + (BQ_ALL ? "?alle=1" : "")); } catch (e) { toast(e.message, true); return; }
  renderQueues();
  if (BQ_OPEN) bqOpen(BQ_OPEN, true);
}
function bqToggleAll() { BQ_ALL = !BQ_ALL; $("bqAllBtn").textContent = BQ_ALL ? "Skjul færdige køer" : "Vis færdige køer"; loadQueues(); }
const BQ_ST = {aktiv: ["I gang", "info"], stoppet: ["Stoppet", "warn"], "færdig": ["Færdig", "ok"]};
function renderQueues() {
  $("bqList").innerHTML = BQ.queues.length ? '<div class="card tp"><div class="kl">' + BQ.queues.map(q => `<div class="kr click" onclick="bqOpen(${q.id})">
    <div class="who"><b>${esc(q.name)}</b> <span class="pill ${BQ_ST[q.status][1]}">${BQ_ST[q.status][0]}</span>
      <div class="small">oprettet ${kDay(q.created)} · ${q.counts.sendt} sendt · ${q.counts.venter} venter${q.counts.sprunget ? " · " + q.counts.sprunget + " sprunget over" : ""}</div></div>
    <div class="amt">${q.counts.sendt}/${q.total}</div></div>`).join("") + "</div></div>"
    : '<div class="card"><div class="empty">Ingen køer. Tryk <b>Ny besked til flere</b> for at sende samme besked til mange kunder.</div></div>';
  const waiting = BQ.queues.filter(q => q.status === "aktiv").reduce((a, q) => a + q.counts.venter, 0);
  setBadge("koe", waiting, false);
}
async function bqOpen(id, quiet) {
  let q; try { q = await api("/api/beskeder/koe/" + id); } catch (e) { toast(e.message, true); return; }
  BQ_OPEN = id;
  const next = q.items.find(i => i.status === "venter");
  $("bqOpen").innerHTML = `<div class="card"><div class="row" style="justify-content:space-between"><div><h2 style="margin:0">${esc(q.name)}</h2>
      <div class="small">${q.counts.sendt} af ${q.total} sendt${q.counts.sprunget ? " · " + q.counts.sprunget + " sprunget over" : ""}</div></div>
    <div class="btns">${q.status === "aktiv" && next ? `<button class="b pri" onclick="bqNext(${q.id})">Send næste</button>` : ""}
      ${q.status === "aktiv" ? `<button class="b" onclick="bqStatus(${q.id},'stoppet')">Stop køen</button>` : q.status === "stoppet" ? `<button class="b" onclick="bqStatus(${q.id},'aktiv')">Fortsæt</button>` : ""}
      <button class="b" onclick="BQ_OPEN=null;$('bqOpen').innerHTML=''">Luk</button></div></div>
    <div class="kl" style="margin-top:10px">${q.items.map(i => `<div class="kr"><div class="who"><b>${esc(i.name)}</b> ${i.status === "sendt" ? '<span class="pill ok">Sendt</span>' : i.status === "sprunget" ? '<span class="pill">Sprunget over</span>' : ""}
        <div class="small">${i.tg ? "Telegram" : i.fb ? "Messenger" : "ingen chat på kundekortet"}${i.done_at ? " · " + kDay(i.done_at) : ""}</div></div>
      <div class="btns">${i.status === "venter" ? `<button class="b sm pri" onclick="bqSend(${q.id},${i.id})">Send</button>` : `<button class="b sm" onclick="bqItem(${q.id},${i.id},'undo')">Fortryd</button>`}</div></div>`).join("")}</div></div>`;
  window._bq = q; tipAll($("bqOpen"));
  if (!quiet) $("bqOpen").scrollIntoView({behavior: "smooth", block: "start"});
}
function bqSend(qid, iid) {
  const it = window._bq.items.find(x => x.id === iid);
  bSend(it, async a => { await api(`/api/beskeder/item/${iid}`, {method: "POST", body: JSON.stringify({action: a}), keepalive: true}); await loadQueues(); });
}
function bqNext(qid) { const n = window._bq.items.find(i => i.status === "venter"); if (n) bqSend(qid, n.id); }
async function bqItem(qid, iid, a) { try { await api(`/api/beskeder/item/${iid}`, {method: "POST", body: JSON.stringify({action: a})}); loadQueues(); } catch (e) { toast(e.message, true); } }
async function bqStatus(qid, st) { try { await api(`/api/beskeder/koe/${qid}/status`, {method: "POST", body: JSON.stringify({status: st})}); loadQueues(); } catch (e) { toast(e.message, true); } }
async function bqNew() {
  if (!BQ) await loadQueues();
  await kNeed().catch(() => {});
  const tpl = BQ.templates.map(t => [t.id, t.name]);
  kForm("Ny besked til flere kunder", [
    {k: "template_id", label: "Skabelon", type: "select", options: tpl, hint: "Teksten kan rettes på næste side og pr. kunde, når du sender."},
    {k: "who", label: "Hvem skal have den?", type: "select", options: [["alle", "Alle aktive kunder"], ["tjeneste", "Kunder med en bestemt tjeneste"], ["metode", "Kunder med en bestemt betalingsmetode"]]},
    {k: "service", label: "Tjeneste (hvis valgt ovenfor)", type: "select", options: BQ.services},
    {k: "method", label: "Betalingsmetode (hvis valgt ovenfor)", type: "select", options: [["MobilePay", "MobilePay"], ["Revolut", "Revolut"], ["Andet", "Andet"]]},
    {k: "family", label: "Også familie (Egen)", type: "check"},
  ], {who: "alle"}, async v => {
    const pre = await api("/api/beskeder/modtagere", {method: "POST", body: JSON.stringify(v)});
    if (!pre.count) throw new Error("ingen modtagere passer til dit valg");
    const t = BQ.templates.find(x => String(x.id) === String(v.template_id));
    setTimeout(() => kForm(`Tjek beskeden – ${pre.count} ${pre.count === 1 ? "kunde" : "kunder"}`, [
      {k: "name", label: "Navn på køen (kun til dig)"},
      {k: "text", label: "Beskeden", type: "textarea", hint: `Modtagere: ${esc(pre.customers.slice(0, 12).map(c => c.name).join(", "))}${pre.count > 12 ? " …" : ""}. ${pre.customers.filter(c => !c.tg && !c.fb).length} har hverken Telegram eller Messenger på kundekortet – dem kan du kopiere til.`},
    ], {name: t.name, text: t.text}, async w => {
      const q = await api("/api/beskeder/koe", {method: "POST", body: JSON.stringify({...v, ...w})});
      toast("Køen er lavet – tryk Send næste"); await loadQueues(); bqOpen(q.id);
    }, "Lav køen"), 50);
  }, "Næste");
}

// ---------- ønsker klar
async function loadReady() {
  try { BR = await api("/api/beskeder/klar" + (BR_DONE ? "?done=1" : "")); } catch (e) { toast(e.message, true); return; }
  renderReady();
}
function brToggleDone() { BR_DONE = !BR_DONE; $("brDoneBtn").textContent = BR_DONE ? "Vis dem, der venter" : "Vis sendte"; loadReady(); }
function renderReady() {
  $("brInfo").textContent = !BR.enabled ? "Seerr er ikke sat op (SEERR_URL og SEERR_APIKEY i fangarr.env)." : BR.checked ? `Seerr tjekkes hvert 10. minut – senest ${fmt(BR.checked)}.` : "";
  $("brList").innerHTML = BR.items.length ? '<div class="card tp"><div class="kl">' + BR.items.map(i => `<div class="kr"><div class="who"><b>${esc(i.name)}</b> · ${esc(i.title || "?")}
      ${i.status === "sendt" ? ' <span class="pill ok">Sendt</span>' : i.status === "sprunget" ? ' <span class="pill">Sprunget over</span>' : ""}
      <div class="small">${i.media === "tv" ? "Serie" : "Film"} · klar ${kDay(i.ready_at)}${i.done_at ? " · " + kDay(i.done_at) : ""} · ${i.tg ? "Telegram" : i.fb ? "Messenger" : "ingen chat på kundekortet"}</div></div>
    <div class="btns">${i.status === "venter" ? `<button class="b sm pri" onclick="brSend(${i.id})">Send</button><button class="b sm" onclick="brAct(${i.id},'skip')">Spring over</button>` : `<button class="b sm" onclick="brAct(${i.id},'undo')">Fortryd</button>`}</div></div>`).join("") + "</div></div>"
    : `<div class="card"><div class="empty">${BR_DONE ? "Ingen sendt endnu." : "Ingen ønsker venter på en besked."}</div></div>`;
  if (!BR_DONE) setBadge("klar", BR.items.length, false);
  tipAll($("brList"));
}
function brSend(id) {
  const it = BR.items.find(x => x.id === id);
  bSend(it, async a => { BR = await api(`/api/beskeder/klar/${id}`, {method: "POST", body: JSON.stringify({action: a}), keepalive: true}); BR_DONE = false; renderReady(); });
}
async function brAct(id, a) { try { BR = await api(`/api/beskeder/klar/${id}`, {method: "POST", body: JSON.stringify({action: a})}); BR_DONE = false; $("brDoneBtn").textContent = "Vis sendte"; renderReady(); loadHome(); } catch (e) { toast(e.message, true); } }
async function brCheck() { try { BR = await api("/api/beskeder/klar/tjek", {method: "POST"}); renderReady(); toast(BR.new ? `${BR.new} nye klar` : "Ingen nye"); } catch (e) { toast(e.message, true); } }

// ---------- ændring for alle
async function loadPrices() {
  let d; try { d = await api("/api/beskeder/pris"); } catch (e) { toast(e.message, true); return; }
  const sel = $("bp_service"); if (!sel.options.length) sel.innerHTML = d.services.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
  if (!$("bp_from").value) { const n = new Date(); n.setMonth(n.getMonth() + 1); $("bp_from").value = n.toISOString().slice(0, 7); }
  $("bpList").innerHTML = d.changes.length ? '<table><tbody>' + d.changes.map(c => `<tr><td><b>${esc(c.service)}</b> → ${kkr(c.price_new)}</td><td>fra ${esc(c.from_text)}</td>
    <td>${c.count} ${c.count === 1 ? "kunde" : "kunder"}</td><td>${c.cancelled_at ? '<span class="pill">Annulleret</span>' : c.applied_at ? `<span class="pill ok">Gennemført ${kDay(c.applied_at)}</span>` : '<span class="pill info">Venter på datoen</span>'}</td>
    <td>${!c.applied_at && !c.cancelled_at ? `<button class="b sm danger" onclick="bpCancel(${c.id})">Annullér</button>` : ""}${c.queue_id ? ` <button class="b sm" onclick="go('besk','koe');setTimeout(()=>bqOpen(${c.queue_id}),300)">Se beskederne</button>` : ""}</td></tr>`).join("") + "</tbody></table>"
    : "Ingen prisændringer endnu.";
  tipAll($("bpList"));
}
function bpBody() { return {service: $("bp_service").value, price: $("bp_price").value, only_price: $("bp_only").value, from: $("bp_from").value, family: $("bp_family").checked}; }
async function bpPlan() {
  try { BP = await api("/api/beskeder/pris/plan", {method: "POST", body: JSON.stringify(bpBody())}); } catch (e) { toast(e.message, true); return; }
  const p = BP;
  $("bpPlan").innerHTML = `<div class="card"><h2>${p.customers.length} ${p.customers.length === 1 ? "kunde rammes" : "kunder rammes"}</h2>
    <div class="small">${esc(p.service_name)} → ${kkr(p.price)} pr. måned fra ${esc(p.from_text)}. Samlet pr. måned: ${kkr(p.monthly_before)} → <b>${kkr(p.monthly_after)}</b>. Intet er ændret endnu.</div>
    ${p.pending.length ? `<div class="warn" style="margin-top:10px">Der venter allerede en ændring af ${esc(p.service_name)}: ${esc(p.pending.join(", "))}. Annullér den først, hvis den nye skal erstatte den.</div>` : ""}
    ${p.customers.length ? `<table style="margin-top:10px"><thead><tr><th>Kunde</th><th class="num">Pris nu</th><th class="num">Pr. måned før → efter</th><th class="num hs">Pr. opkrævning før → efter</th></tr></thead><tbody>
      ${p.customers.map(c => `<tr><td>${esc(c.name)}${c.tg || c.fb ? "" : ' <span class="small">(ingen chat)</span>'}</td><td class="num">${kkr(c.old_price)}</td>
        <td class="num">${kkr(c.monthly_before)} → <b>${kkr(c.monthly_after)}</b></td><td class="num hs">${kkr(c.charge_before)} → ${kkr(c.charge_after)} <span class="small">${esc(c.freq)}</span></td></tr>`).join("")}</tbody></table>
    <label class="check" style="margin-top:12px"><input type="checkbox" id="bp_queue" checked> Læg beskeden "Prisændring" i send-køen</label>
    <div class="row" style="margin:12px 0 0"><button class="b pri" onclick="bpConfirm()">Bekræft ændringen</button><button class="b" onclick="$('bpPlan').innerHTML=''">Annullér</button></div>` : ""}</div>`;
  tipAll($("bpPlan"));
}
async function bpConfirm() {
  const p = BP;
  if (!confirm(`Ændr ${p.service_name} til ${p.price} kr. pr. måned fra ${p.from_text} for ${p.customers.length} kunder?\n\nPriserne skiftes den dato. Opkrævninger før datoen røres ikke. Ændringen kan annulleres, indtil datoen er nået.`)) return;
  try { const r = await api("/api/beskeder/pris", {method: "POST", body: JSON.stringify({...bpBody(), queue: $("bp_queue").checked, confirm_ids: p.customers.map(c => c.id)})});
        $("bpPlan").innerHTML = ""; toast("Ændringen er gemt"); loadPrices(); if (r.queue_id) { go("besk", "koe"); setTimeout(() => bqOpen(r.queue_id), 300); } }
  catch (e) { toast(e.message, true); }
}
async function bpCancel(id) {
  if (!confirm("Annullér prisændringen? Priserne ændres ikke, og beskederne i køen stoppes.")) return;
  try { await api("/api/beskeder/pris/" + id, {method: "DELETE"}); loadPrices(); } catch (e) { toast(e.message, true); }
}

// ---------- skabeloner
async function loadTemplates() {
  try { BT = await api("/api/beskeder/skabeloner"); } catch (e) { toast(e.message, true); return; }
  $("btList").innerHTML = BT.templates.map(t => `<div class="kr"><div class="who"><b>${esc(t.name)}</b> <span class="pill">${esc(BT.kinds[t.kind] || t.kind)}</span>
    <div class="small" style="white-space:pre-line">${esc(t.text.length > 180 ? t.text.slice(0, 180) + " …" : t.text)}</div></div>
    <div class="btns"><button class="b sm" onclick="btEdit(${t.id})">Ret</button>${t.kind === "fri" ? `<button class="b sm danger" onclick="btDel(${t.id})">Slet</button>` : ""}</div></div>`).join("");
  tipAll($("btList"));
}
function btEdit(id) {
  const t = id ? BT.templates.find(x => x.id === id) : {name: "", text: "Hej {fornavn}\n\n\n\nMvh Stream365"};
  kForm(id ? "Ret skabelon" : "Ny skabelon", [{k: "name", label: "Navn"}, {k: "text", label: "Tekst", type: "textarea", hint: "Felter: " + BT.fields.join(" ")}], t,
    async v => { BT = await api("/api/beskeder/skabeloner", {method: "POST", body: JSON.stringify({...v, id: id || null, kind: t.kind})}); loadTemplates(); });
}
async function btDel(id) { if (!confirm("Slet skabelonen?")) return; try { await api("/api/beskeder/skabeloner/" + id, {method: "DELETE"}); loadTemplates(); } catch (e) { toast(e.message, true); } }

// ---------- Guide › Søgninger
async function loadSearches() {
  let d; try { d = await api("/api/beskeder/soegninger"); } catch (e) { toast(e.message, true); return; }
  $("gsNo").innerHTML = !d.enabled ? "Guidens tæller er ikke forbundet." : d.nohits.length
    ? '<table><tbody>' + d.nohits.map(q => `<tr><td><b>${esc(q.q)}</b></td><td class="num">${q.nohit}×</td><td class="small">${esc((q.users || []).slice(0, 3).join(", "))}</td></tr>`).join("") + "</tbody></table>"
    : (d.known ? "Alle søgninger gav et svar i guiden." : "Ingen data endnu. Guiden gemmer antal svar fra version 2.2.0 – husk at bygge guiden igen.");
  $("gsSeerr").innerHTML = d.seerr_error ? esc(d.seerr_error) : !d.seerr ? "Seerr er ikke sat op." : d.seerr.length
    ? '<table><tbody>' + d.seerr.map(t => `<tr><td><b>${esc(t.title)}</b> <span class="small">${t.type}</span>${t.available ? ' <span class="pill ok">i Plex</span>' : ""}</td><td class="num">${t.users} ${t.users === 1 ? "kunde" : "kunder"}</td></tr>`).join("") + "</tbody></table>"
    : "Ingen ønsker de sidste 90 dage.";
  $("gsAll").innerHTML = d.all.length ? d.all.map(q => `<span class="pill" style="margin:0 6px 6px 0;display:inline-block">${esc(q.q)} · ${q.n}${q.nohit ? ` · <span style="color:var(--bad)">${q.nohit} uden svar</span>` : ""}</span>`).join("") : "Ingen søgninger de sidste 30 dage.";
}

// ---------- tidslinje på kundekortet
const TL_ICON = {kunde: "👤", opkraevning: "🧾", betalt: "✅", oensker: "🎬", besked: "✉️", klar: "📬", pris: "💰", note: "📝"};
async function kTimelineLoad(cid) {
  const el = $("kTimeline"); if (!el) return;
  let d; try { d = await api("/api/beskeder/tidslinje/" + cid); } catch (e) { el.innerHTML = ""; return; }
  const ev = d.events, show = el.dataset.all ? ev : ev.slice(0, 12);
  el.innerHTML = `<div class="ksec"><h3>Tidslinje</h3><button class="b sm" onclick="kNote(${cid})">Skriv note</button></div>
    ${show.length ? `<div class="tl">${show.map(e => `<div class="tlr"><span class="tli">${TL_ICON[e.kind] || "•"}</span><div class="who"><span>${esc(e.text)}</span><div class="small">${kDay(e.ts)}</div></div>
      ${e.id ? `<button class="b sm danger" onclick="kNoteDel(${e.id},${cid})">Slet</button>` : ""}</div>`).join("")}</div>` : '<div class="small">Intet endnu.</div>'}
    ${ev.length > show.length ? `<button class="b sm" style="margin-top:8px" onclick="$('kTimeline').dataset.all=1;kTimelineLoad(${cid})">Vis alle ${ev.length}</button>` : ""}`;
  tipAll(el);
}
function kNote(cid) {
  kForm("Note på tidslinjen", [{k: "text", label: "Note", type: "textarea", hint: "Kun til dig. Skriv aldrig kodeord her."}], {},
    async v => { await api("/api/beskeder/tidslinje/" + cid, {method: "POST", body: JSON.stringify(v)}); kTimelineLoad(cid); });
}
async function kNoteDel(id, cid) { if (!confirm("Slet noten?")) return; try { await api("/api/beskeder/tidslinje/note/" + id, {method: "DELETE"}); kTimelineLoad(cid); } catch (e) { toast(e.message, true); } }
