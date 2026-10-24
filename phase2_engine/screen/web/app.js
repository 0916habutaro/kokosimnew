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
  noSession: false, // 起動時にセーブを選ぶ前
  competitions: { filter: { year: "", segment: "", level: "", status: "" }, view: null },
  matches: { date: "", detail: null },
  schools: {
    data: null, view: [], filter: { pref: "", owner: "", result: "", name: "" },
    sortKey: "pref", sortDir: 1, selected: null, detail: null, tab: "overview",
  },
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

// 「4月9日（木）」。今日なら「今日」
function jpDate(iso, withToday = true) {
  if (!iso) return "";
  if (withToday && state.header && iso === state.header.date) return "今日";
  const d = new Date(iso);
  return `${d.getMonth() + 1}月${d.getDate()}日（${DOW[d.getDay()]}）`;
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
    button.disabled = state.noSession && item.id !== "saves";
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
  if (state.page === "schools") return renderSchools(content);
  if (state.page === "records") return renderRecords(content);
  if (state.page === "saves") return renderSaves(content);
  const title = (state.menu.find((m) => m.id === state.page) || {}).label || "";
  content.innerHTML = `<div class="head"><h2>${esc(title)}</h2></div>
    <div class="scroll"><div class="empty">この画面はこれから作ります。</div></div>`;
}

// ---- 今日 ----

function matchLine(m) {
  const done = m.status === "completed";
  return `<tr class="click" data-year="${m.school_year}" data-cid="${esc(m.competition_id)}" data-id="${esc(m.match_id)}">
    <td class="muted" style="width:200px">${esc(m.competition_name)}<br><small>${esc(m.round_name)}</small></td>
    <td style="text-align:right" class="${m.winner_id === m.team1_id ? "w" : ""}">${esc(m.team1_name)}</td>
    <td class="n" style="width:90px;text-align:center">${done ? `${m.team1_score ?? ""} − ${m.team2_score ?? ""}` : "vs"}</td>
    <td class="${m.winner_id === m.team2_id ? "w" : ""}">${esc(m.team2_name)}</td>
    ${done ? `<td class="muted num" style="width:90px">${jpDate(m.match_date)}</td>` : ""}</tr>`;
}

async function renderToday(content) {
  const data = await call("today");
  if (!data) return;
  renderHeader(data.header);
  const header = data.header;
  const competitions = header.active_competitions.slice(0, 12).map((row) =>
    `<tr><td title="${esc(row.name)}">${esc(row.short_name)}</td><td class="muted">${row.next_date ? "次の試合 " + jpDate(row.next_date) : ""}</td></tr>`).join("");
  content.innerHTML = `<div class="head"><h2>今日</h2><span class="muted">${jpDate(header.date, false)}</span></div>
    <div class="scroll"><div class="split">
      <div>
        <div class="panel"><h3>今日の全国の試合</h3><div class="big">${header.today_match_count}<small class="muted" style="font-size:16px"> 試合</small></div></div>
        <div class="panel"><h3>注目の試合</h3>${data.featured.length
          ? `<table class="list">${data.featured.map(matchLine).join("")}</table>`
          : '<div class="muted">今日の試合はありません</div>'}</div>
      </div>
      <div>
        <div class="panel"><h3>直近の大きな結果</h3>${data.recent_results.length
          ? `<table class="list">${data.recent_results.map(matchLine).join("")}</table>`
          : '<div class="muted">最近の決勝はありません</div>'}</div>
        <div class="panel"><h3>進行中の大会</h3>${competitions ? `<table class="list">${competitions}</table>` : '<div class="muted">進行中の大会はありません</div>'}</div>
      </div>
    </div></div>`;
  content.querySelectorAll("tr.click").forEach((tr) => tr.addEventListener("click", () =>
    openMatch(Number(tr.dataset.year), tr.dataset.cid, tr.dataset.id)));
}

// ---- 記録 ----

