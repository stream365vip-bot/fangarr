// Opkrævning: månedens liste, Send besked (Telegram/Messenger med beskeden klar) og Økonomi.
// ---------- opkrævning
async function loadPay(period) {
  try { await kNeed(); KP = await api("/api/kunder/charges" + ((period || (KP && KP.period)) ? "?period=" + (period || KP.period) : "")); }
  catch (e) { toast(e.message, true); return; }
  renderPay();
}
function renderPay() {
  if (!KP) return;
  const L = KP.charges, live = L.filter(c => c.status !== "sprunget over");
  const tot = live.reduce((a, c) => a + c.amount, 0), paid = live.filter(c => c.status === "betalt").reduce((a, c) => a + c.amount, 0);
  const pct = tot ? Math.round(paid / tot * 100) : 0, n = s => L.filter(c => c.status === s).length, late = L.filter(c => c.late).length;
  $("payMonth").textContent = KP.label; $("payNow").style.display = KP.period === KP.current ? "none" : "";
  $("payHead").innerHTML = KP.preview
    ? `<b>${kkr(tot)}</b> fra ${live.length} kunder ventes opkrævet i ${esc(KP.label)}. <span class="small" style="display:block">Listen oprettes af sig selv den 1. i måneden. Beløbene er et skøn ud fra de nuværende priser.</span>`
    : (live.length ? `<div class="row" style="justify-content:space-between;margin:0"><div><b style="font:600 22px var(--head)">${kkr(paid)}</b> <span style="color:var(--muted)">af ${kkr(tot)} modtaget</span></div><b style="font:600 18px var(--head);color:var(--accent)">${pct} %</b></div>
      <div class="money"><i style="width:${pct}%"></i></div>
      <div class="small">${n("betalt")} af ${live.length} har betalt${n("ny") ? ` · ${n("ny")} er ikke anmodet endnu` : ""}${late ? ` · <span style="color:var(--bad)">${late} har ventet mere end ${K.settings.remind_days} dage</span>` : ""}</div>`
      : (KP.period < KP.current ? `Der er ingen opkrævninger gemt for ${esc(KP.label)}. <button class="b sm" onclick="payGen()">Opret dem nu</button>` : "Ingen kunder skal opkræves i denne måned."));
  const isToday = c => KP.today != null && c.due === KP.today;
  if (KPF === "idag" && KP.today == null) KPF = "alle";
  const F = [["alle", "Alle", L.length], ...(KP.today != null ? [["idag", "I dag", L.filter(isToday).length]] : []), ["mangler", "Mangler", L.filter(c => c.status === "ny" || c.status === "anmodet").length], ["ny", "Ikke anmodet", n("ny")], ["anmodet", "Anmodet", n("anmodet")],
    ["betalt", "Betalt", n("betalt")], ["MobilePay", "MobilePay", L.filter(c => c.method === "MobilePay").length], ["Revolut", "Revolut", L.filter(c => c.method === "Revolut").length]];
  $("payPills").innerHTML = KP.preview ? "" : F.map(([k, l, c]) => `<button class="${KPF === k ? "on" : ""}" onclick="KPF='${k}';renderPay()">${l}<span>${c}</span></button>`).join("");
  const show = L.filter(c => KP.preview || KPF === "alle" || (KPF === "idag" ? isToday(c) : KPF === "mangler" ? (c.status === "ny" || c.status === "anmodet") : (c.status === KPF || c.method === KPF)));
  $("paySort").innerHTML = L.length ? `<span class="small" style="margin:0">Sortér efter</span><button class="b sm" aria-pressed="${KPS === "navn"}" style="${KPS === "navn" ? "border-color:var(--accent);color:var(--accent)" : ""}" onclick="paySort('navn')">Navn</button><button class="b sm" aria-pressed="${KPS === "dato"}" style="${KPS === "dato" ? "border-color:var(--accent);color:var(--accent)" : ""}" onclick="paySort('dato')">Betalingsdato</button>` : "";
  if (KPS === "dato") show.sort((a, b) => a.due - b.due || a.name.localeCompare(b.name, "da"));
  let lastDue = null;
  renderNews();
  $("payList").innerHTML = show.length ? `<div class="kl">${show.map(c => {
    const grp = KPS === "dato" && c.due !== lastDue ? `<div class="kgrp ${isToday(c) ? "now" : ""}">d. ${c.due}.${isToday(c) ? " · i dag" : ""} <span>${show.filter(x => x.due === c.due).length} ${show.filter(x => x.due === c.due).length === 1 ? "kunde" : "kunder"} · ${kkr(show.filter(x => x.due === c.due && x.status !== "sprunget over").reduce((s, x) => s + x.amount, 0))}</span></div>` : "";
    lastDue = c.due;
    const [st, cl] = K_ST[c.status], adj = c.adjust.map(a => `${esc(a.text || (a.amount < 0 ? "Fradrag" : "Tillæg"))} ${a.amount > 0 ? "+" : ""}${kkr(a.amount)}`).join(" · ");
    let b = "";
    if (c.id) {
      if (c.status === "ny") b = `<button class="b sm pri" onclick="paySend(${c.id})">Send besked</button><button class="b sm" onclick="payAct(${c.id},'request')">Anmodet</button><button class="b sm" onclick="payAct(${c.id},'paid')">Betalt</button>`;
      else if (c.status === "anmodet") b = `<button class="b sm" onclick="paySend(${c.id})">Send igen</button><button class="b sm pri" onclick="payAct(${c.id},'paid')">Betalt</button>`;
      else if (c.status === "betalt") b = `<button class="b sm" onclick="payAct(${c.id},'unpaid')">Fortryd betalt</button>`;
      else b = `<button class="b sm" onclick="payAct(${c.id},'unskip')">Tag med igen</button>`;
      b += `<button class="b sm" onclick="payEdit(${c.id})" aria-label="Ret opkrævningen">Ret</button>`;
    }
    return grp + `<div class="kr ${c.status === "betalt" || c.status === "sprunget over" ? "done" : ""} ${c.late ? "late" : ""}">
      <div class="who"><b style="cursor:pointer" onclick="kOpen(${c.customer_id})">${esc(c.name)}</b> <span class="pill ${c.late ? "bad" : cl}">${c.late ? "Mangler betaling" : st}</span>
        <div class="small"><b style="font-weight:600;color:${isToday(c) ? "var(--accent)" : "var(--text)"}">d. ${c.due}.</b> · ${esc(c.services || "–")} · ${esc(c.method || "ingen betalingsmetode")}${c.contact ? " · " + esc(c.contact) : ""}${c.status === "anmodet" ? " · " + (c.sent_at ? "besked sendt " : "anmodet ") + kDay(c.requested_at) : ""}${c.status === "betalt" ? " · betalt " + kDay(c.paid_at) : ""}</div>
        ${adj || c.note ? `<div class="small">${adj}${adj && c.note ? " · " : ""}${esc(c.note)}</div>` : ""}</div>
      <div class="amt">${kkr(c.amount)}</div><div class="btns">${b}</div></div>`; }).join("")}</div>`
    : `<div class="empty">${L.length ? "Ingen i denne visning." : "Intet at vise."}</div>`;
}
async function payAct(id, action, extra) {
  try { KP = await api(`/api/kunder/charges/${id}`, {method: "POST", body: JSON.stringify({action, ...(extra || {})})}); renderPay(); loadHome(); } catch (e) { toast(e.message, true); }
}


