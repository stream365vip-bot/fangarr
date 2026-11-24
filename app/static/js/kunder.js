// Kunder: kundeliste, kundekortet (også Seerr-ønsker på kortet), IPTV-linjer, delte logins og indstillinger.
// Fælles for Kunder, Opkrævning og Beskeder: K (indstillinger og tjenester), kForm og kShow.
// ====================================================================== 1.16: kunder og betalinger
let KPS = "navn"; try { KPS = localStorage.getItem("fangarr_pay_sort") === "dato" ? "dato" : "navn"; } catch (e) {}
function paySort(v) { KPS = v; try { localStorage.setItem("fangarr_pay_sort", v); } catch (e) {} renderPay(); }
let K = null, KC = [], KP = null, KPF = "alle", KCF = "aktive", KI = null, KIF = "maaned", KE = null, KCUR = null;
const kdlg = $("kdlg"), edlg = $("edlg");
const kkr = v => Number(v || 0).toLocaleString("da-DK") + " kr.";
const kDay = t => { if (!t) return "–"; const d = new Date(t); return isNaN(d) ? esc(t) : d.toLocaleDateString("da-DK", {day: "numeric", month: "short", year: "numeric"}); };
const kAgo = ts => { if (!ts) return "aldrig set"; const d = Math.floor((Date.now() / 1000 - ts) / 86400); return d <= 0 ? "set i dag" : d === 1 ? "set i går" : `set for ${d} dage siden`; };
const K_FLAG = {cyklus: ["Mangler cyklus", "warn"], metode: ["Mangler betalingsmetode", "warn"], pris: ["Mangler pris", "warn"],
  plexvaek: ["Plex-brugeren findes ikke længere", "bad"], ulinket: ["Plex-konto ikke fundet i Tautulli", "info"], inaktiv: ["Ikke set længe", ""]};
const K_ST = {ny: ["Ikke anmodet", ""], anmodet: ["Anmodet", "info"], betalt: ["Betalt", "ok"], "sprunget over": ["Sprunget over", ""], kommer: ["Kommer", ""]};
const K_STATUS = {aktiv: "Aktiv", pause: "Pause", stoppet: "Stoppet"};
const K_MONTH = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august", "september", "oktober", "november", "december"];
const kSvc = s => (K.services.find(x => x[0] === s) || [s, s])[1];
const kFlags = f => f.length ? `<span class="ktags">${f.map(x => `<span class="pill ${K_FLAG[x][1]}">${K_FLAG[x][0]}</span>`).join("")}</span>` : "";
async function kState() { K = await api("/api/kunder/state"); return K; }
async function kNeed() { if (!K) await kState(); }

