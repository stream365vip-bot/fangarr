// Overblik: "Kræver din handling", apps med lampe, dagens tal – og nye premierer (2.0: siden Premierer er fjernet).

// ---------- nye premierer (vises på Overblik, når der er nogen)
let PREM = [];
async function premOpen() {
  const box = $("homePrem");
  if (!box.hidden) { box.hidden = true; return; }
  box.hidden = false; fillRuleSelect("prem_rule", "series");
  $("premList").innerHTML = '<div class="small">Henter fra Seerr …</div>';
  try { const d = await api("/api/premieres?days=21&lang=da"); PREM = d.items.filter(p => !p.exists && !p.following); renderPrem(); }
  catch (e) { $("premList").innerHTML = `<div class="small" style="color:var(--bad)">${esc(e.message)}</div>`; }
  box.scrollIntoView({behavior: "smooth", block: "start"});
}
function renderPrem() {
  $("premList").innerHTML = PREM.length ? '<div class="kl">' + PREM.map((p, i) => `<div class="kr">
    <div class="who"><b>${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener" style="color:inherit">${esc(p.title)}</a>` : esc(p.title)}</b>
      ${p.exists ? '<span class="tag">findes i Sonarr</span>' : ""}${p.following ? '<span class="tag">følges</span>' : ""}
      <div class="small">${esc(p.date)} · ${esc(p.network || "kanal ukendt")} · ${esc((p.genres || []).map(g => GENRE_DA[g] || g).join(", ") || p.type || "")}</div>
      ${p.summary ? `<div class="small">${esc(p.summary)}</div>` : ""}</div>
    <div class="btns">${p.exists ? "" : `<button class="b sm" ${p.tvdb ? "" : 'disabled title="Ikke på TheTVDB endnu – brug Følg"'} onclick="premAdd(${i})">Tilføj nu</button>
      <button class="b sm" ${p.following ? "disabled" : ""} onclick="premFollow(${i})">Følg</button>
      <button class="b sm" onclick="premNo(${i})">Ikke interesseret</button>`}</div></div>`).join("") + "</div>"
    : '<div class="empty">Ingen nye premierer lige nu.</div>';
}
async function premAdd(i) {
  const p = PREM[i];
  if (!confirm(`Tilføj “${p.title}” til Sonarr nu med reglen “${$("prem_rule").selectedOptions[0]?.text}”?`)) return;
  try { const r = await api("/api/premieres/add", {method: "POST", body: JSON.stringify({rule_id: +$("prem_rule").value, tvdb: p.tvdb, title: p.title})});
        toast(`${p.title}: ${r.result}`); p.exists = true; renderPrem(); load(); loadHome(); } catch (e) { toast(e.message, true); }
}
async function premFollow(i) {
  const p = PREM[i];
  try { await api("/api/premieres/follow", {method: "POST", body: JSON.stringify({rule_id: +$("prem_rule").value, title: p.title, date: p.date})});
        toast(`${p.title} følges – den står nu på ventelisten`); p.following = true; renderPrem(); load(); loadHome(); } catch (e) { toast(e.message, true); }
}
async function premNo(i) {
  const p = PREM[i];
  try { await api("/api/premieres/no", {method: "POST", body: JSON.stringify({tmdb: p.tmdb})}); PREM.splice(i, 1); renderPrem();
        if (OV && OV.premieres_new) { OV.premieres_new--; renderHome(); } } catch (e) { toast(e.message, true); }
}
// "Skjul de viste": premiererne tæller ikke længere under Kræver din handling (en ny premiere vises igen)
function premSeen() {
  const ids = (PREM || []).map(p => p.tmdb).filter(Boolean);
  $("homePrem").hidden = true;
  if (OV) { OV.premieres_new = 0; renderHome(); }
  if (ids.length) api("/api/premieres/seen", {method: "POST", body: JSON.stringify({ids})}).catch(() => {});
}

// Tallet ved Drift i menuen: apps, der ikke svarer (rødt), ellers opgaver på huskelisten i dag
function driftBadge() {
  const bad = ((CONN || {}).items || []).filter(c => !c.ok).length, hc = ((OV || {}).huske || {}).count || 0;
  setBadge("drift", bad || hc, !!bad);
}

// ---------- forside
async function loadHome() {
  try { OV = await api("/api/overview"); } catch (e) { return; }
  const t = OV.translator || {}, sh = (OV.sharing || {}).buckets || {};
  setBadge("wait", OV.suggestions, false); setBadge("tr", t.problems, true); setBadge("share", sh.bloker, true);
  setBadge("oensker", (OV.oensker || {}).problems, true);
  const hc = (OV.huske || {}).count || 0; setBadge("huske", hc, false); driftBadge();
  const kb = OV.kunder || {}; setBadge("pay", kb.overdue, true); const iptv = (kb.iptv_due || 0) + (kb.iptv_expired || 0);
  setBadge("cust", (kb.setup || 0) + iptv, !!kb.iptv_expired); setBadge("iptv", iptv, !!kb.iptv_expired);
  if ($("trProbN")) $("trProbN").textContent = t.problems ? ` (${t.problems})` : "";
  S.disk_pct = OV.disk_pct; S.today = OV.today; renderStatus();
  renderHome();
}
function renderHome() {
  if (!OV) return;
  const t = OV.translator || {}, shS = OV.sharing, sh = (shS || {}).buckets || {}, todo = [];
  const add = (n, bad, title, text, action, fn) => todo.push({n, bad, title, text, action, fn});
  const down = ((CONN || {}).items || []).filter(c => !c.ok);
  if (down.length) add(down.length, true, down.length === 1 ? `${esc(down[0].name)} svarer ikke` : "Apps svarer ikke", down.length === 1 ? `Fangarr får ikke svar fra appen (${down[0].detail}). Se Drift › Forbindelser.` : down.map(c => `${c.name}: ${c.detail}`).join(" · "), "Se forbindelser", "go('drift','forbindelser')");
  const appsDown = (APPS || {}).down || [];
  if (appsDown.length) add(appsDown.length, true, appsDown.length === 1 ? `${esc(appsDown[0])} er nede` : "Apps er nede", appsDown.length === 1 ? "Uptime Kuma får ikke svar fra appen." : appsDown.map(esc).join(" · "), "Se apps", "document.getElementById('homeAppsCard').scrollIntoView({behavior:'smooth'})");
  const hu = OV.huske || {};
  (hu.due || []).slice(0, 5).forEach(h => add("📌", h.due < new Date().toISOString().slice(0, 10), esc(h.title),
    (h.server ? h.server + (h.command ? ": " + h.command : "") : h.command || "") || "Fra huskelisten. Tryk Udført, når det er gjort.", "Åbn huskelisten", "go('drift','huskeliste')"));
  if ((hu.count || 0) > 5) add(hu.count - 5, false, "Flere opgaver på huskelisten", "Se dem alle under Drift › Huskeliste.", "Åbn huskelisten", "go('drift','huskeliste')");
  if (OV.errors_24h) add(OV.errors_24h, true, "Fejl det seneste døgn", "Fangarr kunne ikke slå en titel op eller tilføje den. Se detaljerne i loggen.", "Se fejlene", "logPick('fejl');go('log','alle')");
  if (OV.suggestions) add(OV.suggestions, false, OV.suggestions === 1 ? "Forslag venter på godkendelse" : "Forslag venter på godkendelse", "Titler på ventelisten med et muligt match. Tryk Godkend ved det rigtige.", "Åbn ventelisten", "go('wait')");
  if (t.problems) add(t.problems, true, t.problems === 1 ? "Oversættelse er gået galt" : "Oversættelser er gået galt", "Prøv igen, eller opgiv dem, så de vises uden dansk tekst.", "Se problemer", "go('tr','problemer')");
  if (sh.bloker) add(sh.bloker, true, sh.bloker === 1 ? "Bruger kan blokeres" : "Brugere kan blokeres", `Fremmede tv er brugt samtidig med kundens egne. Seneste analyse ${fmt(shS.at)}.`, "Åbn kontodeling", "go('share')");
  if (sh.afgoer) add(sh.afgoer, false, "Brugere skal du selv afgøre", "Fangarr kan ikke se, hvilket sted der er kundens. Vælg kundens sted.", "Åbn kontodeling", "go('share')");
  const kb = OV.kunder || {};
  if (kb.overdue) add(kb.overdue, true, kb.overdue === 1 ? "Kunde mangler at betale" : "Kunder mangler at betale", `${kkr(kb.overdue_kr)} er anmodet for længe siden og ikke markeret som betalt.`, "Åbn opkrævning", "KPF='mangler';go('pay')");
  if (kb.unrequested) add(kb.unrequested, false, kb.unrequested === 1 ? "Kunde er ikke anmodet endnu" : "Kunder er ikke anmodet endnu", `Opkrævningen for ${kb.label} er klar. Kopiér beskeden, send den, og tryk Anmodet.`, "Åbn opkrævning", "KPF='ny';go('pay')");
  if (kb.iptv_due) add(kb.iptv_due, false, kb.iptv_due === 1 ? "IPTV-linje skal fornyes i denne måned" : "IPTV-linjer skal fornyes i denne måned", "Tryk Fornyet på linjen, når den er fornyet hos leverandøren.", "Se linjerne", "KIF='maaned';go('cust','iptv')");
  if (kb.iptv_expired) add(kb.iptv_expired, true, kb.iptv_expired === 1 ? "IPTV-linje står som udløbet" : "IPTV-linjer står som udløbet", "Udløbsdatoen er overskredet. Forny linjen, eller ret datoen, hvis den allerede er fornyet.", "Se linjerne", "KIF='udloebet';go('cust','iptv')");
  const oe = OV.oensker || {};
  if (oe.enabled && oe.problems) add(oe.problems, true, "Seerr-ønsker kræver et kig", oe.braked ? "Bremsen er slået til: for mange ville miste retten til at ønske på én gang. Intet er fjernet." : oe.error ? "Seerr svarer ikke, så Fangarr kan ikke styre, hvem der må ønske." : "Der er noget, Fangarr ikke kan afgøre selv – se listen øverst på siden.", "Åbn Seerr-ønsker", "go('oensker')");
  if (oe.enabled && oe.mode === "prove" && oe.plan) add(oe.plan, false, oe.plan === 1 ? "Ændring i Seerr venter (prøvetilstand)" : "Ændringer i Seerr venter (prøvetilstand)", "Fangarr viser kun, hvad den ville ændre. Se listen igennem, og slå styringen til, når den ser rigtig ud.", "Se ændringerne", "go('oensker')");
  if (kb.setup) add(kb.setup, false, kb.setup === 1 ? "Kunde mangler opsætning" : "Kunder mangler opsætning", "Der mangler cyklus, betalingsmetode eller pris, så de bliver ikke opkrævet endnu.", "Åbn kunder", "KCF='opsaet';go('cust','liste')");
  if (OV.premieres_new) add(OV.premieres_new, false, OV.premieres_new === 1 ? "Ny premiere" : "Nye premierer", "Kommende danske serier, der hverken findes i Sonarr eller følges. Tilføj eller følg dem lige her.", "Vis premierer", "premOpen()");
  if (VER && VER.update) add("↑", false, `Version ${esc(VER.latest)} er klar`, "Kør ./opdater.sh i /opt/fangarr på feeder. Fangarr er væk i få sekunder, og streaming påvirkes ikke.", "", "");
  $("homeWarn").innerHTML = OV.dry_run ? '<div class="warn">Prøvetilstand er slået til. Fangarr logger kun, hvad den ville tilføje. Slå den fra under Regler › Indstillinger.</div>' : "";
  $("homeTodo").innerHTML = `<div class="th"><h2>Kræver din handling</h2><span class="small" style="margin:0">${todo.length ? todo.length + (todo.length === 1 ? " ting" : " ting") : ""}</span></div>` +
    (todo.length ? todo.map(x => `<button class="ti" ${x.fn ? `onclick="${x.fn}"` : "disabled"}><span class="n ${x.bad ? "bad" : ""}">${x.n}</span>
      <span class="tx"><b>${x.title}</b><span>${esc(x.text)}</span></span>${x.action ? `<span class="go"><span>${x.action} </span>→</span>` : ""}</button>`).join("")
      : '<div class="none">Intet kræver din handling lige nu.</div>');
  const tot = OV.today.series + OV.today.movie, near = OV.disk_pct != null && OV.disk_pct >= OV.max_disk_pct - 1;
  const k = [
    ["Tilføjet i dag", tot, `${OV.today.series} serier · ${OV.today.movie} film`],
    ["Diskplads", `<span style="${near ? "color:var(--warn)" : ""}">${OV.disk_pct ?? "?"} %</span>`, `Fangarr stopper ved ${OV.max_disk_pct} %`],
    ["På ventelisten", OV.waiting, OV.suggestions ? `${OV.suggestions} med forslag` : "ingen med forslag"]];
  if (t.enabled && t.ok === false) k.push(["Oversætteren", '<span style="color:var(--bad)">svarer ikke</span>', "se Forbindelser"]);
  if (t.hidden != null) k.push(["Skjult for kunderne", t.hidden, "venter på dansk tekst"]);
  if (t.month_kr != null) k.push(["Oversat denne måned", `${t.month_kr.toLocaleString("da-DK")} kr.`, `prognose ${(t.forecast_kr ?? 0).toLocaleString("da-DK")} kr.${t.budget_kr ? " af " + t.budget_kr.toLocaleString("da-DK") + " kr." : ""}`]);
  if (OV.rescued_24h) k.push(["Hentet for sonarr2", OV.rescued_24h, "afsnit det seneste døgn"]);
  $("homeKpis").innerHTML = k.map(([l, v, s]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${esc(s)}</div></div>`).join("");
  setBadge("home", todo.length, todo.some(x => x.bad));
}
async function loadConn(refresh) {
  if (refresh) $("homeConn").innerHTML = '<span class="small">Tjekker …</span>';
  try { CONN = await api("/api/connections?refresh=" + (refresh ? 1 : 0)); } catch (e) { return; }
  $("homeConn").innerHTML = CONN.items.length ? CONN.items.map(c => `<span class="conn ${c.ok ? "" : "bad"}"><i></i>${esc(c.name)} <span>${c.ok ? "i orden" : esc(c.detail)}</span></span>`).join("")
    : '<span class="small">Ingen apps er sat op i fangarr.env.</span>';
  const bad = CONN.items.filter(c => !c.ok).length; setBadge("conn", bad, true); driftBadge();
  renderHome();
}
const APP_T = {up: "Oppe", down: "Nede", pending: "Tjekker igen", maint: "Vedligehold", unknown: "Ukendt", none: "Ingen lampe"};
async function loadApps(refresh) {
  if (!S || !(S.features || {}).apps) return;
  $("homeAppsCard").style.display = "";
  try { APPS = await api("/api/apps?refresh=" + (refresh ? 1 : 0)); } catch (e) { return; }
  $("homeAppsInfo").innerHTML = APPS.ok ? "Tryk på en app for at åbne den. Lamperne kommer fra Uptime Kuma." : `<span style="color:var(--bad)">${esc(APPS.error || "Uptime Kuma svarer ikke")}</span>`;
  $("homeApps").innerHTML = APPS.groups.length ? APPS.groups.map(g => `<div><h3>${esc(g.name)}</h3><div class="appgrid">` + g.apps.map(a =>
    `<a class="app ${a.state}" ${a.url ? `href="${esc(a.url)}" target="_blank" rel="noopener"` : ""} title="${esc(a.name)}${a.uptime != null ? " – oppetid 24 timer: " + a.uptime + " %" : ""}"><b>${esc(a.name)}</b><span><i></i>${APP_T[a.state] || ""}</span></a>`).join("") + "</div></div>").join("")
    : `<span class="small">Der er ingen apps på statussiden "${esc(APPS.slug)}" i Uptime Kuma endnu.</span>`;
  renderHome();
}
async function loadVersion() {
  try { VER = await api("/api/version"); } catch (e) { return; }
  $("verBox").innerHTML = `Fangarr ${esc(VER.version)}` + (VER.update ? `<span class="upd">Version ${esc(VER.latest)} er klar. Kør ./opdater.sh på feeder.</span>` : (VER.latest ? '<span style="display:block">nyeste version</span>' : ""));
  renderHome();
}