// ---------- send besked: åbner chatten i Telegram/Messenger med beskeden klar og sætter kunden til Anmodet
const sdlg = $("sdlg");
let SC = null;
const S_VAR = {link: "Betalingslink (kunden har ikke Revolut)", app: "Direkte i Revolut-appen (kunden har Revolut)"};
// På Android åbnes appen direkte (tg:// og en "intent"-adresse til Messenger), så browseren ikke viser hjemmesiden i stedet.
// På computer bruges de almindelige adresser t.me og m.me.
const ANDROID = /Android/i.test(navigator.userAgent);
function tgUrl(h, text) {
  let u = String(h || "").trim(), phone = false;
  if (/^\+?[\d ]+$/.test(u)) { u = u.replace(/\D/g, ""); if (u.length === 8) u = "45" + u; phone = true; }
  const t = encodeURIComponent(text);
  const pkg = K && K.settings.app_tg_pkg;
  if (ANDROID && pkg) return `intent://resolve?${phone ? "phone" : "domain"}=${u}&text=${t}#Intent;scheme=tg;package=${pkg};end`;
  if (ANDROID) return `tg://resolve?${phone ? "phone" : "domain"}=${u}&text=${t}`;
  return `https://t.me/${phone ? "+" : ""}${u}?text=${t}`;
}
function fbUrl(h) {
  const u = encodeURIComponent(String(h || "").trim()), web = "https://m.me/" + u;
  const pkg = K && K.settings.app_fb_pkg;      // uden pakkenavn vælger Android selv den app, der må åbne m.me-links – ellers browseren
  return ANDROID ? `intent://m.me/${u}#Intent;scheme=https;action=android.intent.action.VIEW;${pkg ? "package=" + pkg + ";" : ""}S.browser_fallback_url=${encodeURIComponent(web)};end` : web;
}
function paySend(id) {
  const c = KP.charges.find(x => x.id === id); if (!c) return;
  SC = c;
  const two = Object.keys(c.messages).length > 1;
  $("sdTitle").textContent = (c.status === "anmodet" ? "Send igen – " : "Send besked – ") + c.name; $("sdErr").textContent = "";
  $("sdBody").innerHTML = `<div class="small" style="margin-bottom:12px">${kkr(c.amount)} · ${esc(c.method || "ingen betalingsmetode")}${c.news ? ' · <span style="color:var(--accent)">nyheden er med</span>' : ""}</div>
    ${two ? `<div class="field" style="margin-bottom:12px"><label for="sd_var">Sådan anmoder du kunden</label><select id="sd_var" onchange="sVar()"><option value="">– vælg –</option>${Object.keys(c.messages).map(v => `<option value="${v}" ${v === c.variant ? "selected" : ""}>${S_VAR[v]}</option>`).join("")}</select>
      <div class="small">Fangarr husker valget på kundekortet til næste gang.</div></div>
    <div class="field" id="sd_linkBox" style="margin-bottom:12px"><label for="sd_link">Betalingslink fra Revolut</label>
      <div style="display:flex;gap:6px"><input type="text" id="sd_link" inputmode="url" autocomplete="off" spellcheck="false" placeholder="https://…" value="${esc(c.pay_link)}" oninput="sUpd()"><button class="b" type="button" onclick="sPaste()">Sæt ind</button></div>
      <div class="small">Lav linket i Revolut-appen, kopiér det, og tryk Sæt ind. Det sættes ind, hvor der står {link} i beskeden.</div></div>` : ""}
    <div class="field"><label for="sd_text">Beskeden til kunden</label><textarea class="kta" id="sd_text" style="min-height:230px" oninput="sUpd()"></textarea>
      <div class="small">Du kan rette teksten her – det gælder kun denne besked. Den faste tekst retter du under Beskeder › Skabeloner.</div></div>
    <div class="small" id="sd_how" style="margin-top:10px"></div>`;
  const tg = c.tg && c.channel !== "messenger", fb = c.fb && c.channel !== "telegram";
  $("sdFoot").innerHTML = `<button class="b" onclick="sCopy()">Kopiér</button><button class="b ${tg || fb ? "" : "pri"}" onclick="sShare()">Del …</button>`
    + (fb ? `<a class="b pri" id="sd_fb" ${ANDROID ? "" : 'target="_blank" rel="noopener"'} onclick="return sGo('fb')">Kopiér + åbn Messenger</a>` : "")
    + (tg ? `<a class="b pri" id="sd_tg" ${ANDROID ? "" : 'target="_blank" rel="noopener"'} onclick="return sGo('tg')">Åbn i Telegram</a>` : "");
  $("sd_how").innerHTML = (tg ? "<b>Åbn i Telegram</b> åbner chatten med kunden med beskeden skrevet – du trykker bare send. " : "")
    + (fb ? "<b>Kopiér + åbn Messenger</b> kopierer beskeden og åbner chatten med kunden – hold fingeren i skrivefeltet, vælg Sæt ind, og tryk send. " : "")
    + "<b>Del …</b> åbner telefonens delemenu – vælg appen og kunden, så står beskeden klar. <b>Kopiér</b> kopierer beskeden, så du selv kan sætte den ind et sted. Alle knapperne sætter kunden til Anmodet."
    + (!tg && !fb ? ` <a href="#" onclick="sdlg.close();kOpen(${c.customer_id});return false">Skriv kundens Telegram- eller Messenger-brugernavn på kundekortet</a>, så kan chatten åbnes direkte.` : "");
  sVar(); sdlg.showModal();
}
function sVariant() { const el = $("sd_var"); return el ? el.value : Object.keys(SC.messages)[0]; }
function sVar() {
  const v = sVariant();
  if ($("sd_linkBox")) $("sd_linkBox").style.display = v === "link" ? "" : "none";
  $("sd_text").value = SC.messages[v || SC.variant || Object.keys(SC.messages)[0]] || "";
  sUpd();
}
function sLink() { return sVariant() === "link" && $("sd_link") ? $("sd_link").value.trim() : ""; }
function sText() { return $("sd_text").value.split("{link}").join(sLink()).trim(); }
function sUpd() {
  const t = sText();
  if ($("sd_tg")) $("sd_tg").href = tgUrl(SC.tg, t);
  if ($("sd_fb")) $("sd_fb").href = fbUrl(SC.fb);
}
async function sPaste() {
  try { $("sd_link").value = (await navigator.clipboard.readText()).trim(); sUpd(); }
  catch (e) { toast("Kunne ikke læse udklipsholderen – hold fingeren i feltet og vælg Sæt ind", true); $("sd_link").focus(); }
}
function sCheck() {
  const v = sVariant(); let err = "";
  if (!v) err = "Vælg først, hvordan du anmoder kunden.";
  else if (v === "link" && !/^https:\/\/\S{4,}$/.test(sLink())) err = "Indsæt betalingslinket fra Revolut (det begynder med https://).";
  else if (v === "link" && !$("sd_text").value.includes("{link}")) err = "Beskeden mangler {link} – skriv {link} dér, hvor linket skal stå.";
  else if (!sText()) err = "Beskeden er tom.";
  $("sdErr").textContent = err;
  return !err;
}
function sCopyNow(t) {     // kopierer med det samme (uden at vente), så det også virker, når en anden app åbner lige bagefter
  const a = document.createElement("textarea"); a.value = t; a.style.position = "fixed"; a.style.opacity = "0"; sdlg.appendChild(a); a.select();
  let ok = false; try { ok = document.execCommand("copy"); } catch (e) {} a.remove();
  if (navigator.clipboard) navigator.clipboard.writeText(t).catch(() => {});
  return ok;
}
async function sDone(how) {
  const c = SC, body = {action: "sent", variant: sVariant(), link: sLink(), news: c.news && !!(K.news && sText().includes(K.news.text.trim()))};
  try {
    KP = await api(`/api/kunder/charges/${c.id}`, {method: "POST", body: JSON.stringify(body), keepalive: true});
    sdlg.close(); toast(how + " – " + c.name + " er sat til Anmodet");
    try { await kState(); } catch (e) {}
    renderPay(); loadHome();
  } catch (e) { $("sdErr").textContent = e.message; }
}
function sGo(kind) {       // kaldes af linket selv, så telefonen åbner appen direkte
  if (!sCheck()) return false;
  sUpd();
  if (kind === "fb") sCopyNow(sText());
  setTimeout(() => sDone(kind === "fb" ? "Kopieret, Messenger åbnet" : "Telegram åbnet"), 50);
  return true;
}
async function sShare() {
  if (!sCheck()) return;
  const t = sText();
  if (!navigator.share) { sCopyNow(t); toast("Denne browser har ingen delemenu – beskeden er kopieret i stedet"); return sDone("Kopieret"); }
  try { await navigator.share({text: t}); } catch (e) { if (e.name !== "AbortError") $("sdErr").textContent = "Kunne ikke åbne delemenuen – brug Kopiér."; return; }
  sDone("Delt");
}
function sCopy() { if (!sCheck()) return; sCopyNow(sText()); sDone("Kopieret"); }
async function payGen() { try { KP = await api("/api/kunder/charges/generate", {method: "POST", body: JSON.stringify({period: KP.period})}); renderPay(); } catch (e) { toast(e.message, true); } }
function payEdit(id) {
  const c = KP.charges.find(x => x.id === id);
  kForm("Ret opkrævningen – " + c.name, [
    {k: "amount", label: "Beløb (kr.)", type: "money", hint: `Udregnet beløb: ${kkr(c.base)}${c.adjust.length ? " plus fradrag/tillæg" : ""}. Gælder kun denne opkrævning.`},
    {k: "note", label: "Note", type: "text"},
    {k: "recalc", label: "Regn beløbet ud igen fra kundens nuværende priser", type: "check"},
    {k: "skip", label: "Spring denne opkrævning over (kunden skal ikke betale i denne måned)", type: "check"},
    ...(c.status === "anmodet" ? [{k: "unrequest", label: "Fortryd Anmodet", type: "check"}] : [])],
    {amount: c.amount, note: c.note, skip: c.status === "sprunget over"},
    async v => {
      if (v.recalc) await api(`/api/kunder/charges/${id}`, {method: "POST", body: JSON.stringify({action: "recalc"})});
      else await api(`/api/kunder/charges/${id}`, {method: "POST", body: JSON.stringify({action: "edit", amount: v.amount, note: v.note})});
      if (v.unrequest) await api(`/api/kunder/charges/${id}`, {method: "POST", body: JSON.stringify({action: "unrequest"})});
      KP = await api(`/api/kunder/charges/${id}`, {method: "POST", body: JSON.stringify({action: v.skip ? "skip" : "unskip"})});
      renderPay(); loadHome();
    });
}


