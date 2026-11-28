// Drift: forbindelser til apps (render i overblik.js › loadConn) og hentegrænsen hos trackeren.
// Hentegrænse (1.22.0): hvad Fangarr søger igen lige nu, og hvad der er sket de sidste 30 dage
async function loadGrab() {
  const el = $("grabInfo");
  if (!el) return;
  try {
    const d = await api("/api/hentegraense");
    if (!d.enabled) { el.textContent = "Slået fra (GRAB_RETRY=false i fangarr.env, eller sonarr2 er ikke forbundet)."; return; }
    const group = rows => { const g = {}; rows.forEach(r => (g[r.series] = g[r.series] || []).push(r)); return g; };
    const word = {hentet: "hentet", opgivet: "opgivet – søg selv", droppet: "ikke længere overvåget"};
    const w = group(d.waiting), r = group(d.recent);
    let h = `<b>Slået til:</b> ${d.batch} afsnit hvert ${d.minutes}. minut, giver op efter ${d.hours} timer.`;
    h += Object.keys(w).length
      ? "<br><b>Søges igen lige nu:</b><br>" + Object.entries(w).map(([t, x]) => `${esc(t)}: ${x.map(e => esc(e.label)).join(", ")}`).join("<br>")
      : "<br>Intet venter lige nu.";
    if (Object.keys(r).length) h += "<br><b>Seneste 30 dage:</b><br>" + Object.entries(r).map(([t, x]) =>
      `${esc(t)}: ${x.map(e => esc(e.label) + " (" + (word[e.status] || esc(e.status)) + ")").join(", ")}`).join("<br>");
    el.innerHTML = h;
  } catch (e) { el.textContent = "Kunne ikke hente status for hentegrænsen."; }
}