async function renderRecords(content) {
  const data = await call("records", state.recordsYear || null);
  if (!data) return;
  state.recordsYear = data.school_year;
  const school = (e) => `<span class="link" data-school="${esc(e.school_id)}">${esc(e.name)}</span><span class="muted">（${esc(e.prefecture)}）</span>`
    + (e.championship_count ? `<span class="muted">　${e.championship_count.total}回目の優勝${breakdown(e.championship_count)}</span>` : "");
  // 「12回目」と内訳（実際の記録＋ゲーム内）
  const breakdown = (c) => c.actual ? `（実際${c.actual}＋ゲーム${c.game}）` : "";
  const nth = (c) => c ? `<span class="num">${c.total}回目</span><span class="muted">${breakdown(c)}</span>` : "";
  const nationals = data.nationals.map((n) => `<div class="panel"><h3>${esc(n.competition_name)}${n.started && !n.finished ? '　<span class="badge active">進行中</span>' : ""}</h3>
    ${n.played ? `<table class="list">${["優勝", "準優勝", "ベスト4", "ベスト8"].map((f) => `<tr><td style="width:80px">${badge(f === "優勝" ? 3000 : f === "準優勝" ? 2000 : 0, f)}</td>
      <td>${(n.groups[f] || []).map(school).join("　") || '<span class="muted">−</span>'}</td></tr>`).join("")}</table>`
      : `<div class="muted">${n.started ? "始まったばかりです" : "まだ行われていません"}</div>`}</div>`).join("");
  const reps = data.representatives.map((r) => `<tr><td>${esc(r.area)}</td>
    <td>${r.school_id ? `<span class="link" data-school="${esc(r.school_id)}">${esc(r.name)}</span>` : '<span class="muted">未定</span>'}</td>
    <td>${nth(r.appearance)}</td>
    <td>${r.koshien ? badge(r.koshien === "優勝" ? 3000 : 0, r.koshien) : ""}</td></tr>`).join("");
  const senbatsu = data.senbatsu.map((r) => `<tr><td>${esc(r.prefecture)}</td><td><span class="link" data-school="${esc(r.school_id)}">${esc(r.name)}</span></td><td>${nth(r.appearance)}</td><td>${badge(r.finish === "優勝" ? 3000 : 0, r.finish)}</td></tr>`).join("");
  content.innerHTML = `<div class="head"><h2>記録</h2>
      <select id="r-year">${data.years.map((y) => `<option value="${y}" ${y === data.school_year ? "selected" : ""}>${y}年度</option>`).join("")}</select></div>
    <div class="scroll">
      <div class="split">${nationals}</div>
      <div class="split">
        <div class="panel"><h3>夏の代表校</h3><table class="list"><tr><th>地区</th><th>代表校</th><th>出場</th><th>甲子園</th></tr>${reps}</table></div>
        <div class="panel"><h3>選抜の出場校</h3>${senbatsu ? `<table class="list"><tr><th>都道府県</th><th>学校</th><th>出場</th><th>成績</th></tr>${senbatsu}</table>` : '<div class="muted">まだ選ばれていません</div>'}</div>
      </div>
    </div>`;
  $("r-year").addEventListener("change", (e) => { state.recordsYear = Number(e.target.value); renderPage(); });
  content.querySelectorAll(".link[data-school]").forEach((a) => a.addEventListener("click", () => openSchool(a.dataset.school)));
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
        <td title="${esc(c.name)}">${esc(c.short_name)}</td><td>${esc(c.segment_label)}</td><td>${esc(c.level_label)}</td>
        <td>${jpDate(c.start_date, false)} 〜 ${jpDate(c.end_date, false)}</td>
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
      <td>${esc(m.round_name)}</td>
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
    }).join("") || '<tr><td class="muted">まだ試合をしていません</td></tr>'}</table>
    <p><span class="link" id="to-school">学校の画面へ →</span></p>`;
  $("b-side").querySelectorAll(".link[data-id]").forEach((a) => a.addEventListener("click", () => selectMatch(a.dataset.id)));
  $("to-school").addEventListener("click", () => openSchool(school));
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
  const groups = {};
  for (const m of data.matches) (groups[m.competition_name] ||= []).push(m);
  content.innerHTML = `<div class="head"><h2>試合</h2>
      <button class="btn small" id="d-prev" ${data.prev_date ? "" : "disabled"}>← 前の試合日</button>
      <span class="num" style="font-size:16px">${slashDate(data.date)}</span>
      <button class="btn small" id="d-next" ${data.next_date ? "" : "disabled"}>次の試合日 →</button>
      <div class="spacer"></div><span class="muted num">${data.matches.length} 試合</span></div>
    <div class="scroll">${Object.entries(groups).map(([competition, matches]) => `
      <div class="panel"><h3>${esc(competition)}</h3><table class="list">
      ${matches.map((m) => `<tr class="click" data-year="${m.school_year}" data-cid="${esc(m.competition_id)}" data-id="${esc(m.match_id)}">
        <td style="width:220px" class="muted">${esc(m.round_name)}</td>
        <td style="text-align:right" class="${m.winner_id === m.team1_id ? "w" : ""}">${esc(m.team1_name)}</td>
        <td class="n" style="width:90px;text-align:center">${m.status === "completed" ? `${m.team1_score} − ${m.team2_score}` : "−"}</td>
        <td class="${m.winner_id === m.team2_id ? "w" : ""}">${esc(m.team2_name)}</td></tr>`).join("")}
      </table></div>`).join("") || '<div class="empty">この日の試合はありません。</div>'}</div>`;
  if (data.prev_date) $("d-prev").addEventListener("click", () => { state.matches.date = data.prev_date; renderPage(); });
  if (data.next_date) $("d-next").addEventListener("click", () => { state.matches.date = data.next_date; renderPage(); });
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
      <p><span class="link" data-school="${esc(m.team1_id)}">${esc(m.team1_name)}</span>　／　<span class="link" data-school="${esc(m.team2_id)}">${esc(m.team2_name)}</span>　<span class="muted">（学校の画面へ）</span></p>
      ${m.has_detail ? `
        <div class="panel" style="margin-top:14px"><h3>試合の要点</h3>${highlights || '<div class="muted">得点はありませんでした</div>'}</div>
        <div class="cols">
          <div class="panel"><h3>${esc(m.team1_name)}</h3>${batting(m.team1_id)}<div style="height:10px"></div>${pitching(m.team1_id)}</div>
          <div class="panel"><h3>${esc(m.team2_name)}</h3>${batting(m.team2_id)}<div style="height:10px"></div>${pitching(m.team2_id)}</div>
        </div>` : `<p class="muted">${m.status === "completed" ? "この試合の詳しい記録はありません。" : "まだ試合をしていません。"}</p>`}
    </div>`;
  $("m-back").addEventListener("click", () => { state.matches.detail = null; renderPage(); });
  content.querySelectorAll(".link[data-school]").forEach((a) => a.addEventListener("click", () => openSchool(a.dataset.school)));
}