// ---------- lille formular til at rette én ting (tjeneste, linje, fradrag, login)
function kForm(title, fields, vals, onSave, saveText) {
  $("edTitle").textContent = title; $("edErr").textContent = ""; $("edSave").textContent = saveText || "Gem"; $("edSave").disabled = false;
  $("edBody").innerHTML = fields.map(f => {
    const v = vals[f.k] ?? "", id = "ef_" + f.k, hint = f.hint ? `<div class="small">${f.hint}</div>` : "";
    if (f.type === "check") return `<div class="field" style="margin-bottom:12px"><label class="check"><input type="checkbox" id="${id}" ${v ? "checked" : ""}> ${esc(f.label)}</label>${hint}</div>`;
    if (f.type === "multi") return `<div class="field" style="margin-bottom:12px"><label>${esc(f.label)}</label>${hint}<div id="${id}" class="kmulti">${f.options.map(([o, l]) =>
      `<label class="check"><input type="checkbox" value="${esc(o)}" ${(v || []).map(String).includes(String(o)) ? "checked" : ""}> ${esc(l)}</label>`).join("")}</div></div>`;
    let inp;
    if (f.type === "select") inp = `<select id="${id}">${f.options.map(([o, l]) => `<option value="${esc(o)}" ${String(o) === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    else if (f.type === "textarea") inp = `<textarea id="${id}" style="min-height:70px">${esc(v)}</textarea>`;
    else if (f.type === "secret") inp = `<div style="display:flex;gap:6px"><input type="text" id="${id}" autocomplete="off" spellcheck="false" placeholder="${f.has ? "gemt – lad feltet stå tomt for at beholde den" : ""}">` +
      (f.has ? `<button class="b" type="button" onclick="kFill('${f.ref[0]}', ${f.ref[1]}, '${id}')">Vis</button>` : "") + `</div>`;
    else inp = `<input type="${f.type === "date" ? "date" : "text"}" ${f.type === "money" || f.type === "int" ? 'inputmode="decimal"' : ""} id="${id}" value="${esc(v)}" placeholder="${esc(f.ph || "")}" autocomplete="off">`;
    return `<div class="field" style="margin-bottom:12px"><label for="${id}">${esc(f.label)}</label>${inp}${hint}</div>`;
  }).join("");
  $("edSave").onclick = async () => {
    const out = {};
    fields.forEach(f => { const el = $("ef_" + f.k);
      out[f.k] = f.type === "check" ? el.checked : f.type === "multi" ? [...el.querySelectorAll("input:checked")].map(i => i.value) : el.value.trim(); });
    try { await onSave(out); edlg.close(); } catch (e) { $("edErr").textContent = e.message; }
  };
  edlg.showModal();
}
async function kFill(kind, id, inputId) { try { $(inputId).value = (await api(`/api/kunder/secret/${kind}/${id}`)).password || ""; } catch (e) { toast(e.message, true); } }
async function kShow(kind, id, btn) {
  try {
    const s = await api(`/api/kunder/secret/${kind}/${id}`), box = document.createElement("span");
    box.innerHTML = (s.username ? `<span class="ksecret">${esc(s.username)}</span> ` : "") + (s.password ? `<span class="ksecret">${esc(s.password)}</span>` : '<span class="small">ingen kode gemt</span>');
    btn.replaceWith(box);
    setTimeout(() => { if (box.isConnected) { const b = document.createElement("button"); b.className = "b sm"; b.textContent = "Vis kode"; b.onclick = () => kShow(kind, id, b); box.replaceWith(b); } }, 60000);
  } catch (e) { toast(e.message, true); }
}


// ---------- kundeliste
async function loadCust() {
  try { await kState(); KC = await api("/api/kunder/customers"); } catch (e) { toast(e.message, true); return; }
  renderCust();
}
function renderCust() {
  const q = $("kq").value.trim().toLowerCase(), setup = c => c.flags.some(f => ["cyklus", "metode", "pris"].includes(f));
  const G = {aktive: c => c.status === "aktiv" && c.kind === "kunde", opsaet: setup, obs: c => c.flags.some(f => ["plexvaek", "ulinket", "inaktiv"].includes(f)),
    pause: c => c.status === "pause", stoppet: c => c.status === "stoppet", egne: c => c.kind === "egen", alle: () => true};
  const N = [["aktive", "Aktive"], ["opsaet", "Mangler opsætning"], ["obs", "Tjek Plex"], ["pause", "Pause"], ["stoppet", "Stoppet"], ["egne", "Egne"], ["alle", "Alle"]];
  $("kPills").innerHTML = N.map(([k, l]) => `<button class="${KCF === k ? "on" : ""}" onclick="KCF='${k}';renderCust()">${l}<span>${KC.filter(G[k]).length}</span></button>`).join("");
  const sy = K.sync;
  $("kSyncInfo").innerHTML = !K.tautulli ? '<span style="color:var(--warn)">Tautulli er ikke sat op i fangarr.env, så Plex-brugere kan ikke hentes.</span>'
    : sy ? `Senest synket fra Tautulli ${fmt(sy.at)} · ${sy.users} Plex-brugere${sy.created && sy.created.length ? ` · nye kunder: <b>${esc(sy.created.join(", "))}</b>` : ""}${sy.gone && sy.gone.length ? ` · ikke længere i Plex: <b>${esc(sy.gone.join(", "))}</b>` : ""}`
    : "Der er ikke synket fra Tautulli endnu. Tryk <b>Synk fra Tautulli</b>. Derefter sker det af sig selv hver nat.";
  const L = KC.filter(c => (q ? true : G[KCF](c)) && (!q || [c.name, c.phone, c.email, c.notes, ...c.services.flatMap(s => [s.username, s.email, s.label])].some(v => String(v || "").toLowerCase().includes(q))));
  $("kList").innerHTML = L.length ? `<div class="kl">${L.map(c => {
    const sv = [...new Set(c.services.filter(s => s.active).map(s => kSvc(s.service)))].join(", "), acc = c.services.filter(s => s.service === "plex").length;
    return `<div class="kr click" onclick="kOpen(${c.id})"><div class="who"><b>${esc(c.name)}</b>${c.status !== "aktiv" ? ` <span class="pill">${K_STATUS[c.status]}</span>` : ""}${c.kind === "egen" ? ' <span class="pill">Egen</span>' : ""}${kFlags(c.flags)}
      <div class="small">${esc(sv || "ingen tjenester")}${acc > 1 ? ` · ${acc} Plex-konti` : ""}${c.iptv_lines ? ` · ${c.iptv_lines} IPTV-${c.iptv_lines === 1 ? "linje" : "linjer"}` : ""}${c.last_seen ? " · " + kAgo(c.last_seen) : ""}</div></div>
      <div class="meta hs">${esc(c.method || "–")}</div><div class="meta">${c.kind === "egen" ? "" : esc(c.freq ? c.freq_text + " · " + c.cycle_text : "ingen cyklus")}</div>
      <div class="amt">${c.kind === "egen" ? "–" : kkr(c.per_charge || c.monthly)}</div></div>`; }).join("")}</div>`
    : `<div class="empty">${KC.length ? "Ingen kunder i denne visning." : "Der er ingen kunder endnu. Tryk <b>Synk fra Tautulli</b> eller <b>Ny kunde</b>."}</div>`;
}
async function kSync() {
  const b = $("kSyncBtn"); b.disabled = true; b.textContent = "Henter fra Tautulli …";
  try { const r = await api("/api/kunder/sync", {method: "POST"});
    toast(`Synket: ${r.users} Plex-brugere` + (r.created.length ? `, ${r.created.length} nye kunder` : "") + (r.linked.length ? `, ${r.linked.length} koblet til kunder` : "")); await loadCust(); loadHome(); }
  catch (e) { toast(e.message, true); }
  b.disabled = false; b.textContent = "Synk fra Tautulli";
}
const K_FREQ = [["", "– vælg –"], ["maaned", "Månedlig"], ["kvartal", "Kvartal"], ["halvaar", "Halvårlig"], ["aar", "Årlig"]];
function kCycleOpts(freq, cur) {
  const n = {kvartal: 3, halvaar: 6, aar: 12}[freq];
  if (!n) return freq === "maaned" ? '<option value="">Hver måned</option>' : '<option value="">vælg frekvens først</option>';
  let o = "";
  for (let s = 1; s <= n; s++) { const m = []; for (let x = s; x <= 12; x += n) m.push(x); o += `<option value="${s}" ${Number(cur) === s ? "selected" : ""}>${n === 12 ? K_MONTH[s - 1] : m.join("/")}</option>`; }
  return o;
}
function kNew() {
  kForm("Ny kunde", [{k: "name", label: "Navn", type: "text"}, {k: "method", label: "Betalingsmetode", type: "select", options: [["", "– vælg –"], ["MobilePay", "MobilePay"], ["Revolut", "Revolut"], ["Andet", "Andet"]]},
    {k: "freq", label: "Hvor tit betaler kunden?", type: "select", options: K_FREQ, hint: "Cyklus (hvilke måneder) og tjenester vælger du på kundekortet bagefter."}],
    {}, async v => { const c = await api("/api/kunder/customers", {method: "POST", body: JSON.stringify(v)}); await loadCust(); kOpen(c.id); }, "Opret");
}
async function kOpen(id) {
  try { await kNeed(); KCUR = await api("/api/kunder/customers/" + id); } catch (e) { toast(e.message, true); return; }
  renderCard(); if (!kdlg.open) kdlg.showModal();
}
function renderCard() {
  const c = KCUR, sel = (id, opts, cur) => `<select id="${id}">${opts.map(([v, l]) => `<option value="${v}" ${String(v) === String(cur ?? "") ? "selected" : ""}>${l}</option>`).join("")}</select>`;
  $("kdTitle").textContent = c.name; $("kdErr").textContent = "";
  $("kdBody").innerHTML = `${c.flags.length ? `<div style="margin-bottom:12px">${kFlags(c.flags)}</div>` : ""}
    <div class="grid">
      <div class="field"><label>Navn</label><input type="text" id="kc_name" value="${esc(c.name)}"></div>
      <div class="field"><label>Status</label>${sel("kc_status", Object.entries(K_STATUS), c.status)}</div>
      <div class="field"><label>Type</label>${sel("kc_kind", [["kunde", "Kunde (betaler)"], ["egen", "Egen (familie – opkræves ikke)"]], c.kind)}</div>
      <div class="field"><label>Betalingsmetode</label>${sel("kc_method", [["", "– vælg –"], ["MobilePay", "MobilePay"], ["Revolut", "Revolut"], ["Andet", "Andet"]], c.method)}</div>
      <div class="field"><label>Revolut: sådan anmoder du</label>${sel("kc_revolut", [["", "– vælges, når du sender –"], ["link", "Betalingslink (har ikke Revolut)"], ["app", "Direkte i Revolut-appen"]], c.revolut)}
        <div class="small">Kun for kunder, der betaler med Revolut.</div></div>
      <div class="field"><label>Hvor tit betaler kunden?</label><select id="kc_freq" onchange="$('kc_cycle').innerHTML=kCycleOpts(this.value)">${K_FREQ.map(([v, l]) => `<option value="${v}" ${v === (c.freq || "") ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      <div class="field"><label>Cyklus (måneder, der opkræves)</label><select id="kc_cycle">${kCycleOpts(c.freq, c.cycle)}</select></div>
      <div class="field"><label>Fast dato i måneden (valgfri)</label><input type="text" inputmode="numeric" id="kc_due_day" value="${c.due_day ?? ""}" placeholder="fx 15"></div>
      <div class="field"><label>Telefon</label><input type="text" id="kc_phone" value="${esc(c.phone)}"></div>
      <div class="field"><label>E-mail</label><input type="text" id="kc_email" value="${esc(c.email)}"></div>
      <div class="field"><label>Kontakt via</label><input type="text" id="kc_contact" value="${esc(c.contact)}" placeholder="FB, TG, SMS …">
        <div class="small">FB = Messenger, TG = Telegram. Bestemmer, hvilken app Send besked åbner.</div></div>
      <div class="field"><label>Telegram-brugernavn eller nummer</label><input type="text" id="kc_tg" value="${esc(c.tg)}" placeholder="@brugernavn" autocomplete="off" spellcheck="false">
        <div class="small">Står i Telegram på kundens profil. Så åbner Send besked chatten med beskeden klar. Et telefonnummer virker kun, hvis kunden viser sit nummer.</div></div>
      <div class="field"><label>Messenger-brugernavn</label><input type="text" id="kc_fb" value="${esc(c.fb)}" placeholder="fornavn.efternavn.12" autocomplete="off" spellcheck="false">
        <div class="small">Det, der står efter facebook.com/ på kundens profil (eller tallet efter id=). Du kan også indsætte hele adressen.</div></div>
    </div>
    <div class="field" style="margin-top:12px"><label>Noter</label><textarea id="kc_notes" style="min-height:60px">${esc(c.notes)}</textarea></div>

    <div class="ksec"><h3>Tjenester <span class="small">· ${kkr(c.monthly)} pr. måned${c.freq ? ` · ${kkr(c.per_charge)} pr. opkrævning` : ""}</span></h3><button class="b sm" onclick="kSvcEdit()">Tilføj tjeneste</button></div>
    ${c.services.length ? c.services.map(s => `<div class="kitem" style="${s.active ? "" : "opacity:.55"}"><div class="who"><b>${esc(kSvc(s.service))}</b>${s.label ? " · " + esc(s.label) : ""}${s.active ? "" : ' <span class="pill">slået fra</span>'}
        <div class="small">${[s.username && esc(s.username), s.email && s.email !== s.username && esc(s.email), s.service === "plex" ? (s.plex ? (s.plex.active ? kAgo(s.plex.last_seen) : '<span style="color:var(--bad)">findes ikke længere i Plex</span>') : '<span style="color:var(--info)">ikke koblet til en Plex-bruger</span>') : "", s.note && esc(s.note)].filter(Boolean).join(" · ")}</div></div>
      <div class="amt">${kkr(s.price)}<span class="small"> /md.</span></div>
      <div class="btns">${s.has_password ? `<button class="b sm" onclick="kShow('service', ${s.id}, this)">Vis kode</button>` : ""}<button class="b sm" onclick="kSvcEdit(${s.id})">Ret</button></div></div>`).join("") : '<div class="small">Ingen tjenester endnu.</div>'}

    <div id="kSeerr"></div>

    <div class="ksec"><h3>Fradrag og tillæg</h3><button class="b sm" onclick="kAdjAdd()">Tilføj</button></div>
    ${c.adjust.length ? c.adjust.map(a => `<div class="kitem" style="${a.remaining ? "" : "opacity:.55"}"><div class="who"><b>${esc(a.text || (a.amount < 0 ? "Fradrag" : "Tillæg"))}</b>
        <div class="small">${a.remaining ? `regnes med på ${a.remaining === 1 ? "næste opkrævning" : "de næste " + a.remaining + " opkrævninger"}` : "er brugt"}</div></div>
      <div class="amt">${a.amount > 0 ? "+" : ""}${kkr(a.amount)}</div><div class="btns"><button class="b sm danger" onclick="kAdjDel(${a.id})">Fjern</button></div></div>`).join("")
      : '<div class="small">Bruges til fx "træk 49 kr. fra næste", en gratis måned eller halv pris. Skriv minus foran et fradrag. Teksten og beløbet står i beskeden til kunden.</div>'}

    <div class="ksec"><h3>IPTV-linjer</h3><button class="b sm" onclick="kLineEdit(null, ${c.id})">Tilføj linje</button></div>
    ${c.iptv.length ? c.iptv.map(l => `<div class="kitem"><div class="who"><b>${esc(l.label || l.username || "Linje")}</b>
        <div class="small">udløber <span style="${l.expired && l.renew ? "color:var(--bad)" : ""}">${kDay(l.expires)}</span>${l.renew ? "" : " · fornyes ikke"}${l.tivimate ? " · TiViMate: " + esc(l.tivimate) : ""}</div></div>
      <div class="btns"><button class="b sm" onclick="kShow('iptv', ${l.id}, this)">Vis kode</button><button class="b sm" onclick="kLineEdit(${l.id})">Ret</button></div></div>`).join("") : '<div class="small">Ingen linjer.</div>'}

    <div class="ksec"><h3>Opkrævninger</h3></div>
    ${c.charges.length ? `<table><tbody>${c.charges.map(h => `<tr><td>${K_MONTH[Number(h.period.slice(5, 7)) - 1]} ${h.period.slice(0, 4)}</td><td class="num">${kkr(h.amount)}</td>
      <td><span class="pill ${h.late ? "bad" : K_ST[h.status][1]}">${h.late ? "Mangler betaling" : K_ST[h.status][0]}</span></td><td class="small hs">${h.paid_at ? "betalt " + kDay(h.paid_at) : h.requested_at ? "anmodet " + kDay(h.requested_at) : ""}</td></tr>`).join("")}</tbody></table>` : '<div class="small">Ingen opkrævninger endnu.</div>'}

    <div id="kTimeline"></div>`;
  $("kdFoot").innerHTML = `<button class="b danger" onclick="kDelete()">Slet</button><button class="b" onclick="kMerge()">Flet ind i anden kunde</button><button class="b pri" onclick="kSaveCard()">Gem</button>`;
  kSeerrLoad(c.id);
  kTimelineLoad(c.id);   // 2.2: tidslinje og noter (udsendelse.js)
}
function kCardVals() { const o = {}; ["name", "status", "kind", "method", "revolut", "freq", "cycle", "due_day", "phone", "email", "contact", "tg", "fb", "notes"].forEach(k => o[k] = $("kc_" + k).value.trim()); return o; }
async function kSaveCard(quiet) {
  try { KCUR = await api("/api/kunder/customers/" + KCUR.id, {method: "PUT", body: JSON.stringify(kCardVals())}); if (!quiet) { kdlg.close(); toast("Gemt"); } kAfter(); return true; }
  catch (e) { $("kdErr").textContent = e.message; return false; }
}
function kAfter() { if (TAB === "cust") { loadCust(); if (SUB.cust === "iptv") loadIptv(); } if (TAB === "pay") loadPay(); loadHome(); }
async function kDelete() {
  if (!confirm(`Slet ${KCUR.name}?\n\nKunden, tjenesterne og ubetalte opkrævninger slettes og kan ikke hentes tilbage. IPTV-linjer bevares under "Ingen kunde".\n\nVil du kun stoppe opkrævningen, så sæt Status til Stoppet i stedet.`)) return;
  try { await api("/api/kunder/customers/" + KCUR.id, {method: "DELETE"}); kdlg.close(); toast("Kunden er slettet"); kAfter(); } catch (e) { $("kdErr").textContent = e.message; }
}
function kMerge() {
  const opts = KC.filter(x => x.id !== KCUR.id).map(x => [x.id, x.name]);
  if (!opts.length) { toast("Åbn kundelisten først", true); return; }
  kForm(`Flet ${KCUR.name} ind i en anden kunde`, [{k: "into", label: "Kunden, der betaler", type: "select", options: [["", "– vælg –"], ...opts],
    hint: `Bruges, når en anden kunde betaler for denne konto. Tjenester, IPTV-linjer og fradrag flyttes over, og "${esc(KCUR.name)}" forsvinder som selvstændig kunde. Det kan ikke fortrydes.`}], {},
    async v => { if (!v.into) throw new Error("vælg en kunde"); KCUR = await api(`/api/kunder/customers/${KCUR.id}/merge`, {method: "POST", body: JSON.stringify({into: Number(v.into)})}); renderCard(); kAfter(); }, "Flet");
}
function kSvcEdit(id) {
  const s = id ? KCUR.services.find(x => x.id === id) : {service: "plex", price: "", active: true, plex_user_id: ""};
  const free = (K.plex_free || []).map(p => [p.user_id, `${p.friendly_name} (${p.username})`]);
  if (s.plex) free.unshift([s.plex_user_id, `${s.plex.friendly_name} (${s.plex.username})`]);
  const fields = [{k: "service", label: "Tjeneste", type: "select", options: K.services},
    {k: "label", label: "Navn på kontoen (valgfrit)", type: "text", ph: "fx Casper eller Stue", hint: "Bruges, når kunden betaler for flere konti."},
    {k: "price", label: "Pris pr. måned (kr.)", type: "money"},
    {k: "plex_user_id", label: "Plex-bruger i Tautulli (kun Plex)", type: "select", options: [["", "– ingen –"], ...free]},
    {k: "username", label: "Brugernavn", type: "text"}, {k: "email", label: "E-mail", type: "text"},
    {k: "password", label: "Kodeord", type: "secret", has: s.has_password, ref: ["service", s.id]},
    {k: "note", label: "Note", type: "text"}, {k: "active", label: "Aktiv (regnes med i prisen)", type: "check"},
    ...(id ? [{k: "customer_id", label: "Hører til kunden", type: "select", options: (KC.length ? KC : [KCUR]).map(x => [x.id, x.name]), hint: "Vælg en anden kunde for at flytte tjenesten."},
      {k: "remove", label: "Slet tjenesten helt", type: "check"}] : [])];
  kForm(id ? "Ret tjeneste" : "Tilføj tjeneste", fields, {...s, customer_id: KCUR.id}, async v => {
    if (v.remove) { if (!confirm("Slet tjenesten? Det kan ikke fortrydes.")) throw new Error("ikke slettet"); KCUR = await api("/api/kunder/services/" + id, {method: "DELETE"}); }
    else { const r = await api("/api/kunder/services", {method: "POST", body: JSON.stringify({...v, id, customer_id: Number(v.customer_id || KCUR.id), plex_user_id: v.service === "plex" ? v.plex_user_id : ""})});
      KCUR = r.id === KCUR.id ? r : await api("/api/kunder/customers/" + KCUR.id); }
    K = await kState(); renderCard(); kAfter();
  });
}
function kAdjAdd() {
  kForm("Fradrag eller tillæg", [{k: "text", label: "Tekst – står i beskeden til kunden", type: "text", ph: "fx Rabat som ny kunde", hint: "Skriv det, så kunden forstår det: fx Gratis måned (henvisning), Rabat som ny kunde eller Ekstra ønsker i Seerr. I beskeden står der fx: 🎁 Rabat som ny kunde: -60 kr."}, {k: "amount", label: "Beløb (kr.) – minus for fradrag", type: "money", ph: "-120"},
    {k: "remaining", label: "Hvor mange opkrævninger skal det gælde?", type: "int", hint: "1 = kun den næste opkrævning."}], {remaining: 1},
    async v => { KCUR = await api("/api/kunder/adjust", {method: "POST", body: JSON.stringify({...v, customer_id: KCUR.id})}); renderCard(); });
}
async function kAdjDel(id) { try { KCUR = await api("/api/kunder/adjust/" + id, {method: "DELETE"}); renderCard(); } catch (e) { toast(e.message, true); } }

// ---------- Seerr-ønsker på kundekortet (1.23.0)
let KSE = null;
const ksUnits = (f, t) => [f ? `${f} film` : "", t ? `${t} ${t === 1 ? "sæson" : "sæsoner"}` : ""].filter(Boolean).join(" og ");
async function kSeerrLoad(cid) {
  const box = $("kSeerr"); if (!box) return;
  if (!(S && S.features && S.features.oensker)) { box.innerHTML = ""; return; }
  box.innerHTML = '<div class="ksec"><h3>Seerr-ønsker</h3></div><div class="small">Henter …</div>';
  try { const r = await api("/api/oensker/customer/" + cid); if (!KCUR || KCUR.id !== cid) return; KSE = r; }
  catch (e) { box.innerHTML = `<div class="ksec"><h3>Seerr-ønsker</h3></div><div class="small">${esc(e.message)}</div>`; return; }
  kSeerrRender();
}
function kSeerrRender() {
  const box = $("kSeerr"); if (!box || !KSE || !KCUR || KSE.customer_id !== KCUR.id) return;
  const fam = KSE.kind === "egen";
  let h = `<div class="ksec"><h3>Seerr-ønsker${KSE.next && !fam ? ` <span class="small">· næste betaling ${esc(KSE.next.text)}</span>` : ""}</h3></div>`;
  if (KSE.mode !== "til") h += `<div class="small" style="margin:0 0 8px;color:var(--info)">${KSE.mode === "prove" ? "Prøvetilstand: Fangarr ændrer endnu ikke noget i Seerr. Se Seerr-ønsker i menuen." : "Styringen af Seerr er slået fra under Kunder › Seerr-ønsker."}</div>`;
  if (!KSE.accounts.length) { box.innerHTML = h + '<div class="small">Kunden har ingen Plex-konto, der er koblet til en Plex-bruger. Koble kontoen under Tjenester, så kan Fangarr styre ønskerne i Seerr.</div>'; return; }
  if (fam) h += '<div class="small" style="margin:0 0 8px">Familie (type Egen): kan ønske ubegrænset i Seerr og opkræves ikke.</div>';
  else if (!KSE.next) h += '<div class="small" style="margin:0 0 8px;color:var(--warn)">Kunden har ingen næste betaling (tjek status og cyklus), så der kan ikke vælges pakke eller købes ønsker.</div>';
  h += KSE.accounts.map(a => {
    const p = a.package, cr = a.credits, left = ksUnits(cr.film.unused, cr.tv.unused);
    const nowTxt = a.seerr ? esc(a.seerr.limits) : a.in_seerr === false ? '<span style="color:var(--warn)">findes ikke i Seerr (har ikke logget ind i Seerr endnu)</span>' : "kan ikke ønske";
    const use = a.usage ? ` · brugt de sidste 30 dage: ${ksUnits(a.usage.film, a.usage.tv) || "intet"}` : "";
    const pend = a.pending ? `<div class="small" style="color:var(--info)">${a.pending.to ? "Skifter til " + esc(a.pending.name) : "Pakken stopper"} fra ${kDay(a.pending.date)}</div>` : "";
    const buys = a.buys.length ? `<div class="small">Køb: ${a.buys.slice(0, 5).map(b => `${kDay(b.created)} ${ksUnits(b.film, b.tv)} (${kkr(b.amount)}) <a href="#" onclick="kSeerrUndo(${b.id});return false">fortryd</a>`).join(" · ")}</div>` : "";
    return `<div class="kitem"><div class="who"><b>${esc(a.name)}</b>${p ? ` · ${esc(p.name)} <span class="small">(${ksUnits(p.film, p.tv)} pr. 30 dage)</span>` : fam ? "" : ' · <span class="small">ingen pakke</span>'}
        <div class="small">I Seerr nu: ${nowTxt}${use}</div>${pend}${left ? `<div class="small">Købte ønsker tilbage: ${left}</div>` : ""}${buys}</div>
      ${p ? `<div class="amt">${kkr(p.price)}<span class="small"> /md.</span></div>` : ""}
      ${fam || !KSE.next ? "" : `<div class="btns"><button class="b sm" onclick="kSeerrPkg(${a.plex_user_id})">${p ? "Skift pakke" : "Vælg pakke"}</button><button class="b sm" onclick="kSeerrBuy(${a.plex_user_id})">Køb ønsker</button></div>`}</div>`;
  }).join("");
  box.innerHTML = h;
}
function kSeerrDlg(title, body, saveText, onSave, quoteFn) {
  $("edTitle").textContent = title; $("edErr").textContent = ""; $("edSave").textContent = saveText; $("edSave").disabled = true;
  $("edBody").innerHTML = body + '<div class="card" id="ksq" style="margin:12px 0 0"><div class="small">Beregner …</div></div>';
  let t = null, n = 0;
  const refresh = async () => {
    const me = ++n;
    try {
      const q = await quoteFn(); if (me !== n) return;
      $("ksq").innerHTML = q.lines.map(l => `<div style="margin:2px 0">${esc(l)}</div>`).join("") + `<div style="margin-top:8px"><b>Næste betaling ${esc(q.next_text)}: ${kkr(q.next_amount)}</b></div>`;
      $("edErr").textContent = ""; $("edSave").disabled = q.kind === "samme";
    } catch (e) { if (me !== n) return; $("ksq").innerHTML = `<div class="small">${esc(e.message)}</div>`; $("edSave").disabled = true; }
  };
  $("edBody").querySelectorAll("select,input").forEach(el => el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => { clearTimeout(t); $("edSave").disabled = true; t = setTimeout(refresh, 250); }));
  $("edSave").onclick = async () => {
    try { $("edSave").disabled = true; await onSave(); edlg.close(); }
    catch (e) { $("edErr").textContent = e.message; $("edSave").disabled = false; }
  };
  edlg.showModal(); refresh();
}
async function kAfterSeerr() { try { KCUR = await api("/api/kunder/customers/" + KCUR.id); renderCard(); kAfter(); } catch (e) { toast(e.message, true); } }
function kSeerrPkg(pid) {
  const a = KSE.accounts.find(x => x.plex_user_id === pid), cur = a.package ? a.package.key : "";
  const opts = [["", "Ingen pakke"], ...KSE.packages.map(p => [p.key, `${p.name} – ${ksUnits(p.film, p.tv)} pr. 30 dage – ${kkr(p.price)} pr. måned`])];
  const note = a.pending ? `<div class="small" style="color:var(--info);margin-top:6px">Planlagt: ${a.pending.to ? "skifter til " + esc(a.pending.name) : "pakken stopper"} fra ${kDay(a.pending.date)}. Vælg ${esc(a.package ? a.package.name : "Ingen pakke")} for at fortryde.</div>` : "";
  kSeerrDlg(`Pakke til ${a.name}`, `<div class="field"><label for="ksp">Pakke</label><select id="ksp">${opts.map(([v, l]) => `<option value="${v}" ${v === cur ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
      <div class="small">En ny eller større pakke virker med det samme – næste betaling får et tillæg for dagene indtil da. En mindre pakke eller stop gælder fra næste betaling.</div>${note}</div>`, "Gem",
    async () => { const r = await api("/api/oensker/package", {method: "POST", body: JSON.stringify({customer_id: KCUR.id, plex_user_id: pid, package: $("ksp").value})}); toast(r.message); await kAfterSeerr(); },
    () => api("/api/oensker/quote", {method: "POST", body: JSON.stringify({customer_id: KCUR.id, plex_user_id: pid, package: $("ksp").value})}));
}
function kSeerrBuy(pid) {
  const a = KSE.accounts.find(x => x.plex_user_id === pid);
  kSeerrDlg(`Køb ønsker til ${a.name}`, `<div class="grid">
      <div class="field"><label for="ksf">Film (${kkr(KSE.price_film)} pr. stk.)</label><input type="number" id="ksf" min="0" max="999" value="1" inputmode="numeric"></div>
      <div class="field"><label for="kst">Sæsoner (${kkr(KSE.price_tv)} pr. stk.)</label><input type="number" id="kst" min="0" max="999" value="0" inputmode="numeric"></div></div>
      <div class="small">Købte ønsker kommer oveni en evt. pakke, virker med det samme og udløber aldrig. Beløbet lægges på næste betaling.</div>`, "Køb",
    async () => { const r = await api("/api/oensker/buy", {method: "POST", body: JSON.stringify({customer_id: KCUR.id, plex_user_id: pid, film: $("ksf").value, tv: $("kst").value})}); toast(r.message); await kAfterSeerr(); },
    () => api("/api/oensker/quote", {method: "POST", body: JSON.stringify({what: "buy", customer_id: KCUR.id, plex_user_id: pid, film: $("ksf").value, tv: $("kst").value})}));
}
async function kSeerrUndo(bid) {
  if (!confirm("Fortryd købet?\n\nØnskerne fjernes, og beløbet tages af næste betaling. Det kan kun lade sig gøre, når ønskerne ikke er brugt, og beløbet ikke er anmodet.")) return;
  try { const r = await api("/api/oensker/buy/" + bid, {method: "DELETE"}); toast(r.message); await kAfterSeerr(); } catch (e) { toast(e.message, true); }
}


// ---------- IPTV-linjer
async function loadIptv() { try { await kNeed(); if (!KC.length) KC = await api("/api/kunder/customers"); KI = await api("/api/kunder/iptv"); } catch (e) { toast(e.message, true); return; } renderIptv(); }
function renderIptv() {
  const L = KI.lines, m = l => (l.expires || "").slice(0, 7);
  const G = {maaned: l => l.renew && m(l) === KI.period, naeste: l => l.renew && m(l) === KI.next, udloebet: l => l.renew && l.expires && m(l) < KI.period, ingen: l => !l.customer_id, alle: () => true};
  const N = [["maaned", "Fornyes denne måned"], ["naeste", "Næste måned"], ["udloebet", "Allerede udløbet"], ["ingen", "Ingen kunde"], ["alle", "Alle"]];
  $("iptvPills").innerHTML = N.map(([k, l]) => `<button class="${KIF === k ? "on" : ""}" onclick="KIF='${k}';renderIptv()">${l}<span>${L.filter(G[k]).length}</span></button>`).join("");
  const S = L.filter(G[KIF]), cost = S.reduce((a, l) => a + (l.cost || 0), 0);
  $("iptvList").innerHTML = S.length ? `<div class="small" style="margin:0 0 10px">${S.length} ${S.length === 1 ? "linje" : "linjer"} · ${kkr(cost)} i alt</div><div class="kl">${S.map(l => `<div class="kr">
      <div class="who"><b>${esc(l.label || l.username || "Linje")}</b>${l.renew ? "" : ' <span class="pill">Fornyes ikke</span>'}
        <div class="small">${l.customer_id ? `<a href="#" onclick="kOpen(${l.customer_id});return false" style="color:inherit">${esc(l.customer)}</a>` : '<span style="color:var(--warn)">ingen kunde</span>'}${l.tivimate ? " · TiViMate: " + esc(l.tivimate) : ""}${l.note ? " · " + esc(l.note) : ""}</div></div>
      <div class="meta">udløber <b style="color:${l.expired && l.renew ? "var(--bad)" : "var(--text)"}">${kDay(l.expires)}</b></div><div class="amt">${l.cost ? kkr(l.cost) : "–"}</div>
      <div class="btns"><button class="b sm" onclick="kShow('iptv', ${l.id}, this)">Vis kode</button><button class="b sm pri" onclick="kRenew(${l.id})">Fornyet</button><button class="b sm" onclick="kLineEdit(${l.id})">Ret</button></div></div>`).join("")}</div>`
    : `<div class="empty">${L.length ? "Ingen linjer i denne visning." : "Der er ingen IPTV-linjer endnu."}</div>`;
}
function kLineOf(id) { return (KI && KI.lines.find(x => x.id === id)) || (KCUR && KCUR.iptv.find(x => x.id === id)); }
async function kLineSaved(r) { KI = r; if (TAB === "cust" && SUB.cust === "iptv") renderIptv(); if (kdlg.open && KCUR) { KCUR = await api("/api/kunder/customers/" + KCUR.id); renderCard(); } loadHome(); }
function kLineEdit(id, cid) {
  const l = id ? kLineOf(id) : {customer_id: cid || "", renew: true};
  kForm(id ? "Ret IPTV-linje" : "Ny IPTV-linje", [
    {k: "customer_id", label: "Kunde", type: "select", options: [["", "– ingen kunde –"], ...(KC.length ? KC : (KCUR ? [KCUR] : [])).map(x => [x.id, x.name])]},
    {k: "label", label: "Navn på linjen", type: "text", ph: "fx Stue eller Værelse"},
    {k: "username", label: "Brugernavn", type: "text"}, {k: "password", label: "Kode", type: "secret", has: l.has_password, ref: ["iptv", l.id]},
    {k: "expires", label: "Udløber", type: "date"}, {k: "cost", label: "Hvad koster en fornyelse? (kr.)", type: "money"},
    {k: "tivimate", label: "TiViMate-konto (valgfrit)", type: "text"}, {k: "note", label: "Note", type: "text"},
    {k: "renew", label: "Skal fornyes, når den udløber", type: "check"},
    ...(id ? [{k: "remove", label: "Slet linjen helt", type: "check"}] : [])], l,
    async v => {
      if (v.remove) { if (!confirm("Slet linjen med brugernavn og kode? Det kan ikke fortrydes.")) throw new Error("ikke slettet"); await kLineSaved(await api("/api/kunder/iptv/" + id, {method: "DELETE"})); }
      else await kLineSaved(await api("/api/kunder/iptv", {method: "POST", body: JSON.stringify({...v, id})}));
    });
}
function kRenew(id) {
  const l = kLineOf(id), today = new Date().toISOString().slice(0, 10), d = new Date((l.expires && l.expires > today ? l.expires : today) + "T12:00:00");
  d.setFullYear(d.getFullYear() + 1);
  kForm("Fornyet – " + (l.label || l.username || "linje"), [{k: "expires", label: "Ny udløbsdato", type: "date", hint: "Foreslået: 12 måneder frem. Ret datoen, hvis du har købt en anden periode."},
    {k: "cost", label: "Pris for fornyelsen (kr.)", type: "money"}], {expires: d.toISOString().slice(0, 10), cost: l.cost || ""},
    async v => { await kLineSaved(await api("/api/kunder/iptv", {method: "POST", body: JSON.stringify({id, ...v})})); toast("Linjen er fornyet"); }, "Gem ny dato");
}

// ---------- delte logins
let KL = [];
async function loadLogins() { try { KL = await api("/api/kunder/logins"); } catch (e) { return; } renderLogins(); }
function renderLogins() {
  $("kLogins").innerHTML = KL.length ? `<div class="kl">${KL.map(l => `<div class="kr"><div class="who"><b>${esc(l.service || "Login")}</b>${l.label ? " · " + esc(l.label) : ""}
      <div class="small">${esc(l.username)}${l.note ? " · " + esc(l.note) : ""}</div></div>
      <div class="btns">${l.has_password ? `<button class="b sm" onclick="kShow('login', ${l.id}, this)">Vis kode</button>` : ""}<button class="b sm" onclick="kLoginEdit(${l.id})">Ret</button></div></div>`).join("")}</div>`
    : '<div class="empty">Ingen delte logins endnu.</div>';
}
function kLoginEdit(id) {
  const l = id ? KL.find(x => x.id === id) : {};
  kForm(id ? "Ret login" : "Nyt login", [{k: "service", label: "Tjeneste", type: "text", ph: "fx Spotify"}, {k: "label", label: "Navn (valgfrit)", type: "text", ph: "fx Familie 1"},
    {k: "username", label: "Brugernavn / e-mail", type: "text"}, {k: "password", label: "Kodeord", type: "secret", has: l.has_password, ref: ["login", l.id]},
    {k: "note", label: "Note", type: "text"}, ...(id ? [{k: "remove", label: "Slet dette login", type: "check"}] : [])], l,
    async v => { if (v.remove) { if (!confirm("Slet dette login? Det kan ikke fortrydes.")) throw new Error("ikke slettet"); KL = await api("/api/kunder/logins/" + id, {method: "DELETE"}); }
      else KL = await api("/api/kunder/logins", {method: "POST", body: JSON.stringify({...v, id})}); renderLogins(); });
}


// ---------- indstillinger for kunder
const KS = ["remind_days", "remind_repeat_days", "pay_days", "inactive_days", "plex_price", "message_hour", "sync_hour", "template", "pay_link_text", "pay_revolut_text", "pay_mobilepay_text", "pay_other_text", "app_tg_pkg", "app_fb_pkg"];
let KS_READY = false;   // felterne er fyldt ud fra K.settings – før det må Gem ikke sende tomme felter
function renderKSet() { if (K) { KS.forEach(k => $("ks_" + k).value = K.settings[k] ?? ""); KS_READY = true;
    const miss = ["{betaling}", "{rabatter}", "{nyhed}"].filter(f => !String(K.settings.template || "").includes(f)), w = $("ks_tplWarn");
    w.style.display = miss.length ? "" : "none"; w.innerHTML = miss.length ? `Skabelonen mangler ${miss.map(esc).join(", ")}. Uden ${miss.length === 1 ? "det felt" : "de felter"} kommer ${miss.map(f => ({"{betaling}": "betalingslinket", "{rabatter}": "rabatter og tillæg", "{nyhed}": "nyheden"})[f]).join(", ")} ikke med i beskeden. Sæt ${miss.length === 1 ? "det" : "dem"} ind på hver sin linje, og tryk Gem skabelonen.` : ""; } }
async function kSaveSettings() {
  if (!K || !KS_READY) { toast("Indstillingerne er ikke hentet endnu – prøv igen om et øjeblik", true); return; }
  const b = {}; KS.forEach(k => b[k] = $("ks_" + k).value);
  try { K.settings = await api("/api/kunder/settings", {method: "PUT", body: JSON.stringify(b)}); renderKSet(); toast("Gemt"); } catch (e) { toast(e.message, true); }
}
