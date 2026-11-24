// Regler: reglerne, afprøv en titel, prøv en regel på historikken, autobrr-filtre og indstillinger.
function renderRules() {
  const el = $("ruleList");
  if (!S.instances.length) {
    el.innerHTML = '<div class="card warn">Ingen Sonarr/Radarr er sat op. Tjek ARR_INSTANCES og API-nøglerne i fangarr.env.</div>';
    return;
  }
  if (!S.rules.length) { el.innerHTML = '<div class="card empty">Ingen regler endnu. Tryk “+ Ny regel”.</div>'; return; }
  el.innerHTML = S.rules.map((r, i) => {
    const f = [];
    if (list(r.release_contains)) f.push(`Udgivelse med <b>${esc(list(r.release_contains))}</b>`);
    if (list(r.release_excludes)) f.push(`ikke <b>${esc(list(r.release_excludes))}</b>`);
    if (list(r.languages)) f.push(`sprog <b>${esc(r.languages.map(l => LANG_DA[l] || l).join(", "))}</b>`);
    if (list(r.genres_any)) f.push(`genre <b>${esc(r.genres_any.map(g => GENRE_DA[g] || g).join(", "))}</b>`);
    if (list(r.genres_none)) f.push(`ikke <b>${esc(r.genres_none.map(g => GENRE_DA[g] || g).join(", "))}</b>`);
    if (r.year_min || r.year_max) f.push(`år <b>${r.year_min || "…"}–${r.year_max || "…"}</b>`);
    if (r.min_rating) f.push(`rating mindst <b>${r.min_rating}</b>`);
    if (r.resolution) f.push(`kun <b>${esc(r.resolution)}</b>`);
    if (r.released_months) f.push(`udkommet inden for <b>${r.released_months} mdr.</b>`);
    if (list(r.networks_any)) f.push(`kanal <b>${esc(list(r.networks_any))}</b>`);
    const where = `→ <b>${esc(r.instance)}</b> › <b>${esc(r.root_folder)}</b>` +
      (r.media === "series" ? ` · overvåg ${MONITOR_DA[r.monitor] || r.monitor}` : "") +
      ` · mærke <b>${esc(r.tag || "auto-fangarr")}</b>`;
    return `<div class="card rule ${r.active ? "" : "off"}">
      <div><h3>${i + 1}. ${esc(r.name)} <span class="tag ${r.media === "series" ? "s" : "m"}">${r.media === "series" ? "Serier" : "Film"}</span>
        ${r.active ? "" : '<span class="tag">Slået fra</span>'}${r.extra ? '<span class="tag">Ekstra udgave</span>' : ""}${r.wait ? '<span class="tag">Venter på TheTVDB</span>' : ""}${r.allow_missing_genre || r.allow_missing_year ? `<span class="tag">Tillader manglende ${[r.allow_missing_genre && "genre", r.allow_missing_year && "år"].filter(Boolean).join(" og ")}</span>` : ""}</h3>
        <div class="facts">${f.length ? f.join(" · ") : "Ingen krav – alt passer"}</div>
        <div class="facts" style="margin-top:4px">${where}</div></div>
      <div class="btns">
        <button class="b" title="Flyt op" onclick="move(${i},-1)" ${i ? "" : "disabled"}>↑</button>
        <button class="b" title="Flyt ned" onclick="move(${i},1)" ${i < S.rules.length - 1 ? "" : "disabled"}>↓</button>
        <button class="b" onclick="toggleRule(${r.id})">${r.active ? "Slå fra" : "Slå til"}</button>
        <button class="b" onclick="editRule(${r.id})">Redigér</button>
        <button class="b danger" onclick="delRule(${r.id})">Slet</button></div></div>`;
  }).join("");
}

function pickHtml(id, values, labels, chosen) {
  $(id).innerHTML = values.map(v =>
    `<label class="${chosen.includes(v) ? "on" : ""}"><input type="checkbox" value="${esc(v)}" ${chosen.includes(v) ? "checked" : ""}>${esc(labels[v] || v)}</label>`).join("");
  $(id).querySelectorAll("input").forEach(i => i.onchange = () => i.parentElement.classList.toggle("on", i.checked));
}
function picked(id) { return [...$(id).querySelectorAll("input:checked")].map(i => i.value); }
const csv = v => (v || "").split(",").map(x => x.trim()).filter(Boolean);