// ---- 学校：一覧（見えている行だけ描く） → 詳細（タブ） ----

const SCHOOL_COLS = [
  ["pref", "都道府県"], ["name", "校名"], ["ownership", "設置者"],
  ["overall", "総合", 1], ["batting", "打撃", 1], ["pitching", "投手", 1],
  ["defense", "守備", 1], ["running", "走力", 1], ["record", "勝敗", 1], ["best", "今年度の最高成績"],
];
const RESULT_FILTERS = [
  ["", "成績すべて"], ["3000", "甲子園出場"], ["2000", "地区大会出場以上"], ["1012", "都道府県ベスト8以上"],
];
const RH = 32;

function openSchool(schoolId) {
  state.schools.detail = schoolId;
  state.schools.tab = "overview";
  state.page = "schools";
  renderMenu();
  renderPage();
}

async function renderSchools(content) {
  const st = state.schools;
  if (st.detail) return renderSchoolDetail(content, st.detail);
  const data = await call("schools");
  if (!data) return;
  st.data = data;
  const prefs = [...new Map(data.schools.map((s) => [s.prefecture_code, s.prefecture])).entries()].sort();
  const owners = [...new Set(data.schools.map((s) => s.ownership))];
  const f = st.filter;
  const opt = (value, label, current) => `<option value="${esc(value)}" ${value === current ? "selected" : ""}>${esc(label)}</option>`;
  content.innerHTML = `<div class="head"><h2>学校</h2>
      <select id="s-pref">${opt("", "全国", f.pref)}${prefs.map(([c, n]) => opt(c, n, f.pref)).join("")}</select>
      <select id="s-owner">${opt("", "設置者すべて", f.owner)}${owners.map((o) => opt(o, o, f.owner)).join("")}</select>
      <select id="s-result">${RESULT_FILTERS.map(([v, l]) => opt(v, l, f.result)).join("")}</select>
      <input type="search" id="s-name" placeholder="校名で探す" value="${esc(f.name)}">
      ${data.abilities_status === "computing" ? '<span class="muted">能力を計算しています…</span>' : ""}
      <div class="spacer"></div><span class="muted num" id="s-count"></span></div>
    <div class="body">
      <div class="grid"><div class="ghead" id="s-head"></div><div class="gscroll" id="s-scroll"><div id="s-space"></div></div></div>
      <aside class="side" id="s-side"><div class="empty">学校を選ぶと、今年度の成績が出ます。</div></aside>
    </div>`;
  for (const [id, key] of [["s-pref", "pref"], ["s-owner", "owner"], ["s-result", "result"]]) {
    $(id).addEventListener("change", (e) => { f[key] = e.target.value; applySchoolFilter(); });
  }
  $("s-name").addEventListener("input", (e) => { f.name = e.target.value.trim(); applySchoolFilter(); });
  $("s-scroll").addEventListener("scroll", () => requestAnimationFrame(renderSchoolRows));
  applySchoolFilter();
  if (st.selected) showSchoolSide(st.selected);
  if (data.abilities_status === "computing") {
    clearTimeout(renderSchools.retry);
    renderSchools.retry = setTimeout(() => {
      if (state.page === "schools" && !st.detail && !state.busy) renderPage();
    }, 4000);
  }
}

