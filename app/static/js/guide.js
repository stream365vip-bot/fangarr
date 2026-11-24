// Guide: besøg på guide.stream365.vip og nyhederne øverst i guiden.
// ---------- guide (besøg på guide.stream365.vip)
let GD = null, gOpen = new Set();
const G_MON = ["jan.", "feb.", "mar.", "apr.", "maj", "jun.", "jul.", "aug.", "sep.", "okt.", "nov.", "dec."];
function gDate(t) { if (!t) return "–"; const m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d:\d\d)/.exec(t); return m ? `${Number(m[3])}. ${G_MON[Number(m[2]) - 1]} kl. ${m[4]}` : esc(t); }
async function loadGuide() {
  try { GD = await api("/api/guide?days=" + $("gDays").value); renderGuide(); } catch (e) { toast(e.message, true); }
}
function gToggle(uid) { gOpen.has(uid) ? gOpen.delete(uid) : gOpen.add(uid); renderGuide(); }
function renderGuide() {
  const d = GD, k = d.kpis;
  $("gNote").innerHTML = d.enabled ? (d.first_event ? "" : '<div class="warn">Tælleren er sat op, men der er ingen besøg i perioden endnu. Tallene begynder, når den nye udgave af guiden (nyt) er installeret, og den første kunde åbner guiden.</div>')
    : `<div class="warn"><b>Tælleren er ikke sat op endnu.</b> Fangarr kan ikke se mappen <code>${esc(d.dir)}</code>. Tilføj linjen <code>- "/opt/nyt/data/statistik:/guide-stat:ro"</code> under <code>volumes:</code> i <code>/opt/fangarr/docker-compose.yml</code> på feeder, og genstart Fangarr (se LÆSMIG › Guide).</div>`;
  $("gKpis").innerHTML = [
    ["Har været inde", k.visitors, `brugere de seneste ${d.days} dage`],
    ["Besøg", k.visits, `${k.sections} læste afsnit · ${k.searches} søgninger`],
    ["Har accepteret reglerne", k.accepted, k.active_customers ? `af ${k.active_customers} aktive kunder med Plex` : "i alt"],
    ["Har aldrig været inde", k.never, "aktive kunder – se listen nederst"],
  ].map(x => `<div class="kpi"><div class="l">${x[0]}</div><div class="v">${x[1]}</div><div class="s">${x[2]}</div></div>`).join("");
  $("gUsers").innerHTML = d.users.length ? d.users.map(u => {
    const open = gOpen.has(u.uid), secs = u.sections, qs = u.searches;
    const detail = open ? `<tr><td colspan="6" style="background:var(--bg)">
      <div class="small" style="margin:0 0 8px">Første besøg i perioden: ${gDate(u.first)} · Login på en enhed: ${u.logins} · Regler accepteret: ${gDate(u.accepted_at)}</div>
      <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px">
        <div><b>Afsnit, brugeren har læst</b>${secs.length ? "<ul style='margin:6px 0 0; padding-left:18px'>" + secs.map(s => `<li>${esc(s.title)}${s.n > 1 ? ` <span class="small">× ${s.n}</span>` : ""} <span class="small">– ${gDate(s.last)}</span></li>`).join("") + "</ul>" : '<div class="small">Ingen afsnit endnu.</div>'}</div>
        <div><b>Søgninger</b>${qs.length ? "<ul style='margin:6px 0 0; padding-left:18px'>" + qs.map(s => `<li>“${esc(s.q)}” <span class="small">– ${gDate(s.t)}</span></li>`).join("") + "</ul>" : '<div class="small">Ingen søgninger.</div>'}</div>
      </div></td></tr>` : "";
    return `<tr><td><b>${esc(u.name)}</b>${u.known ? "" : ' <span class="tag" title="Plex-kontoen findes ikke under Kunder – synk fra Tautulli">ukendt i Kunder</span>'}<div class="small">${esc(u.username)}</div></td>
      <td>${gDate(u.last)}</td><td class="num">${u.visits}</td><td class="num hs">${secs.length}</td><td class="num hs">${qs.length}</td>
      <td class="num"><button class="b sm" onclick="gToggle('${esc(u.uid)}')" aria-expanded="${open}">${open ? "Skjul" : "Vis"}</button></td></tr>${detail}`; }).join("")
    : '<tr><td colspan="6" class="empty">Ingen har været inde i perioden.</td></tr>';
  $("gSecs").innerHTML = d.sections.length ? d.sections.map(s => `<tr><td><b>${esc(s.title)}</b></td><td class="num">${s.users}</td><td class="num">${s.views}</td><td style="white-space:nowrap">${gDate(s.last)}</td></tr>`).join("")
    : '<tr><td colspan="4" class="empty">Ingen læste afsnit i perioden.</td></tr>';
  $("gQs").innerHTML = d.searches.length ? d.searches.map(s => `<tr><td><b>${esc(s.q)}</b></td><td class="num">${s.n}</td><td>${esc(s.users.join(", "))}</td><td style="white-space:nowrap">${gDate(s.last)}</td></tr>`).join("")
    : '<tr><td colspan="4" class="empty">Ingen søgninger i perioden.</td></tr>';
  $("gMore").innerHTML =
    (d.earlier.length ? `<details class="card" style="margin-top:14px"><summary><b>Har accepteret reglerne, men ikke været inde i perioden (${d.earlier.length})</b> <span class="small">(tryk for at folde ud)</span></summary>
      <ul style="margin:10px 0 0; padding-left:20px; line-height:1.6">${d.earlier.map(a => `<li>${esc(a.name)} <span class="small">(${esc(a.username)}) – accepterede ${gDate(a.accepted_at)}</span></li>`).join("")}</ul></details>` : "") +
    (d.never.length ? `<details class="card" style="margin-top:14px"><summary><b>Aktive kunder, der aldrig har været inde (${d.never.length})</b> <span class="small">(tryk for at folde ud)</span></summary>
      <p class="small">Kunder med en aktiv Plex-konto, som hverken har accepteret reglerne eller besøgt guiden. Bruges, hvis du vil minde nogen om guiden.</p>
      <div style="columns:220px; line-height:1.7">${d.never.map(n => `<div>${esc(n)}</div>`).join("")}</div></details>` : "");
}

