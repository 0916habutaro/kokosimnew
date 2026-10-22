// 正式な画面（game_definition.md §9、ADR-044）。
// データは Python の ScreenApi（window.pywebview.api）からだけ読む。
// 日付を進めている間は progress() 以外を呼ばない。
"use strict";

const STOP_MESSAGES = {
  big_scene: "大きな場面の前で止まりました",
  match_day: "次の試合日になりました",
  competition_end: "大会が終わりました",
};
const DOW = ["日", "月", "火", "水", "木", "金", "土"];
const SEGMENTS = [["", "すべて"], ["spring", "春"], ["summer", "夏"], ["autumn", "秋"]];
const LEVELS = [["", "すべて"], ["national", "全国"], ["regional", "地区"], ["local", "都道府県"]];

const state = {
  page: "today",
  header: null,
  menu: [],
  busy: false,
  competitions: { filter: { year: "", segment: "", level: "", status: "" }, view: null },
  matches: { date: "", detail: null },
  bracket: null,
  zoom: 1,
};

const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function svgEl(tag, attrs = {}, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function dotDate(iso) {
  return iso ? iso.replaceAll("-", ".") : "";
}

function slashDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${iso.slice(5).replace("-", "/")}（${DOW[d.getDay()]}）`;
}

function showToast(message, isError = false) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.hidden = true; }, 5000);
}

// Python を呼ぶ（日付を進めている間は呼ばない）
async function call(name, ...args) {
  if (state.busy) return null;
  const result = await api()[name](...args);
  if (result && result.error) {
    showToast(result.error, true);
    return null;
  }
  return result;
}

// ---- 上の帯とメニュー ----

function renderHeader(header) {
  state.header = header;
  const d = new Date(header.date);
  $("date").textContent = dotDate(header.date);
  $("dow").textContent = `（${DOW[d.getDay()]}）`;
  $("date-sub").textContent = `${header.school_year}年度 ・ 今日の試合 ${header.today_match_count}試合`;
}

function renderMenu() {
  const menu = $("menu");
  menu.replaceChildren();
  for (const item of state.menu) {
    if (item.id === "saves") menu.append(Object.assign(document.createElement("div"), { className: "gap" }));
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = item.label;
    button.className = item.id === state.page ? "on" : "";
    button.addEventListener("click", () => showPage(item.id));
    menu.append(button);
  }
}

function showPage(page) {
  if (state.busy) return;
  state.page = page;
  renderMenu();
  renderPage();
}

function renderPage() {
  const content = $("content");
  content.replaceChildren();
  if (state.page === "today") return renderToday(content);
  if (state.page === "competitions") return renderCompetitions(content);
  if (state.page === "matches") return renderMatches(content);
  const title = (state.menu.find((m) => m.id === state.page) || {}).label || "";
  content.innerHTML = `<div class="head"><h2>${esc(title)}</h2></div>
    <div class="scroll"><div class="empty">この画面はこれから作ります。</div></div>`;
}

// ---- 今日（次のPRで作り込む） ----

function renderToday(content) {
  const header = state.header;
  const rows = header.active_competitions.slice(0, 12).map((row) =>
    `<tr><td>${esc(row.name)}</td><td class="muted">${row.next_date ? "次の試合 " + slashDate(row.next_date) : ""}</td></tr>`).join("");
  content.innerHTML = `<div class="head"><h2>今日</h2></div>
    <div class="scroll">
      <div class="panel"><h3>今日の全国の試合</h3><div class="big">${header.today_match_count}<small class="muted" style="font-size:16px"> 試合</small></div></div>
      <div class="panel"><h3>進行中の大会</h3>${rows ? `<table class="list">${rows}</table>` : '<div class="muted">進行中の大会はありません</div>'}</div>
    </div>`;
}

// ---- 大会：一覧 → トーナメント表 ----

async function renderCompetitions(content) {
  const view = state.competitions.view;
  if (view) return renderBracketPage(content, view);
  const data = await call("competitions");
  if (!data) return;
  const f = state.competitions.filter;
  if (!f.year) f.year = String(state.header.school_year);
  const years = data.school_years.map((y) => `<option value="${y}" ${String(y) === f.year ? "selected" : ""}>${y}年度</option>`).join("");
  const tabs = (items, key) => items.map(([value, label]) =>
    `<button class="tab ${f[key] === value ? "on" : ""}" data-key="${key}" data-value="${value}">${label}</button>`).join("");
  const rows = data.competitions.filter((c) =>
    String(c.school_year) === f.year && (!f.segment || c.segment === f.segment) && (!f.level || c.level === f.level));
  content.innerHTML = `<div class="head"><h2>大会</h2>
      <select id="c-year">${years}</select>
      <div class="tabs">${tabs(SEGMENTS, "segment")}</div>
      <div class="tabs">${tabs(LEVELS, "level")}</div>
      <div class="spacer"></div><span class="muted num">${rows.length} 大会</span></div>
    <div class="scroll"><table class="list">
      <tr><th>大会</th><th>季節</th><th>区分</th><th>期間</th><th>状態</th><th>優勝</th></tr>
      ${rows.map((c) => `<tr class="click" data-year="${c.school_year}" data-id="${esc(c.competition_id)}">
        <td>${esc(c.name)}</td><td>${esc(c.segment_label)}</td><td>${esc(c.level_label)}</td>
        <td class="num">${slashDate(c.start_date)} 〜 ${slashDate(c.end_date)}</td>
        <td><span class="badge ${c.status}">${esc(c.status_label)}</span></td>
        <td class="${c.champion_name ? "w" : ""}">${esc(c.champion_name)}</td></tr>`).join("")}
    </table></div>`;
  $("c-year").addEventListener("change", (e) => { f.year = e.target.value; renderPage(); });
  content.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
    f[b.dataset.key] = b.dataset.value;
    renderPage();
  }));
  content.querySelectorAll("tr.click").forEach((tr) => tr.addEventListener("click", () => {
    state.competitions.view = { year: Number(tr.dataset.year), id: tr.dataset.id };
    renderPage();
  }));
}

async function renderBracketPage(content, view) {
  const data = await call("bracket", view.year, view.id);
  if (!data) return;
  state.bracket = data;
  const c = data.competition;
  content.innerHTML = `<div class="head">
      <button class="btn small" id="b-back">← 大会の一覧</button>
      <h2>${esc(c.name)}</h2><span class="badge ${c.status}">${esc(c.status_label)}</span>
      <div class="spacer"></div>
      <div class="tabs"><button class="btn small" id="z-out" title="縮小">−</button>
      <button class="btn small" id="z-fit" title="全体">全体</button>
      <button class="btn small" id="z-in" title="拡大">＋</button></div></div>
    <div class="body">
      <div class="paper-wrap" id="paper-wrap"></div>
      <aside class="side" id="b-side"><div class="empty">トーナメント表の試合（交点）を押すと<br>スコアが出ます。<br>学校名を押すと勝ち上がりが<br>青く表示されます。</div></aside>
    </div>`;
  $("b-back").addEventListener("click", () => { state.competitions.view = null; renderPage(); });
  $("z-in").addEventListener("click", () => setZoom(state.zoom * 1.2));
  $("z-out").addEventListener("click", () => setZoom(state.zoom / 1.2));
  $("z-fit").addEventListener("click", fitZoom);
  $("paper-wrap").addEventListener("wheel", (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    setZoom(state.zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1));
  }, { passive: false });
  drawPaper();
}

function setZoom(zoom) {
  state.zoom = Math.min(2, Math.max(0.25, zoom));
  drawPaper();
}

function fitZoom() {
  const svg = document.querySelector("#paper-wrap svg");
  if (!svg) return;
  if (state.zoom < 1) return setZoom(1);
  const wrap = $("paper-wrap");
  const box = svg.viewBox.baseVal;
  setZoom(Math.min(1, (wrap.clientHeight - 90) / box.height, (wrap.clientWidth - 80) / box.width));
}

const ROW = 22, NAME_W = 150, COL_W = 64;

function drawPaper() {
  const data = state.bracket;
  const wrap = $("paper-wrap");
  const paper = document.createElement("div");
  paper.className = "paper";
  const c = data.competition;
  const name = (id) => data.names[id] || "";
  const main = data.main;
  const champion = main && main.champion_id;
  paper.innerHTML = `<div class="title">${esc(c.name)}${champion ? `　<span class="champ">優勝 ${esc(name(champion))}</span>` : ""}</div>`;
  if (!main) {
    paper.innerHTML += `<div class="muted" style="color:#7a756a">本大会の組み合わせはまだ決まっていません。</div>`;
  } else {
    paper.append(bracketSvg(main, name));
  }
  wrap.replaceChildren(paper);
  if (data.other_matches.length) wrap.append(otherMatches(data.other_matches, name));
}

function bracketSvg(main, name) {
  const svg = svgEl("svg");
  const X = (round) => NAME_W + round * COL_W;
  const Y = (y) => 26 + y * ROW + ROW / 2;
  const width = X(main.total_rounds) + 150;
  const height = 26 + main.rows.length * ROW + 10;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", width * state.zoom);
  svg.setAttribute("height", height * state.zoom);
  main.round_names.forEach((label, i) =>
    svg.append(svgEl("text", { x: X(i + 1) - 4, y: 14, "text-anchor": "end", class: "rlabel" }, label)));
  const lines = svgEl("g"), texts = svgEl("g"), hits = svgEl("g");
  svg.append(lines, texts, hits);
  const champion = main.champion_id;
  main.rows.forEach((row) => {
    const text = svgEl("text", {
      x: NAME_W - 8, y: Y(row.y) + 4, "text-anchor": "end",
      class: "tname" + (row.school_id === champion ? " champion" : ""),
    }, name(row.school_id));
    text.addEventListener("click", () => trace(row.school_id));
    texts.append(text);
  });
  const seg = (x1, y1, x2, y2, win, team) => lines.append(svgEl("path", {
    d: x1 === x2 ? `M${x1} ${y1}V${y2}` : `M${x1} ${y1}H${x2}`,
    class: "seg" + (win ? " win" : ""), "data-team": team || "",
  }));
  for (const m of main.matches) {
    const x = X(m.round), ym = Y(m.y);
    for (const child of m.children) {
      const yc = Y(child.y);
      const win = !!m.winner_id && child.school_id === m.winner_id;
      seg(X(child.round), yc, x, yc, win, child.school_id);
      seg(x, yc, x, ym, win, child.school_id);
      if (child.score !== null && child.score !== undefined) {
        texts.append(svgEl("text", { x: x - 4, y: yc - 3, "text-anchor": "end", class: "sc" + (win ? " win" : "") }, child.score));
      }
    }
    hits.append(svgEl("circle", { cx: x, cy: ym, r: 2.6, class: "dot" + (m.winner_id ? " win" : "") }));
    const hit = svgEl("rect", { x: x - 9, y: ym - 9, width: 18, height: 18, rx: 4, class: "hit", "data-id": m.match_id });
    hit.addEventListener("click", () => selectMatch(m.match_id));
    hits.append(hit);
  }
  if (champion) {
    const yf = Y(main.final_y), xf = X(main.total_rounds);
    seg(xf, yf, xf + 28, yf, true, champion);
    texts.append(svgEl("text", { x: xf + 34, y: yf + 5, class: "tname champion" }, name(champion)));
  }
  return svg;
}

function otherMatches(matches, name) {
  const box = document.createElement("div");
  box.className = "panel others";
  box.innerHTML = `<h3>予選・シード決めの試合</h3><table class="list">
    <tr><th>日</th><th>段階</th><th>対戦</th><th class="n">スコア</th></tr>
    ${matches.map((m) => `<tr class="click" data-id="${esc(m.match_id)}"><td class="num">${slashDate(m.match_date)}</td>
      <td>${esc(m.group_name || m.round_name)}</td>
      <td><span class="${m.winner_id === m.team1_id ? "w" : ""}">${esc(name(m.team1_id))}</span> − <span class="${m.winner_id === m.team2_id ? "w" : ""}">${esc(name(m.team2_id))}</span></td>
      <td class="n">${m.team1_score ?? ""}${m.team1_score !== null ? "−" : ""}${m.team2_score ?? ""}</td></tr>`).join("")}
  </table>`;
  box.querySelectorAll("tr.click").forEach((tr) => tr.addEventListener("click", () => selectMatch(tr.dataset.id)));
  return box;
}

function trace(school) {
  const data = state.bracket;
  const svg = document.querySelector("#paper-wrap svg");
  svg.querySelectorAll(".trace").forEach((e) => e.classList.remove("trace"));
  svg.querySelectorAll(`path[data-team="${CSS.escape(school)}"]`).forEach((e) => e.classList.add("trace"));
  const name = (id) => data.names[id] || "";
  const games = data.main.matches.filter((m) => m.children.some((c) => c.school_id === school) && m.winner_id);
  $("b-side").innerHTML = `<div class="muted">${esc(data.competition.name)}</div><h2 style="margin:6px 0 10px">${esc(name(school))}</h2>
    <table class="log">${games.map((m) => {
      const me = m.children.find((c) => c.school_id === school);
      const op = m.children.find((c) => c.school_id !== school) || {};
      const won = m.winner_id === school;
      return `<tr><td>${esc(m.round_name)}</td><td>${esc(name(op.school_id))}</td><td class="r ${won ? "w" : ""}">${won ? "○" : "●"}</td>
        <td class="num">${me.score ?? ""}-${op.score ?? ""}</td><td><span class="link" data-id="${esc(m.match_id)}">詳細</span></td></tr>`;
    }).join("") || '<tr><td class="muted">まだ試合をしていません</td></tr>'}</table>`;
  $("b-side").querySelectorAll(".link").forEach((a) => a.addEventListener("click", () => selectMatch(a.dataset.id)));
}

async function selectMatch(matchId) {
  const data = state.bracket;
  document.querySelectorAll("#paper-wrap .hit.sel").forEach((e) => e.classList.remove("sel"));
  const hit = document.querySelector(`#paper-wrap .hit[data-id="${CSS.escape(matchId)}"]`);
  if (hit) hit.classList.add("sel");
  const m = await call("match", data.competition.school_year, data.competition.competition_id, matchId);
  if (!m) return;
  $("b-side").innerHTML = `<div class="muted">${esc(m.competition_name)}</div>
    <h2 style="margin:6px 0 2px">${esc(m.round_name || m.group_name)}</h2>
    <div class="muted num">${slashDate(m.match_date)}</div>
    ${scoreboard(m)}
    ${m.status === "completed" ? `<p><span class="link" id="to-match">試合の画面で見る →</span></p>` : '<p class="muted">まだ試合をしていません。</p>'}`;
  const link = $("to-match");
  if (link) link.addEventListener("click", () => openMatch(m.school_year, m.competition_id, m.match_id));
}

