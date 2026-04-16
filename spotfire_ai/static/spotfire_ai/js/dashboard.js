/**
 * dashboard.js
 *
 * 역할: Spotfire Report 대시보드의 모든 클라이언트 로직
 *
 * 구조:
 *   1.  상수
 *   2.  state 객체
 *   3.  초기화 (DOMContentLoaded)
 *   4.  필터 수집 유틸
 *   5.  Report Data fetch → M/W/D chart
 *   6.  Chart 렌더링 (Plotly bar)
 *   7.  Bar 클릭 핸들러
 *   8.  Click Detail fetch → raw table / top panel
 *   9.  Detail 패널 렌더링 (Rawdata / Top Show)
 *  10.  Sidebar / UI 유틸
 *  11.  에러 / 토스트 유틸
 *  12.  AI Copilot
 */

"use strict";

// ═══════════════════════════════════════════════════════════════
// 1. 상수
// ═══════════════════════════════════════════════════════════════

const URLS       = window.SF_URLS || {};
const ALL_VALUE  = "ALL";
const VALID_FLAGS = ["M", "W", "D"];
const CHART_IDS  = { M: "chartM", W: "chartW", D: "chartD" };
const COLORS = [
  "#6366f1", "#06b6d4", "#10b981", "#f59e0b",
  "#ef4444", "#8b5cf6", "#ec4899", "#3b82f6",
  "#14b8a6", "#f97316",
];

const MAX_RENDER_ROWS = 500;

/**
 * Top Show 그룹화 기준 컬럼 목록 (고정)
 * Raw 테이블은 이벤트 로그이므로 숫자 컬럼 대신
 * 이 목록으로 드롭다운을 구성하고 건수(cnt)를 JS 에서 직접 집계한다.
 *
 * 집계 계층:
 *   line                              → 라인별
 *   line + eqp_id                     → 라인+설비별
 *   line + eqp_id + param_type        → 라인+설비+파라미터유형별
 *   line + eqp_id + param_type + param_name → 전체 4단계
 */
const TOP_GROUP_OPTIONS = [
  { value: "line",                                    label: "Line"                              },
  { value: "line,eqp_id",                             label: "Line + EQP ID"                     },
  { value: "line,eqp_id,param_type",                  label: "Line + EQP ID + Param Type"        },
  { value: "line,eqp_id,param_type,param_name",       label: "Line + EQP ID + Param Type + Param Name" },
  { value: "eqp_id",                                  label: "EQP ID"                            },
  { value: "eqp_id,param_type",                       label: "EQP ID + Param Type"               },
  { value: "eqp_id,param_type,param_name",            label: "EQP ID + Param Type + Param Name"  },
  { value: "param_type",                              label: "Param Type"                        },
  { value: "param_type,param_name",                   label: "Param Type + Param Name"           },
  { value: "param_name",                              label: "Param Name"                        },
];

const MSG = {
  MISSING_BAR : "bar 를 먼저 클릭하세요.",
  NET_ERROR   : (msg) => `네트워크 오류: ${msg}`,
  API_ERROR   : (msg) => `API 오류: ${msg}`,
};


// ═══════════════════════════════════════════════════════════════
// 2. state 객체
// ═══════════════════════════════════════════════════════════════

const state = {
  /** @type {{ flag: string, yyyy: string, flagdate: string } | null} */
  selectedBar: null,
  /** @type {{ M: object, W: object, D: object }} */
  chartData: {},
  /** @type {object[]} */
  rawRows: [],
  /** @type {string[]} */
  rawColumns: [],
  /** @type {"raw" | "top"} */
  detailMode: "raw",
  copilot: { open: false },
};


