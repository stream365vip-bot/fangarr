// Start: hentes sidst, når alle de andre filer er læst.
async function init() {
  fillDescriptions();          // "Bruges til" og "Sådan bruger du siden" fra hjaelp.js
  await load();
  if (!S) return;
  const [tab, sub] = location.hash.replace("#", "").split("/");
  go(tab || "home", sub);
  loadVersion();
  if (TAB !== "home") { loadHome(); loadConn(0); loadApps(0); }
  // hvert minut: tallene i menuen og "Kræver din handling" (forbindelserne gemmes 60 sek. i Fangarr)
  setInterval(() => { if (!document.hidden) { loadHome(); loadConn(0); if (TAB === "home") loadApps(0); } }, 60000);
  setInterval(loadVersion, 3 * 3600 * 1000);
}
init();
