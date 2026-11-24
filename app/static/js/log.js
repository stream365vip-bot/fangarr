// Log: Tilføjet (det, der er sendt til Sonarr og Radarr) og Alle beslutninger. "Hentet?" viser, om titlen er kommet hjem.
const LOG_PILLS = [["", "Alle"], ["tilføjet", "Tilføjet"], ["findes allerede", "Findes allerede"], ["afvist", "Afvist"], ["venteliste", "Venteliste"], ["fejl", "Fejl"]];
function logPick(v) { logFirst = false; $("logFilter").value = v; renderLog(); }
async function loadLog() {
  try {
    const [rows, sum] = await Promise.all([api("/api/log?limit=500"), api("/api/log/summary")]);
    logRows = rows;
    if (logFirst) { logFirst = false; $("logFilter").value = S.settings.dry_run ? "ville tilføje" : ""; }
    renderLog();
    const order = ["tilføjet", "ville tilføje", "venteliste", "findes allerede", "afvist", "loft nået", "for lidt plads", "udløbet", "fejl"];
    const keys = [...order.filter(k => sum[k]), ...Object.keys(sum).filter(k => !order.includes(k))];
    $("logSummary").innerHTML = '<span class="chip">Sidste døgn:</span>' +
      (keys.length ? keys.map(k => `<span class="chip">${esc(k)} <b>${sum[k]}</b></span>`).join("") : '<span class="chip">intet</span>');
    await loadAdded(); renderLog(); renderAdded();
  } catch (e) { toast(e.message, true); }
}
function renderLog() {
  const f = $("logFilter").value;
  $("logPills").innerHTML = LOG_PILLS.map(([v, l]) => `<button class="${f === v ? "on" : ""}" onclick="logPick('${v}')">${l}<span>${v ? logRows.filter(r => r.decision === v).length : logRows.length}</span></button>`).join("");
  const rows = logRows.filter(r => !f || r.decision === f);
  $("logBody").innerHTML = rows.length ? rows.map(r => { const a = r.decision === "tilføjet" ? addedFor(r) : null; return `<tr>
    <td style="white-space:nowrap;color:var(--muted)">${esc(r.ts.replace("T", " ").slice(0, 16))}</td>
    <td><b>${arrLink(a, esc(r.title))}</b>${r.year ? " (" + r.year + ")" : ""} <span class="small">${r.media === "movie" ? "Film" : "Serie"}</span><div class="small">${esc(r.release)}</div></td>
    <td class="d ${dcls(r.decision)}">${esc(r.decision)}</td>
    <td>${homePill(a)}</td>
    <td>${esc(r.rule)}</td><td>${esc(r.detail)}${r.info ? `<div class="small" style="margin-top:4px">Fundet: ${esc(r.info)}</div>` : ""}</td></tr>`; }).join("")
    : `<tr><td colspan="6" class="empty">${f ? "Intet i loggen med den beslutning." : "Intet i loggen endnu."}</td></tr>`;
}
function renderAdded() {
  const R = (ADDED_ROWS || []).slice(0, 200);
  $("logAdded").innerHTML = R.length ? R.map(a => `<tr><td style="white-space:nowrap;color:var(--muted)">${fmt(a.ts)}</td>
    <td><b>${arrLink(a, esc(a.title))}</b> <span class="small">${a.media === "movie" ? "Film" : "Serie"}</span></td>
    <td>${esc(a.instance)}</td><td class="hs" style="color:var(--muted)">${esc(a.rule)}</td><td>${homePill(a)}</td></tr>`).join("")
    : '<tr><td colspan="5" class="empty">Fangarr har ikke tilføjet noget endnu.</td></tr>';
}