// ═══════════════════════════════════════════════════════════════
// 3. 초기화
// ═══════════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
  initTheme();

  // Top Show 드롭다운 초기 구성 + 이벤트 등록 (내부에서 null 체크 포함)
  _initTopGroupSelect();

  fetchReportData();

  // ── 헬퍼: null-safe addEventListener ──────────────────────
  // getElementById 가 null 을 반환해도 이후 등록이 멈추지 않도록 방어한다.
  function on(id, event, handler) {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener(event, handler);
    } else {
      console.warn(`[dashboard] element not found: #${id}`);
    }
  }

  on("applyFilterBtn",    "click",  fetchReportData);
  on("resetFilterBtn",    "click",  resetFilters);
  on("yFieldSelect",      "change", fetchReportData);

  document.querySelectorAll('input[name="detailMode"]').forEach((radio) => {
    radio.addEventListener("change", onDetailModeChange);
  });

  // topGroupSelect / topNInput 은 _initTopGroupSelect() 내부에서 등록됨

  on("contextClearBtn",   "click",  clearSelectedBar);
  on("sidebarCollapseBtn","click",  () => toggleSidebar(false));
  on("sidebarToggleBtn",  "click",  () => toggleSidebar(true));
  on("themeToggleBtn",    "click",  toggleTheme);

  on("copilotToggleBtn",  "click",  () => toggleCopilot(true));
  on("copilotCloseBtn",   "click",  () => toggleCopilot(false));
  on("aiSendBtn",         "click",  sendAiQuestion);
  on("aiInput",           "keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendAiQuestion(); }
  });

  document.querySelectorAll(".sf-quick-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const q = btn.dataset.q;
      if (!q) return;
      const input = document.getElementById("aiInput");
      if (input) input.value = q;
      sendAiQuestion();
    });
  });
});

/**
 * Top Show 그룹 선택 드롭다운을 TOP_GROUP_OPTIONS 로 초기 구성한다.
 * Raw 테이블에 숫자 컬럼이 없으므로 고정 그룹 옵션을 사용한다.
 */
function _initTopGroupSelect() {
  const select  = document.getElementById("topGroupSelect");
  const topNEl  = document.getElementById("topNInput");

  if (!select) {
    console.warn("[dashboard] #topGroupSelect not found — Top Show will be unavailable");
    return;
  }

  // 옵션 채우기
  select.innerHTML = "";
  TOP_GROUP_OPTIONS.forEach((opt) => {
    const el       = document.createElement("option");
    el.value       = opt.value;
    el.textContent = opt.label;
    select.appendChild(el);
  });

  // 기본값: Line + EQP ID (2단계)
  select.value = "line,eqp_id";

  // 이벤트 등록 (DOMContentLoaded 에서 별도 등록하지 않음)
  select.addEventListener("change", renderDetailPanel);
  if (topNEl) topNEl.addEventListener("change", renderDetailPanel);
}


// ═══════════════════════════════════════════════════════════════
// 4. 필터 수집 유틸
// ═══════════════════════════════════════════════════════════════

function collectFilters() {
  const params = new URLSearchParams();

  function addMultiSelect(selectId, paramName) {
    const el = document.getElementById(selectId);
    if (!el) return;
    const selected = Array.from(el.selectedOptions).map((o) => o.value);
    if (!selected.length || selected.includes(ALL_VALUE)) return;
    selected.forEach((v) => params.append(paramName, v));
  }

  addMultiSelect("filterLine",      "line");
  addMultiSelect("filterSdwtProd",  "sdwt_prod");
  addMultiSelect("filterEqpModel",  "eqp_model");
  addMultiSelect("filterEqpId",     "eqp_id");
  addMultiSelect("filterParamType", "param_type");

  params.append("m_rank", document.getElementById("rankM").value || 999);
  params.append("w_rank", document.getElementById("rankW").value || 999);
  params.append("d_rank", document.getElementById("rankD").value || 999);
  params.append("y_field", document.getElementById("yFieldSelect").value);

  return params;
}

function collectFiltersAsDict() {
  const result = {};

  function addMultiSelect(selectId, fieldName) {
    const el = document.getElementById(selectId);
    if (!el) return;
    const selected = Array.from(el.selectedOptions).map((o) => o.value);
    if (!selected.length || selected.includes(ALL_VALUE)) return;
    result[fieldName] = selected;
  }

  addMultiSelect("filterLine",      "line");
  addMultiSelect("filterSdwtProd",  "sdwt_prod");
  addMultiSelect("filterEqpModel",  "eqp_model");
  addMultiSelect("filterEqpId",     "eqp_id");
  addMultiSelect("filterParamType", "param_type");

  return result;
}

