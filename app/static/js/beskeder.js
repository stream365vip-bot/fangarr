// Beskeder: skabelonen til opkrævningen (felterne ligger i Kunders indstillinger, K.settings) og nyheden i opkrævningen.
// ---------- nyhed til kunderne (flettes ind med {nyhed} – hver kunde får den én gang)
function renderNews() {
  const n = K && K.news, info = n ? `Nyhed i opkrævningen: sendt til ${n.sent} af ${n.total} kunder.` : "";
  if ($("payNewsInfo")) $("payNewsInfo").innerHTML = info ? `${esc(info)} <a href="#besk/nyhed" onclick="go('besk','nyhed');return false">Ret nyheden</a>` : "";
  $("payNewsState").textContent = n ? info : "Ingen nyhed lige nu.";
  if (document.activeElement !== $("payNewsText")) $("payNewsText").value = n ? n.text : "";
  $("payNewsFresh").style.display = $("payNewsDel").style.display = n ? "" : "none";
  $("payNewsHelp").innerHTML = n ? `Lagt ind ${kDay(n.created)}. <b>Gem</b> retter teksten – dem, der har fået nyheden, får den ikke igen. <b>Send til alle igen</b> starter forfra, så alle får den med næste opkrævning.` : "";
}
async function newsSave(fresh) {
  if (fresh && !confirm("Send nyheden til alle igen?\n\nAlle kunder får den med deres næste opkrævning – også dem, der allerede har fået den.")) return;
  try { K.news = await api("/api/kunder/news", {method: "PUT", body: JSON.stringify({text: $("payNewsText").value, fresh})}); toast("Nyheden er gemt"); renderNews(); }
  catch (e) { toast(e.message, true); }
}
async function newsDel() {
  if (!confirm("Fjern nyheden?\n\nDen kommer ikke med i flere beskeder. Kunder, der ikke har fået den endnu, får den ikke.")) return;
  try { await api("/api/kunder/news", {method: "DELETE"}); K.news = null; $("payNewsText").value = ""; toast("Nyheden er fjernet"); renderNews(); }
  catch (e) { toast(e.message, true); }
}
