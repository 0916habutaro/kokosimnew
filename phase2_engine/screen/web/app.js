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
    player: null, // 選手の画面（学校ID・選手ID）
    coach: null, // 監督の画面（永久監督ID・戻り先）
  },
  recordsTab: "year",
  recordsBest8: {},
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

// ---- 画面の行き来（マウスの「戻る」「進む」ボタン） ----

const nav = { back: [], forward: [], current: null, restoring: false };

// いま開いている画面（メニュー・大会・試合・学校・年度など）
function location_() {
  return JSON.stringify({
    page: state.page,
    competition: state.competitions.view,
    matches: state.matches,
    school: state.schools.detail, tab: state.schools.tab, player: state.schools.player, coach: state.schools.coach,
    recordsYear: state.recordsYear || null,
    recordsTab: state.recordsTab, recordsBest8: state.recordsBest8,
  });
}

// 画面を描く前に呼ぶ。開く画面が変わったら、前の画面を「戻る」に積む
function recordLocation() {
  const here = location_();
  if (nav.restoring || here === nav.current) return;
  if (nav.current !== null) {
    nav.back.push(nav.current);
    if (nav.back.length > 100) nav.back.shift();
    nav.forward = [];
  }
  nav.current = here;
}

// 画面の中で決まった値（直近の試合日・年度など）を、いまの画面の記録に反映する
function refreshLocation() {
  nav.current = location_();
}

function goHistory(from, to) {
  if (state.busy || !from.length) return;
  to.push(nav.current);
  nav.current = from.pop();
  const saved = JSON.parse(nav.current);
  state.page = saved.page;
  state.competitions.view = saved.competition;
  state.matches = saved.matches;
  state.schools.detail = saved.school;
  state.schools.tab = saved.tab;
  state.schools.player = saved.player || null;
  state.schools.coach = saved.coach || null;
  state.recordsYear = saved.recordsYear;
  state.recordsTab = saved.recordsTab || "year";
  state.recordsBest8 = saved.recordsBest8 || {};
  nav.restoring = true;
  try {
    renderMenu();
    renderPage();
  } finally {
    nav.restoring = false;
  }
}

window.addEventListener("mouseup", (e) => {
  // 3＝戻る、4＝進む（マウスのサイドボタン）
  if (e.button !== 3 && e.button !== 4) return;
  e.preventDefault();
  if (e.button === 3) goHistory(nav.back, nav.forward);
  else goHistory(nav.forward, nav.back);
});
window.addEventListener("keydown", (e) => {
  if (!e.altKey) return;
  if (e.key === "ArrowLeft") goHistory(nav.back, nav.forward);
  if (e.key === "ArrowRight") goHistory(nav.forward, nav.back);
});

function renderPage() {
  recordLocation();
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

// 試合の表。列の幅を決めておき、校名の長さでスコアの列がずれないようにする
function matchTable(rows, line, widths) {
  return `<table class="list fixed"><colgroup>${widths.map((w) => `<col${w ? ` style="width:${w}px"` : ""}>`).join("")}</colgroup>${rows.map(line).join("")}</table>`;
}
const MATCH_LINE_COLS = [200, 0, 90, 0];
const MATCH_LINE_COLS_DATED = [200, 0, 90, 0, 100];

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
    `<tr class="click" data-open-year="${row.school_year}" data-open-id="${esc(row.competition_id)}"><td title="${esc(row.name)}">${esc(row.short_name)}</td><td class="muted">${row.next_date ? "次の試合 " + jpDate(row.next_date) : ""}</td></tr>`).join("");
  content.innerHTML = `<div class="head"><h2>今日</h2><span class="muted">${jpDate(header.date, false)}</span></div>
    <div class="scroll"><div class="split">
      <div>
        <div class="panel"><h3>今日の全国の試合</h3><div class="big">${header.today_match_count}<small class="muted" style="font-size:16px"> 試合</small></div></div>
        <div class="panel"><h3>注目の試合</h3>${data.featured.length
          ? matchTable(data.featured, matchLine, MATCH_LINE_COLS)
          : '<div class="muted">今日の試合はありません</div>'}</div>
      </div>
      <div>
        <div class="panel"><h3>直近の大きな結果</h3>${data.recent_results.length
          ? matchTable(data.recent_results, matchLine, MATCH_LINE_COLS_DATED)
          : '<div class="muted">最近の決勝はありません</div>'}</div>
        <div class="panel"><h3>開催中の大会</h3>${competitions ? `<table class="list">${competitions}</table>` : '<div class="muted">開催中の大会はありません</div>'}</div>
      </div>
    </div></div>`;
  content.querySelectorAll("tr.click[data-id]").forEach((tr) => tr.addEventListener("click", () =>
    openMatch(Number(tr.dataset.year), tr.dataset.cid, tr.dataset.id)));
  content.querySelectorAll("tr.click[data-open-id]").forEach((tr) => tr.addEventListener("click", () =>
    openCompetition(Number(tr.dataset.openYear), tr.dataset.openId)));
}

// 大会の画面（トーナメント表）を開く
function openCompetition(year, competitionId) {
  state.competitions.view = { year, id: competitionId };
  state.page = "competitions";
  renderMenu();
  renderPage();
}

// ---- 記録 ----

function recordsTabs() {
  return `<div class="tabs">${[["year", "年度別記録"], ["best8", "大会別ベスト8"]].map(([key, label]) =>
    `<button class="tab ${state.recordsTab === key ? "on" : ""}" data-records-tab="${key}">${label}</button>`).join("")}</div>`;
}

function bindRecordsTabs(content) {
  content.querySelectorAll("[data-records-tab]").forEach((button) => button.addEventListener("click", () => {
    state.recordsTab = button.dataset.recordsTab;
    renderPage();
  }));
}

async function renderBest8(content) {
  const requested = JSON.stringify(state.recordsBest8);
  const data = await call("records_best8", state.recordsBest8);
  if (requested !== JSON.stringify(state.recordsBest8)) return;
  if (!data || state.page !== "records" || state.recordsTab !== "best8") return;
  state.recordsBest8 = data.filters;
  refreshLocation();
  const f = data.filters;
  const select = (key, label, items) => `<label>${label} <select id="rb-${key}">${items.map(([value, text]) =>
    `<option value="${esc(value)}" ${String(f[key] || "") === String(value) ? "selected" : ""}>${esc(text)}</option>`).join("")}</select></label>`;
  const school = (s) => `<div><button class="link" data-school="${esc(s.school_id)}">${esc(s.name)}</button>${s.prefecture ? `<small class="muted">（${esc(s.prefecture)}）</small>` : ""}</div>`;
  const title = (r, text) => r.can_open ? `<button class="link" data-record-year="${r.school_year}" data-record-cid="${esc(r.competition_id)}">${esc(text)}</button>` : esc(text);
  content.innerHTML = `<div class="head"><h2>記録</h2>${recordsTabs()}</div>
    <div class="best8-filters">
      ${select("segment", "季節", SEGMENTS)} ${select("level", "大会区分", LEVELS)}
      ${select("region", "地域", [["", "すべて"], ...Object.entries(data.regions)])}
      ${select("prefecture", "都道府県", [["", "すべて"], ...Object.entries(data.prefectures)])}
      ${select("competition_id", "大会名", data.competitions.map((c) => [c.competition_id, c.name]))}
      ${select("count", "表示年数", [[5, "5年"], [10, "10年"], [20, "20年"]])}
      <form id="rb-range"><label>開始年度 <input id="rb-start" type="number" min="1" max="${data.latest}" placeholder="${data.start}" value="${esc(f.start || "")}"></label>
        <label>終了年度 <input id="rb-end" type="number" min="1" max="${data.latest}" placeholder="${data.end}" value="${esc(f.end || "")}"></label>
        <button class="btn" type="submit">表示</button><button class="btn" type="button" id="rb-latest">最新年度に戻す</button></form>
    </div>
    <div class="scroll best8-scroll"><p class="muted">${data.start}〜${data.end}年度。順位は本大会の完了後に表示します。校名は大会当時の名前です。</p>
      <table class="list best8-table"><colgroup><col style="width:95px"><col style="width:210px"><col><col><col style="width:220px"><col style="width:250px"><col style="width:100px"></colgroup>
        <thead><tr><th>年度</th><th>大会名</th><th>優勝</th><th>準優勝</th><th>ベスト4</th><th>ベスト8</th><th>状態</th></tr></thead>
        <tbody>${data.rows.map((r) => `<tr><td>${title(r, `${r.school_year}年度`)}</td><td>${title(r, r.competition_name || data.competitions.find((c) => c.competition_id === r.competition_id)?.name || r.competition_id)}</td>
          ${["優勝", "準優勝", "ベスト4", "ベスト8"].map((finish) => `<td>${r.groups[finish].map(school).join("") || '<span class="muted">−</span>'}</td>`).join("")}<td>${esc(r.status)}</td></tr>`).join("")}</tbody></table>
      ${data.rows.length ? "" : '<p class="muted">条件に合う大会はありません。</p>'}</div>`;
  bindRecordsTabs(content);
  for (const key of ["segment", "level", "region", "prefecture", "competition_id", "count"]) {
    $("rb-" + key).addEventListener("change", (e) => {
      state.recordsBest8[key] = e.target.value;
      // 年数変更は終了年度を維持し、その年数の範囲へ戻す。
      if (key === "count") delete state.recordsBest8.start;
      renderPage();
    });
  }
  $("rb-range").addEventListener("submit", (e) => {
    e.preventDefault();
    const start = $("rb-start").value, end = $("rb-end").value;
    if (start && end && Number(start) > Number(end)) return showToast("開始年度・終了年度を確認してください", true);
    Object.assign(state.recordsBest8, { start, end });
    renderPage();
  });
  $("rb-latest").addEventListener("click", () => {
    delete state.recordsBest8.start; delete state.recordsBest8.end;
    renderPage();
  });
  content.querySelectorAll("[data-school]").forEach((a) => a.addEventListener("click", () => openSchool(a.dataset.school)));
  content.querySelectorAll("[data-record-cid]").forEach((a) => a.addEventListener("click", () => openCompetition(Number(a.dataset.recordYear), a.dataset.recordCid)));
}