function mediaChanged(r) {
  const media = $("r_media").value;
  const inst = S.instances.filter(i => i.type === (media === "movie" ? "radarr" : "sonarr"));
  $("r_instance").innerHTML = inst.map(i => `<option>${esc(i.name)}</option>`).join("") || '<option value="">(ingen fundet)</option>';
  if (r && r.instance) $("r_instance").value = r.instance;
  const keepA = r ? (r.genres_any || []) : picked("p_genres_any");
  const keepN = r ? (r.genres_none || []) : picked("p_genres_none");
  const all = [...new Set([...GENRES[media], ...keepA, ...keepN])];
  pickHtml("p_genres_any", all, GENRE_DA, keepA);
  pickHtml("p_genres_none", all, GENRE_DA, keepN);
  $("monitorField").style.display = media === "series" ? "" : "none";
  $("availField").style.display = media === "movie" ? "" : "none";
  $("netLabel").textContent = media === "series" ? "Tv-kanal / netværk – en af" : "Filmselskab – et af";
  loadOptions(r);
}
async function loadOptions(r) {
  const name = $("r_instance").value;
  $("r_root_folder").innerHTML = ""; $("r_quality_profile_id").innerHTML = ""; $("optMsg").textContent = "";
  if (!name) return;
  try {
    const o = await api(`/api/instance/${encodeURIComponent(name)}/options`);
    $("r_root_folder").innerHTML = o.root_folders.map(p => `<option>${esc(p)}</option>`).join("");
    $("r_quality_profile_id").innerHTML = o.profiles.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
    if (r && r.root_folder) $("r_root_folder").value = r.root_folder;
    if (r && r.quality_profile_id) $("r_quality_profile_id").value = String(r.quality_profile_id);
  } catch (e) { $("optMsg").textContent = "Kunne ikke hente mapper/profiler: " + e.message; }
}