function schoolValue(s, key) {
  if (key === "pref") return s.prefecture_code + s.name;
  if (key === "record") return s.wins - s.losses / 100;
  if (key === "best") return s.best_score;
  if (["overall", "batting", "pitching", "defense", "running"].includes(key)) return s.abilities ? s.abilities[key] : -1;
  return s[key] ?? "";
}

function applySchoolFilter() {
  const st = state.schools, f = st.filter;
  st.view = st.data.schools.filter((s) =>
    (!f.pref || s.prefecture_code === f.pref) && (!f.owner || s.ownership === f.owner)
    && (!f.result || s.best_score >= Number(f.result))
    && (!f.name || s.name.includes(f.name) || s.official_name.includes(f.name)));
  st.view.sort((a, b) => {
    const x = schoolValue(a, st.sortKey), y = schoolValue(b, st.sortKey);
    return (x < y ? -1 : x > y ? 1 : 0) * st.sortDir;
  });
  $("s-count").textContent = `${st.view.length.toLocaleString()} 校`;
  $("s-head").innerHTML = SCHOOL_COLS.map(([key, label, num]) =>
    `<div data-k="${key}" class="${num ? "n" : ""} ${key === st.sortKey ? "sorted" : ""}">${label}${key === st.sortKey ? (st.sortDir > 0 ? " ▲" : " ▼") : ""}</div>`).join("");
  $("s-head").querySelectorAll("div").forEach((d) => d.addEventListener("click", () => {
    const key = d.dataset.k, numeric = (SCHOOL_COLS.find((c) => c[0] === key) || [])[2] || key === "best";
    st.sortDir = st.sortKey === key ? -st.sortDir : (numeric ? -1 : 1);
    st.sortKey = key;
    applySchoolFilter();
  }));
  $("s-scroll").scrollTop = 0;
  renderSchoolRows();
}

function badge(score, label) {
  if (!label) return "";
  const cls = score >= 3000 ? "b-top" : score >= 2000 ? "b-mid" : "";
  return `<span class="badge ${cls}">${esc(label)}</span>`;
}

function renderSchoolRows() {
  const st = state.schools, scroll = $("s-scroll"), space = $("s-space");
  if (!scroll) return;
  space.style.height = `${st.view.length * RH}px`;
  const first = Math.max(0, Math.floor(scroll.scrollTop / RH) - 5);
  const last = Math.min(st.view.length, first + Math.ceil(scroll.clientHeight / RH) + 10);
  let html = "";
  for (let i = first; i < last; i++) {
    const s = st.view[i], a = s.abilities;
    const ab = (key) => a ? a[key].toFixed(1) : "…";
    html += `<div class="grow ${s.school_id === st.selected ? "sel" : ""}" style="top:${i * RH}px" data-id="${esc(s.school_id)}">
      <div>${esc(s.prefecture)}</div><div title="${esc(s.official_name)}">${esc(s.name)}</div><div>${esc(s.ownership)}</div>
      <div class="n">${ab("overall")}</div><div class="n">${ab("batting")}</div><div class="n">${ab("pitching")}</div>
      <div class="n">${ab("defense")}</div><div class="n">${ab("running")}</div><div class="n">${s.wins}-${s.losses}</div>
      <div>${badge(s.best_score, s.best)}</div></div>`;
  }
  space.innerHTML = html;
  space.querySelectorAll(".grow").forEach((r) => r.addEventListener("click", () => {
    st.selected = r.dataset.id;
    renderSchoolRows();
    showSchoolSide(r.dataset.id);
  }));
}