async function renderRecords(content) {
  if (state.recordsTab === "best8") return renderBest8(content);
  const data = await call("records", state.recordsYear || null);
  if (!data) return;
  state.recordsYear = data.school_year;
  refreshLocation();
  const school = (e) => `<span class="link" data-school="${esc(e.school_id)}">${esc(e.name)}</span><span class="muted">（${esc(e.prefecture)}）</span>`
    + (e.championship_count ? `<span class="muted">　${e.championship_count.total}回目の優勝${breakdown(e.championship_count)}</span>` : "");
  // 「12回目」と内訳（実際の記録＋ゲーム内）
  const breakdown = (c) => c.actual ? `（実際${c.actual}＋ゲーム${c.game}）` : "";
  const nth = (c) => c ? `<span class="num">${c.total}回目</span><span class="muted">${breakdown(c)}</span>` : "";
  const nationals = data.nationals.map((n) => `<div class="panel"><h3>${esc(n.competition_name)}${n.started && !n.finished ? '　<span class="badge active">開催中</span>' : ""}</h3>
    ${n.played ? `<table class="list">${["優勝", "準優勝", "ベスト4", "ベスト8"].map((f) => `<tr><td style="width:80px">${badge(f === "優勝" ? 3000 : f === "準優勝" ? 2000 : 0, f)}</td>
      <td>${(n.groups[f] || []).map(school).join("　") || '<span class="muted">−</span>'}</td></tr>`).join("")}</table>`
      : `<div class="muted">${n.started ? "始まったばかりです" : "まだ行われていません"}</div>`}</div>`).join("");
  const reps = data.representatives.map((r) => `<tr><td>${esc(r.area)}</td>
    <td>${r.school_id ? `<span class="link" data-school="${esc(r.school_id)}">${esc(r.name)}</span>` : '<span class="muted">未定</span>'}</td>
    <td>${nth(r.appearance)}</td>
    <td>${r.koshien ? badge(r.koshien === "優勝" ? 3000 : 0, r.koshien) : ""}</td></tr>`).join("");
  const senbatsu = data.senbatsu.map((r) => `<tr><td>${esc(r.prefecture)}</td><td><span class="link" data-school="${esc(r.school_id)}">${esc(r.name)}</span></td><td>${nth(r.appearance)}</td><td>${badge(r.finish === "優勝" ? 3000 : 0, r.finish)}</td></tr>`).join("");
  content.innerHTML = `<div class="head"><h2>記録</h2>${recordsTabs()}
      <select id="r-year">${data.years.map((y) => `<option value="${y}" ${y === data.school_year ? "selected" : ""}>${y}年度</option>`).join("")}</select></div>
    <div class="scroll">
      <div class="split">${nationals}</div>
      <div class="split">
        <div class="panel"><h3>夏の代表校</h3><table class="list"><tr><th>地区</th><th>代表校</th><th>出場</th><th>甲子園</th></tr>${reps}</table></div>
        <div class="panel"><h3>選抜の出場校</h3>${senbatsu ? `<table class="list"><tr><th>都道府県</th><th>学校</th><th>出場</th><th>成績</th></tr>${senbatsu}</table>` : '<div class="muted">まだ選ばれていません</div>'}</div>
      </div>
    </div>`;
  bindRecordsTabs(content);
  $("r-year").addEventListener("change", (e) => { state.recordsYear = Number(e.target.value); renderPage(); });
  content.querySelectorAll(".link[data-school]").forEach((a) => a.addEventListener("click", () => openSchool(a.dataset.school)));
}

// ---- 大会：一覧 → トーナメント表 ----