function editRule(id) {
  const r = id ? S.rules.find(x => x.id === id) : {active: true, search: true, media: "series", monitor: "latestSeason",
            minimum_availability: "released", tag: "auto-fangarr", release_contains: ["NORDiC", "DANiSH"]};
  editing = id || null;
  $("dlgTitle").textContent = id ? "Redigér regel" : "Ny regel";
  $("dlgErr").textContent = "";
  $("r_name").value = r.name || "";
  $("r_media").value = r.media;
  $("r_active").checked = !!r.active;
  $("r_release_contains").value = (r.release_contains || []).join(", ");
  $("r_release_excludes").value = (r.release_excludes || []).join(", ");
  const langs = r.languages || [];
  pickHtml("p_languages", LANGS, LANG_DA, langs);
  $("r_languages_extra").value = langs.filter(l => !LANGS.includes(l)).join(", ");
  $("r_year_min").value = r.year_min || "";
  $("r_year_max").value = r.year_max || "";
  $("r_min_rating").value = r.min_rating || "";
  $("r_networks_any").value = (r.networks_any || []).join(", ");
  $("r_monitor").value = r.monitor || "latestSeason";
  $("r_minimum_availability").value = r.minimum_availability || "released";
  $("r_tag").value = r.tag || "";
  $("r_search").checked = r.search !== false;
  $("r_wait").checked = !!r.wait;
  $("r_allow_missing_genre").checked = !!r.allow_missing_genre;
  $("r_allow_missing_year").checked = !!r.allow_missing_year;
  $("r_extra").checked = !!r.extra;
  $("r_resolution").value = r.resolution || "";
  $("r_released_months").value = r.released_months || "";
  mediaChanged(r);
  dlg.showModal();
}
async function saveRule() {
  const body = {
    name: $("r_name").value, media: $("r_media").value, instance: $("r_instance").value, active: $("r_active").checked,
    release_contains: csv($("r_release_contains").value), release_excludes: csv($("r_release_excludes").value),
    languages: [...picked("p_languages"), ...csv($("r_languages_extra").value)],
    genres_any: picked("p_genres_any"), genres_none: picked("p_genres_none"),
    year_min: $("r_year_min").value, year_max: $("r_year_max").value,
    min_rating: $("r_min_rating").value.replace(",", "."),
    networks_any: csv($("r_networks_any").value),
    root_folder: $("r_root_folder").value, quality_profile_id: $("r_quality_profile_id").value,
    monitor: $("r_monitor").value, minimum_availability: $("r_minimum_availability").value,
    tag: $("r_tag").value, search: $("r_search").checked, wait: $("r_wait").checked,
    allow_missing_genre: $("r_allow_missing_genre").checked, allow_missing_year: $("r_allow_missing_year").checked,
    extra: $("r_extra").checked, resolution: $("r_resolution").value, released_months: $("r_released_months").value,
  };
  try {
    S.rules = await api(editing ? `/api/rules/${editing}` : "/api/rules", {method: editing ? "PUT" : "POST", body: JSON.stringify(body)});
    dlg.close(); renderRules(); toast("Reglen er gemt");
  } catch (e) { $("dlgErr").textContent = e.message; }
}
async function delRule(id) {
  const r = S.rules.find(x => x.id === id);
  if (!confirm(`Slet reglen “${r.name}”?`)) return;
  S.rules = await api(`/api/rules/${id}`, {method: "DELETE"}); renderRules(); toast("Reglen er slettet");
}
async function toggleRule(id) {
  const r = {...S.rules.find(x => x.id === id)}; r.active = !r.active;
  try { S.rules = await api(`/api/rules/${id}`, {method: "PUT", body: JSON.stringify(r)}); renderRules(); }
  catch (e) { toast(e.message, true); }
}
async function move(i, d) {
  const ids = S.rules.map(r => r.id); [ids[i], ids[i + d]] = [ids[i + d], ids[i]];
  S.rules = await api("/api/rules/order", {method: "POST", body: JSON.stringify({ids})}); renderRules();
}


