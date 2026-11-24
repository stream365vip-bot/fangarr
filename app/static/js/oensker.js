// Seerr-ønsker: hvem der må ønske i Seerr (pakker, enkeltkøb, familie) og ændringerne i Seerr.
// ---------- siden Seerr-ønsker (1.23.0)
let OE = null;
const OE_MODES = [["fra", "Fra", "Fangarr rører ikke Seerr."], ["prove", "Prøvetilstand", "Fangarr viser kun, hvad den ville ændre i Seerr."], ["til", "Til", "Fangarr retter Seerr for alvor."]];
async function loadOensker() { try { OE = await api("/api/oensker/state"); } catch (e) { toast(e.message, true); return; } renderOensker(); }
function renderOensker() {
  const d = OE, st = d.state || {}, s = d.settings, mode = s.mode;
  if (!d.enabled) {
    $("oeHead").innerHTML = '<div class="warn">Seerr er ikke sat op. Tilføj SEERR_URL og SEERR_APIKEY i fangarr.env (se LÆSMIG).</div>';
    ["oeWarn", "oePlan", "oeFam"].forEach(i => $(i).innerHTML = ""); $("oeCan").innerHTML = $("oeAcc").innerHTML = $("oeLog").innerHTML = ""; return;
  }
  $("oeHead").innerHTML = `<div class="card"><div class="row" style="justify-content:space-between;align-items:flex-start">
      <div><b>Styring af Seerr</b><div class="small">${OE_MODES.find(m => m[0] === mode)[2]} ${st.at ? "Senest gennemgået " + fmt(st.at) + "." : "Ikke gennemgået endnu."}${mode === "til" && st.at ? ` ${st.applied || 0} ${st.applied === 1 ? "ændring" : "ændringer"} lavet ved seneste gennemgang.` : ""}</div></div>
      <div class="pills" style="margin:0">${OE_MODES.map(([k, l]) => `<button class="${mode === k ? "on" : ""}" onclick="oeMode('${k}')">${l}</button>`).join("")}</div></div></div>`;
  const w = [];
  if (st.error) w.push(`<div class="warn"><b>Seerr svarer ikke.</b> ${esc(st.error)}</div>`);
  if (st.braked) w.push('<div class="warn"><b>Bremsen er slået til.</b> For mange ville miste retten til at ønske på én gang, så Fangarr har ikke fjernet nogen. Tjek listen herunder. Er den rigtig, kan du hæve bremsen under Indstillinger.</div>');
  (st.problems || []).forEach(x => w.push(`<div class="warn">${esc(x)}</div>`));
  (st.unclear || []).forEach(x => w.push(`<div class="warn"><a href="#" onclick="kOpen(${x.customer_id});return false">${esc(x.name)}</a> har tjenesten Ekstra ønsker (${kkr(x.price)}/md.), men Fangarr kan ikke se, hvilken pakke og konto det er: ${esc(x.why)}. Vælg pakken på kundekortet under Seerr-ønsker ud for den rigtige konto – den gamle tjeneste bliver til pakken, uden tillæg, når prisen passer.</div>`));
  (st.errors || []).forEach(x => w.push(`<div class="warn">${esc(x)}</div>`));
  $("oeWarn").innerHTML = w.join("");
  const plan = st.plan || [];
  $("oePlanTitle").textContent = mode === "prove" ? `Det ville Fangarr ændre i Seerr (${plan.length})` : mode === "til" ? "Ændringer ved seneste gennemgang" : "Ændringer i Seerr";
  $("oePlan").innerHTML = mode === "fra" ? '<div class="small">Styringen er slået fra.</div>' : plan.length ? `<div class="card" style="padding:0;overflow-x:auto"><table>
      <thead><tr><th>Seerr-bruger</th><th>Nu</th><th>Bliver</th><th class="hs">Grundlag</th></tr></thead><tbody>${plan.map(x => `<tr>
        <td><b>${x.customer_id ? `<a href="#" onclick="kOpen(${x.customer_id});return false" style="color:inherit">${esc(x.name)}</a>` : esc(x.name)}</b></td>
        <td class="small">${esc(x.from)}</td><td>${x.remove ? '<span class="pill bad">kan ikke ønske</span>' : esc(x.to)}${x.auto_off ? ' <span class="small">· Auto-anmod slås fra</span>' : ""}</td><td class="small hs">${esc(x.basis)}</td></tr>`).join("")}</tbody></table></div>`
    : '<div class="small">Seerr passer med Fangarr – der er intet at ændre.</div>';
  const can = st.can || [];
  $("oeCan").innerHTML = can.length ? can.map(x => `<tr><td><b>${x.customer_id ? `<a href="#" onclick="kOpen(${x.customer_id});return false" style="color:inherit">${esc(x.name)}</a>` : esc(x.name)}</b></td>
      <td>${esc(x.limits)}</td><td class="small hs">${esc(x.basis)}</td><td class="small hs">${x.usage ? ksUnits(x.usage.film, x.usage.tv) || "intet" : "–"}</td></tr>`).join("")
    : '<tr><td colspan="4" class="empty">Ingen.</td></tr>';
  $("oeAcc").innerHTML = d.accounts.length ? d.accounts.map(x => `<tr><td><a href="#" onclick="kOpen(${x.customer_id});return false" style="color:inherit"><b>${esc(x.customer)}</b></a></td><td>${esc(x.account)}</td>
      <td>${x.package ? `${esc(x.package)} <span class="small">${kkr(x.price)}/md.</span>` : '<span class="small">ingen</span>'}${x.pending ? `<div class="small" style="color:var(--info)">${x.pending.name ? "skifter til " + esc(x.pending.name) : "stopper"} ${kDay(x.pending.date)}</div>` : ""}</td>
      <td class="hs">${ksUnits(x.film_left, x.tv_left) || '<span class="small">–</span>'}</td></tr>`).join("")
    : '<tr><td colspan="4" class="empty">Ingen kunder har en pakke eller købte ønsker endnu. Vælg det på kundekortet.</td></tr>';
  $("oeFam").innerHTML = d.family.length ? `<div class="card">${d.family.map(f => `<div style="margin:2px 0"><a href="#" onclick="kOpen(${f.customer_id});return false">${esc(f.name)}</a> <span class="small">${f.accounts.length ? esc(f.accounts.join(", ")) : "ingen Plex-konto koblet"}</span></div>`).join("")}</div>`
    : '<div class="small">Ingen kunder er mærket Egen (familie). Sæt Type til Egen på kundekortet, så kan de ønske ubegrænset.</div>';
  $("oe_untouchable").value = s.untouchable || ""; $("oe_price_film").value = s.price_film; $("oe_price_tv").value = s.price_tv; $("oe_brake").value = s.brake;
  const sh = d.shop || {};
  $("oe_shop").checked = !!s.shop;
  $("oeShopInfo").innerHTML = !sh.token ? '<div class="warn"><b>Nøglen mangler.</b> Køb i guiden kræver <code>NYT_TOKEN</code> i fangarr.env og samme nøgle hos guiden – se LÆSMIG › Køb i guiden.</div>'
    : sh.open ? '<div class="small" style="color:var(--ok)">Åbent – kunderne kan vælge pakke og købe ønsker i guiden.</div>'
    : !s.shop ? '<div class="small">Lukket – slå det til herunder.</div>'
    : '<div class="small" style="color:var(--warn)">Slået til, men lukket, fordi styringen af Seerr ikke står på Til.</div>';
  const secs = d.sections || [];
  $("oe_shop_section").innerHTML = '<option value="">Find selv afsnittet om Seerr</option>' +
    (s.shop_section && !secs.some(x => x.id === s.shop_section) ? `<option value="${esc(s.shop_section)}" selected>${esc(s.shop_section)} (findes ikke i guiden)</option>` : "") +
    secs.map(x => `<option value="${esc(x.id)}" ${x.id === s.shop_section ? "selected" : ""}>${esc(x.title)}</option>`).join("");
  $("oePkgs").innerHTML = s.packages.map(p => `<tr><td><b>${esc(p.name)}</b></td><td class="num"><input type="number" min="0" id="oep_${p.key}_film" value="${p.film}" style="width:80px"></td>
      <td class="num"><input type="number" min="0" id="oep_${p.key}_tv" value="${p.tv}" style="width:80px"></td><td class="num"><input type="text" inputmode="decimal" id="oep_${p.key}_price" value="${p.price}" style="width:90px"></td></tr>`).join("");
  $("oeLog").innerHTML = d.log.length ? d.log.map(l => `<tr><td style="white-space:nowrap;color:var(--muted)">${fmt(l.ts)}</td><td>${l.customer_id ? `<a href="#" onclick="kOpen(${l.customer_id});return false" style="color:inherit">${esc(l.text)}</a>` : esc(l.text)}</td></tr>`).join("")
    : '<tr><td class="empty">Intet endnu.</td></tr>';
}
async function oeMode(m) {
  const plan = ((OE.state || {}).plan || []).length;
  if (m === "til" && !confirm(`Slå styringen af Seerr til?\n\nFangarr retter nu Seerr for alvor${plan ? ` – de ${plan} ændringer på listen bliver lavet med det samme` : ""}. Admin og konti under Rør ikke røres aldrig.`)) return;
  try { await api("/api/oensker/settings", {method: "PUT", body: JSON.stringify({mode: m})}); toast(m === "til" ? "Styringen er slået til" : m === "prove" ? "Prøvetilstand" : "Styringen er slået fra"); await oeSync(true); }
  catch (e) { toast(e.message, true); }
}
async function oeSave() {
  const packages = OE.settings.packages.map(p => ({key: p.key, film: $(`oep_${p.key}_film`).value, tv: $(`oep_${p.key}_tv`).value, price: $(`oep_${p.key}_price`).value}));
  try { await api("/api/oensker/settings", {method: "PUT", body: JSON.stringify({untouchable: $("oe_untouchable").value, price_film: $("oe_price_film").value,
      price_tv: $("oe_price_tv").value, brake: $("oe_brake").value, packages, shop: $("oe_shop").checked, shop_section: $("oe_shop_section").value})}); toast("Gemt"); await oeSync(true); }
  catch (e) { toast(e.message, true); }
}
async function oeSync(quiet) {
  const b = $("oeSyncBtn"); b.disabled = true; b.textContent = "Gennemgår …";
  try { OE = await api("/api/oensker/sync", {method: "POST"}); renderOensker(); if (!quiet) toast("Seerr er gennemgået"); loadHome(); }
  catch (e) { toast(e.message, true); }
  finally { b.disabled = false; b.textContent = "Gennemgå Seerr nu"; }
}