function resetFilters() {
  ["filterLine", "filterSdwtProd", "filterEqpModel", "filterEqpId", "filterParamType"]
    .forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      Array.from(el.options).forEach((o) => { o.selected = (o.value === ALL_VALUE); });
    });

  document.getElementById("rankM").value        = 999;
  document.getElementById("rankW").value        = 999;
  document.getElementById("rankD").value        = 999;
  document.getElementById("yFieldSelect").value = "cnt";

  fetchReportData();
}


// ═══════════════════════════════════════════════════════════════
// 5. Report Data fetch (M/W/D chart)
// ═══════════════════════════════════════════════════════════════

async function fetchReportData() {
  setChartLoading(true);

  const params = collectFilters();
  const url    = `${URLS.reportData}?${params.toString()}`;

  try {
    const res  = await fetch(url);
    const json = await res.json();

    if (!json.ok) { showToast(MSG.API_ERROR(json.error)); return; }

    state.chartData = json.data;

    VALID_FLAGS.forEach((flag) => {
      renderBarChart(flag, json.data[flag]);
    });

  } catch (err) {
    showToast(MSG.NET_ERROR(err.message));
  } finally {
    setChartLoading(false);
  }
}


// ═══════════════════════════════════════════════════════════════
// 6. Chart 렌더링 (Plotly bar)
// ═══════════════════════════════════════════════════════════════

function renderBarChart(flag, data) {
  const divId = CHART_IDS[flag];
  if (!divId) return;

  if (!data || !data.flagdates || !data.flagdates.length) {
    Plotly.react(divId, [], {
      annotations: [{ text: "데이터 없음", xref: "paper", yref: "paper",
                      x: 0.5, y: 0.5, showarrow: false, font: { color: "#999", size: 13 } }],
      margin: { t: 10, b: 20, l: 20, r: 10 },
      paper_bgcolor: "transparent",
    }, { displayModeBar: false });
    return;
  }

  const { flagdates, series } = data;

  const traces = series.map((s, idx) => ({
    type:          "bar",
    name:          s.name,
    x:             flagdates,
    y:             s.y,
    marker:        { color: COLORS[idx % COLORS.length] },
    hovertemplate: "<b>%{x}</b><br>%{y:,.0f}<extra>%{fullData.name}</extra>",
  }));

  const yLabel    = document.getElementById("yFieldSelect").value;
  const isDark    = document.documentElement.getAttribute("data-theme") === "dark";
  const fontColor = isDark ? "#94a3b8" : "#64748b";
  const hoverBg   = isDark ? "#1e293b" : "#0f172a";

  const layout = {
    barmode: "group",
    margin:  { t: 8, b: 56, l: 46, r: 8 },
    xaxis:   { tickangle: -30, automargin: true, fixedrange: true },
    yaxis:   { title: { text: yLabel, font: { size: 11 } }, automargin: true, fixedrange: true },
    legend:  { orientation: "h", y: -0.28, font: { size: 10 } },
    plot_bgcolor:  "transparent",
    paper_bgcolor: "transparent",
    font:          { family: "Inter, sans-serif", size: 11, color: fontColor },
    hoverlabel:    { bgcolor: hoverBg, font: { color: "#f1f5f9", size: 11 }, bordercolor: "#334155" },
  };

  Plotly.react(divId, traces, layout, { responsive: true, displayModeBar: false });

  const el = document.getElementById(divId);
  if (typeof el.removeAllListeners === "function") el.removeAllListeners("plotly_click");
  el.on("plotly_click", (eventData) => onBarClick(flag, eventData));
}

function setChartLoading(isLoading) {
  VALID_FLAGS.forEach((flag) => {
    const el = document.getElementById(`loading${flag}`);
    if (el) el.style.display = isLoading ? "flex" : "none";
  });
}


