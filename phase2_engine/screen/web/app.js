// 正式な画面（game_definition.md §9、ADR-044）。
// データは Python の ScreenApi（window.pywebview.api）からだけ読む。
"use strict";

const STOP_MESSAGES = {
  big_scene: "大きな場面の前で止まりました",
  match_day: "次の試合日になりました",
  competition_end: "大会が終わりました",
};

const PAGE_TITLES = {
  today: "今日",
  competitions: "大会",
  matches: "試合",
  schools: "学校",
  records: "記録",
  saves: "セーブ",
};

const state = { page: "today", header: null, menu: [] };

function api() {
  return window.pywebview.api;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.hidden = true; }, 5000);
}

// ---- 上の帯 ----

function renderHeader(header) {
  state.header = header;
  document.getElementById("date-label").textContent = header.date_label;
  document.getElementById("date-sub").textContent =
    `${header.school_year}年度 ・ 今日の試合 ${header.today_match_count}試合`;
}

// ---- 左のメニュー ----

function renderMenu() {
  const menu = document.getElementById("menu");
  menu.replaceChildren();
  for (const item of state.menu) {
    if (item.id === "saves") menu.append(el("div", { class: "menu-gap" }));
    menu.append(el("button", {
      type: "button",
      class: item.id === state.page ? "active" : "",
      onclick: () => showPage(item.id),
    }, item.label));
  }
}

function showPage(page) {
  state.page = page;
  renderMenu();
  renderPage();
}

// ---- 本文（ページごとの画面は次のPRから入れる） ----

function renderPage() {
  const content = document.getElementById("content");
  const title = el("h1", {}, PAGE_TITLES[state.page] || "");
  if (state.page === "today") {
    content.replaceChildren(title, ...todayPanels());
  } else {
    content.replaceChildren(
      title,
      el("div", { class: "panel muted" }, "この画面はこれから作ります。"),
    );
  }
}

function todayPanels() {
  const header = state.header;
  const competitions = header.active_competitions.slice(0, 12);
  return [
    el("div", { class: "panel" },
      el("h2", {}, "今日の全国の試合"),
      el("div", { class: "big-number" }, `${header.today_match_count}試合`)),
    el("div", { class: "panel" },
      el("h2", {}, "進行中の大会"),
      competitions.length
        ? el("ul", { class: "list" }, competitions.map((row) =>
          el("li", {}, row.name, el("span", { class: "muted" },
            row.next_date ? `　次の試合 ${row.next_date}` : ""))))
        : el("div", { class: "muted" }, "進行中の大会はありません")),
  ];
}

// ---- 日付を進める ----

async function advance(options) {
  setBusy(true);
  const poll = setInterval(updateProgress, 250);
  try {
    const result = await api().advance(options);
    if (result.error) {
      showToast(result.error, true);
      return;
    }
    renderHeader(result.header);
    renderPage();
    const parts = [`${result.played_match_count}試合を行いました`];
    if (result.stopped_reason) parts.unshift(STOP_MESSAGES[result.stopped_reason] || "");
    showToast(parts.filter(Boolean).join("。"));
  } finally {
    clearInterval(poll);
    setBusy(false);
  }
}

function setBusy(busy) {
  document.getElementById("btn-day").disabled = busy;
  document.getElementById("btn-bulk").disabled = busy;
  document.getElementById("progress").hidden = !busy;
  if (busy) {
    document.getElementById("progress-date").textContent = state.header.date_label;
    document.getElementById("progress-sub").textContent = "";
    document.getElementById("progress-fill").style.width = "0";
  }
}

async function updateProgress() {
  const progress = await api().progress();
  if (!progress.running) return;
  document.getElementById("progress-date").textContent = progress.current_date;
  document.getElementById("progress-sub").textContent =
    `${progress.advanced_days}日 ・ ${progress.played_match_count}試合`;
  const fill = document.getElementById("progress-fill");
  if (progress.target_date) {
    const start = Date.parse(progress.from_date);
    const ratio = (Date.parse(progress.current_date) - start) /
      Math.max(1, Date.parse(progress.target_date) - start);
    fill.style.width = `${Math.min(100, Math.round(ratio * 100))}%`;
  } else {
    fill.style.width = `${(progress.advanced_days * 7) % 100}%`;
  }
}

function openBulkDialog() {
  const select = document.getElementById("bulk-competition");
  select.replaceChildren(...state.header.active_competitions.map((row) =>
    el("option", { value: `${row.school_year}|${row.competition_id}` }, row.name)));
  const dateInput = document.getElementById("bulk-date");
  dateInput.min = state.header.date;
  if (!dateInput.value || dateInput.value <= state.header.date) dateInput.value = "";
  document.getElementById("bulk-dialog").showModal();
}

function onBulkClose(event) {
  const dialog = event.target;
  if (dialog.returnValue !== "start") return;
  const form = document.getElementById("bulk-form");
  const mode = form.elements.mode.value;
  const options = {
    mode,
    stop_at_big_scene: document.getElementById("bulk-stop-big").checked,
  };
  if (mode === "competition_end") {
    const [year, competitionId] = document.getElementById("bulk-competition").value.split("|");
    if (!competitionId) return showToast("大会を選んでください", true);
    options.school_year = Number(year);
    options.competition_id = competitionId;
  }
  if (mode === "date") {
    options.target_date = document.getElementById("bulk-date").value;
    if (!options.target_date) return showToast("日付を選んでください", true);
  }
  advance(options);
}

// ---- 起動 ----

async function start() {
  const shell = await api().shell();
  if (shell.error) {
    showToast(shell.error, true);
    return;
  }
  state.menu = shell.menu;
  renderHeader(shell.header);
  renderMenu();
  renderPage();
  document.getElementById("btn-day").addEventListener("click", () => advance({ mode: "day" }));
  document.getElementById("btn-bulk").addEventListener("click", openBulkDialog);
  document.getElementById("bulk-dialog").addEventListener("close", onBulkClose);
}

window.addEventListener("pywebviewready", start);
