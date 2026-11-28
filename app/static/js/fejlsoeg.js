// Fejlsøg pr. kunde (2.4.0): knappen Fejlsøg på kundekortet og under Kontodeling › Blokeringer.
let FS_ID = null;
function fsOpen(cid) {
  FS_ID = cid; $("fsTitle").textContent = "Fejlsøg";
  $("fsBody").innerHTML = `<p class="hint" style="margin-top:0">Alt, hvad Fangarr kan se om kunden lige nu. Fangarr sender intet – kopiér forslaget til svar, hvis det passer.</p>
    <div class="row" style="margin:0 0 12px"><input type="text" id="fsQ" placeholder="Titel, kunden spørger om (valgfri)" style="flex:1;min-width:180px" onkeydown="if(event.key==='Enter')fsRun()">
      <button class="b pri" onclick="fsRun()">Fejlsøg</button></div><div id="fsOut"><div class="empty">Henter …</div></div>`;
  if (!fsdlg.open) fsdlg.showModal();
  fsRun();
}
async function fsRun() {
  let d; $("fsOut").innerHTML = '<div class="empty">Henter …</div>';
  try { d = await api(`/api/fejlsoeg/${FS_ID}?titel=${encodeURIComponent($("fsQ").value.trim())}`); }
  catch (e) { $("fsOut").innerHTML = `<div class="warn">${esc(e.message)}</div>`; return; }
  $("fsTitle").textContent = "Fejlsøg – " + d.customer.name;
  const st = d.status, H = d.hidden;
  const status = Array.isArray(st) ? st.map(s => `<span class="chip"><span class="dotc ${s.state === "up" ? "g" : s.state === "down" ? "r" : ""}"></span>${esc(s.name)}</span>`).join(" ")
    : st && st.error ? `<span class="small" style="color:var(--warn)">${esc(st.error)}</span>` : '<span class="small">Uptime Kuma er ikke sat op.</span>';
  const play = p => `<tr><td class="hs" style="white-space:nowrap">${lt(p.started)}</td><td><b>${esc(p.title)}</b>${p.percent != null ? `<div class="small">${Math.round(p.percent)} % set</div>` : ""}</td>
    <td class="small">${esc(p.device || "–")}${p.resolution ? " · " + esc(p.resolution) : ""}</td>
    <td class="small">${p.transcode ? `<span style="color:var(--warn)">omkodet</span>${p.video ? " · billede: " + esc(p.video) : ""}${p.audio ? " · lyd: " + esc(p.audio) : ""}${p.reasons.length ? `<div>${p.reasons.map(esc).join("; ")}</div>` : ""}` : '<span style="color:var(--ok)">direkte</span>'}
      ${p.bitrate ? `<div>${(p.bitrate / 1000).toLocaleString("da-DK", {maximumFractionDigits: 1})} Mbit/s</div>` : ""}${p.subs ? `<div>tekster: ${esc(p.subs)}</div>` : ""}</td></tr>`;
  const table = (rows, empty) => rows.length ? `<div style="overflow-x:auto"><table><thead><tr><th>Tid</th><th>Titel</th><th>Enhed</th><th>Afspilning</th></tr></thead><tbody>${rows.map(play).join("")}</tbody></table></div>` : `<div class="small">${empty}</div>`;
  const hid = !d.query ? "" : !H ? '<div class="small">Oversætteren er ikke sat op.</div>' : H.error ? `<div class="small" style="color:var(--warn)">${esc(H.error)}</div>` : H.off ? '<div class="small">Skjul indtil dansk er slået fra – alt vises med det samme.</div>' :
    (H.waiting.length ? H.waiting.map(w => `<div><b>${esc(w.title)}</b> – <span style="color:var(--warn)">skjult, venter på dansk tekst</span>${w.reveal_by ? ` · vises senest ${lt(w.reveal_by)}` : ""}</div>`).join("") : "") +
    (H.shown.length ? H.shown.map(w => `<div><b>${esc(w.title)}</b> – vist ${lt(w.shown_at)}${w.danish ? "" : ' <span style="color:var(--warn)">uden dansk tekst</span>'}</div>`).join("") : "") +
    (!H.waiting.length && !H.shown.length ? `<div class="small">Intet med “${esc(d.query)}” er skjult eller vist den seneste uge.</div>` : "");
  const viol = d.violations.length ? d.violations.map(v => `<div>${lt(v.created)} · <b>${esc(v.rule)}</b> ${blkActTag(v.action)}${v.title ? " · " + esc(v.title) : ""}</div>`).join("") : '<div class="small">Ingen de seneste 7 dage.</div>';
  $("fsOut").innerHTML = `${d.errors.map(e => `<div class="warn" style="margin-bottom:8px">${esc(e)}</div>`).join("")}
    <div class="shbox"><b>Forslag til svar</b> <button class="b sm" onclick="shCopyText($('fsSug').value)">Kopiér</button>
      <textarea id="fsSug" style="min-height:110px;margin-top:8px">${esc(d.suggestion)}</textarea></div>
    <div class="shbox"><b>Status lige nu</b><div style="margin-top:6px">${status}</div></div>
    ${d.query ? `<div class="shbox"><b>“${esc(d.query)}”</b><div style="margin-top:6px">${hid}</div></div>` : ""}
    <div class="shbox"><b>Ser lige nu</b><div style="margin-top:6px">${table(d.now, "Kunden ser ikke noget lige nu.")}</div></div>
    <div class="shbox"><b>Stoppet af Tracearr</b> <span class="small">– seneste 7 dage</span><div style="margin-top:6px">${viol}</div></div>
    <div class="shbox"><b>Seneste afspilninger</b><div style="margin-top:6px">${d.tracearr ? table(d.plays, "Ingen afspilninger fundet.") : '<div class="small">Tracearr er ikke sat op.</div>'}</div></div>`;
}