// ═══════════════════════════════════════════════════════════════
// 7. Bar 클릭 핸들러
// ═══════════════════════════════════════════════════════════════

function onBarClick(flag, eventData) {
  if (!eventData?.points?.length) return;

  const point    = eventData.points[0];
  const flagdate = String(point.x);
  const yyyy     = state.chartData?.[flag]?.yyyy_map?.[flagdate]
                 ?? String(new Date().getFullYear());

  state.selectedBar = { flag, yyyy, flagdate };

  updateContextBar();
  updateCopilotContextHint();
  fetchClickDetail();
}

function clearSelectedBar() {
  state.selectedBar = null;
  state.rawRows     = [];
  state.rawColumns  = [];

  document.getElementById("contextBar").style.display = "none";
  document.getElementById("sfDetail").style.display   = "none";

  updateCopilotContextHint();
}


// ═══════════════════════════════════════════════════════════════
// 8. Click Detail fetch
// ═══════════════════════════════════════════════════════════════

async function fetchClickDetail() {
  const { flag, yyyy, flagdate } = state.selectedBar || {};

  if (!flag || !yyyy || !flagdate) { showToast(MSG.MISSING_BAR); return; }

  setDetailLoading(true);
  document.getElementById("sfDetail").style.display = "block";

  const params = collectFilters();
  params.append("flag",     flag);
  params.append("yyyy",     yyyy);
  params.append("flagdate", flagdate);

  const url = `${URLS.clickDetail}?${params.toString()}`;

  try {
    const res  = await fetch(url);
    const json = await res.json();

    if (!json.ok) { showToast(MSG.API_ERROR(json.error)); return; }

    state.rawRows    = json.data.rows    || [];
    state.rawColumns = json.data.columns || [];

    const countEl = document.getElementById("detailCount");
    if (countEl) {
      countEl.textContent = `총 ${(json.data.total || 0).toLocaleString()}건`;
    }

    renderDetailPanel();

  } catch (err) {
    showToast(MSG.NET_ERROR(err.message));
  } finally {
    setDetailLoading(false);
  }
}


// ═══════════════════════════════════════════════════════════════
// 9. Detail 패널 렌더링 (Rawdata Show / Top Show)
// ═══════════════════════════════════════════════════════════════

function renderDetailPanel() {
  const isRaw = (state.detailMode === "raw");

  document.getElementById("rawDataPanel").style.display = isRaw ? "block" : "none";
  document.getElementById("topDataPanel").style.display = isRaw ? "none"  : "block";
  document.getElementById("topOptions").style.display   = isRaw ? "none"  : "flex";

  if (isRaw) {
    renderRawTable();
  } else {
    renderTopPanel();
  }
}

function onDetailModeChange(e) {
  state.detailMode = e.target.value;
  if (state.rawRows.length) renderDetailPanel();
}

// ── Rawdata Show ──────────────────────────────────────────────

function renderRawTable() {
  const thead   = document.getElementById("rawTableHead");
  const tbody   = document.getElementById("rawTableBody");
  const emptyEl = document.getElementById("rawTableEmpty");

  thead.innerHTML = "";
  tbody.innerHTML = "";

  if (!state.rawColumns.length || !state.rawRows.length) {
    if (emptyEl) emptyEl.style.display = "block";
    return;
  }
  if (emptyEl) emptyEl.style.display = "none";

  const headerRow = document.createElement("tr");
  state.rawColumns.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col;
    th.title       = col;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);

  const visibleRows = state.rawRows.slice(0, MAX_RENDER_ROWS);
  const fragment    = document.createDocumentFragment();

  visibleRows.forEach((row) => {
    const tr = document.createElement("tr");
    state.rawColumns.forEach((col) => {
      const td  = document.createElement("td");
      const val = row[col];
      td.textContent = (val != null) ? val : "";
      if (typeof val === "number") td.style.textAlign = "right";
      tr.appendChild(td);
    });
    fragment.appendChild(tr);
  });
  tbody.appendChild(fragment);

  if (state.rawRows.length > MAX_RENDER_ROWS) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan     = state.rawColumns.length;
    td.className   = "sf-table-truncate-msg";
    td.textContent = `… 상위 ${MAX_RENDER_ROWS}건 표시 (전체 ${state.rawRows.length.toLocaleString()}건)`;
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
}

