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