// ---------- Guide › Nyheder (1.24.0) – kortet øverst i guiden og nyhedens pop-up
let NW = null, NE = null, nwCard = null, nwPrevItem = null, nwPrevContact = null, nwT = null, nwDev = "phone", NWG = {theme: "", svg: {}};
const NW_ST = {kladde: "Kladde", planlagt: "Planlagt", aktiv: "Aktiv", udloebet: "Udløbet"};
const NW_ACT = {popup: "Åbner pop-up", section: "Fører til afsnit", shop: "Åbner Få flere ønsker", none: "Ingen knap"};
function nwLocal(d) { const p = n => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; }
function nwDay(v) { if (!v) return ""; const m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d:\d\d)/.exec(v); if (!m) return esc(v); const t = m[4] === "23:59" || m[4] === "00:00" ? "" : " kl. " + m[4]; return `${Number(m[3])}. ${G_MON[Number(m[2]) - 1]}${t}`; }
function nwPeriod(d) { return d.start ? (d.end ? `${nwDay(d.start)} – ${nwDay(d.end)}` : `fra ${nwDay(d.start)} – ingen slutdato`) : "ingen periode"; }
async function nwLoad() {
  try { NW = await api("/api/nyheder"); nwRender(); } catch (e) { toast(e.message, true); }
}
function nwAge(s) { return s < 90 ? `${s} sek.` : s < 5400 ? `${Math.round(s / 60)} min.` : `${Math.round(s / 3600)} timer`; }
function nwRender() {
  const d = NW, g = d.guide;
  $("nwNote").innerHTML = (!g.seen ? `<div class="warn"><b>Guiden har ikke hentet nyheder endnu.</b> Det sker, når guiden (appen <code>nyt</code>) er opdateret til den nye udgave – se LÆSMIG › Nyheder i guiden. Indtil da kan du skrive og forhåndsvise nyheder, men kunderne ser dem ikke.</div>`
      : !g.ok ? `<div class="warn"><b>Guiden har ikke hentet nyheder i ${nwAge(g.age)}.</b> Kunderne ser stadig de nyheder, guiden hentede sidst. Tjek at <code>nyt</code> kører på feeder.</div>`
      : `<div class="small" style="margin:0 0 12px">Guiden hentede nyhederne for ${nwAge(g.age)} siden. En udgivet eller rettet nyhed ses af kunderne inden for et minut.</div>`) +
    (d.stat_ok ? "" : '<div class="small" style="margin:0 0 12px">Tallene for "set" og "tryk" kommer fra guidens tæller – de vises, når tælleren er sat op (se fanen Besøg).</div>');
  const act = d.items.filter(x => x.status === "aktiv").length;
  $("nwTabN").textContent = act ? ` (${act})` : "";
  $("nwItems").innerHTML = d.items.length ? d.items.map((x, i) => {
    const t = d.themes[x.data.theme] || {}, st = x.stats;
    const warn = x.warnings.concat(x.published ? x.problems : []);
    return `<div class="card nwitem"><div class="sw" style="background:${esc(t.bg)};${t.border && t.border !== "none" ? "border:" + esc(t.border) : ""}" aria-hidden="true">${NWG.svg[x.id] || ""}</div>
      <div class="who"><b>${esc(x.data.title || "(uden overskrift)")}</b><span class="nwst ${x.status}">${NW_ST[x.status]}</span>
        <div class="small">${esc(t.name || "")} · ${NW_ACT[x.data.action]} · ${nwPeriod(x.data)}${x.data.only_new ? " · kun nye brugere" : ""}</div>
        ${warn.map(w => `<div class="small" style="color:var(--warn)">⚠ ${esc(w)}</div>`).join("")}</div>
      <div class="cnt">${st ? `${st.seen} set<br>${st.click + st.popup} tryk${st.contact ? `<br>${st.contact} skrev` : ""}` : "–"}</div>
      <div class="btns"><button class="b sm" onclick="nwMove(${i},-1)" ${i ? "" : "disabled"} aria-label="Flyt op">↑</button><button class="b sm" onclick="nwMove(${i},1)" ${i < d.items.length - 1 ? "" : "disabled"} aria-label="Flyt ned">↓</button>
        <button class="b" onclick="nwOpen(${x.id})">Rediger</button></div></div>`; }).join("")
    : '<div class="card empty">Ingen nyheder endnu. Tryk <b>Ny nyhed</b> for at lave den første.</div>';
  const s = d.settings;
  $("nw_messenger").value = s.messenger || ""; $("nw_telegram").value = s.telegram || ""; $("nw_label").value = s.contact_label || ""; $("nw_days").value = s.new_days;
  nwThumbs();
}
async function nwThumbs() {
  // små billeder af hver nyhed i listen (illustrationen i nyhedens farver)
  for (const x of NW.items) {
    const k = x.id + ":" + x.updated;
    if (NWG.svg[x.id] && NWG.svg["k" + x.id] === k) continue;
    if (!x.data.art) { NWG.svg[x.id] = ""; continue; }
    try { const r = await api("/api/nyheder/preview", {method: "POST", body: JSON.stringify(x.data)}); NWG.svg[x.id] = r.item.art; NWG.svg["k" + x.id] = k; } catch (e) { NWG.svg[x.id] = ""; }
  }
  document.querySelectorAll("#nwItems .nwitem .sw").forEach((el, i) => { const x = NW.items[i]; if (x && NWG.svg[x.id] !== undefined) el.innerHTML = NWG.svg[x.id]; });
}
async function nwMove(i, dir) {
  const ids = NW.items.map(x => x.id), j = i + dir; if (j < 0 || j >= ids.length) return;
  [ids[i], ids[j]] = [ids[j], ids[i]];
  try { await api("/api/nyheder/order", {method: "POST", body: JSON.stringify({ids})}); await nwLoad(); } catch (e) { toast(e.message, true); }
}
async function nwSaveSet() {
  try { const r = await api("/api/nyheder/settings", {method: "PUT", body: JSON.stringify({messenger: $("nw_messenger").value, telegram: $("nw_telegram").value,
          contact_label: $("nw_label").value, new_days: $("nw_days").value})}); toast(r.message); await nwLoad(); } catch (e) { toast(e.message, true); }
}
function nwBlank(theme) {
  const ex = NW.themes[theme || "tilbud"].ex;
  return {theme: theme || "tilbud", tag: "", title: ex.title, text: ex.text, btn: ex.btn, action: "popup", section: "", art: ex.art,
          art_t1: "+2", art_t2: "måneder", art_t3: "med i købet", start: nwLocal(new Date()), end: "", countdown: false, closable: true, only_new: false,
          popup: {title: "", price: "", price_sub: "", intro: "", steps: [{title: "", text: "", art: ""}], read: "", contact: true, close: "Forstået"}};
}
function nwNew() { NE = {id: 0, published: false, status: "kladde", data: nwBlank("tilbud")}; nwEditor(); }
function nwOpen(id) {
  const x = NW.items.find(i => i.id === id); if (!x) return;
  const d = JSON.parse(JSON.stringify(x.data));
  if (!d.popup.steps.length) d.popup.steps.push({title: "", text: "", art: ""});
  NE = {id: x.id, published: x.published, status: x.status, data: d}; nwEditor();
}
function nwBack(ask) {
  if (ask && NE && NE.dirty && !confirm("Gå tilbage uden at gemme? Dine ændringer forsvinder.")) return;
  if (nwCard) { nwCard.stop(); nwCard = null; }
  NE = null; $("nwEdit").hidden = true; $("nwEdit").innerHTML = ""; $("nwList").hidden = false; $("nwNote").hidden = false; nwLoad();
}
function nwEditor() {
  $("nwList").hidden = true; $("nwNote").hidden = true; $("nwEdit").hidden = false;
  if (nwCard) { nwCard.stop(); nwCard = null; }
  $("nwEdit").innerHTML = `<div class="row" style="justify-content:space-between">
      <div class="row" style="margin:0"><button class="b sm" onclick="nwBack(true)">← Alle nyheder</button><h3 style="margin:0">${NE.id ? "Rediger nyhed" : "Ny nyhed"}</h3><span class="nwst ${NE.status}">${NW_ST[NE.status]}</span></div></div>
    <div class="nwgrid"><div id="nwForm"></div>
      <aside class="nwprev" aria-label="Forhåndsvisning"><div class="row" style="justify-content:space-between;margin-bottom:8px"><b>Sådan ser kunderne den</b>
          <div class="nwdev" role="group" aria-label="Skærm"><button type="button" aria-pressed="${nwDev === "phone"}" onclick="nwDevice('phone')">Telefon</button><button type="button" aria-pressed="${nwDev === "pc"}" onclick="nwDevice('pc')">Computer</button></div></div>
        <div class="nwframe ${nwDev}" id="nwFrame"><div class="nwfake" aria-hidden="true"><span>☰ Menu</span><span class="s">Søg i guiden …</span></div><div id="nwPrevHost"></div>
          <div class="nwhero" aria-hidden="true"><i>STREAM365-GUIDEN</i><b>Få mere ud af Plex, <em>fra første aften</em></b></div></div>
        <div class="btns" style="justify-content:flex-start;margin-top:10px" id="nwPopBtn"></div>
        <div class="nwprob" id="nwProb"></div></aside></div>
    <div class="nwfoot" id="nwFoot"></div>`;
  nwSyncDev(); nwForm(); nwFootRender(); nwPreview(true);
}
function nwDevice(d) { nwDev = d; document.querySelectorAll(".nwdev button").forEach(b => b.setAttribute("aria-pressed", String(b.textContent === (d === "phone" ? "Telefon" : "Computer")))); $("nwFrame").className = "nwframe " + d; nwSyncDev(); }
function nwSyncDev() { const g = document.querySelector(".nwgrid"); if (g) g.classList.toggle("wide", nwDev === "pc"); }
function nwSecOpts(cur, none) {
  const secs = NW.sections;
  let o = none ? `<option value="">${none}</option>` : "";
  if (cur && !secs.some(s => s.id === cur)) o += `<option value="${esc(cur)}" selected>${esc(cur)} (findes ikke i guiden)</option>`;
  return o + secs.map(s => `<option value="${esc(s.id)}" ${s.id === cur ? "selected" : ""}>${esc(s.title)}</option>`).join("");
}
function nwArtOpts(cur) { return `<option value="">Ingen illustration</option>` + NW.arts.map(a => `<option value="${a.key}" ${a.key === cur ? "selected" : ""}>${esc(a.name)}</option>`).join(""); }
function nwForm() {
  const d = NE.data, p = d.popup, th = NW.themes;
  const secs = NW.sections.length;
  const secHint = secs ? "" : '<div class="small">Listen over afsnit kommer fra guiden, når den har hentet nyheder første gang. Indtil da kan du skrive afsnittets id (fra adressen, fx <code>seerr</code>).</div>';
  const contactOk = !!NW.contact;
  $("nwForm").innerHTML = `
    <fieldset><legend>Skabelon</legend><p class="small" style="margin:0 0 8px">Vælger farverne – og en tekst at starte fra, hvis du ikke har skrevet noget selv.</p>
      <div class="nwthemes">${Object.entries(th).map(([k, t]) => `<button type="button" aria-pressed="${d.theme === k}" onclick="nwTheme('${k}')"><i style="background:${esc(t.bg)};${t.border !== "none" ? "border:" + esc(t.border) : ""}"></i>${esc(t.name)}</button>`).join("")}</div></fieldset>
    <fieldset><legend>Kortet</legend>
      <div class="grid"><div class="field" style="grid-column:1/-1"><label for="nwf_title">Overskrift</label><input type="text" id="nwf_title" data-k="title" maxlength="100" value="${esc(d.title)}"></div>
        <div class="field" style="grid-column:1/-1"><label for="nwf_text">Kort tekst</label><textarea id="nwf_text" data-k="text" rows="2" maxlength="300">${esc(d.text)}</textarea></div>
        <div class="field"><label for="nwf_tag">Mærkat <span class="small">(lille tekst øverst)</span></label><input type="text" id="nwf_tag" data-k="tag" maxlength="24" placeholder="${esc(th[d.theme].name)}" value="${esc(d.tag)}"></div></div>
      <label style="margin-top:12px">Illustration</label>
      <div class="nwarts" id="nwArts"><div class="small">Henter …</div></div>
      ${d.art === "billet" ? `<div class="grid" style="margin-top:12px">
        <div class="field"><label for="nwf_t1">Billet – stor tekst</label><input type="text" id="nwf_t1" data-k="art_t1" maxlength="6" value="${esc(d.art_t1)}" placeholder="fx +2 eller −50%"></div>
        <div class="field"><label for="nwf_t2">Billet – linje 1</label><input type="text" id="nwf_t2" data-k="art_t2" maxlength="18" value="${esc(d.art_t2)}"></div>
        <div class="field"><label for="nwf_t3">Billet – linje 2</label><input type="text" id="nwf_t3" data-k="art_t3" maxlength="18" value="${esc(d.art_t3)}"></div></div>` : ""}
    </fieldset>
    <fieldset><legend>Knappen</legend>
      <div class="grid"><div class="field"><label for="nwf_action">Knappen</label><select id="nwf_action" onchange="nwSet('action', this.value, true)">
          <option value="popup" ${d.action === "popup" ? "selected" : ""}>Åbner nyhedens pop-up</option><option value="section" ${d.action === "section" ? "selected" : ""}>Fører til et afsnit i guiden</option><option value="shop" ${d.action === "shop" ? "selected" : ""}>Åbner "Få flere ønsker" (køb i guiden)</option>
          <option value="none" ${d.action === "none" ? "selected" : ""}>Ingen knap</option></select></div>
        ${d.action !== "none" ? `<div class="field"><label for="nwf_btn">Tekst på knappen</label><input type="text" id="nwf_btn" data-k="btn" maxlength="40" value="${esc(d.btn)}"></div>` : ""}
        ${d.action === "shop" ? `<div class="small" style="grid-column:1/-1;${(NW.shop || {}).open ? "" : "color:var(--warn)"}">${(NW.shop || {}).open ? 'Knappen åbner arket, hvor kunden selv vælger pakke eller køber film og sæsoner.' : 'Køb i guiden er ikke åbent endnu – slå det til under Kunder › Seerr-ønsker › Indstillinger. Indtil da vises kortet uden knap.'}</div>` : ""}
        ${d.action === "section" ? `<div class="field" style="grid-column:1/-1"><label for="nwf_sec">Afsnit i guiden</label>${secs ? `<select id="nwf_sec" data-k="section">${nwSecOpts(d.section, "Vælg afsnit …")}</select>` : `<input type="text" id="nwf_sec" data-k="section" value="${esc(d.section)}" placeholder="afsnittets id">`}${secHint}</div>` : ""}</div>
    </fieldset>
    <fieldset><legend>Hvornår</legend>
      <div class="grid"><div class="field"><label for="nwf_start">Vises fra</label><input type="datetime-local" id="nwf_start" data-k="start" value="${esc(d.start)}"></div>
        <div class="field"><label for="nwf_end">Vises til <span class="small">(tom = indtil du skjuler den)</span></label><input type="datetime-local" id="nwf_end" data-k="end" value="${esc(d.end)}"></div></div>
      <div style="display:grid;gap:10px;margin-top:12px">
        <label class="check"><input type="checkbox" ${d.countdown ? "checked" : ""} onchange="nwSet('countdown', this.checked)"> Nedtælling til slutdatoen <span class="small" style="margin:0">– dage, timer og minutter</span></label>
        <label class="check"><input type="checkbox" ${d.closable ? "checked" : ""} onchange="nwSet('closable', this.checked)"> Kunden kan lukke den <span class="small" style="margin:0">– huskes på enheden</span></label>
        <label class="check"><input type="checkbox" ${d.only_new ? "checked" : ""} onchange="nwSet('only_new', this.checked)"> Kun for nye brugere <span class="small" style="margin:0">– de første ${NW.settings.new_days} dage efter de accepterede reglerne</span></label></div>
    </fieldset>
    ${d.action === "popup" ? `<fieldset><legend>Pop-up'en</legend>
      <p class="small" style="margin:0 0 10px">Det, kunden ser, når de trykker på knappen. Forsvinder sammen med nyheden.</p>
      <div class="grid"><div class="field" style="grid-column:1/-1"><label for="nwp_title">Overskrift <span class="small">(tom = samme som kortet)</span></label><input type="text" id="nwp_title" data-k="popup.title" maxlength="100" value="${esc(p.title)}" placeholder="${esc(d.title)}"></div>
        <div class="field"><label for="nwp_price">Pris <span class="small">(valgfri – vises stort)</span></label><input type="text" id="nwp_price" data-k="popup.price" maxlength="24" value="${esc(p.price)}" placeholder="fx 1.200 kr."></div>
        <div class="field"><label for="nwp_psub">Under prisen</label><input type="text" id="nwp_psub" data-k="popup.price_sub" maxlength="80" value="${esc(p.price_sub)}" placeholder="fx for 14 måneder · ca. 86 kr. om måneden"></div>
        <div class="field" style="grid-column:1/-1"><label for="nwp_intro">Indledning</label><textarea id="nwp_intro" data-k="popup.intro" rows="3" maxlength="600">${esc(p.intro)}</textarea></div></div>
      <label style="margin-top:12px">Trin <span class="small">(vises som "Sådan gør du")</span></label>
      ${p.steps.map((s, i) => `<div class="nwstep"><div class="h"><span class="no">${i + 1}</span><b style="flex:1">Trin ${i + 1}</b>
          <button type="button" class="b sm" onclick="nwStep(${i},-1)" ${i ? "" : "disabled"} aria-label="Flyt trin ${i + 1} op">↑</button><button type="button" class="b sm" onclick="nwStep(${i},1)" ${i < p.steps.length - 1 ? "" : "disabled"} aria-label="Flyt trin ${i + 1} ned">↓</button>
          <button type="button" class="b sm danger" onclick="nwStep(${i},0)" aria-label="Slet trin ${i + 1}">Slet</button></div>
        <div class="field"><label for="nws_t${i}">Overskrift</label><input type="text" id="nws_t${i}" data-step="${i}" data-f="title" maxlength="80" value="${esc(s.title)}"></div>
        <div class="field" style="margin-top:8px"><label for="nws_x${i}">Tekst</label><textarea id="nws_x${i}" data-step="${i}" data-f="text" rows="2" maxlength="400">${esc(s.text)}</textarea></div>
        <div class="field" style="margin-top:8px"><label for="nws_a${i}">Illustration</label><select id="nws_a${i}" data-step="${i}" data-f="art">${nwArtOpts(s.art)}</select></div></div>`).join("")}
      ${p.steps.length < 8 ? '<button type="button" class="b" onclick="nwStep(-1,0)">+ Tilføj trin</button>' : ""}
      <div class="grid" style="margin-top:14px"><div class="field"><label for="nwp_read">Læs også i guiden <span class="small">(link nederst)</span></label>${secs ? `<select id="nwp_read" data-k="popup.read">${nwSecOpts(p.read, "Intet link")}</select>` : `<input type="text" id="nwp_read" data-k="popup.read" value="${esc(p.read)}" placeholder="afsnittets id">`}</div>
        <div class="field"><label for="nwp_close">Knap nederst <span class="small">(lukker pop-up'en)</span></label><input type="text" id="nwp_close" data-k="popup.close" maxlength="30" value="${esc(p.close)}"></div></div>
      <label class="check" style="margin-top:12px"><input type="checkbox" ${p.contact ? "checked" : ""} ${contactOk ? "" : "disabled"} onchange="nwSet('popup.contact', this.checked)"> Vis knappen "${esc((NW.contact || {}).label || NW.settings.contact_label || "Skriv til os")}" <span class="small" style="margin:0">${contactOk ? "– Messenger/Telegram fra Indstillinger" : "– sæt links ind under Indstillinger på listen først"}</span></label>
    </fieldset>` : ""}`;
  $("nwForm").querySelectorAll("[data-k]").forEach(el => el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => nwSet(el.dataset.k, el.value)));
  $("nwForm").querySelectorAll("[data-step]").forEach(el => el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => {
    NE.data.popup.steps[Number(el.dataset.step)][el.dataset.f] = el.value; NE.dirty = true; nwPreview(); }));
  nwArts();
}
async function nwArts() {
  const d = NE.data, key = [d.theme, d.art_t1, d.art_t2, d.art_t3].join("|");
  if (NWG.key !== key) {
    try { NWG.list = await api(`/api/nyheder/gallery?theme=${encodeURIComponent(d.theme)}&t1=${encodeURIComponent(d.art_t1)}&t2=${encodeURIComponent(d.art_t2)}&t3=${encodeURIComponent(d.art_t3)}`); NWG.key = key; }
    catch (e) { return; }
  }
  const box = $("nwArts"); if (!box || !NE) return;
  const bg = NW.themes[d.theme].bg;
  box.innerHTML = `<button type="button" aria-pressed="${!d.art}" onclick="nwSet('art','',true)"><span class="a none" style="background:${esc(bg)};color:${esc(NW.themes[d.theme].ink)}">Ingen</span><span class="n">Ingen illustration</span></button>` +
    NWG.list.map(a => `<button type="button" aria-pressed="${d.art === a.key}" onclick="nwSet('art','${a.key}',true)"><span class="a" style="background:${esc(bg)}">${a.svg}</span><span class="n">${esc(a.name)}</span></button>`).join("");
}
function nwTheme(k) {
  const d = NE.data, old = NW.themes[d.theme].ex, ex = NW.themes[k].ex;
  // eksempelteksten skiftes kun, hvis du ikke har skrevet din egen
  for (const f of ["title", "text", "btn"]) if (!d[f] || d[f] === old[f]) d[f] = ex[f];
  if (!d.art || d.art === old.art) d.art = ex.art;
  d.theme = k; NE.dirty = true; nwForm(); nwPreview();
}
function nwSet(k, v, rerender) {
  if (!NE) return;
  const path = k.split("."); let o = NE.data;
  while (path.length > 1) o = o[path.shift()];
  o[path[0]] = v; NE.dirty = true;
  if (rerender || k === "art_t1" || k === "art_t2" || k === "art_t3") { if (rerender) nwForm(); else { clearTimeout(nwArts._t); nwArts._t = setTimeout(nwArts, 400); } }
  nwPreview();
}
function nwStep(i, dir) {
  const st = NE.data.popup.steps;
  if (i === -1) st.push({title: "", text: "", art: ""});
  else if (dir === 0) { if ((st[i].title || st[i].text) && !confirm("Slet trin " + (i + 1) + "?")) return; st.splice(i, 1); }
  else { const j = i + dir; [st[i], st[j]] = [st[j], st[i]]; }
  NE.dirty = true; nwForm(); nwPreview();
}
function nwPreview(now) {
  clearTimeout(nwT);
  nwT = setTimeout(async () => {
    if (!NE) return;
    try {
      const r = await api("/api/nyheder/preview", {method: "POST", body: JSON.stringify(NE.data)});
      if (!NE) return;
      nwPrevItem = r.item; nwPrevContact = r.contact;
      const host = $("nwPrevHost");
      if (window.S365News && host) {
        if (!nwCard) nwCard = S365News.card(host, [r.item], {preview: true, contact: r.contact, note: t => toast(t)});
        else { nwCard.o.contact = r.contact; nwCard.update([r.item]); }
      }
      $("nwPopBtn").innerHTML = r.item.popup ? '<button class="b" onclick="nwPop()">Åbn pop-up\'en</button>' : "";
      $("nwProb").innerHTML = r.problems.length ? `<b>Før nyheden kan udgives:</b><ul>${r.problems.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
      NE.problems = r.problems; nwFootRender();
    } catch (e) { $("nwProb").textContent = e.message; }
  }, now ? 0 : 300);
}
function nwPop() { if (nwPrevItem && window.S365News) S365News.popup(nwPrevItem, nwPrevContact, {preview: true, note: t => toast(t)}); }
function nwFootRender() {
  const f = $("nwFoot"); if (!f || !NE) return;
  const bad = (NE.problems || []).length > 0;
  f.innerHTML = (NE.id ? '<button class="b danger" onclick="nwDel()">Slet</button><button class="b" onclick="nwCopy()">Kopiér</button>' : "") + '<span class="sp"></span>' +
    '<button class="b" onclick="nwBack(true)">Annullér</button>' +
    (NE.published ? `<button class="b" onclick="nwSave(false)">Skjul for kunderne</button><button class="b pri" onclick="nwSave(null)" ${bad ? "disabled" : ""}>Gem</button>`
                  : `<button class="b" onclick="nwSave(null)">Gem kladde</button><button class="b pri" onclick="nwSave(true)" ${bad ? "disabled" : ""}>Udgiv</button>`);
}
async function nwSave(publish) {
  if (publish === false && !confirm("Skjul nyheden for kunderne? Den bliver en kladde, som du kan udgive igen.")) return;
  if (publish === true && !confirm(`Udgiv nyheden? Kunderne ser den ${NE.data.start && NE.data.start > nwLocal(new Date()) ? "fra " + nwDay(NE.data.start).replace(/<[^>]+>/g, "") : "inden for et minut"}.`)) return;
  try {
    const body = JSON.stringify({data: NE.data, publish});
    const r = NE.id ? await api("/api/nyheder/" + NE.id, {method: "PUT", body}) : await api("/api/nyheder", {method: "POST", body});
    toast(r.message); NE.dirty = false; nwBack();
  } catch (e) { toast(e.message, true); }
}
async function nwCopy() {
  if (NE.dirty && !confirm("Kopiér den gemte udgave? Ændringer, du ikke har gemt, kommer ikke med.")) return;
  try { const r = await api(`/api/nyheder/${NE.id}/copy`, {method: "POST"}); toast(r.message); NE.dirty = false; await nwLoad(); nwOpen(r.id); } catch (e) { toast(e.message, true); }
}
async function nwDel() {
  if (!confirm(`Slet nyheden "${NE.data.title}"? Det kan ikke fortrydes.${NE.published ? " Den forsvinder fra guiden inden for et minut." : ""}`)) return;
  try { const r = await api("/api/nyheder/" + NE.id, {method: "DELETE"}); toast(r.message); NE.dirty = false; nwBack(); } catch (e) { toast(e.message, true); }
}