// ── Top Show (cnt 기반 그룹 집계) ────────────────────────────

/**
 * state.rawRows 를 JS 에서 직접 그룹별 카운팅해 Top-N 차트 + 테이블을 렌더링한다.
 *
 * Raw 테이블은 이벤트 로그이므로 숫자 측정 컬럼이 없다.
 * 대신 topGroupSelect 에서 선택한 컬럼 조합으로 group_by 하고
 * 행 수를 cnt 로 집계한다.
 *
 * 흐름:
 *   1. topGroupSelect.value ("line,eqp_id" 등) 파싱 → groupCols 배열
 *   2. state.rawRows 를 groupCols 기준으로 Map 집계 → { key: cnt }
 *   3. cnt 내림차순 정렬 → 상위 topN 추출
 *   4. Plotly 수평 bar + 순위 테이블 렌더링
 */
function renderTopPanel() {
  if (!state.rawRows.length) return;

  const groupColStr = document.getElementById("topGroupSelect").value || "line,eqp_id";
  const groupCols   = groupColStr.split(",").map((c) => c.trim()).filter(Boolean);
  const topN        = Math.max(1, parseInt(document.getElementById("topNInput").value, 10) || 10);

  // ── 그룹별 cnt 집계 ──────────────────────────────────────
  const cntMap = new Map(); // key(string) → { cols 값들, cnt }

  state.rawRows.forEach((row) => {
    // 그룹 키: "L1|EQP-001" 형태 (구분자 | 사용)
    const keyParts  = groupCols.map((col) => (row[col] != null ? String(row[col]) : ""));
    const key       = keyParts.join("|");

    if (cntMap.has(key)) {
      cntMap.get(key).cnt += 1;
    } else {
      const entry = { cnt: 1 };
      groupCols.forEach((col) => { entry[col] = row[col] != null ? String(row[col]) : ""; });
      cntMap.set(key, entry);
    }
  });

  // ── cnt 내림차순 정렬 → 상위 N 추출 ─────────────────────
  const sorted = Array.from(cntMap.values())
    .sort((a, b) => b.cnt - a.cnt)
    .slice(0, topN);

  if (!sorted.length) {
    showToast("집계 결과가 없습니다.");
    return;
  }

  // ── y축 레이블: 그룹 컬럼 값들을 " / " 로 연결 ──────────
  const yLabels = sorted.map((row) =>
    groupCols.map((col) => row[col] || "-").join(" / ")
  );
  const xValues = sorted.map((row) => row.cnt);

  // ── Plotly 수평 bar ─────────────────────────────────────
  const isDark    = document.documentElement.getAttribute("data-theme") === "dark";
  const fontColor = isDark ? "#94a3b8" : "#64748b";

  const traces = [{
    type:          "bar",
    orientation:   "h",
    x:             xValues,
    y:             yLabels,
    marker:        { color: yLabels.map((_, i) => COLORS[i % COLORS.length]) },
    text:          xValues.map((v) => v.toLocaleString()),
    textposition:  "auto",
    hovertemplate: "<b>%{y}</b><br>발생 건수: %{x:,}<extra></extra>",
  }];

  const layout = {
    margin:  { t: 8, b: 30, l: 160, r: 60 },
    xaxis: {
      title:      { text: "발생 건수 (cnt)", font: { size: 11 } },
      automargin: true,
      fixedrange: true,
    },
    yaxis: {
      automargin: true,
      fixedrange: true,
      autorange:  "reversed",   // 1위가 맨 위
    },
    plot_bgcolor:  "transparent",
    paper_bgcolor: "transparent",
    font:          { family: "Inter, sans-serif", size: 11, color: fontColor },
    hoverlabel:    { bgcolor: "#0f172a", font: { color: "#f1f5f9", size: 11 }, bordercolor: "#334155" },
  };

  Plotly.react("chartTop", traces, layout, { responsive: true, displayModeBar: false });

  // ── chartTop bar 클릭 → 해당 그룹 Rawdata 표시 ──────────
  const topEl = document.getElementById("chartTop");
  if (typeof topEl.removeAllListeners === "function") {
    topEl.removeAllListeners("plotly_click");
  }
  topEl.on("plotly_click", (eventData) => {
    if (!eventData?.points?.length) return;
    const pointIdx  = eventData.points[0].pointIndex;
    const clickedRow = sorted[pointIdx];
    if (clickedRow) onTopBarClick(clickedRow, groupCols);
  });

  // ── 순위 테이블 ─────────────────────────────────────────
  _renderTopTable(sorted, groupCols);
}