// ---- 得点板 ----

function scoreboard(m, wide = false) {
  const board = m.board || [
    { school_id: m.team1_id, name: m.team1_name, innings: [], runs: m.team1_score },
    { school_id: m.team2_id, name: m.team2_name, innings: [], runs: m.team2_score },
  ];
  const n = Math.max(9, ...board.map((b) => b.innings.length));
  const cells = (line) => Array.from({ length: n }, (_, i) =>
    `<td>${line[i] === null ? (i < line.length ? "x" : "") : (line[i] ?? "")}</td>`).join("");
  const hasHits = board.some((b) => b.hits !== undefined && b.hits !== null);
  const rows = board.map((b) => `<tr class="${m.winner_id && m.winner_id !== b.school_id ? "loser" : ""}">
    <td class="team">${esc(b.name)}</td>${cells(b.innings)}<td class="total">${b.runs ?? ""}</td>
    ${hasHits ? `<td class="sub">${b.hits ?? ""}</td><td class="sub">${b.errors ?? ""}</td>` : ""}</tr>`).join("");
  return `<div class="board ${wide ? "wide" : ""}"><table><tr><th></th>${Array.from({ length: n }, (_, i) => `<th>${i + 1}</th>`).join("")}
    <th>計</th>${hasHits ? "<th>安</th><th>失</th>" : ""}</tr>${rows}</table></div>`;
}