function showSchoolSide(schoolId) {
  const s = state.schools.data.schools.find((x) => x.school_id === schoolId);
  if (!s) return;
  const games = s.wins + s.losses;
  $("s-side").innerHTML = `<div class="muted">${esc(s.prefecture)}・${esc(s.ownership)}</div><h2>${esc(s.name)}</h2>
    <div class="muted" style="font-size:12px">${esc(s.official_name)}</div>
    <div class="stats" style="grid-template-columns:repeat(3,1fr)"><div class="stat"><b>${s.abilities ? s.abilities.overall.toFixed(1) : "…"}</b><span>総合</span></div>
      <div class="stat"><b>${s.wins}-${s.losses}</b><span>今年度の勝敗</span></div>
      <div class="stat"><b>${games ? (s.wins / games).toFixed(3).replace(/^0/, "") : "-"}</b><span>勝率</span></div></div>
    <div class="muted" style="font-size:12px">今年度の最高成績</div>
    <p>${s.best ? badge(s.best_score, s.best) : '<span class="muted">今年度の試合はまだありません</span>'}</p>
    <p><button class="btn" id="s-open">詳しく見る →</button></p>`;
  $("s-open").addEventListener("click", () => openSchool(schoolId));
}

const SCHOOL_TABS = [["overview", "概要"], ["yearly", "年度別成績"], ["koshien", "甲子園"], ["members", "部員"], ["games", "試合一覧"]];
const ABILITY_LABELS = [
  ["overall", "総合"], ["batting", "打撃"], ["contact", "ミート"], ["power", "長打"], ["discipline", "選球"],
  ["pitching", "投手"], ["ace", "エース"], ["pitching_depth", "投手層"], ["bullpen", "救援"],
  ["defense", "守備"], ["running", "走力"],
];
const HANDS = { R: "右", L: "左", S: "両" };

async function renderSchoolDetail(content, schoolId) {
  const st = state.schools;
  const d = await call("school", schoolId);
  if (!d) return;
  content.innerHTML = `<div class="head"><button class="btn small" id="sd-back">← 学校の一覧</button>
      <h2>${esc(d.name)}</h2><span class="muted">${esc(d.prefecture)}・${esc(d.ownership)}　${esc(d.official_name)}</span></div>
    <div class="dtabs">${SCHOOL_TABS.map(([k, l]) => `<button class="dtab ${st.tab === k ? "on" : ""}" data-k="${k}">${l}</button>`).join("")}</div>
    <div class="scroll" id="sd-body"></div>`;
  $("sd-back").addEventListener("click", () => { st.detail = null; renderPage(); });
  content.querySelectorAll(".dtab").forEach((b) => b.addEventListener("click", () => { st.tab = b.dataset.k; renderPage(); }));
  const body = $("sd-body");
  if (st.tab === "overview") body.innerHTML = schoolOverview(d);
  if (st.tab === "yearly") body.innerHTML = schoolYearly(d);
  if (st.tab === "koshien") body.innerHTML = schoolKoshien(d);
  if (st.tab === "members") body.innerHTML = schoolMembers(d);
  if (st.tab === "games") await schoolGames(body, d);
}

function schoolOverview(d) {
  const a = d.abilities;
  const bars = a ? ABILITY_LABELS.map(([k, l]) =>
    `<span>${l}</span><div class="bar"><div style="width:${Math.max(0, Math.min(100, a[k]))}%"></div></div><span class="num">${a[k].toFixed(1)}</span>`).join("")
    : '<span class="muted">能力は選手で試合をしているときに出ます</span>';
  const rows = d.this_year.map((r) => `<tr><td>${esc(r.competition_name)}</td><td class="n">${r.wins}-${r.losses}</td><td>${badge(r.score, r.finish)}</td></tr>`).join("");
  return `<div class="split">
    <div class="panel"><h3>能力の内訳</h3><div class="bars">${bars}</div></div>
    <div class="panel"><h3>${d.school_year}年度の成績</h3>${rows ? `<table class="list"><tr><th>大会</th><th class="n">勝敗</th><th>成績</th></tr>${rows}</table>` : '<div class="muted">まだ試合をしていません</div>'}</div>
  </div>`;
}