// ---------- Sikkerhed (2.3.0): adresser uden Authelia og åbne porte – Fangarr ændrer intet
const SIK_ST = {ok: ["ok", "i orden"], fund: ["bad", "fund"], undtaget: ["", "undtaget"], "ingen-svar": ["warn", "svarer ikke"]};
let SIK = null;
async function loadSik() {
  try { SIK = await api("/api/sikkerhed"); } catch (e) { $("sikInfo").textContent = e.message; return; }
  const R = SIK.result || {}, run = R.running;
  $("sikBtn").disabled = !!run; $("sikBtn").textContent = run ? "Tjekker …" : "Tjek nu";
  if (run) setTimeout(() => { if (TAB === "drift" && SUB.drift === "sikkerhed") loadSik(); }, 5000);
  if (!R.finished) { $("sikInfo").innerHTML = run ? "Tjekket kører – portene tager et par minutter." : "Ikke tjekket endnu. Tryk Tjek nu (kører også selv hver mandag kl. 3)."; $("sikPorts").innerHTML = $("sikUrls").innerHTML = ""; return; }
  const fund = R.findings || 0;
  $("sikInfo").innerHTML = `Seneste tjek ${fmt(R.finished)}${R.manual ? " (i hånden)" : ""} – ` +
    (fund ? `<b style="color:var(--bad)">${fund} fund</b>` : '<b style="color:var(--ok)">ingen fund</b>') +
    (run ? " · kører igen nu …" : "") + ((R.errors || []).length ? `<div class="warn">${R.errors.map(esc).join("<br>")}</div>` : "");
  $("sikPorts").innerHTML = (R.hosts || []).map(h => `<div class="card"><h2>${esc(h.name)} <span class="small">${esc(h.ip)}</span></h2>
    <div class="small">${h.reachable ? `Åbne porte udefra: <b>${h.open.join(", ") || "ingen"}</b> (${h.scanned.toLocaleString("da-DK")} porte tjekket på ${String(h.seconds).replace(".", ",")} sek.)` : '<span style="color:var(--warn)">Kunne ikke nås – ingen porte svarede.</span>'}</div>
    ${h.unexpected.length ? `<div class="warn">Ikke på listen: <b>${h.unexpected.join(", ")}</b> – find ud af, hvilken app der har åbnet porten.</div>` : ""}
    ${h.reachable && h.closed.length ? `<div class="small" style="color:var(--warn)">Forventet åben, men lukket: ${h.closed.join(", ")} (er appen nede?)</div>` : ""}</div>`).join("");
  const U = (R.urls || []).slice().sort((a, b) => (a.status === "fund" ? 0 : 1) - (b.status === "fund" ? 0 : 1));
  $("sikUrls").innerHTML = U.length ? `<div class="card" style="padding:0; overflow-x:auto"><table><thead><tr><th>App</th><th>Adresse</th><th>Resultat</th></tr></thead><tbody>` +
    U.map(u => { const [c, l] = SIK_ST[u.status] || ["", u.status];
      return `<tr><td><b>${esc(u.app)}</b></td><td class="small">${esc(u.url)}</td><td><span class="pill ${c}">${l}</span> <span class="small">${esc(u.text)}</span></td></tr>`; }).join("") + "</tbody></table></div>"
    : '<div class="empty">Ingen adresser at tjekke – Apps-listen (Indstillinger › Apps og widget) er tom.</div>';
}
async function sikRun() {
  try { await api("/api/sikkerhed/tjek", {method: "POST"}); toast("Tjekket er startet"); setTimeout(loadSik, 800); } catch (e) { toast(e.message, true); }
}
function sikCfg() {
  const c = (SIK || {}).config || {};
  kForm("Sikkerhedstjek – indstillinger", [
    {k: "hosts", label: "Servere og porte, der skal være åbne", type: "textarea", hint: "Én server pr. linje: navn, offentlig adresse og de porte, der skal være åbne udefra. Fx <code>feeder 65.21.142.239 22,80,443,56881</code>"},
    {k: "ports", label: "Porte der tjekkes", hint: "1-65535 = alle. Kortere liste = hurtigere, men en ny ukendt port opdages måske ikke."},
    {k: "public", label: "Apps, der må være åbne uden Authelia", type: "textarea", hint: "Appens navn som i Apps-listen, adskilt af komma (fx plex, seerr, guide)."},
    {k: "open_api", label: "Apps med bevidst åben /api", type: "textarea", hint: "Fx tracearr (mobilappen) og tautulli (Fangarr bruger den). Ret kun, hvis du har besluttet det."},
  ], c, async v => { await api("/api/sikkerhed/indst", {method: "PUT", body: JSON.stringify(v)}); toast("Gemt – gælder fra næste tjek"); loadSik(); });
}

