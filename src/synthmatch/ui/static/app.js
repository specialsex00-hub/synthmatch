// synthmatch UI
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = { inst: null, info: null, job: null, pollTimer: null };

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.detail || `${res.status} ${res.statusText}`);
  return body;
}
const post = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data ?? {}) });

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 5000);
}

function fmtTime(sec) {
  if (!isFinite(sec) || sec < 0) return "-";
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}時間${m}分` : m ? `${m}分${s}秒` : `${s}秒`;
}

const GROUP_NAMES = { "SN-A": "SuperNATURAL Acoustic", "SN-S": "SuperNATURAL Synth", PCM: "PCM Synth" };

// ---------- タブ ----------
function showTab(name) {
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
  $$(".tab").forEach((t) => (t.hidden = t.id !== `tab-${name}`));
  try { localStorage.setItem("tab", name); } catch {}
  if (name === "library") loadPresets();
  if (name === "match") loadHistory();
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

// ---------- 楽器 ----------
async function loadInstruments() {
  const list = await api("/api/instruments");
  const sel = $("#instrument");
  let saved = null;
  try { saved = localStorage.getItem("instrument"); } catch {}
  sel.innerHTML = list.map((i) => `<option value="${esc(i.id)}">${esc(i.name)}${i.error ? "（設定エラー）" : ""}</option>`).join("");
  const fromUrl = new URLSearchParams(location.search).get("instrument");
  const pick = list.find((i) => i.id === fromUrl) || list.find((i) => i.id === saved && !i.error) || list.find((i) => i.type === "hardware" && !i.error) || list[0];
  if (pick) sel.value = pick.id;
  await selectInstrument(sel.value);
}
$("#instrument").addEventListener("change", (e) => selectInstrument(e.target.value));

async function selectInstrument(id) {
  state.inst = id;
  try { localStorage.setItem("instrument", id); } catch {}
  await refreshInfo();
  loadDevices();
  if (!$("#tab-library").hidden) loadPresets();
}

async function refreshInfo() {
  const info = await api(`/api/instruments/${state.inst}`);
  state.info = info;
  $("#inst-file").textContent = info.file;
  $("#inst-settings").innerHTML = Object.entries(info.settings).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
  const pct = info.total ? (info.recorded / info.total) * 100 : 0;
  $("#overall-bar").style.width = `${pct}%`;
  $("#overall-text").textContent = `${info.recorded} / ${info.total} 音色 録音済み`;

  const cats = info.categories.slice().sort((a, b) => a.name.localeCompare(b.name));
  const opts = `<option value="">すべてのカテゴリ</option>` + cats.map((c) => `<option value="${esc(c.name)}">${esc(c.name)}（${c.recorded}/${c.total}）</option>`).join("");
  for (const id of ["#build-category", "#lib-category"]) {
    const sel = $(id), v = sel.value;
    sel.innerHTML = opts;
    sel.value = v;
  }
  const groups = {};
  for (const c of cats) {
    const [g, name] = c.name.includes(":") ? c.name.split(/:(.*)/s) : ["", c.name];
    (groups[g] ||= []).push({ ...c, label: name });
  }
  $("#cat-table").innerHTML = Object.entries(groups).map(([g, list]) => {
    const t = list.reduce((a, c) => a + c.total, 0), r = list.reduce((a, c) => a + c.recorded, 0);
    return `${g ? `<h3 class="cat-group">${esc(GROUP_NAMES[g] || g)} <span class="muted">${r}/${t}</span></h3>` : ""}
      <div class="cat-grid">${list.map((c) => `
        <div class="cat ${c.recorded === c.total ? "complete" : ""}" data-cat="${esc(c.name)}" title="クリックで録音対象に選ぶ">
          <span>${esc(c.label)}</span><span class="num">${c.recorded}/${c.total}</span>
          <div class="bar"><span style="width:${(c.recorded / c.total) * 100}%"></span></div>
        </div>`).join("")}</div>`;
  }).join("");
  $$(".cat").forEach((el) => el.addEventListener("click", () => { $("#build-category").value = el.dataset.cat; updateEstimate(); }));
  updateEstimate();
}

function updateEstimate() {
  if (!state.info) return;
  const cat = $("#build-category").value;
  const c = cat ? state.info.categories.find((x) => x.name === cat) : { total: state.info.total, recorded: state.info.recorded };
  let n = $("#build-overwrite").checked ? c.total : c.total - c.recorded;
  const limit = parseInt($("#build-limit").value);
  if (limit) n = Math.min(limit, c.total);
  const per = state.info.type === "hardware" ? 15 : 0.3;
  $("#build-estimate").textContent = n ? `約 ${n} 音色・${fmtTime(n * per)}` : "すべて録音済み";
}
["#build-category", "#build-limit", "#build-overwrite"].forEach((s) => $(s).addEventListener("input", updateEstimate));

async function loadDevices() {
  const box = $("#devices");
  box.innerHTML = `<span class="muted">確認中…</span>`;
  try {
    const d = await api("/api/devices");
    box.innerHTML = `
      <b>MIDI出力</b><ul>${d.midi_outputs.map((n) => `<li>${esc(n)}</li>`).join("") || "<li class='muted'>なし</li>"}</ul>
      <b>オーディオ入力</b><ul>${d.audio_inputs.map((a) => `<li>${esc(a.name)} <span class="muted">(${a.channels}ch, ${a.sample_rate}Hz)</span></li>`).join("") || "<li class='muted'>なし</li>"}</ul>
      ${d.errors.map((e) => `<p class="muted">${esc(e)}</p>`).join("")}
      <p class="muted small">名前が違う場合は ${esc(state.info?.file ?? "楽器設定")} を編集して、ページを再読み込みしてください。</p>`;
    const has = (list, want) => list.some((n) => n.toLowerCase().includes(want.toLowerCase()));
    const st = $("#conn-status");
    if (state.info?.type === "hardware") {
      const port = state.info.settings["MIDI出力"], dev = state.info.settings["録音デバイス"];
      const midiOk = has(d.midi_outputs, port);
      const audioOk = dev.startsWith("(") || has(d.audio_inputs.map((a) => a.name), dev);
      st.innerHTML = `<span class="tag ${midiOk ? "ok" : "warn"}">MIDI ${midiOk ? "接続OK" : "見つかりません"}</span>
        <span class="tag ${audioOk ? "ok" : "warn"}">録音 ${audioOk ? "接続OK" : "見つかりません"}</span>`;
      $("#devices-box").open = !(midiOk && audioOk);
    } else {
      st.innerHTML = `<span class="tag ok">接続不要</span>`;
    }
  } catch (e) {
    box.textContent = e.message;
  }
}
$("#refresh-devices").addEventListener("click", (e) => { e.preventDefault(); loadDevices(); });

// テスト録音の音色候補
$("#test-preset-q").addEventListener("input", async (e) => {
  const q = e.target.value.trim();
  if (q.length < 2) return;
  const r = await api(`/api/instruments/${state.inst}/presets?q=${encodeURIComponent(q)}&limit=30`);
  $("#test-preset-list").innerHTML = r.presets.map((p) => `<option value="${esc(p.name)}">${esc(p.category)}</option>`).join("");
});

$("#test-btn").addEventListener("click", async () => {
  let preset_id = null;
  const q = $("#test-preset-q").value.trim();
  if (q) {
    const r = await api(`/api/instruments/${state.inst}/presets?q=${encodeURIComponent(q)}&limit=50`);
    const hit = r.presets.find((p) => p.name === q) || r.presets[0];
    if (!hit) return toast("その名前の音色が見つかりません");
    preset_id = hit.id;
  }
  $("#test-result").innerHTML = `<div class="verdict">録音中…</div>`;
  startJob(() => post(`/api/instruments/${state.inst}/test`, { preset_id }));
});

// ---------- ライブラリ録音 ----------
$("#build-btn").addEventListener("click", () => {
  const body = {
    category: $("#build-category").value || null,
    limit: parseInt($("#build-limit").value) || null,
    overwrite: $("#build-overwrite").checked,
  };
  startJob(() => post(`/api/instruments/${state.inst}/build`, body));
});

function rerecord(id, name) {
  if (!confirm(`「${name}」を録音し直しますか？`)) return;
  startJob(() => post(`/api/instruments/${state.inst}/build`, { ids: [id], overwrite: true }));
}

// ---------- 音色ライブラリ ----------
let presetTimer;
async function loadPresets() {
  if (!state.inst) return;
  const params = new URLSearchParams({ limit: 300 });
  if ($("#lib-q").value) params.set("q", $("#lib-q").value);
  if ($("#lib-category").value) params.set("category", $("#lib-category").value);
  if ($("#lib-recorded").value) params.set("recorded", $("#lib-recorded").value);
  const r = await api(`/api/instruments/${state.inst}/presets?${params}`);
  $("#lib-count").textContent = r.total > r.presets.length ? `${r.total} 件中 ${r.presets.length} 件を表示` : `${r.total} 件`;
  $("#lib-rows").innerHTML = r.presets.map((p) => `
    <tr>
      <td>${esc(p.name)}</td>
      <td class="muted">${esc(p.category)}</td>
      <td>${p.recorded ? `<span class="tag ok">済</span>` : `<span class="tag">未</span>`}</td>
      <td>${p.audio ? `<audio controls preload="none" src="${esc(p.audio)}"></audio>` : ""}
        <button class="small" data-rec="${esc(p.id)}" data-name="${esc(p.name)}">${p.recorded ? "録り直す" : "録音"}</button></td>
    </tr>`).join("");
  $$("[data-rec]").forEach((b) => b.addEventListener("click", () => rerecord(b.dataset.rec, b.dataset.name)));
}
["#lib-q", "#lib-category", "#lib-recorded"].forEach((s) =>
  $(s).addEventListener("input", () => { clearTimeout(presetTimer); presetTimer = setTimeout(loadPresets, 250); }));

// ---------- 曲から探す ----------
const drop = $("#song-drop");
const songInput = $("input[name=song]", drop);
function showSongName() {
  const f = songInput.files[0];
  drop.classList.toggle("has-file", !!f);
  $("span", drop).innerHTML = f ? esc(f.name) : `曲ファイルをドロップ、またはクリックして選択<br><small class="muted">mp3 / wav など</small>`;
}
songInput.addEventListener("change", showSongName);
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  if (e.dataTransfer.files.length) { songInput.files = e.dataTransfer.files; showSongName(); }
});

$("#match-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  fd.set("instrument_id", state.inst);
  if (!$("input[name=midi]").files.length) fd.delete("midi");
  $("#match-result").innerHTML = "";
  $("#match-log").textContent = "アップロード中…";
  startJob(() => api("/api/match", { method: "POST", body: fd }));
});

function renderMatch(r) {
  const cands = r.candidates.map((c) => `
    <div class="cand ${c.rank === 1 ? "first" : ""}">
      <div class="rank">${c.rank}</div>
      <h3>${esc(c.name)}</h3>
      <div class="meta">${esc(c.category)} ・ スコア ${c.score}（${c.stage === "rerank" ? "実際に鳴らして比較" : "ライブラリで比較"}）</div>
      <div>
        ${c.audio ? `<audio controls preload="none" src="${esc(c.audio)}"></audio>` : ""}
        ${c.hints.length ? `<ul>${c.hints.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>` : `<p class="muted small">大きな違いは見つかりませんでした</p>`}
      </div>
    </div>`).join("");
  $("#match-result").innerHTML = `
    <div class="card">
      <div class="result-head">
        <div><h2>候補（${esc(r.instrument)}）</h2>
          <span class="muted small"><a href="${esc(r.midi)}" download>MIDI</a> ・ <a href="${esc(r.report_md)}" target="_blank">report.md</a></span></div>
        <div><div class="muted small">取り出したキーボードの音</div><audio controls src="${esc(r.target_audio)}"></audio></div>
      </div>
      <div class="cands">${cands}</div>
      <p class="muted small">スコアは小さいほど近い。上の「取り出したキーボードの音」と聴き比べてください。</p>
    </div>`;
}

async function loadHistory() {
  const rows = await api("/api/history");
  $("#history").innerHTML = rows.map((h) => `
    <li><span>${esc(h.name)}<br><span class="muted small">1位: ${esc(h.top ?? "-")}</span></span>
    <a href="${esc(h.report_md)}" target="_blank">レポート</a></li>`).join("") || `<li class="muted">まだありません</li>`;
}

// ---------- ジョブ ----------
async function startJob(fn) {
  try {
    const job = await fn();
    state.job = job;
    renderJob(job);
    poll();
  } catch (e) {
    toast(e.message);
    if ($("#test-result").textContent === "録音中…") $("#test-result").innerHTML = "";
    $("#match-log").textContent = "";
  }
}

function poll() {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(async () => {
    if (!state.job) return;
    try {
      const job = await api(`/api/jobs/${state.job.id}`);
      state.job = job;
      renderJob(job);
      if (job.status === "running") poll();
      else onJobEnd(job);
    } catch { poll(); }
  }, 800);
}

$$("[data-cancel]").forEach((b) => b.addEventListener("click", async () => {
  if (state.job) await post(`/api/jobs/${state.job.id}/cancel`);
  toast("中止しています（今の音色が終わったら止まります）");
}));

const JOB_LABEL = { build: "録音中", test: "テスト録音中", match: "照合中" };
function renderJob(job) {
  const running = job.status === "running";
  const pill = $("#job-pill");
  pill.hidden = !running;
  pill.textContent = `${JOB_LABEL[job.kind]}${job.kind === "build" && job.total ? ` ${job.progress}/${job.total}` : ""}`;
  $("#build-btn").disabled = $("#test-btn").disabled = $("#match-btn").disabled = running;

  if (job.kind === "build") {
    $("#build-run").hidden = false;
    $("h2", $("#build-run")).textContent = running ? "録音中" : { done: "録音完了", cancelled: "中止しました", error: "エラー" }[job.status];
    $("[data-cancel]", $("#build-run")).hidden = !running;
    const pct = job.total ? (job.progress / job.total) * 100 : 0;
    $("#build-bar").style.width = `${pct}%`;
    const c = job.data.counts || {};
    $("#build-progress").innerHTML = `<b>${job.progress} / ${job.total}</b>（録音 ${c.done || 0}・済 ${c.skipped || 0}${c.silent ? `・<span style="color:var(--danger)">無音 ${c.silent}</span>` : ""}）`;
    $("#build-current").innerHTML = running && job.data.current ? `いま: <b>${esc(job.data.current)}</b>` : "";
    const done = (c.done || 0) + (c.silent || 0);
    const elapsed = (Date.now() / 1000) - job.started;
    $("#build-eta").textContent = running && done ? `残り 約${fmtTime((elapsed / done) * (job.total - job.progress))}` : job.error ? job.error : "";
    $("#build-recent").innerHTML = (job.data.recent || []).map((r) => `
      <li><span class="name">${esc(r.name)} <span class="muted small">${esc(r.category)}</span></span>
      ${r.status === "silent" ? `<span class="tag warn">無音</span>` : r.audio ? `<audio controls preload="none" src="${esc(r.audio)}"></audio>` : ""}</li>`).join("");
  }
  if (job.kind === "match") {
    $("#match-run").hidden = !running && job.status === "done";
    $("h2", $("#match-run")).textContent = running ? "処理中" : { cancelled: "中止しました", error: "エラー", done: "完了" }[job.status];
    $("[data-cancel]", $("#match-run")).hidden = !running;
    $("#match-log").textContent = job.log.join("\n") + (job.error ? `\n\nエラー: ${job.error}` : "");
    $("#match-log").scrollTop = 1e9;
  }
}

function onJobEnd(job) {
  if (job.kind === "test") {
    const r = job.result;
    $("#test-result").innerHTML = job.status === "done"
      ? `<div class="verdict ${r.peak_db < -50 || r.peak_db > -0.5 ? "bad" : "good"}">
          <b>${esc(r.preset)}</b> ・ ピーク ${r.peak_db} dB<br>${esc(r.verdict)}
          <audio controls autoplay src="${esc(r.audio)}"></audio></div>`
      : `<div class="verdict bad">${esc(job.error || "中止しました")}</div>`;
  }
  if (job.kind === "build") {
    refreshInfo();
    if (!$("#tab-library").hidden) loadPresets();
    if (job.status === "error") toast(job.error);
  }
  if (job.kind === "match") {
    if (job.status === "done") { renderMatch(job.result); loadHistory(); }
    else if (job.status === "error") toast(job.error);
  }
}

// ---------- 起動 ----------
(async () => {
  let tab = "record";
  try { tab = localStorage.getItem("tab") || tab; } catch {}
  if (["record", "library", "match"].includes(location.hash.slice(1))) tab = location.hash.slice(1);
  showTab(tab);
  await loadInstruments();
  // ページを開き直したとき、実行中のジョブがあれば表示を再開
  const cur = await api("/api/jobs/current").catch(() => null);
  if (cur && cur.status === "running") { state.job = cur; renderJob(cur); poll(); }
  else if (cur && cur.kind === "match" && cur.status === "done") renderMatch(cur.result);
})();