/**
 * Top Show 순위 테이블 렌더링.
 *
 * @param {object[]} rows       - cnt 내림차순 정렬된 집계 결과
 * @param {string[]} groupCols  - 그룹 기준 컬럼 목록
 */
function _renderTopTable(rows, groupCols) {
  const thead = document.getElementById("topTableHead");
  const tbody = document.getElementById("topTableBody");
  thead.innerHTML = "";
  tbody.innerHTML = "";

  if (!rows.length) return;

  // 헤더: # + 그룹 컬럼들 + cnt
  const displayCols = [...groupCols, "cnt"];
  const headerRow   = document.createElement("tr");

  const thRank       = document.createElement("th");
  thRank.textContent = "#";
  headerRow.appendChild(thRank);

  displayCols.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col === "cnt" ? "발생 건수" : col;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);

  // 바디
  const fragment = document.createDocumentFragment();
  rows.forEach((row, idx) => {
    const tr = document.createElement("tr");

    const rankTd       = document.createElement("td");
    rankTd.textContent = idx + 1;
    rankTd.className   = "sf-rank-cell";
    tr.appendChild(rankTd);

    displayCols.forEach((col) => {
      const td  = document.createElement("td");
      const val = row[col];
      td.textContent = (val != null) ? (typeof val === "number" ? val.toLocaleString() : val) : "";
      if (col === "cnt") {
        td.style.textAlign = "right";
        td.classList.add("sf-highlight-cell");
      }
      tr.appendChild(td);
    });

    fragment.appendChild(tr);
  });
  tbody.appendChild(fragment);
}

/**
 * Top Show bar 클릭 핸들러.
 * 클릭된 그룹(groupCols 기준)에 해당하는 rawRows 를 필터링해 하단에 표시한다.
 *
 * @param {object}   clickedRow  - sorted 배열의 해당 항목 (groupCols 값 + cnt 포함)
 * @param {string[]} groupCols   - 현재 집계 기준 컬럼 목록
 */
function onTopBarClick(clickedRow, groupCols) {
  // 클릭된 그룹의 조건에 맞는 raw rows 필터링
  const filtered = state.rawRows.filter((row) =>
    groupCols.every((col) => String(row[col] ?? "") === String(clickedRow[col] ?? ""))
  );

  // 배지 텍스트: "line=L1 / eqp_id=EQP-001" 형태
  const badgeText = groupCols
    .map((col) => `${col}=${clickedRow[col] || "-"}`)
    .join(" / ");

  _renderTopRaw(filtered, badgeText);
}

/**
 * Top Show 하단 Rawdata 패널 렌더링.
 *
 * @param {object[]} rows       - 필터링된 raw rows
 * @param {string}   badgeText  - 상단 배지에 표시할 그룹 설명
 */