// ---------- Trackere (2.3.0): seedingkrav og hit-and-run ud fra qBittorrent
const gb = b => b == null ? "–" : (b / 1e9 >= 1000 ? (b / 1e12).toLocaleString("da-DK", {maximumFractionDigits: 2}) + " TB" : (b / 1e9).toLocaleString("da-DK", {maximumFractionDigits: 1}) + " GB");
let TRK = null;
async function loadTrk(refresh) {
  try { TRK = await api("/api/trackere?refresh_now=" + (refresh ? 1 : 0)); } catch (e) { $("trkInfo").textContent = e.message; return; }
  if (!TRK.enabled) { $("trkInfo").innerHTML = '<div class="warn">Fangarr har intet login til qBittorrent. Tilføj QBIT_URL, QBIT_USER og QBIT_PASS i fangarr.env (se installationsguiden).</div>'; $("trkList").innerHTML = ""; return; }
  $("trkInfo").innerHTML = (TRK.error ? `<div class="warn">${esc(TRK.error)}</div>` : "") + (TRK.at ? `Hentet fra qBittorrent ${fmt(TRK.at)} · ${TRK.total} torrents i alt. Opdateres hvert 15. minut.` : "");
  const G = TRK.groups || [];
  $("trkList").innerHTML = G.map(g => { const r = g.rule, krav = r.hours || r.ratio ? `${r.hours ? r.hours.toLocaleString("da-DK") + " timer" : ""}${r.hours && r.ratio ? " eller " : ""}${r.ratio ? "ratio " + String(r.ratio).replace(".", ",") : ""}` : "intet krav";
    const row = t => `<tr><td>${esc(t.name)}<div class="small">${esc(t.category || "")}</div></td><td>${esc(t.state)}</td><td class="num">${String(t.seed_h).replace(".", ",")} t</td><td class="num">${String(t.ratio).replace(".", ",")}</td><td class="num">${t.progress} %</td></tr>`;
    return `<div class="card"><h2>${esc(g.name)}</h2>
    <div class="small">${g.count} ${g.count === 1 ? "torrent" : "torrents"} · ${gb(g.size)} · uploadet ${gb(g.uploaded)} · ratio ${g.ratio == null ? "–" : String(g.ratio).replace(".", ",")}
      ${g.up_1 != null ? " · sidste døgn " + gb(g.up_1) : ""}${g.up_7 != null ? " · sidste 7 dage " + gb(g.up_7) : ""}</div>
    <div class="small">Krav: ${krav}${r.alert ? "" : " – <i>ingen besked</i>"} · ${g.pending_n ? `<b>${g.pending_n}</b> har ikke opfyldt kravet endnu` : "alle har opfyldt kravet"}</div>
    ${g.stalled.length ? `<div class="warn"><b>${g.stalled.length} står stille før kravet</b> – start dem igen i qBittorrent, ellers risikerer du hit-and-run.</div>` : ""}
    ${g.issues.length ? `<div class="small" style="color:var(--warn)">${g.issues.length} med tracker-fejl (mærket issue).</div>` : ""}
    ${g.pending_n ? `<details style="margin-top:8px"><summary class="small">Vis dem, der ikke har opfyldt kravet</summary><div style="overflow-x:auto"><table><thead><tr><th>Torrent</th><th>Tilstand</th><th class="num">Seedet</th><th class="num">Ratio</th><th class="num">Hentet</th></tr></thead><tbody>${g.pending.map(row).join("")}</tbody></table></div>${g.pending_n > g.pending.length ? `<div class="small">… og ${g.pending_n - g.pending.length} mere</div>` : ""}</details>` : ""}</div>`; }).join("")
    + ((TRK.gone || []).length ? `<div class="card"><h2>Fjernet før kravet (30 dage)</h2><div class="small">Torrents, der forsvandt fra qBittorrent, før de havde seedet nok. Hold øje med trackerens hit-and-run-liste.</div><table><tbody>${TRK.gone.map(x => `<tr><td>${esc(x.tracker)}</td><td>${esc(x.name)}</td><td class="num">${String(x.seed_h).replace(".", ",")} t · ratio ${String(x.ratio).replace(".", ",")}</td><td class="small">${fmt(x.gone_at)}</td></tr>`).join("")}</tbody></table></div>` : "");
}
function trkRules() {
  const R = (TRK || {}).rules || {}, f = [], v = {};
  Object.entries(R).filter(([n]) => n !== "Andet").forEach(([n, r]) => {
    f.push({k: n + "_h", label: `${n}: timers seeding`, type: "int"}, {k: n + "_r", label: `${n}: eller ratio`, type: "money"}, {k: n + "_a", label: `${n}: besked ved risiko`, type: "check"});
    v[n + "_h"] = r.hours; v[n + "_r"] = String(r.ratio).replace(".", ","); v[n + "_a"] = r.alert; });
  kForm("Trackernes krav", f, v, async o => { const b = {};
    Object.keys(R).filter(n => n !== "Andet").forEach(n => b[n] = {hours: Number(String(o[n + "_h"]).replace(",", ".")), ratio: Number(String(o[n + "_r"]).replace(",", ".")), alert: o[n + "_a"]});
    await api("/api/trackere/regler", {method: "PUT", body: JSON.stringify(b)}); toast("Gemt"); loadTrk(1); });
}