async function runTest() {
  const p = {media: $("t_media").value, title: $("t_title").value, year: $("t_year").value, release: $("t_release").value};
  $("testResult").innerHTML = '<div class="card empty">Tester…</div>';
  try {
    const r = await api("/api/test", {method: "POST", body: JSON.stringify(p)});
    const cls = r.decision === "ville tilføje" ? "good" : (r.decision === "fejl" ? "bad" : "meh");
    if (r.decision === "venteliste") r.decision = "ville komme på ventelisten";
    const m = r.match;
    $("testResult").innerHTML = `<div class="card result ${cls}">
      <h2>${esc(r.decision[0].toUpperCase() + r.decision.slice(1))}${r.rule ? " – " + esc(r.rule) : ""}</h2>
      <div class="facts">${esc(r.detail)}</div>
      ${m ? `<div class="facts" style="margin-top:10px">Fundet: <b>${esc(m.title)} (${m.year || "?"})</b> · sprog <b>${esc(LANG_DA[m.language] || m.language || "?")}</b>
        · genrer <b>${esc(m.genres.map(g => GENRE_DA[g] || g).join(", ") || "ingen")}</b> · ${r.media === "series" ? "kanal" : "selskab"} <b>${esc(m.network || "?")}</b>
        · rating <b>${m.rating || "ingen"}</b>${m.exists ? " · <b>findes allerede</b>" : ""}</div>` : ""}
      ${r.checks.length ? `<ul class="checks">${r.checks.map(c => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}</div>`
      + (r.extra ? `<div class="card result ${r.extra.decision === "ville tilføje" ? "good" : (r.extra.decision === "fejl" ? "bad" : "meh")}" style="margin-top:10px">
      <h2>Ekstra udgave: ${esc(r.extra.decision)}${r.extra.rule ? " – " + esc(r.extra.rule) : ""}</h2>
      <div class="facts">${esc(r.extra.detail)}</div>
      ${r.extra.match && r.extra.match.released ? `<div class="facts" style="margin-top:6px">Tidligste udgivelsesdato hos TMDb: <b>${esc(r.extra.match.released)}</b></div>` : ""}
      ${r.extra.checks.length ? `<ul class="checks">${r.extra.checks.map(c => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}</div>` : "");
  } catch (e) { $("testResult").innerHTML = `<div class="card result bad">${esc(e.message)}</div>`; }
}


async function loadAutobrr() {
  $("abCards").innerHTML = '<div class="card empty">Henter…</div>';
  try { AB = await api("/api/autobrr"); } catch (e) { $("abCards").innerHTML = ""; toast(e.message, true); return; }
  $("abStatus").innerHTML = !AB.configured
    ? '<div class="warn">autobrr er ikke forbundet. Du kan stadig kopiere filteret og importere det i autobrr (Filters › Import). Vil du have Fangarr til at oprette det selv, så tilføj AUTOBRR_URL og AUTOBRR_APIKEY i fangarr.env.</div>'
    : (AB.error ? `<div class="warn">Kan ikke hente fra autobrr: ${esc(AB.error)}</div>`
                : `<div class="card"><span class="chip live">Forbundet</span> <span class="small">${esc(AB.url)} · Fangarr kaldes på ${esc(AB.fangarr_url)}/webhook/autobrr</span></div>`);
  $("abCards").innerHTML = ["series", "movie"].map(m => {
    const d = AB.defaults[m], words = AB.words[m], exist = AB.filters.find(f => f.name === d.name);
    const hasRules = S.rules.some(r => r.active && r.media === m);
    return `<div class="card">
      <h2>${m === "series" ? "Serier" : "Film"} ${exist ? '<span class="tag">findes i autobrr</span>' : ""}</h2>
      ${hasRules ? "" : `<div class="warn">Der er ingen aktive regler for ${m === "series" ? "serier" : "film"} endnu. Lav dem først.</div>`}
      <div class="grid">
        <div class="field"><label>Filternavn i autobrr</label><input type="text" id="ab_${m}_name" value="${esc(d.name)}"></div>
        <div class="field"><label>Kategorier (trackerens)</label><input type="text" id="ab_${m}_categories" value="${esc(d.categories)}">
          <div class="small">Komma mellem. * = hvad som helst. Tjek trackerens kategorinavne.</div></div>
        ${m === "series" ? `<div class="field"><label>Sæsoner</label><input type="text" id="ab_${m}_seasons" value="${esc(d.seasons)}">
          <div class="small">"1" = kun nye serier (første afsnit og hele sæson 1). Tomt = alle sæsoner.</div></div>` : ""}
      </div>
      <div class="facts" style="margin-top:12px">Udgivelsen skal indeholde: <b>${!hasRules ? "–" : (words.length ? esc(words.join(", ")) : "alt (en regel har intet krav)")}</b></div>
      ${AB.configured && !AB.error ? `<label style="margin-top:14px">Trackere</label>
        <div class="pick" id="ab_${m}_idx">${AB.indexers.map(i => { const on = (d.indexers || []).includes(i.id); return `<label class="${on ? "on" : ""}"><input type="checkbox" value="${i.id}" ${on ? "checked" : ""}>${esc(i.name)}</label>`; }).join("") || '<span class="small">Ingen trackere i autobrr.</span>'}</div>` : ""}
      <div class="row" style="margin:16px 0 0">
        ${AB.configured && !AB.error ? `<button class="b pri" onclick="applyAb('${m}')">${exist ? "Opdatér i autobrr" : "Opret i autobrr"}</button>` : ""}
        <button class="b" onclick="exportAb('${m}')">Vis import-JSON</button>
      </div>
      <div id="ab_${m}_out"></div></div>`;
  }).join("");
  document.querySelectorAll("#abCards .pick input").forEach(i => i.onchange = () => i.parentElement.classList.toggle("on", i.checked));
}
function abOpts(m) {
  const o = {media: m, name: $(`ab_${m}_name`).value, categories: $(`ab_${m}_categories`).value};
  if ($(`ab_${m}_seasons`)) o.seasons = $(`ab_${m}_seasons`).value;
  const box = $(`ab_${m}_idx`); if (box) o.indexers = [...box.querySelectorAll("input:checked")].map(i => +i.value);
  return o;
}
async function applyAb(m) {
  try {
    const r = await api("/api/autobrr/apply", {method: "POST", body: JSON.stringify(abOpts(m))});
    toast(`Filteret "${r.name}" er ${r.action} i autobrr`); loadAutobrr();
  } catch (e) { toast(e.message, true); }
}
async function exportAb(m) {
  try {
    const j = JSON.stringify(await api("/api/autobrr/export", {method: "POST", body: JSON.stringify(abOpts(m))}), null, 2);
    $(`ab_${m}_out`).innerHTML = `<p class="hint" style="margin-top:14px">I autobrr: <b>Filters › Import</b>, indsæt teksten, og gem. Åbn derefter filteret, vælg trackere under <b>General</b>, tjek fanen <b>External</b>, og gem igen.</p>
      <div class="row"><button class="b" id="ab_${m}_copy">Kopiér</button></div><pre id="ab_${m}_json">${esc(j)}</pre>`;
    $(`ab_${m}_copy`).onclick = async () => {
      try { await navigator.clipboard.writeText(j); toast("Kopieret"); }
      catch (e) { const r = document.createRange(); r.selectNodeContents($(`ab_${m}_json`)); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); toast("Teksten er markeret – tryk Ctrl+C"); }
    };
  } catch (e) { toast(e.message, true); }
}