function schoolYearly(d) {
  const cell = (part) => part.best ? `${esc(part.best)}<span class="muted num">　${part.wins}-${part.losses}</span>` : '<span class="muted">−</span>';
  return `<div class="panel"><table class="list"><tr><th>年度</th><th>春</th><th>夏</th><th>秋</th><th class="n">勝敗</th></tr>
    ${d.yearly.map((y) => `<tr><td class="num">${y.school_year}</td><td>${cell(y.spring)}</td><td>${cell(y.summer)}</td><td>${cell(y.autumn)}</td><td class="n">${y.wins}-${y.losses}</td></tr>`).join("")}
  </table></div>`;
}

// 甲子園：合計（実際＋ゲーム内）と内訳。実際の記録がない学校はゲーム内だけ
function schoolKoshien(d) {
  const record = (p) => `${p.wins}-${p.losses}${p.draws ? `-${p.draws}` : ""}`;
  const block = (label, until, k) => {
    const t = k.total, a = k.actual, g = k.game;
    const row = (name, p, years) => `<tr><td>${name}</td><td class="n">${p.appearances}</td><td class="n">${record(p)}</td>
      <td class="n">${p.championships || 0}</td><td>${esc(p.best || "−")}</td><td class="num">${years}</td></tr>`;
    return `<div class="panel"><h3>${label}</h3>
      <div class="stats"><div class="stat"><b>${t.appearances}</b><span>出場回数</span></div>
        <div class="stat"><b>${record(t)}</b><span>通算勝敗</span></div>
        <div class="stat"><b>${t.championships}</b><span>優勝</span></div>
        <div class="stat"><b>${esc(t.best || "−")}</b><span>最高成績</span></div>
        <div class="stat"><b>${t.last_year || "−"}</b><span>最近の出場</span></div></div>
      <table class="list"><tr><th>内訳</th><th class="n">出場</th><th class="n">勝敗</th><th class="n">優勝</th><th>最高成績</th><th>出場した年</th></tr>
        ${a ? row(`実際の記録（${until}まで）`, a, esc(a.years.join("、") || (a.last_year ? `最近 ${a.last_year}` : "−"))) : ""}
        ${row("ゲーム内の記録", g, g.years.join("、") || "−")}
      </table></div>`;
  };
  return block("夏の甲子園", "2025年", d.koshien.summer) + block("春の選抜", "2026年", d.koshien.spring);
}

function schoolMembers(d) {
  if (!d.members.length) return '<div class="empty">部員は選手で試合をしているときに出ます。</div>';
  return `<div class="panel"><table class="list"><tr><th>名前</th><th>学年</th><th>守備位置</th><th>投打</th></tr>
    ${d.members.map((m) => `<tr><td>${esc(m.name)}</td><td>${m.grade}年</td><td>${esc(m.position)}</td><td>${HANDS[m.throws] || m.throws}投${HANDS[m.bats] || m.bats}打</td></tr>`).join("")}
  </table></div>`;
}

async function schoolGames(body, d) {
  const st = state.schools;
  st.gamesYear = st.gamesYear && d.years.includes(st.gamesYear) ? st.gamesYear : d.school_year;
  const data = await call("school_matches", d.school_id, st.gamesYear);
  if (!data) return;
  body.innerHTML = `<div class="head" style="padding:0 0 10px;border:0"><select id="sg-year">${d.years.map((y) => `<option value="${y}" ${y === st.gamesYear ? "selected" : ""}>${y}年度</option>`).join("")}</select></div>
    <div class="panel"><table class="list"><tr><th>日</th><th>大会</th><th>回戦</th><th>相手</th><th></th><th class="n">スコア</th></tr>
    ${data.matches.map((m) => `<tr class="click" data-year="${m.school_year}" data-cid="${esc(m.competition_id)}" data-id="${esc(m.match_id)}">
      <td class="num">${slashDate(m.match_date)}</td><td>${esc(m.competition_name)}</td><td>${esc(m.round_name)}</td>
      <td>${esc(m.opponent_name)}</td><td class="${m.won ? "w" : ""}">${m.won ? "○" : "●"}</td><td class="n">${m.score}-${m.opponent_score}</td></tr>`).join("")
      || '<tr><td class="muted">試合はありません</td></tr>'}</table></div>`;
  $("sg-year").addEventListener("change", (e) => { st.gamesYear = Number(e.target.value); renderPage(); });
  body.querySelectorAll("tr.click").forEach((tr) => tr.addEventListener("click", () =>
    openMatch(Number(tr.dataset.year), tr.dataset.cid, tr.dataset.id)));
}