// ---------- økonomi
async function loadEco(year) { try { KE = await api("/api/kunder/economy" + (year ? "?year=" + year : (KE ? "?year=" + KE.year : ""))); } catch (e) { toast(e.message, true); return; } renderEco(); }
function renderEco() {
  const M = KE.months, sum = k => M.reduce((a, m) => a + m[k], 0), res = sum("result");
  $("ecoYear").textContent = KE.year;
  $("ecoKpis").innerHTML = [["Indtægt i året", kkr(sum("income")), "betalt + ventet"], ["IPTV-linjer", kkr(sum("iptv")), "fornyelser i året"], ["Faste udgifter", kkr(sum("fixed")), KE.fixed.length ? KE.fixed.map(f => f.name).join(", ") : "ingen angivet"],
    ["Resultat", `<span style="color:${res < 0 ? "var(--bad)" : "var(--ok)"}">${kkr(res)}</span>`, `${KE.customers} aktive kunder · ${kkr(KE.monthly_income)} pr. måned`]]
    .map(([l, v, s]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${esc(s)}</div></div>`).join("");
  $("ecoBody").innerHTML = M.map(m => m.nodata ? `<tr><td style="text-transform:capitalize;color:var(--muted)">${m.label}</td><td colspan="5" class="small">ingen opkrævninger gemt i Fangarr</td></tr>` : `<tr style="${m.state === "now" ? "background:var(--panel2)" : ""}"><td style="text-transform:capitalize">${m.label}${m.state === "future" ? ' <span class="small">skøn</span>' : ""}</td>
    <td class="num">${m.has_charges ? kkr(m.charged) : m.state === "past" ? "–" : `<span style="color:var(--muted)">${kkr(m.forecast)}</span>`}</td>
    <td class="num">${m.has_charges ? kkr(m.paid) : "–"}</td><td class="num hs">${m.iptv ? kkr(m.iptv) : "–"}</td><td class="num hs">${m.fixed ? kkr(m.fixed) : "–"}</td>
    <td class="num"><b style="color:${m.result < 0 ? "var(--bad)" : "inherit"}">${kkr(m.result)}</b></td></tr>`).join("") +
    `<tr><td><b>I alt</b></td><td class="num"><b>${kkr(M.reduce((a, m) => a + (m.has_charges ? m.charged : m.state === "past" ? 0 : m.forecast), 0))}</b></td><td class="num"><b>${kkr(sum("paid"))}</b></td>
     <td class="num hs"><b>${kkr(sum("iptv"))}</b></td><td class="num hs"><b>${kkr(sum("fixed"))}</b></td><td class="num"><b>${kkr(res)}</b></td></tr>`;
  $("ecoNote").innerHTML = "IPTV-udgiften er prisen på de linjer, der udløber i måneden. Faste udgifter retter du nederst på denne side.";
}