// ---------- prøv regel på historik
let SIM = [];
async function runSim() {
  const id = $("sim_rule").value; if (!id) { toast("Lav en regel først", true); return; }
  $("simBtn").disabled = true; $("simResult").innerHTML = ""; SIM = [];
  try {
    const job = await api("/api/simulate", {method: "POST", body: JSON.stringify({rule_id: +id, days: $("sim_days").value})});
    poll(job, "simProg", j => { $("simBtn").disabled = false; if (j) { SIM = j.results || []; renderSim(); } });
  } catch (e) { $("simBtn").disabled = false; toast(e.message, true); }
}
function renderSim() {
  if (!SIM.length) { $("simResult").innerHTML = '<div class="card empty">Ingen udgivelser at teste i perioden.</div>'; return; }
  const hit = r => r.decision === "ville tilføje" || r.decision === "venteliste";
  const f = $("simFilter").value;
  const rows = SIM.filter(r => !f || (f === "hit") === hit(r));
  const n = SIM.filter(hit).length, ex = SIM.filter(r => r.decision === "findes allerede").length;
  $("simResult").innerHTML = `<div class="chips" style="margin:12px 0"><span class="chip">Testet <b>${SIM.length}</b></span>
      <span class="chip">Ville fange <b>${n}</b></span><span class="chip">Findes allerede <b>${ex}</b></span><span class="chip">Afvist <b>${SIM.length - n - ex}</b></span></div>
    <div class="card" style="padding:0; overflow-x:auto"><table>
    <thead><tr><th>Titel</th><th>Beslutning</th><th>Hvorfor</th></tr></thead><tbody>` +
    rows.map(r => `<tr><td><b>${esc(r.title)}</b>${r.year ? " (" + r.year + ")" : ""}${r.count > 1 ? ` <span class="small">×${r.count}</span>` : ""}
        <div class="small">${esc(r.release)}</div><div class="small">${fmt(r.ts)}</div></td>
      <td class="d ${dcls(r.decision)}">${esc(r.decision === "venteliste" ? "ville vente" : r.decision)}</td>
      <td>${esc(r.detail)}${r.match ? `<div class="small" style="margin-top:4px">Fundet: ${esc(r.match.title)} (${r.match.year || "?"}) · ${esc(LANG_DA[r.match.language] || r.match.language || "sprog ukendt")} · ${esc((r.match.genres || []).map(g => GENRE_DA[g] || g).join(", ") || "ingen genrer")}</div>` : ""}</td></tr>`).join("") +
    "</tbody></table></div>";
}