// ---- セーブ ----

// 確かめる・名前を聞く小さなダイアログ。OK なら入力（入力がなければ true）、やめたら null
function ask({ title, body = "", input = null, ok = "OK" }) {
  const dialog = $("ask-dialog");
  $("ask-title").textContent = title;
  $("ask-body").innerHTML = body;
  $("ask-ok").textContent = ok;
  const field = $("ask-input");
  field.hidden = input === null;
  field.value = input ?? "";
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => {
      if (dialog.returnValue !== "ok") return resolve(null);
      resolve(input === null ? true : field.value.trim());
    }, { once: true });
    dialog.returnValue = "";
    dialog.showModal();
    if (input !== null) field.select();
  });
}

async function renderSaves(content) {
  content.innerHTML = `<div class="head"><h2>セーブ</h2><div class="spacer"></div>
      <button class="btn" id="sv-save" type="button">今すぐセーブ</button>
      <button class="btn primary" id="sv-new" type="button">新しく始める…</button></div>
    <div class="note">${state.noSession
      ? "遊ぶセーブを読み込むか、新しく始めてください。"
      : "日付を進めるたびに自動セーブしています。読み込むと、そのセーブの続きから遊びます。"}</div>
    <div class="scroll" id="sv-body"><div class="empty">読み込み中…</div></div>`;
  $("sv-save").disabled = state.noSession;
  $("sv-save").addEventListener("click", async () => {
    const data = await call("save_now");
    if (data) { showToast("セーブしました"); drawSaves(data); }
  });
  $("sv-new").addEventListener("click", newSave);
  const data = await call("saves");
  if (data && state.page === "saves") drawSaves(data);
}

function drawSaves(data) {
  const body = $("sv-body");
  if (!body) return;
  if (!data.slots.length) {
    body.innerHTML = `<div class="empty">セーブがありません。</div>`;
    return;
  }
  body.innerHTML = `<table class="list"><thead><tr>
      <th>名前</th><th>ゲームの日付</th><th>保存した日時</th><th></th></tr></thead><tbody>
    ${data.slots.map((row) => `<tr class="${row.current ? "current" : ""}" data-slot="${esc(row.slot_id)}">
      <td>${esc(row.title)}${row.current ? `<span class="tag">遊んでいるセーブ</span>` : ""}</td>
      <td>${esc(row.date_label)}</td><td>${esc(row.saved_at)}</td>
      <td class="actions">
        ${row.current ? "" : `<button class="btn small" data-act="open" type="button"${row.loadable ? "" : " disabled"}>読み込む</button>`}
        <button class="btn small" data-act="rename" type="button">名前を変える</button>
        <button class="btn small" data-act="recover" type="button">前の状態に戻す…</button>
        ${row.current ? "" : `<button class="btn small" data-act="delete" type="button">削除</button>`}
      </td></tr>`).join("")}</tbody></table>`;
  body.querySelectorAll("button[data-act]").forEach((button) => button.addEventListener("click", () => {
    const slot = button.closest("tr").dataset.slot;
    const row = data.slots.find((r) => r.slot_id === slot);
    ({ open: openSave, rename: renameSave, recover: recoverSave, delete: deleteSave })[button.dataset.act](row);
  }));
}

async function renameSave(row) {
  const title = await ask({ title: "名前を変える", input: row.title });
  if (!title) return;
  const data = await call("rename_save", row.slot_id, title);
  if (data) drawSaves(data);
}

async function deleteSave(row) {
  const ok = await ask({
    title: "セーブを削除する",
    body: `「${esc(row.title)}」を削除します。自動セーブと前の状態も消え、元に戻せません。`,
    ok: "削除する",
  });
  if (!ok) return;
  const data = await call("delete_save", row.slot_id);
  if (data) { showToast("削除しました"); drawSaves(data); }
}