function _renderTopRaw(rows, badgeText) {
  const panel    = document.getElementById("topRawPanel");
  const badge    = document.getElementById("topRawBadge");
  const countEl  = document.getElementById("topRawCount");
  const thead    = document.getElementById("topRawTableHead");
  const tbody    = document.getElementById("topRawTableBody");

  if (!panel) return;

  // 데이터 없으면 패널 숨김
  if (!rows.length) {
    panel.style.display = "none";
    showToast("해당 그룹의 Raw 데이터가 없습니다.");
    return;
  }

  // 배지 및 건수 표시
  badge.textContent  = badgeText;
  countEl.textContent = `${rows.length.toLocaleString()}건`;
  panel.style.display = "block";

  // 헤더
  thead.innerHTML = "";
  const columns   = state.rawColumns.length ? state.rawColumns : Object.keys(rows[0]);
  const headerRow = document.createElement("tr");
  columns.forEach((col) => {
    const th       = document.createElement("th");
    th.textContent = col;
    th.title       = col;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);

  // 바디 (최대 500건)
  tbody.innerHTML = "";
  const fragment  = document.createDocumentFragment();
  const visible   = rows.slice(0, MAX_RENDER_ROWS);

  visible.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((col) => {
      const td  = document.createElement("td");
      const val = row[col];
      td.textContent = (val != null) ? val : "";
      if (typeof val === "number") td.style.textAlign = "right";
      tr.appendChild(td);
    });
    fragment.appendChild(tr);
  });
  tbody.appendChild(fragment);

  // 행 수 초과 안내
  if (rows.length > MAX_RENDER_ROWS) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan     = columns.length;
    td.className   = "sf-table-truncate-msg";
    td.textContent = `… 상위 ${MAX_RENDER_ROWS}건 표시 (전체 ${rows.length.toLocaleString()}건)`;
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
}

/**
 * Top Show Rawdata 패널 닫기.
 */
function closeTopRaw() {
  const panel = document.getElementById("topRawPanel");
  if (panel) panel.style.display = "none";
}

function setDetailLoading(isLoading) {
  const loadingEl = document.getElementById("detailLoading");
  const bodyEl    = document.getElementById("detailBody");

  if (loadingEl) loadingEl.style.display = isLoading ? "flex"   : "none";
  if (bodyEl)    bodyEl.style.visibility = isLoading ? "hidden" : "visible";
}


// ═══════════════════════════════════════════════════════════════
// 10. Sidebar / UI 유틸
// ═══════════════════════════════════════════════════════════════

function initTheme() {
  const saved     = localStorage.getItem("sf-theme");
  const preferred = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  _applyTheme(saved || preferred);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  _applyTheme(current === "dark" ? "light" : "dark");

  VALID_FLAGS.forEach((flag) => {
    if (state.chartData[flag]) renderBarChart(flag, state.chartData[flag]);
  });
  if (state.rawRows.length && state.detailMode === "top") renderTopPanel();
}

function _applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("sf-theme", theme);
}

function toggleSidebar(open) {
  const sidebar = document.getElementById("sfSidebar");
  const main    = document.getElementById("sfMain");
  sidebar.classList.toggle("sf-sidebar--collapsed", !open);
  main.classList.toggle("sf-main--full", !open);
}

function updateContextBar() {
  const { flag, yyyy, flagdate } = state.selectedBar || {};
  if (!flag) return;

  const barEl   = document.getElementById("contextBar");
  const badgeEl = document.getElementById("contextBadge");

  badgeEl.textContent = `${flag} / ${yyyy} / ${flagdate}`;
  barEl.style.display = "flex";
}


// ═══════════════════════════════════════════════════════════════
// 11. 에러 / 토스트 유틸
// ═══════════════════════════════════════════════════════════════

let _toastTimer = null;

function showToast(message, duration = 4000) {
  const el = document.getElementById("sfToast");
  if (!el) return;

  el.textContent = message;
  el.classList.add("sf-toast--show");

  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => {
    el.classList.remove("sf-toast--show");
  }, duration);
}


// ═══════════════════════════════════════════════════════════════
// 12. AI Copilot
// ═══════════════════════════════════════════════════════════════

function getCsrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.content || "";
}

