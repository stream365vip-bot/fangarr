// Bibliotek: statistik over det, Fangarr har tilføjet (størrelse og hvor meget det er set).
// ---------- statistik
let ST = null;
async function loadStats() {
  $("statNote").innerHTML = S.features.tracearr ? "" : '<div class="warn">Tracearr er ikke forbundet. Tilføj TRACEARR_URL og TRACEARR_APIKEY i fangarr.env – indtil da vises kun størrelser.</div>';
  try { const d = await api("/api/stats"); if (d && d.results) { ST = d; renderStats(); } else if (!ST) $("statBody").innerHTML = '<tr><td colspan="7" class="empty">Tryk “Beregn nu”.</td></tr>'; }
  catch (e) { toast(e.message, true); }
}
async function refreshStats() {
  $("statBtn").disabled = true;
  try { const job = await api("/api/stats/refresh", {method: "POST"});
        poll(job, "statProg", j => { $("statBtn").disabled = false; if (j && j.results) { ST = j; renderStats(); } }); }
  catch (e) { $("statBtn").disabled = false; toast(e.message, true); }
}
function renderStats() {
  const R = ST.results;
  $("statRules").innerHTML = `<div class="small" style="margin:10px 0">Beregnet ${fmt(ST.started)}</div>` + (R.rules.length ? `<div class="card" style="padding:0; overflow-x:auto"><table>
    <thead><tr><th>Regel</th><th class="num">Titler</th><th class="num">GB</th><th class="num">Afspilninger</th><th class="num">Pr. 100 GB</th><th class="num">Aldrig set</th><th class="num">Ingen efter 30 dage</th></tr></thead><tbody>` +
    R.rules.map(g => `<tr><td><b>${esc(g.rule)}</b></td><td class="num">${g.titles}</td><td class="num">${g.gb.toLocaleString("da-DK")}</td>
      <td class="num">${g.plays}</td><td class="num">${(g.plays_per_gb * 100).toFixed(1).replace(".", ",")}</td>
      <td class="num">${g.unwatched}</td><td class="num">${g.stale}</td></tr>`).join("") + "</tbody></table></div>" : "");
  const f = $("statFilter").value;
  const rows = statSorted(R.items.filter(i => !f || (f === "stale" ? i.stale : (i.watch && i.watch.plays === 0))));
  $("statBody").innerHTML = rows.length ? rows.map(i => { const w = i.watch; return `<tr>
    <td><b>${esc(i.title)}</b>${i.year ? " (" + i.year + ")" : ""} <span class="small">${i.media === "movie" ? "Film" : "Serie"}</span>${i.stale ? ' <span class="tag" style="color:var(--warn)">kandidat til oprydning</span>' : ""}</td>
    <td>${esc(i.rule)}</td><td style="white-space:nowrap">${esc(i.added)}</td><td class="num">${i.gb.toLocaleString("da-DK")}</td>
    <td class="num">${w ? w.plays : "?"}</td><td class="num">${w ? w.users : "?"}</td><td class="num">${w ? w.plays_30 : "?"}</td></tr>`; }).join("")
    : '<tr><td colspan="7" class="empty">Ingen titler med Fangarr-mærker i Sonarr/Radarr endnu.</td></tr>';
}


// ---------- statistik: sortering
let ST_SORT = {k: "", dir: -1};
const ST_VAL = {title: i => String(i.title || "").toLowerCase(), rule: i => String(i.rule || "").toLowerCase(), added: i => i.added || "", gb: i => i.gb,
  plays: i => i.watch ? i.watch.plays : -1, users: i => i.watch ? i.watch.users : -1, plays_30: i => i.watch ? i.watch.plays_30 : -1};
function statSort(k) { ST_SORT = {k, dir: ST_SORT.k === k ? -ST_SORT.dir : (["title", "rule"].includes(k) ? 1 : -1)}; if (ST) renderStats(); }
function statSorted(rows) {
  document.querySelectorAll("#bib th.sort").forEach(th => { const on = th.dataset.k === ST_SORT.k; th.classList.toggle("on", on); th.setAttribute("aria-sort", on ? (ST_SORT.dir > 0 ? "ascending" : "descending") : "none");
    th.querySelector("i").textContent = on ? (ST_SORT.dir > 0 ? " ↑" : " ↓") : ""; });
  if (!ST_SORT.k) return rows;
  const v = ST_VAL[ST_SORT.k];
  return rows.slice().sort((a, b) => { const x = v(a), y = v(b); return (x < y ? -1 : x > y ? 1 : 0) * ST_SORT.dir; });
}