// ---- 試合：その日の一覧 → 詳細 ----

function openMatch(year, competitionId, matchId) {
  state.matches.detail = { year, competitionId, matchId };
  state.page = "matches";
  renderMenu();
  renderPage();
}

async function renderMatches(content) {
  if (state.matches.detail) return renderMatchDetail(content, state.matches.detail);
  const data = await call("matches_on", state.matches.date);
  if (!data) return;
  state.matches.date = data.date;
  const dates = data.match_dates;
  const index = dates.indexOf(data.date);
  const groups = {};
  for (const m of data.matches) (groups[m.competition_name] ||= []).push(m);
  content.innerHTML = `<div class="head"><h2>試合</h2>
      <button class="btn small" id="d-prev" ${index <= 0 ? "disabled" : ""}>← 前の試合日</button>
      <span class="num" style="font-size:16px">${slashDate(data.date)}</span>
      <button class="btn small" id="d-next" ${index < 0 || index >= dates.length - 1 ? "disabled" : ""}>次の試合日 →</button>
      <div class="spacer"></div><span class="muted num">${data.matches.length} 試合</span></div>
    <div class="scroll">${Object.entries(groups).map(([competition, matches]) => `
      <div class="panel"><h3>${esc(competition)}</h3><table class="list">
      ${matches.map((m) => `<tr class="click" data-year="${m.school_year}" data-cid="${esc(m.competition_id)}" data-id="${esc(m.match_id)}">
        <td style="width:110px" class="muted">${esc(m.round_name || m.group_name)}</td>
        <td style="text-align:right" class="${m.winner_id === m.team1_id ? "w" : ""}">${esc(m.team1_name)}</td>
        <td class="n" style="width:90px;text-align:center">${m.status === "completed" ? `${m.team1_score} − ${m.team2_score}` : "−"}</td>
        <td class="${m.winner_id === m.team2_id ? "w" : ""}">${esc(m.team2_name)}</td></tr>`).join("")}
      </table></div>`).join("") || '<div class="empty">この日の試合はありません。</div>'}</div>`;
  if (index > 0) $("d-prev").addEventListener("click", () => { state.matches.date = dates[index - 1]; renderPage(); });
  if (index >= 0 && index < dates.length - 1) $("d-next").addEventListener("click", () => { state.matches.date = dates[index + 1]; renderPage(); });
  content.querySelectorAll("tr.click").forEach((tr) => tr.addEventListener("click", () =>
    openMatch(Number(tr.dataset.year), tr.dataset.cid, tr.dataset.id)));
}