function toggleCopilot(open) {
  state.copilot.open = open;
  document.getElementById("sfCopilot").classList.toggle("sf-copilot--open", open);
  if (open) updateCopilotContextHint();
}

function updateCopilotContextHint() {
  const el = document.getElementById("copilotContextHint");
  if (!el) return;

  if (state.selectedBar) {
    const { flag, yyyy, flagdate } = state.selectedBar;
    el.textContent   = `📍 선택된 bar: ${flag} / ${yyyy} / ${flagdate}`;
    el.style.display = "block";
  } else {
    el.textContent   = "";
    el.style.display = "none";
  }
}

function appendChatMessage(role, text, previewRows) {
  const history = document.getElementById("copilotHistory");
  if (!history) return null;

  const msgDiv = document.createElement("div");
  msgDiv.className = `sf-chat-msg sf-chat-msg--${role}`;

  const bubble = document.createElement("div");
  bubble.className = "sf-chat-msg__bubble";
  bubble.innerHTML = _escapeHtml(text).replace(/\n/g, "<br>");
  msgDiv.appendChild(bubble);

  if (role === "ai" && previewRows && previewRows.length) {
    msgDiv.appendChild(_buildPreviewTable(previewRows));
  }

  history.appendChild(msgDiv);
  history.scrollTop = history.scrollHeight;

  return msgDiv;
}

function appendChatLoading() {
  const history = document.getElementById("copilotHistory");
  if (!history) return null;

  const msgDiv = document.createElement("div");
  msgDiv.id        = "copilotLoadingMsg";
  msgDiv.className = "sf-chat-msg sf-chat-msg--ai";

  const bubble = document.createElement("div");
  bubble.className = "sf-chat-msg__bubble";
  bubble.innerHTML = '<span class="sf-chat-dots"><span></span><span></span><span></span></span>';
  msgDiv.appendChild(bubble);

  history.appendChild(msgDiv);
  history.scrollTop = history.scrollHeight;

  return msgDiv;
}

function removeChatLoading() {
  const el = document.getElementById("copilotLoadingMsg");
  if (el) el.remove();
}

function _buildPreviewTable(rows) {
  const cols    = Object.keys(rows[0]);
  const wrapper = document.createElement("div");
  wrapper.className = "sf-chat-preview-wrap";

  const table = document.createElement("table");
  table.className = "sf-chat-preview-table";

  const thead     = document.createElement("thead");
  const headerRow = document.createElement("tr");
  cols.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    cols.forEach((col) => {
      const td  = document.createElement("td");
      const val = row[col];
      td.textContent = (val != null) ? val : "";
      if (typeof val === "number") td.style.textAlign = "right";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  wrapper.appendChild(table);

  return wrapper;
}

function _escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function sendAiQuestion() {
  const input    = document.getElementById("aiInput");
  const question = (input?.value || "").trim();
  if (!question) return;

  input.value = "";
  appendChatMessage("user", question);
  appendChatLoading();

  const sendBtn = document.getElementById("aiSendBtn");
  if (sendBtn) sendBtn.disabled = true;

  // page_context 드롭다운 제거 — 항상 "interlock" 기본값 사용
  const pageContext = "interlock";

  const body = {
    question,
    page_context:    pageContext,
    selected_bar:    state.selectedBar || null,
    sidebar_filters: collectFiltersAsDict(),
  };

  try {
    const res = await fetch(URLS.askAi, {
      method:  "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
      body:    JSON.stringify(body),
    });

    const json = await res.json();
    removeChatLoading();

    if (!json.ok) { appendChatMessage("ai", `⚠️ 오류: ${json.error}`); return; }

    const { answer, result_count, results_preview } = json.data;
    const suffix = (result_count != null)
      ? `\n\n📊 조회 결과: ${result_count.toLocaleString()}건`
      : "";

    appendChatMessage("ai", answer + suffix, results_preview || []);

  } catch (err) {
    removeChatLoading();
    appendChatMessage("ai", `⚠️ 네트워크 오류: ${err.message}`);
  } finally {
    if (sendBtn) sendBtn.disabled = false;
  }
}