async function recoverSave(row) {
  const data = await call("recovery", row.slot_id);
  if (!data) return;
  const rows = data.sources.filter((s) => s.valid);
  if (!rows.length) return showToast("戻せる状態がありません", true);
  const body = `<div>戻す状態を選んでください。選んだ状態を手動セーブにして読み込みます。</div>
    <table class="list"><tbody>${rows.map((s, i) => `<tr>
      <td><label><input type="radio" name="ask-source" value="${esc(s.source)}"${i ? "" : " checked"}> ${esc(s.label)}</label></td>
      <td>${esc(s.date_label)}</td><td>${esc(s.saved_at)}</td></tr>`).join("")}</tbody></table>`;
  if (!await ask({ title: `「${row.title}」を前の状態に戻す`, body, ok: "戻して読み込む" })) return;
  const source = ($("ask-body").querySelector("input[name=ask-source]:checked") || {}).value;
  if (source) switchSave("open_save", row.slot_id, source);
}

async function openSave(row) {
  const ok = await ask({
    title: "セーブを読み込む",
    body: `「${esc(row.title)}」（${esc(row.date_label)}）を読み込みます。${state.noSession ? "" : "今のセーブの進み具合は自動セーブに残っています。"}`,
    ok: "読み込む",
  });
  if (ok) switchSave("open_save", row.slot_id, "latest");
}

async function newSave() {
  const title = await ask({
    title: "新しく始める",
    body: `<div>2026年4月1日から新しく始めます。${state.noSession ? "" : "今のセーブの進み具合は自動セーブに残っています。"}</div>
      <label class="field">スロット名（空なら自動）<input class="ask-input" id="ask-slot" type="text" maxlength="64" placeholder="slot01"></label>
      <label class="field">シード（空なら自動）<input class="ask-input" id="ask-seed" type="text" inputmode="numeric" maxlength="10"></label>
      <label class="field">名前</label>`,
    input: "新しいセーブ",
    ok: "始める",
  });
  if (title === null) return;
  if (!title) return showToast("名前を入れてください", true);
  switchSave("new_save", title, $("ask-slot").value.trim(), $("ask-seed").value.trim());
}

// セーブを切り替える（その間は他の呼び出しをしない）
async function switchSave(name, ...args) {
  setBusy(true);
  $("progress-title").textContent = name === "new_save" ? "新しく始めています" : "セーブを読み込んでいます";
  $("progress-date").textContent = "";
  $("progress-fill").style.width = "100%";
  let result;
  try {
    result = await api()[name](...args);
  } finally {
    setBusy(false);
  }
  if (result.error) return showToast(result.error, true);
  state.noSession = false;
  setBusy(false);
  state.competitions = { filter: { year: "", segment: "", level: "", status: "" }, view: null };
  state.recordsYear = null;
  state.matches = { date: "", detail: null };
  state.schools = { ...state.schools, data: null, view: [], selected: null, detail: null, tab: "overview" };
  state.bracket = null;
  renderHeader(result.header);
  showToast(name === "new_save" ? "新しく始めました" : "読み込みました");
  showPage("today");
}

// ---- 日付を進める ----

async function advance(options) {
  setBusy(true);
  if (options.mode === "day") {
    // 1日のときは、その日の試合を行っている間の表示だけにする
    $("progress-title").textContent = "試合を行っています";
    $("progress-sub").textContent =
      `${jpDate(state.header.date, false)}の${state.header.today_match_count}試合を行っています`;
    $("progress-fill").style.width = "100%";
  }
  const poll = options.mode === "day" ? null : setInterval(updateProgress, 250);
  let result;
  try {
    result = await api().advance(options);
  } finally {
    if (poll) clearInterval(poll);
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
  $("btn-day").disabled = busy || state.noSession;
  $("btn-bulk").disabled = busy || state.noSession;
  $("progress").hidden = !busy;
  if (busy) {
    $("progress-title").textContent = "日付を進めています";
    $("progress-date").textContent = state.header ? dotDate(state.header.date) : "";
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
    `<option value="${row.school_year}|${esc(row.competition_id)}">${esc(row.short_name)}</option>`).join("");
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
  if (shell.header) {
    renderHeader(shell.header);
  } else {
    // 起動時にセーブを選ぶ
    state.noSession = true;
    state.page = "saves";
    $("date-sub").textContent = "遊ぶセーブを選んでください";
  }
  renderMenu();
  renderPage();
  setBusy(false);
  $("btn-day").addEventListener("click", () => advance({ mode: "day" }));
  $("btn-bulk").addEventListener("click", openBulkDialog);
  $("bulk-dialog").addEventListener("close", onBulkClose);
}

window.addEventListener("pywebviewready", start);