async function renderMatchDetail(content, detail) {
  const m = await call("match", detail.year, detail.competitionId, detail.matchId);
  if (!m) return;
  const highlights = (m.highlights || []).map((h) => h.kind === "score"
    ? `<div class="hl ${h.is_home_run ? "hr" : ""}"><span class="inn">${h.inning}回${h.half}</span><span class="what">${esc(h.school_name)}　${esc(h.player_name)}　${esc(h.event)}で${h.runs}点</span></div>`
    : `<div class="hl pc"><span class="inn">${h.inning}回${h.half}</span><span class="what">${esc(h.school_name)}　投手交代 → ${esc(h.player_name)}</span></div>`).join("");
  const batting = (team) => `<table class="stat-table"><tr><th>打者</th><th></th><th>打数</th><th>安打</th><th>打点</th><th>本塁打</th><th>四球</th><th>三振</th></tr>
    ${(m.batting[team] || []).map((b) => `<tr><td>${esc(b.name)}</td><td class="pos">${esc(b.position)}</td><td>${b.at_bats}</td><td>${b.hits}</td><td>${b.rbi}</td><td>${b.home_runs}</td><td>${b.walks}</td><td>${b.strikeouts}</td></tr>`).join("")}</table>`;
  const pitching = (team) => `<table class="stat-table"><tr><th>投手</th><th>回</th><th>打者</th><th>安打</th><th>失点</th><th>自責</th><th>四球</th><th>三振</th></tr>
    ${(m.pitching[team] || []).map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.innings)}</td><td>${p.batters_faced}</td><td>${p.hits_allowed}</td><td>${p.runs_allowed}</td><td>${p.earned_runs}</td><td>${p.walks}</td><td>${p.strikeouts}</td></tr>`).join("")}</table>`;
  content.innerHTML = `<div class="head"><button class="btn small" id="m-back">← 試合の一覧</button>
      <h2>${esc(m.competition_name)}　${esc(m.round_name || m.group_name)}</h2>
      <span class="muted num">${slashDate(m.match_date)}</span></div>
    <div class="scroll">
      ${scoreboard(m, true)}
      ${m.has_detail ? `
        <div class="panel" style="margin-top:14px"><h3>試合の要点</h3>${highlights || '<div class="muted">得点はありませんでした</div>'}</div>
        <div class="cols">
          <div class="panel"><h3>${esc(m.team1_name)}</h3>${batting(m.team1_id)}<div style="height:10px"></div>${pitching(m.team1_id)}</div>
          <div class="panel"><h3>${esc(m.team2_name)}</h3>${batting(m.team2_id)}<div style="height:10px"></div>${pitching(m.team2_id)}</div>
        </div>` : `<p class="muted">${m.status === "completed" ? "この試合の詳しい記録はありません。" : "まだ試合をしていません。"}</p>`}
    </div>`;
  $("m-back").addEventListener("click", () => { state.matches.detail = null; renderPage(); });
}

// ---- 日付を進める ----

async function advance(options) {
  setBusy(true);
  const poll = setInterval(updateProgress, 250);
  let result;
  try {
    result = await api().advance(options);
  } finally {
    clearInterval(poll);
    setBusy(false);
  }
  if (result.error) {
    showToast(result.error, true);
    return;
  }
  renderHeader(result.header);
  renderPage();
  const parts = [`${result.played_match_count}試合を行いました`];
  if (result.stopped_reason) parts.unshift(STOP_MESSAGES[result.stopped_reason] || "");
  showToast(parts.filter(Boolean).join("。"));
}

function setBusy(busy) {
  state.busy = busy;
  $("btn-day").disabled = busy;
  $("btn-bulk").disabled = busy;
  $("progress").hidden = !busy;
  if (busy) {
    $("progress-date").textContent = dotDate(state.header.date);
    $("progress-sub").textContent = "";
    $("progress-fill").style.width = "0";
  }
}

async function updateProgress() {
  // 進めている間に呼ぶのは progress() だけ
  const progress = await api().progress();
  if (!progress.running) return;
  $("progress-date").textContent = dotDate(progress.current_date);
  $("progress-sub").textContent = `${progress.advanced_days}日 ・ ${progress.played_match_count}試合`;
  const fill = $("progress-fill");
  if (progress.target_date) {
    const start = Date.parse(progress.from_date);
    const ratio = (Date.parse(progress.current_date) - start) / Math.max(1, Date.parse(progress.target_date) - start);
    fill.style.width = `${Math.min(100, Math.round(ratio * 100))}%`;
  } else {
    fill.style.width = `${(progress.advanced_days * 7) % 100}%`;
  }
}

function openBulkDialog() {
  if (state.busy) return;
  const select = $("bulk-competition");
  select.innerHTML = state.header.active_competitions.map((row) =>
    `<option value="${row.school_year}|${esc(row.competition_id)}">${esc(row.name)}</option>`).join("");
  const dateInput = $("bulk-date");
  dateInput.min = state.header.date;
  if (!dateInput.value || dateInput.value <= state.header.date) dateInput.value = "";
  $("bulk-dialog").showModal();
}

function onBulkClose(event) {
  if (event.target.returnValue !== "start") return;
  const mode = $("bulk-form").elements.mode.value;
  const options = { mode, stop_at_big_scene: $("bulk-stop-big").checked };
  if (mode === "competition_end") {
    const [year, competitionId] = $("bulk-competition").value.split("|");
    if (!competitionId) return showToast("大会を選んでください", true);
    options.school_year = Number(year);
    options.competition_id = competitionId;
  }
  if (mode === "date") {
    options.target_date = $("bulk-date").value;
    if (!options.target_date) return showToast("日付を選んでください", true);
  }
  advance(options);
}

// ---- 起動 ----

async function start() {
  const shell = await call("shell");
  if (!shell) return;
  state.menu = shell.menu;
  renderHeader(shell.header);
  renderMenu();
  renderPage();
  $("btn-day").addEventListener("click", () => advance({ mode: "day" }));
  $("btn-bulk").addEventListener("click", openBulkDialog);
  $("bulk-dialog").addEventListener("close", onBulkClose);
}

window.addEventListener("pywebviewready", start);