async function renderCompetitions(content) {
  const view = state.competitions.view;
  if (view) return renderBracketPage(content, view);
  const f = state.competitions.filter;
  if (!f.year) f.year = String(state.header.school_year);
  // 閉じた年度（前の年度）も選べる。見るだけ
  let data = await call("competitions", f.year);
  if (!data) return;
  if (!data.school_years.map(String).includes(f.year)) {
    f.year = String(state.header.school_year);
    data = await call("competitions", f.year);
    if (!data) return;
  }
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
  if (!data) {
    // 開いていた大会が見られないとき（記録のない年度など）は大会の一覧に戻す
    if (state.busy) return;
    state.competitions.view = null;
    return renderCompetitions(content);
  }
  state.bracket = data;
  const c = data.competition;
  content.innerHTML = `<div class="head">
      <button class="btn small" id="b-back">← 大会の一覧</button>
      <h2>${esc(c.name)}</h2><span class="badge ${c.status}">${esc(c.status_label)}</span>
      ${data.entrants.length ? `<div class="tabs">${[["bracket", "トーナメント表"], ["entrants", "出場校一覧"]].map(([key, label]) =>
        `<button class="tab ${(view.tab || "bracket") === key ? "on" : ""}" data-btab="${key}">${label}</button>`).join("")}</div>` : ""}
      <div class="spacer"></div>
      ${view.tab === "entrants" ? "" : `<div class="tabs"><button class="btn small" id="z-out" title="縮小">−</button>
      <button class="btn small" id="z-fit" title="全体">全体</button>
      <button class="btn small" id="z-in" title="拡大">＋</button></div>`}</div>
    ${view.tab === "entrants" ? entrantsView(data.entrants) : `<div class="body">
      <div class="paper-wrap" id="paper-wrap"></div>
      <aside class="side" id="b-side"><div class="empty">トーナメント表の試合（交点）を押すと<br>スコアが出ます。<br>学校名を押すと勝ち上がりが<br>青く表示されます。</div></aside>
    </div>`}`;
  $("b-back").addEventListener("click", () => { state.competitions.view = null; renderPage(); });
  content.querySelectorAll("[data-btab]").forEach((b) => b.addEventListener("click", () => {
    view.tab = b.dataset.btab;
    renderPage();
  }));
  if (view.tab === "entrants") {
    content.querySelectorAll(".erow").forEach((row) => row.addEventListener("click", () => showEntrant(view, row.dataset.entrant)));
    const first = data.entrants.find((r) => r.school_id === view.entrant) || data.entrants[0];
    if (first) showEntrant(view, first.school_id);
    return;
  }
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

// 全国大会の出場校一覧：左に一覧（2列、スクロールなしで全校）、右に選んだ学校の詳細
function entrantsView(rows) {
  const perColumn = Math.ceil(rows.length / 2);
  return `<div class="body">
    <div class="elist" style="grid-template-rows:repeat(${perColumn},1fr)">
      ${rows.map((r) => `<div class="erow" data-entrant="${esc(r.school_id)}">
        <span class="ename" title="${esc(r.name)}">${esc(r.name)}</span>
        ${r.basis_label ? `<span class="basis">${esc(r.basis_label)}</span>` : ""}
        <span class="ecount${r.appearance_label === "初出場" ? " first" : ""}">${esc(r.appearance_label)}</span>
        <span class="area-tag ${esc(r.region_id)}">${esc(r.area)}</span>
      </div>`).join("")}
    </div>
    <aside class="side" id="e-side"></aside>
  </div>`;
}

async function showEntrant(view, schoolId) {
  document.querySelectorAll(".erow").forEach((row) => row.classList.toggle("on", row.dataset.entrant === schoolId));
  const d = await call("entrant", view.year, view.id, schoolId);
  const side = $("e-side");
  if (!d || !side) return;
  view.entrant = schoolId;
  const a = d.abilities;
  const st = d.stats;
  const avg = (v) => v === null ? "—" : v.toFixed(3).replace(/^0/, "");
  const results = d.results.map((r) => `<h4>${esc(r.competition_name)}　<span class="muted">${esc(r.finish)}（${r.wins}勝${r.losses}敗）</span></h4>
    <table class="list small egames">${r.games.map((g) => `<tr class="click" data-cid="${esc(g.competition_id)}" data-mid="${esc(g.match_id)}">
      <td title="${esc(g.round_name)}">${esc(g.round_name)}</td><td class="${g.won ? "w" : "l"}">${g.won ? "○" : "●"}</td>
      <td class="num">${g.score === null ? "" : `${g.score}-${g.opponent_score}`}</td><td title="${esc(g.opponent_name)}">${esc(g.opponent_name)}</td></tr>`).join("")}</table>`).join("");
  side.innerHTML = `<h3>${esc(d.name)}</h3><div class="muted">${esc(d.prefecture)}</div>
    ${a ? `<div class="radar-row">${abilityRadar(a)}<div class="overall-rank"><span>総合</span>${rankHtml(a.overall)}</div></div>`
      : '<div class="muted">能力は今の年度の大会だけ出ます</div>'}
    <div class="estats">チーム打率 <b class="num">${avg(st.batting_average)}</b>　本塁打 <b class="num">${st.home_runs ?? "—"}</b>　防御率 <b class="num">${st.era === null ? "—" : st.era.toFixed(2)}</b></div>
    ${results || '<div class="muted">予選の成績はありません</div>'}
    <button class="btn" id="e-school">学校の詳細へ</button>`;
  $("e-school").addEventListener("click", () => openSchool(schoolId));
  side.querySelectorAll("tr.click").forEach((tr) => tr.addEventListener("click", () => openMatch(view.year, tr.dataset.cid, tr.dataset.mid)));
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
  const champion = main && (main.champion_id || main.champion_after_draw);
  paper.innerHTML = `<div class="title">${esc(c.name)}${champion ? `　<span class="champ">優勝 ${esc(name(champion))}</span>` : ""}</div>`;
  if (!main) {
    paper.innerHTML += `<div class="muted" style="color:#7a756a">本大会の組み合わせはまだ決まっていません。</div>`;
  } else {
    const row = document.createElement("div");
    row.className = "paper-row";
    row.append(bracketSvg(main, name));
    if ((main.later_rounds || []).length) row.append(laterRounds(main.later_rounds, name));
    paper.append(row);
  }
  wrap.replaceChildren(paper);
  if (data.other_matches.length) wrap.append(otherMatches(data.other_matches, name));
}

function bracketSvg(main, name) {
  const svg = svgEl("svg");
  // 校名の欄は、いちばん長い校名（都道府県つきを含む）に合わせる
  const longest = Math.max(0, ...main.rows.map((row) => name(row.school_id).length));
  const nameW = Math.max(NAME_W, Math.min(300, longest * 13 + 16));
  const X = (round) => nameW + round * COL_W;
  const Y = (y) => 26 + y * ROW + ROW / 2;
  // 準々決勝から抽選し直す大会は、優勝校の欄の代わりに右へ回戦の列を並べる
  // 優勝校の欄は校名（都道府県の順位つきを含む）の長さに合わせる
  const championW = main.champion_id ? name(main.champion_id).length * 14 + 50 : 150;
  const width = X(main.total_rounds) + ((main.later_rounds || []).length ? 24 : Math.max(150, championW));
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
      x: nameW - 8, y: Y(row.y) + 4, "text-anchor": "end",
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

// 前の回戦のあとに抽選する回戦（夏の甲子園の準々決勝から）。抽選前は「抽選待ち」
function laterRounds(rounds, name) {
  const box = document.createElement("div");
  box.className = "later";
  const view = state.competitions.view;
  box.innerHTML = rounds.map((r) => `<div class="later-round"><div class="rlabel">${esc(r.round_name)}</div>
    ${r.drawn ? r.matches.map((m) => `<div class="later-match click" data-id="${esc(m.match_id)}">
      <div class="${m.winner_id && m.winner_id === m.team1_id ? "w" : ""}"><span>${esc(name(m.team1_id))}</span><b>${m.team1_score ?? ""}</b></div>
      <div class="${m.winner_id && m.winner_id === m.team2_id ? "w" : ""}"><span>${esc(name(m.team2_id))}</span><b>${m.team2_score ?? ""}</b></div>
      ${m.match_date ? `<small>${slashDate(m.match_date)}</small>` : ""}</div>`).join("")
      : '<div class="later-wait">抽選待ち</div>'}</div>`).join("");
  box.querySelectorAll(".later-match").forEach((el) => el.addEventListener("click", () =>
    openMatch(view.year, view.id, el.dataset.id)));
  return box;
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
  refreshLocation();
  const groups = {};
  for (const m of data.matches) (groups[m.competition_name] ||= []).push(m);
  content.innerHTML = `<div class="head"><h2>試合</h2>
      <button class="btn small" id="d-prev" ${data.prev_date ? "" : "disabled"}>← 前の試合日</button>
      <span class="num" style="font-size:16px">${slashDate(data.date)}</span>
      <button class="btn small" id="d-next" ${data.next_date ? "" : "disabled"}>次の試合日 →</button>
      <div class="spacer"></div><span class="muted num">${data.matches.length} 試合</span></div>
    <div class="scroll">${Object.entries(groups).map(([competition, matches]) => `
      <div class="panel"><h3>${esc(competition)}</h3>${matchTable(matches, (m) => `<tr class="click" data-year="${m.school_year}" data-cid="${esc(m.competition_id)}" data-id="${esc(m.match_id)}">
        <td class="muted" title="${esc(m.round_name)}">${esc(m.round_name)}</td>
        <td style="text-align:right" class="${m.winner_id === m.team1_id ? "w" : ""}">${esc(m.team1_name)}</td>
        <td class="n" style="text-align:center">${m.status === "completed" ? `${m.team1_score} − ${m.team2_score}` : "−"}</td>
        <td class="${m.winner_id === m.team2_id ? "w" : ""}">${esc(m.team2_name)}</td></tr>`, [300, 0, 90, 0])}</div>`).join("") || '<div class="empty">この日の試合はありません。</div>'}</div>`;
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
    ${(m.batting[team] || []).map((b) => `<tr><td>${playerLink(team, b.player_id, b.name)}</td><td class="pos">${esc(b.position)}</td><td>${b.at_bats}</td><td>${b.hits}</td><td>${b.rbi}</td><td>${b.home_runs}</td><td>${b.walks}</td><td>${b.strikeouts}</td></tr>`).join("")}</table>`;
  const pitching = (team) => `<table class="stat-table"><tr><th>投手</th><th>回</th><th>球数</th><th>打者</th><th>安打</th><th>失点</th><th>自責</th><th>四球</th><th>三振</th></tr>
    ${(m.pitching[team] || []).map((p) => `<tr><td>${playerLink(team, p.player_id, p.name)}</td><td>${esc(p.innings)}</td><td>${p.pitches || ""}</td><td>${p.batters_faced}</td><td>${p.hits_allowed}</td><td>${p.runs_allowed}</td><td>${p.earned_runs}</td><td>${p.walks}</td><td>${p.strikeouts}</td></tr>`).join("")}</table>`;
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
  bindPlayerLinks(content);
}

// ---- 学校：一覧（見えている行だけ描く） → 詳細（タブ） ----

const SCHOOL_COLS = [
  ["pref", "都道府県"], ["name", "校名"], ["ownership", "設置者"],
  ["overall", "総合", 1], ["batting", "打撃", 1], ["pitching", "投手", 1],
  ["defense", "守備", 1], ["running", "走力", 1], ["record", "勝敗", 1], ["rate", "勝率", 1],
  ["best", "今年度の最高成績"],
];

// 学校能力のランク（S〜G）。数値は内部で持ち、境目は config/screen/screen_v1.json
function rankOf(value) {
  for (const [rank, min] of state.ranks || []) if (value >= min) return rank;
  return "G";
}

function rankHtml(value) {
  if (value === undefined || value === null) return "…";
  const rank = rankOf(value);
  return `<span class="rank r-${rank}">${rank}</span>`;
}

// 能力をバーやレーダーに描くときの幅（0〜1）。ランクの境目の広さに合わせる
function abilityScale(value) {
  const mins = (state.ranks || []).map(([, min]) => min);
  const top = mins.length ? mins[0] + 4 : 70, bottom = mins.length ? mins[mins.length - 1] - 6 : 40;
  return Math.max(0, Math.min(1, (value - bottom) / (top - bottom)));
}

function winRate(s) {
  const games = s.wins + s.losses;
  return games ? (s.wins / games).toFixed(3).replace(/^0/, "") : "−";
}
const RESULT_FILTERS = [
  ["", "成績すべて"], ["3000", "甲子園出場"], ["2000", "地区大会出場以上"], ["1012", "都道府県ベスト8以上"],
];
const RH = 32;

function openSchool(schoolId) {
  state.schools.detail = schoolId;
  state.schools.player = null;
  state.schools.coach = null;
  state.schools.tab = "overview";
  state.page = "schools";
  renderMenu();
  renderPage();
}

async function renderSchools(content) {
  const st = state.schools;
  if (st.coach) return renderCoach(content, st.coach);
  if (st.player) return renderPlayer(content, st.player);
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
  if (key === "rate") return s.wins + s.losses ? s.wins / (s.wins + s.losses) + (s.wins + s.losses) / 1e6 : -1;
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
    const ab = (key) => a ? rankHtml(a[key]) : "…";
    html += `<div class="grow ${s.school_id === st.selected ? "sel" : ""}" style="top:${i * RH}px" data-id="${esc(s.school_id)}">
      <div>${esc(s.prefecture)}</div><div title="${esc(s.official_name)}">${esc(s.name)}</div><div>${esc(s.ownership)}</div>
      <div class="n">${ab("overall")}</div><div class="n">${ab("batting")}</div><div class="n">${ab("pitching")}</div>
      <div class="n">${ab("defense")}</div><div class="n">${ab("running")}</div><div class="n">${s.wins}-${s.losses}</div>
      <div class="n">${winRate(s)}</div>
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
    <div class="stats" style="grid-template-columns:repeat(3,1fr)"><div class="stat"><b>${s.abilities ? rankHtml(s.abilities.overall) : "…"}</b><span>総合</span></div>
      <div class="stat"><b>${s.wins}-${s.losses}</b><span>今年度の勝敗</span></div>
      <div class="stat"><b>${games ? winRate(s) : "-"}</b><span>勝率</span></div></div>
    <div class="muted" style="font-size:12px">今年度の最高成績</div>
    <p>${s.best ? badge(s.best_score, s.best) : '<span class="muted">今年度の試合はまだありません</span>'}</p>
    <p><button class="btn" id="s-open">詳しく見る →</button></p>`;
  $("s-open").addEventListener("click", () => openSchool(schoolId));
}

const SCHOOL_TABS = [["overview", "概要"], ["yearly", "年度別成績"], ["koshien", "甲子園"], ["members", "部員"], ["games", "試合一覧"], ["coaches", "歴代監督"]];
const ABILITY_LABELS = [
  ["overall", "総合"], ["batting", "打撃"], ["contact", "ミート"], ["power", "長打"], ["discipline", "選球"],
  ["pitching", "投手"], ["ace", "エース"], ["pitching_depth", "投手層"], ["bullpen", "救援"],
  ["defense", "守備"], ["running", "走力"],
];
const HANDS = { R: "右", L: "左", S: "両" };

async function renderSchoolDetail(content, schoolId) {
  const st = state.schools;
  if (st.tab === "coaches") return renderSchoolCoaches(content, schoolId);
  const d = await call("school", schoolId);
  if (!d) return;
  content.innerHTML = `<div class="head"><button class="btn small" id="sd-back">← 学校の一覧</button>
      <h2>${esc(d.name)}</h2><span class="muted">${esc(d.prefecture)}・${esc(d.ownership)}　${esc(d.official_name)}</span>
      ${d.reputation_rank ? `<span class="muted">評判</span><span class="rank r-${d.reputation_rank}">${d.reputation_rank}</span>` : ""}
      <div class="spacer"></div><button class="btn small" id="sd-edit">編集…</button></div>
    ${d.coach ? `<div class="head"><span class="muted">監督</span><span><button class="link" data-coach="${esc(d.coach.coach_id)}">${esc(d.coach.display_name)}</button>　${d.coach.age}歳（在任${d.coach.tenure_years}年目）</span></div>` : ""}
    <div class="dtabs">${SCHOOL_TABS.filter(([k]) => k !== "coaches" || d.coach).map(([k, l]) => `<button class="dtab ${st.tab === k ? "on" : ""}" data-k="${k}">${l}</button>`).join("")}</div>
    <div class="scroll" id="sd-body"></div>`;
  bindCoachLinks(content);
  $("sd-back").addEventListener("click", () => { st.detail = null; renderPage(); });
  $("sd-edit").addEventListener("click", () => editSchool(d));
  content.querySelectorAll(".dtab").forEach((b) => b.addEventListener("click", () => { st.tab = b.dataset.k; renderPage(); }));
  const body = $("sd-body");
  if (st.tab === "overview") body.innerHTML = schoolOverview(d);
  if (st.tab === "yearly") body.innerHTML = schoolYearly(d);
  if (st.tab === "koshien") body.innerHTML = schoolKoshien(d);
  if (st.tab === "members") { body.innerHTML = schoolMembers(d); bindPlayerLinks(body); }
  if (st.tab === "games") await schoolGames(body, d);
}

function bindCoachLinks(root) {
  root.querySelectorAll("[data-coach]").forEach((el) => el.addEventListener("click", () => openCoach(el.dataset.coach)));
}

function openCoach(coachId) {
  const st = state.schools;
  st.coach = { id: coachId, school: st.detail, tab: st.tab };
  st.player = null;
  state.page = "schools";
  renderMenu();
  renderPage();
}

function tenureNote(d) {
  return `<p class="muted">離任日は異動・退任が有効になる日で、在任はその前日までです。${esc(d.simulation_start)}より前の在任期間は開始時に生成した設定で、実際に進めた過去の実績ではありません。</p>`;
}

function tenureRows(rows, person) {
  return rows.map((p) => `<tr>
    <td>${person ? `<button class="link" data-coach="${esc(p.coach_id)}">${esc(p.name)}</button>`
      : `<button class="link" data-coach-school="${esc(p.school_id)}">${esc(p.school_name)}</button>`}
      ${person ? `<div class="muted">${esc(p.school_name)}（${esc(p.name_basis)}の校名）</div>` : ""}
      ${p.school_name !== p.current_school_name ? `<div class="muted">現在：${esc(p.current_school_name)}</div>` : ""}</td>
    <td class="num">${dotDate(p.start_date)}${p.configured_past ? '<div class="muted">開始時の設定</div>' : ""}</td>
    <td class="num">${p.last_day ? dotDate(p.last_day) : "現在"}</td>
    <td class="num">${p.end_date ? dotDate(p.end_date) : "−"}</td>
    <td>${p.tenure_years}${p.end_date ? "年" : "年目"}</td><td>${esc(p.status)}</td></tr>`).join("");
}

function tenureTable(rows, person) {
  return `<table class="list"><tr><th>${person ? "監督" : "所属校"}</th><th>就任日</th><th>在任最終日</th><th>離任日</th><th>在任</th><th>区分</th></tr>${tenureRows(rows, person)}</table>`;
}

async function renderSchoolCoaches(content, schoolId) {
  const d = await call("school_coaches", schoolId);
  if (!d || state.page !== "schools" || state.schools.detail !== schoolId ||
      state.schools.tab !== "coaches" || state.schools.coach) return;
  content.innerHTML = `<div class="head"><button class="btn small" id="sc-back">← 学校の一覧</button><h2>${esc(d.name)}</h2></div>
    <div class="dtabs">${SCHOOL_TABS.map(([k,l]) => `<button class="dtab ${k === "coaches" ? "on" : ""}" data-k="${k}">${l}</button>`).join("")}</div>
    <div class="scroll"><div class="panel"><h3>歴代監督</h3>${tenureTable(d.coaches, true)}${tenureNote(d)}</div></div>`;
  $("sc-back").addEventListener("click", () => { state.schools.detail = null; renderPage(); });
  content.querySelectorAll(".dtab").forEach((b) => b.addEventListener("click", () => { state.schools.tab = b.dataset.k; renderPage(); }));
  bindCoachLinks(content);
}

async function renderCoach(content, target) {
  const d = await call("coach", target.id);
  if (!d || state.page !== "schools" || state.schools.coach !== target) return;
  const current = d.current_school;
  const record = d.official_record;
  content.innerHTML = `<div class="head"><button class="btn small" id="c-back">← 学校へ戻る</button><h2>${esc(d.name)}</h2><span>${esc(d.status)}</span></div>
    <div class="scroll"><div class="panel"><h3>人物・現在の所属</h3>
      <p>${d.age}歳（${d.birth_year}年生まれ）${d.retired_on ? `　退任日 ${dotDate(d.retired_on)}` : ""}</p>
      <p>${current ? `<button class="link" data-coach-school="${esc(current.school_id)}">${esc(current.name)}</button>　${d.appointment_year}年就任・在任${d.tenure_years}年目` : "現在の所属なし"}</p>
      <p class="muted">年齢と現在の在任年目は年度基準です。</p></div>
      <div class="panel"><h3>能力・采配傾向（1〜100）</h3><table class="list">${d.abilities.map((a) => `<tr><th>${esc(a.label)}</th><td class="n">${a.value}</td><td>${esc(a.description)}</td></tr>`).join("")}</table></div>
      <div class="panel"><h3>指揮した公式戦</h3><p>${record.wins}勝 ${record.losses}敗（${record.games}試合）</p>
      <p class="muted">${esc(record.from_date)}以降の保存された実試合を、試合日の所属で集計。不戦勝・不戦敗、開始前の記録は含みません。</p></div>
      ${coachTournamentView(d.tournament_record, d.simulation_start)}
      <div class="panel"><h3>在任・異動履歴</h3>${tenureTable(d.periods, false)}${tenureNote(d)}</div></div>`;
  $("c-back").addEventListener("click", () => {
    state.schools.coach = null;
    state.schools.detail = target.school;
    state.schools.tab = target.tab;
    renderPage();
  });
  content.querySelectorAll("[data-coach-school]").forEach((a) => a.addEventListener("click", () => openSchool(a.dataset.coachSchool)));
  content.querySelectorAll("[data-coach-cid]").forEach((a) => a.addEventListener("click", () => {
    state.competitions.view = { year: Number(a.dataset.coachYear), id: a.dataset.coachCid };
    state.page = "competitions";
    renderMenu();
    renderPage();
  }));
}

function coachTournamentView(data, start) {
  const link = (r, text) => `<button class="link" data-coach-cid="${esc(r.competition_id)}" data-coach-year="${r.school_year}">${esc(text)}</button>`;
  const school = (r) => `${esc(r.school_name)}${r.school_name !== r.current_school_name ? `<div class="muted">現在：${esc(r.current_school_name)}</div>` : ""}`;
  return `<div class="panel"><h3>大会実績</h3><table class="list">
    <tr><th>大会区分</th><th>出場回数</th><th>優勝回数</th><th>最高成績</th></tr>
    ${data.summary.map((r) => `<tr><td>${esc(r.label)}</td><td class="n">${r.appearances ?? "−"}</td><td class="n">${r.championships}</td><td>${esc(r.best_finish || "−")}</td></tr>`).join("")}</table>
    <p class="muted">出場は本大会に登録され最初の実試合を指揮した監督、最終成績は大会完了後に決勝・敗退戦を指揮した監督へ計上します。同じ大会は各回数に1回まで。途中交代では「出場0回・優勝1回」もあります。${esc(start)}より前の出来事や、不戦で決まった最終成績は加算しません。</p>
    <table class="list"><tr><th>大会年度</th><th>大会</th><th>学校</th><th>本人の記録</th><th>出場の確認日</th><th>成績の決定日</th></tr>
    ${data.records.map((r) => `<tr><td>${link(r, `${r.school_year}年度`)}</td><td>${link(r, r.competition_name)}</td><td>${school(r)}</td>
      <td>${link(r, [r.appearance ? "出場" : "", r.personal_finish || ""].filter(Boolean).join("・"))}</td>
      <td>${r.appearance ? dotDate(r.first_game_date) : "−"}</td><td>${r.personal_finish ? dotDate(r.decision_date) : "−"}</td></tr>`).join("")}</table>
    ${data.records.length ? "" : '<p class="muted">確認できる大会実績はまだありません。</p>'}</div>
    <div class="panel"><h3>所属校に関係する参考記録（本人の実績には加算しない）</h3>
    <p class="muted">開催期間（予定日を含む）と在任期間が重なる学校の公式結果です。監督への帰属を意味しません。不戦を含む大会の公式結果自体は変更しません。</p>
    <table class="list"><tr><th>大会年度</th><th>大会</th><th>学校</th><th>区分</th><th>決着</th><th>学校の最終成績</th></tr>
    ${data.references.map((r) => `<tr><td>${link(r, `${r.school_year}年度`)}</td><td>${link(r, r.competition_name)}</td><td>${school(r)}</td>
      <td>${esc(r.label)}</td><td>${esc(r.resolution)}</td><td>${link(r, r.finish)}</td></tr>`).join("")}</table>
    ${data.references.length ? "" : '<p class="muted">該当する参考記録はありません。</p>'}</div>`;
}

// 学校の編集（そのセーブの中だけ。実際の校名変更・実状に合わせる）
const INFO_LABELS = { display_name: "表示名", short_name: "短い名前", ownership_type: "設置者" };

async function editSchool(d) {
  const e = d.edit;
  const rep = e.reputation;
  const owner = (v) => (e.ownership_options.find((o) => o.value === v) || {}).label || v;
  const history = e.history.map((h) => `<tr><td>${esc(h.date)}</td><td>${Object.entries(h.changes).map(([k, v]) => `${INFO_LABELS[k]}：${esc(k === "ownership_type" ? owner(v) : v)}`).join("、")}</td></tr>`).join("");
  const teamHistory = e.team_history.map((h) => `<tr><td>${esc(h.date)}</td><td>総合力 ${h.before.toFixed(1)} → ${h.achieved.toFixed(1)}（指定 ${h.requested.toFixed(1)}）</td></tr>`).join("");
  const body = `<p>変更はこのセーブに保存します。</p>
    <label class="field">編集する項目<select id="ed-operation" class="ask-input">
      <option value="info">学校の情報</option>${e.team_editable ? '<option value="team">現在のチームの強さ</option>' : ""}
      ${rep ? '<option value="reputation">学校の評判</option>' : ""}</select></label>
    <fieldset id="ed-info"><legend>学校の情報</legend>
      <label class="field">表示名<input class="ask-input" id="ed-display" required type="text" maxlength="60" value="${esc(e.display_name)}"></label>
      <label class="field">短い名前<input class="ask-input" id="ed-short" required type="text" maxlength="20" value="${esc(e.short_name)}"></label>
      <label class="field">設置者<select class="ask-input" id="ed-owner">${e.ownership_options.map((o) => `<option value="${esc(o.value)}" ${o.value === e.ownership_type ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select></label>
      <p>変更日より前の試合は当時の名前で表示します。</p>
      ${history ? `<table class="list">${history}</table>` : ""}</fieldset>
    ${e.team_editable ? `<fieldset id="ed-team" hidden disabled><legend>現在のチームの強さ</legend>
      <p>現在の総合力：${d.abilities ? d.abilities.overall.toFixed(1) : "−"}。現在の部員の能力を調整します。新入生への一律補正はありません。</p>
      <label class="field">指定方法<select id="ed-team-kind"><option value="number">数値</option><option value="rank">ランク</option></select></label>
      <input class="ask-input" id="ed-target" type="number" min="1" max="100" step="0.1" required value="${d.abilities?.overall || 50}">
      <select class="ask-input" id="ed-rank" hidden>${e.team_ranks.map((r) => `<option>${r}</option>`).join("")}</select>
      <button class="btn small" type="button" id="ed-preview">変更結果を確認</button><p id="ed-preview-result" role="status"></p>
      ${teamHistory ? `<table class="list">${teamHistory}</table>` : ""}</fieldset>` : ""}
    ${rep ? `<fieldset id="ed-reputation" hidden disabled><legend>学校の評判</legend>
      <p>現在値：${rep.current.toFixed(3)}（ランク ${esc(rep.rank)}）。${rep.setting ? `指定値：${rep.setting.requested}／${rep.setting.mode === "fixed" ? "固定" : "自動変動"}（${esc(rep.setting.date)}）` : "指定はありません。"}</p>
      <label class="field">評判値（${rep.minimum}〜${rep.maximum}。大きいほど高評価）<input class="ask-input" id="ed-rep-value" type="number" min="${rep.minimum}" max="${rep.maximum}" step="any" required value="${rep.current}"></label>
      <label class="field">年度更新<select class="ask-input" id="ed-rep-mode"><option value="automatic" ${rep.setting?.mode !== "fixed" ? "selected" : ""}>成績に応じて自動変動</option><option value="fixed" ${rep.setting?.mode === "fixed" ? "selected" : ""}>指定した評判値を固定</option></select></label>
      <p>今いる選手の能力は変えず、翌4月以降の新入生に反映します。固定中も他校の変動で全国順位・ランクは変わります。</p></fieldset>` : ""}`;
  const teamTarget = () => $("ed-team-kind").value === "rank" ? $("ed-rank").value : $("ed-target").valueAsNumber;
  const updated = await ask({ title: `「${d.name}」を編集する`, body, ok: "保存する",
    mount: () => {
      $("ed-operation").addEventListener("change", () => {
        for (const key of ["info", "team", "reputation"]) {
          const field = $(`ed-${key}`);
          if (field) { field.hidden = key !== $("ed-operation").value; field.disabled = field.hidden; }
        }
      });
      if (e.team_editable) {
        $("ed-team-kind").addEventListener("change", () => {
          const numeric = $("ed-team-kind").value === "number";
          $("ed-target").hidden = $("ed-target").disabled = !numeric;
          $("ed-rank").hidden = $("ed-rank").disabled = numeric;
          $("ed-preview-result").textContent = "";
        });
        $("ed-preview").addEventListener("click", async () => {
          if (!$("ed-target").disabled && !$("ed-target").reportValidity()) return;
          const button = $("ed-preview"); const output = $("ed-preview-result"); button.disabled = true;
          try {
            const r = await api().preview_team(d.school_id, teamTarget());
            output.textContent = r.error || (r.reached ? `総合力 ${r.before.toFixed(1)} → ${r.achieved.toFixed(1)}。保存すると反映します。` : r.reason);
          } catch (error) { output.textContent = String(error); }
          finally { button.disabled = false; }
        });
      }
    },
    submit: async () => {
      const operation = $("ed-operation").value;
      const payload = operation === "info" ? {
        operation, display_name: $("ed-display").value.trim(), short_name: $("ed-short").value.trim(), ownership_type: $("ed-owner").value,
      } : operation === "team" ? { operation, target: teamTarget() } : {
        operation, value: $("ed-rep-value").valueAsNumber, mode: $("ed-rep-mode").value,
      };
      return api().edit_school(d.school_id, payload);
    },
  });
  if (!updated) return;
  state.schools.data = null;
  showToast(updated.result ? `総合力を ${updated.result.achieved.toFixed(1)} に変更しました` : "保存しました");
  renderPage();
}

function schoolOverview(d) {
  const a = d.abilities;
  const bars = a ? ABILITY_LABELS.map(([k, l]) =>
    `<span>${l}</span><div class="bar"><div style="width:${Math.round(abilityScale(a[k]) * 100)}%"></div></div><span>${rankHtml(a[k])}</span>`).join("")
    : '<span class="muted">能力は選手で試合をしているときに出ます</span>';
  const rows = d.this_year.map((r) => `<tr><td>${esc(r.competition_name)}</td><td class="n">${r.wins}-${r.losses}</td><td>${badge(r.score, r.finish)}</td></tr>`).join("");
  return `<div class="split">
    <div class="panel"><h3>能力</h3>${a ? `<div class="radar-row">${abilityRadar(a)}
      <div class="overall-rank"><span>総合</span>${rankHtml(a.overall)}</div></div>` : ""}<div class="bars">${bars}</div></div>
    <div class="panel"><h3>${d.school_year}年度の成績</h3>${rows ? `<table class="list"><tr><th>大会</th><th class="n">勝敗</th><th>成績</th></tr>${rows}</table>` : '<div class="muted">まだ試合をしていません</div>'}</div>
  </div>`;
}

// 能力のレーダーチャート（ミート・長打・走力・守備・エース・投手層）。総合は横に大きく出す
const RADAR_AXES = [["contact", "ミート"], ["power", "長打"], ["running", "走力"], ["defense", "守備"], ["ace", "エース"], ["pitching_depth", "投手層"]];

function abilityRadar(a) {
  const size = 260, center = size / 2, radius = 88;
  const point = (i, r) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / RADAR_AXES.length;
    return [center + Math.cos(angle) * r, center + Math.sin(angle) * r];
  };
  const ring = (r) => RADAR_AXES.map((_, i) => point(i, r).join(",")).join(" ");
  const rings = [0.25, 0.5, 0.75, 1].map((f) => `<polygon points="${ring(radius * f)}" class="ring"/>`).join("");
  const spokes = RADAR_AXES.map((_, i) => `<line x1="${center}" y1="${center}" x2="${point(i, radius)[0]}" y2="${point(i, radius)[1]}" class="ring"/>`).join("");
  const shape = RADAR_AXES.map(([k], i) => point(i, radius * abilityScale(a[k])).join(",")).join(" ");
  const labels = RADAR_AXES.map(([k, l], i) => {
    const [x, y] = point(i, radius + 22);
    return `<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="middle">${l} <tspan class="r-${rankOf(a[k])}">${rankOf(a[k])}</tspan></text>`;
  }).join("");
  return `<svg class="radar" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">${rings}${spokes}<polygon points="${shape}" class="shape"/>${labels}</svg>`;
}

function schoolYearly(d) {
  const cell = (part) => part.best ? `${esc(part.best)}<span class="muted num">　${part.wins}-${part.losses}</span>` : '<span class="muted">−</span>';
  return `<div class="panel"><table class="list"><tr><th>年度</th><th>春</th><th>夏</th><th>秋</th><th class="n">勝敗</th></tr>
    ${d.yearly.map((y) => `<tr><td class="num">${y.school_year}</td><td>${cell(y.spring)}</td><td>${cell(y.summer)}</td><td>${cell(y.autumn)}</td><td class="n">${y.wins}-${y.losses}</td></tr>`).join("")}
  </table></div>`;
}

// 甲子園：合計（実際＋ゲーム内）と内訳。実際の記録がない学校はゲーム内だけ
function schoolKoshien(d) {
  // 出場のない学校も同じ表にし、ない値は「—」
  const NONE = "—";
  const record = (p) => p && p.appearances ? `${p.wins}-${p.losses}${p.draws ? `-${p.draws}` : ""}` : NONE;
  const champs = (p) => p && p.appearances ? String(p.championships || 0) : NONE;
  const best = (p) => esc((p && p.best) || NONE);
  // 出場した年：一覧がある学校は年を並べ、ない学校は「最近の出場 YYYY年」
  const years = (p) => {
    if (!p || !p.appearances) return NONE;
    if (p.years && p.years.length) return p.years.join("、");
    return p.last_year ? `最近の出場 ${p.last_year}年` : NONE;
  };
  const block = (label, until, k) => {
    const t = k.total;
    const row = (name, p) => `<tr><td>${name}</td><td class="n">${p ? p.appearances : 0}</td><td class="n">${record(p)}</td>
      <td class="n">${champs(p)}</td><td>${best(p)}</td><td class="num">${years(p)}</td></tr>`;
    return `<div class="panel"><h3>${label}</h3>
      <div class="stats"><div class="stat"><b>${t.appearances}</b><span>出場回数</span></div>
        <div class="stat"><b>${record(t)}</b><span>通算勝敗</span></div>
        <div class="stat"><b>${champs(t)}</b><span>優勝</span></div>
        <div class="stat"><b>${best(t)}</b><span>最高成績</span></div>
        <div class="stat"><b>${t.last_year ? `${t.last_year}年` : NONE}</b><span>最近の出場</span></div></div>
      <table class="list"><tr><th>内訳</th><th class="n">出場</th><th class="n">勝敗</th><th class="n">優勝</th><th>最高成績</th><th>出場した年</th></tr>
        ${row(`実際の記録（${until}まで）`, k.actual)}
        ${row("ゲーム内の記録", k.game)}
      </table></div>`;
  };
  return block("夏の甲子園", "2025年", d.koshien.summer) + block("春の選抜", "2026年", d.koshien.spring);
}

function schoolMembers(d) {
  if (!d.members.length) return '<div class="empty">部員は選手で試合をしているときに出ます。</div>';
  return `<div class="panel"><table class="list"><tr><th>名前</th><th>学年</th><th>出身</th><th>守備位置</th><th>投打</th><th>状態</th></tr>
    ${d.members.map((m) => `<tr><td>${playerLink(d.school_id, m.player_id, m.name)}</td><td>${m.grade}年</td><td>${esc(m.hometown)}</td><td>${esc(m.position)}</td><td>${HANDS[m.throws] || m.throws}投${HANDS[m.bats] || m.bats}打</td><td>${injuryBadge(m.injury)}</td></tr>`).join("")}
  </table></div>`;
}

// ---- 選手 ----

// 怪我の印と復帰の見込み
function injuryBadge(injury) {
  if (!injury) return "";
  return `<span class="badge injury">怪我（${esc(injury.label)}）</span> <span class="muted">${slashDate(injury.return_date)}ごろ復帰</span>`;
}

function playerLink(schoolId, playerId, name) {
  return playerId ? `<span class="link" data-player="${esc(playerId)}" data-player-school="${esc(schoolId)}">${esc(name)}</span>` : esc(name);
}

function bindPlayerLinks(root) {
  root.querySelectorAll(".link[data-player]").forEach((a) => a.addEventListener("click", () =>
    openPlayer(a.dataset.playerSchool, a.dataset.player)));
}

function openPlayer(schoolId, playerId) {
  state.schools.detail = schoolId;
  state.schools.player = { school: schoolId, id: playerId };
  state.schools.coach = null;
  state.page = "schools";
  renderMenu();
  renderPage();
}

function abilityCell(item) {
  if (!item || item.value == null) return '<td class="n muted">−</td>';
  return item.rank
    ? `<td class="n"><span class="rank r-${item.rank}">${item.rank}</span> <span class="muted">${item.value}</span></td>`
    : `<td class="n">${item.value}<span class="muted">km/h</span></td>`;
}

async function renderPlayer(content, target) {
  const p = await call("player", target.school, target.id);
  if (!p) return;
  const hands = `${HANDS[p.throws] || p.throws}投${HANDS[p.bats] || p.bats}打`;
  const abilities = p.abilities.length ? `<table class="list">${p.abilities.map((a) => `<tr><td>${esc(a.label)}</td>${abilityCell(a)}</tr>`).join("")}</table>`
    : '<div class="muted">今の能力は在学中の選手だけ出ます。</div>';
  const pitches = p.pitches.length ? `<h3 style="margin-top:12px">変化球</h3><table class="list"><tr><th>球種</th><th class="n">質</th><th class="n">制球</th><th class="n">割合</th></tr>
    ${p.pitches.map((x) => `<tr><td>${esc(x.label)}</td><td class="n">${x.quality}</td><td class="n">${x.command}</td><td class="n">${x.usage}%</td></tr>`).join("")}</table>` : "";
  const trend = p.trend.length ? `<table class="list"><tr><th>能力</th>${p.trend.map((t) => `<th class="n">${t.grade}年 ${esc(t.label)}<br><small class="muted">${t.school_year}年度</small></th>`).join("")}</tr>
    ${p.trend_keys.map((k) => `<tr><td>${esc(k.label)}</td>${p.trend.map((t) => abilityCell(t.values[k.key])).join("")}</tr>`).join("")}</table>`
    : '<div class="muted">まだ記録がありません。</div>';
  const bat = p.seasons.filter((s) => s.batting);
  const pit = p.seasons.filter((s) => s.pitching);
  const batting = bat.length ? `<table class="list"><tr><th>年度</th><th class="n">試合</th><th class="n">打席</th><th class="n">打数</th><th class="n">安打</th><th class="n">本塁打</th><th class="n">打点</th><th class="n">四球</th><th class="n">三振</th><th class="n">盗塁</th><th class="n">打率</th></tr>
    ${bat.map((s) => { const b = s.batting; return `<tr><td>${s.school_year}年度（${s.grade}年）</td><td class="n">${b.games}</td><td class="n">${b.plate_appearances}</td><td class="n">${b.at_bats}</td><td class="n">${b.hits}</td><td class="n">${b.home_runs}</td><td class="n">${b.rbi}</td><td class="n">${b.walks}</td><td class="n">${b.strikeouts}</td><td class="n">${b.stolen_bases}</td><td class="n">${b.average}</td></tr>`; }).join("")}</table>`
    : '<div class="muted">公式戦の打席はまだありません。</div>';
  const pitching = pit.length ? `<h3 style="margin-top:12px">投手</h3><table class="list"><tr><th>年度</th><th class="n">登板</th><th class="n">投球回</th><th class="n">球数</th><th class="n">被安打</th><th class="n">失点</th><th class="n">自責</th><th class="n">四球</th><th class="n">三振</th><th class="n">防御率</th></tr>
    ${pit.map((s) => { const x = s.pitching; return `<tr><td>${s.school_year}年度（${s.grade}年）</td><td class="n">${x.games}</td><td class="n">${esc(x.innings)}</td><td class="n">${x.pitches}</td><td class="n">${x.hits_allowed}</td><td class="n">${x.runs_allowed}</td><td class="n">${x.earned_runs}</td><td class="n">${x.walks}</td><td class="n">${x.strikeouts}</td><td class="n">${x.era}</td></tr>`; }).join("")}</table>` : "";
  content.innerHTML = `<div class="head"><button class="btn small" id="p-back">← ${esc(p.school_name)}</button>
      <h2>${esc(p.name)}</h2><span class="muted">${esc(p.school_name)}　${p.status === "在学" ? `${p.grade}年` : esc(p.status)}・${esc(p.position)}・${hands}</span>
      ${injuryBadge(p.injury)}${p.edit ? '<div class="spacer"></div><button class="btn small" id="p-edit">能力を編集…</button>' : ""}</div>
    <div class="scroll">
      <div class="stats" style="grid-template-columns:repeat(4,1fr)">
        <div class="stat"><b>${esc(p.hometown)}</b><span>出身</span></div>
        <div class="stat"><b>${p.entry_year}年</b><span>入学</span></div>
        <div class="stat"><b>${p.status === "在学" ? `${p.grade}年` : esc(p.status)}</b><span>学年</span></div>
        <div class="stat"><b>${esc(p.growth_type) || "−"}</b><span>成長の型</span></div>
      </div>
      <div class="cols">
        <div class="panel"><h3>今の能力</h3>${abilities}${pitches}</div>
        <div class="panel"><h3>学年ごとの能力の推移</h3>${trend}</div>
      </div>
      <div class="panel" style="margin-top:14px"><h3>成績（公式戦）</h3>${batting}${pitching}</div>
      <div class="panel" style="margin-top:14px"><h3>怪我の履歴</h3>${p.injuries.length
        ? `<table class="list"><tr><th>重さ</th><th>休み始めた日</th><th>復帰（見込み）</th><th class="n">日数</th></tr>
          ${p.injuries.map((i) => `<tr><td>${esc(i.label)}</td><td>${slashDate(i.start)}</td><td>${slashDate(i.return_date)}</td><td class="n">${i.days}</td></tr>`).join("")}</table>`
        : '<div class="muted">怪我はしていません。</div>'}</div>
    </div>`;
  if (p.edit) $("p-edit").addEventListener("click", () => editPlayer(p));
  $("p-back").addEventListener("click", () => { state.schools.player = null; state.schools.tab = "members"; renderPage(); });
}

async function editPlayer(p) {
  const e = p.edit;
  const numeric = (f, prefix) => `<label>${esc(f.label)}<input type="number" id="${prefix}-${f.key}" required min="${f.minimum}" max="${f.maximum}" step="1" value="${f.value}"></label>`;
  const pitchOptions = (value) => e.pitch_types.map((t) => `<option value="${esc(t.key)}" ${t.key === value ? "selected" : ""}>${esc(t.label)}</option>`).join("");
  const pitchRow = (pitch = { pitch_type: "slider", quality: 50, command: 50, usage: 1 }) => `<tr><td><select class="pe-type">${pitchOptions(pitch.pitch_type)}</select></td>${["quality", "command", "usage"].map((k) => `<td><input class="pe-${k}" type="number" required min="1" max="100" step="1" value="${pitch[k]}"></td>`).join("")}<td><button type="button" class="btn small pe-remove">削除</button></td></tr>`;
  const body = `<p>怪我・復帰の補正を掛ける前の能力を編集します。保存後も成長と怪我の経過は続きます。</p>
    <fieldset><legend>能力</legend><div class="ability-edit-grid">${e.fields.map((f) => numeric(f, "pe")).join("")}</div></fieldset>
    <fieldset><legend>守備適性</legend><div class="ability-edit-grid">${e.aptitudes.map((f) => numeric(f, "pa")).join("")}</div></fieldset>
    ${e.pitches.length ? `<fieldset><legend>球種</legend><p>2〜4種類・ストレート必須・重複なし・割合の合計100にしてください。</p>
      <table class="list pitch-edit"><thead><tr><th>球種</th><th>質</th><th>制球</th><th>割合</th><th></th></tr></thead><tbody id="pe-pitches">${e.pitches.map((p) => pitchRow(p)).join("")}</tbody></table>
      <button class="btn small" id="pe-add" type="button">球種を追加</button></fieldset>` : ""}
    ${e.history.length ? `<p>前回の編集：${esc(e.history[e.history.length - 1].date)}</p>` : ""}`;
  const updated = await ask({ title: `${p.name} の能力を編集`, body, ok: "保存する",
    mount: () => {
      if (!e.pitches.length) return;
      $("pe-pitches").addEventListener("click", (event) => {
        if (event.target.classList.contains("pe-remove")) event.target.closest("tr").remove();
      });
      $("pe-add").addEventListener("click", () => {
        if ($("pe-pitches").rows.length >= 4) return;
        $("pe-pitches").insertAdjacentHTML("beforeend", pitchRow());
      });
    },
    submit: async () => {
      const payload = Object.fromEntries(e.fields.map((f) => [f.key, $(`pe-${f.key}`).valueAsNumber]));
      payload.position_aptitude = Object.fromEntries(e.aptitudes.map((f) => [f.key, $(`pa-${f.key}`).valueAsNumber]));
      if (e.pitches.length) payload.pitch_repertoire = Array.from($("pe-pitches").rows).map((row) => ({
        pitch_type: row.querySelector(".pe-type").value,
        ...Object.fromEntries(["quality", "command", "usage"].map((key) => [key, row.querySelector(`.pe-${key}`).valueAsNumber])),
      }));
      return api().edit_player(p.school_id, p.player_id, payload);
    },
  });
  if (!updated) return;
  state.schools.data = null;
  showToast("能力を保存しました");
  renderPage();
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
function ask({ title, body = "", input = null, ok = "OK", mount = null, submit = null }) {
  const dialog = $("ask-dialog");
  $("ask-title").textContent = title;
  $("ask-body").innerHTML = body + '<p id="ask-error" class="edit-error" role="alert" hidden></p>';
  $("ask-ok").textContent = ok;
  const field = $("ask-input");
  field.hidden = input === null;
  field.value = input ?? "";
  const form = dialog.querySelector("form");
  $("ask-cancel").onclick = () => dialog.close("cancel");
  return new Promise((resolve) => {
    let saved = null;
    let saving = false;
    const handler = async (event) => {
      if (!submit || event.submitter?.value === "cancel") return;
      event.preventDefault();
      if (saving) return;
      saving = true;
      const controls = Array.from(form.querySelectorAll("input, select, button"), (node) => [node, node.disabled]);
      controls.forEach(([node]) => { node.disabled = true; });
      $("ask-error").hidden = true;
      try {
        saved = await submit();
        if (!saved || saved.error) throw new Error(saved?.error || "保存できませんでした");
        dialog.close("ok");
      } catch (error) {
        $("ask-error").textContent = error.message || String(error);
        $("ask-error").hidden = false;
        $("ask-error").scrollIntoView({ block: "nearest" });
      } finally {
        saving = false;
        controls.forEach(([node, disabled]) => { node.disabled = disabled; });
      }
    };
    form.addEventListener("submit", handler);
    // 保存中にEscapeで閉じて別の編集を開くのを防ぐ。
    const cancel = (event) => { if (saving) event.preventDefault(); };
    dialog.addEventListener("cancel", cancel);
    dialog.addEventListener("close", () => {
      form.removeEventListener("submit", handler);
      dialog.removeEventListener("cancel", cancel);
      if (dialog.returnValue !== "ok") return resolve(null);
      resolve(submit ? saved : input === null ? true : field.value.trim());
    }, { once: true });
    dialog.returnValue = "";
    dialog.showModal();
    if (mount) mount();
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
    <div class="note" id="sv-setting"></div>
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
  state.injuryLevels = data.injury;
  const setting = $("sv-setting");
  if (setting) {
    const inj = data.injury;
    setting.innerHTML = inj.current ? `このセーブの設定：怪我の頻度 <select id="sv-injury">${inj.levels.map((l) =>
      `<option value="${esc(l.id)}"${l.id === inj.current ? " selected" : ""}>${esc(l.label)}</option>`).join("")}</select>` : "";
    const select = $("sv-injury");
    if (select) select.addEventListener("change", async () => {
      const result = await call("set_injury_level", select.value);
      if (result) { showToast("怪我の頻度を変えました"); drawSaves(result); }
    });
  }
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
      ${state.injuryLevels ? `<label class="field">怪我の頻度（遊んでいる途中でもセーブの画面で変えられます）<select id="ask-injury">${state.injuryLevels.levels.map((l) =>
        `<option value="${esc(l.id)}"${l.id === state.injuryLevels.default ? " selected" : ""}>${esc(l.label)}</option>`).join("")}</select></label>` : ""}
      <label class="field">名前</label>`,
    input: "新しいセーブ",
    ok: "始める",
  });
  if (title === null) return;
  if (!title) return showToast("名前を入れてください", true);
  switchSave("new_save", title, $("ask-slot").value.trim(), $("ask-seed").value.trim(),
    ($("ask-injury") || {}).value || "");
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
  // 別のセーブの画面へは戻らない
  Object.assign(nav, { back: [], forward: [], current: null });
  state.competitions = { filter: { year: "", segment: "", level: "", status: "" }, view: null };
  state.recordsYear = null;
  state.recordsTab = "year";
  state.recordsBest8 = {};
  state.matches = { date: "", detail: null };
  state.schools = { ...state.schools, data: null, view: [], selected: null, detail: null, tab: "overview", player: null, coach: null };
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
  state.ranks = Object.entries(shell.ability_ranks || {}).sort((a, b) => b[1] - a[1]);
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
