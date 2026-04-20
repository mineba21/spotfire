/**
 * stoploss_ai/dashboard.js
 *
 * 역할: 설비 정지로스 현황 대시보드의 모든 클라이언트 로직
 *
 * 구조:
 *   1.  상수
 *   2.  state 객체
 *   3.  초기화 (DOMContentLoaded)
 *   4.  필터 수집 유틸
 *   5.  Report Data fetch → M/W/D chart
 *   6.  Chart 렌더링 (Plotly bar)
 *   7.  Bar 클릭 핸들러
 *   8.  Click Detail fetch → raw table / top panel / ratio panel
 *   9.  Detail 패널 렌더링 (Rawdata / Top Show / Ratio Analysis)
 *  10.  Sidebar / UI 유틸
 *  11.  에러 / 토스트 유틸
 *  12.  AI Copilot
 *  13.  차트 캡처
 *  14.  Raw Data Excel 다운로드
 */

"use strict";

// ═══════════════════════════════════════════════════════════════
// 1. 상수
// ═══════════════════════════════════════════════════════════════

const URLS        = window.SF_URLS || {};
const ALL_VALUE   = "ALL";
const VALID_FLAGS = ["M", "W", "D"];
const CHART_IDS   = { M: "chartM", W: "chartW", D: "chartD" };
const COLORS = [
  "#6366f1", "#06b6d4", "#10b981", "#f59e0b",
  "#ef4444", "#8b5cf6", "#ec4899", "#3b82f6",
  "#14b8a6", "#f97316",
];

const MAX_RENDER_ROWS = 500;

// ── 테이블 정렬 상태 (테이블 ID → { col, dir }) ──────────────────
const _sortState = {};

/**
 * 컬럼 배열을 기준으로 rows를 정렬한 복사본을 반환한다.
 */
function _sortRows(rows, col, dir) {
  return [...rows].sort((a, b) => {
    const va = a[col], vb = b[col];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    const cmp = (typeof va === "number" && typeof vb === "number")
      ? va - vb
      : String(va).localeCompare(String(vb), undefined, { numeric: true });
    return dir === "asc" ? cmp : -cmp;
  });
}

/**
 * thead의 th에 정렬 클릭 핸들러를 붙인다.
 * @param {HTMLElement} thead
 * @param {string[]} columns  - th 순서와 일치하는 컬럼 키 배열
 * @param {string} tableId    - 정렬 상태 키 (예: "rawTable")
 * @param {Function} renderBody - 정렬 후 tbody를 재렌더하는 콜백 (rows) => void
 * @param {Function} getRows  - 원본 rows 배열을 반환하는 콜백 () => rows
 */
function _attachSorting(thead, columns, tableId, getRows, renderBody) {
  if (!_sortState[tableId]) _sortState[tableId] = { col: null, dir: "asc" };
  const ss = _sortState[tableId];

  Array.from(thead.querySelectorAll("th")).forEach((th, i) => {
    const col = columns[i];
    th.classList.add("sf-sortable");
    th.addEventListener("click", () => {
      if (ss.col === col) {
        ss.dir = ss.dir === "asc" ? "desc" : "asc";
      } else {
        ss.col = col;
        ss.dir = "asc";
      }
      Array.from(thead.querySelectorAll("th")).forEach((h) => h.removeAttribute("data-sort"));
      th.setAttribute("data-sort", ss.dir);
      renderBody(_sortRows(getRows(), ss.col, ss.dir));
    });

    // 현재 정렬 상태 복원
    if (ss.col === col) th.setAttribute("data-sort", ss.dir);
  });
}

// Rawdata 테이블에서 숫자로 취급해 우측 정렬할 컬럼 목록
const NUMERIC_COLS = new Set([
  "stoploss", "pm", "qual", "bm", "eng", "etc", "stepchg", "std_time", "rd",
  "plan_time", "rank", "cnt", "ratio", "loss_time_min",
]);

// 컬럼 키 → 표시 레이블 (없으면 키를 대문자로 그대로 사용)
const COL_LABELS = {
  eqp_id:       "EQP ID",
  eqp_model:    "EQP Model",
  sdwt_prod:    "SDWT Prod",
  prc_group:    "PRC Group",
  plan_time:    "Plan Time",
  stoploss:     "Stoploss",
  loss_time_min:"Loss (min)",
  down_comment: "Comment",
  start_time:   "Start",
  end_time:     "End",
  yyyymmdd:     "Date",
};

/**
 * Top Show 그룹화 기준 컬럼 목록
 * stoploss의 eqp_loss_tpm 테이블 컬럼 기준 (loss_time 집계 포함)
 */
const TOP_GROUP_OPTIONS = [
  { value: "area",               label: "Line"              },
  { value: "area,sdwt_prod",     label: "Line + 분임조"      },
  { value: "area,eqp_model",     label: "Line + EQP Model"  },
  { value: "eqp_model",          label: "EQP Model"         },
  { value: "sdwt_prod",          label: "분임조"             },
];

const MSG = {
  MISSING_BAR: "bar 를 먼저 클릭하세요.",
  NET_ERROR:   (msg) => `네트워크 오류: ${msg}`,
  API_ERROR:   (msg) => `API 오류: ${msg}`,
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
  /** @type {object[]} */
  ratioRows: [],
  /** @type {"raw" | "top" | "ratio"} */
  detailMode: "raw",
  /** @type {"min" | "pct"} */
  yMode: "min",
  copilot: { open: false },
};


// ═══════════════════════════════════════════════════════════════
// 3. 초기화
// ═══════════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
  initTheme();

  _initTopGroupSelect();

  fetchReportData();

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

  // Y Mode 토글 버튼
  document.querySelectorAll(".sf-ymode-btn").forEach((btn) => {
    btn.addEventListener("click", () => setYMode(btn.dataset.mode));
  });

  // 필터 select 변경 시 옵션 동적 갱신
  ["filterArea", "filterSdwtProd", "filterEqpModel", "filterEqpId", "filterPrcGroup"]
    .forEach((id) => on(id, "change", refreshFilterOptions));

  document.querySelectorAll('input[name="detailMode"]').forEach((radio) => {
    radio.addEventListener("change", onDetailModeChange);
  });

  on("contextClearBtn",    "click",  clearSelectedBar);
  on("sidebarCollapseBtn", "click",  () => toggleSidebar(false));
  on("sidebarToggleBtn",   "click",  () => toggleSidebar(true));
  on("themeToggleBtn",     "click",  toggleTheme);

  on("copilotToggleBtn",   "click",  () => toggleCopilot(true));
  on("copilotCloseBtn",    "click",  () => toggleCopilot(false));
  on("chartCaptureBtn",    "click",  captureTopChart);
  on("rawExcelBtn",        "click",  downloadRawExcel);
  on("aiSendBtn",          "click",  sendAiQuestion);
  on("aiInput",            "keydown", (e) => {
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
 */
function _initTopGroupSelect() {
  const select = document.getElementById("topGroupSelect");
  const topNEl = document.getElementById("topNInput");

  if (!select) {
    console.warn("[dashboard] #topGroupSelect not found — Top Show will be unavailable");
    return;
  }

  select.innerHTML = "";
  TOP_GROUP_OPTIONS.forEach((opt) => {
    const el       = document.createElement("option");
    el.value       = opt.value;
    el.textContent = opt.label;
    select.appendChild(el);
  });

  select.value = "area";

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
 
  addMultiSelect("filterArea",     "area");
  addMultiSelect("filterSdwtProd", "sdwt_prod");
  addMultiSelect("filterEqpModel", "eqp_model");
  addMultiSelect("filterEqpId",    "eqp_id");
  addMultiSelect("filterPrcGroup", "prc_group");

  params.append("m_rank",  document.getElementById("rankM").value || 999);
  params.append("w_rank",  document.getElementById("rankW").value || 999);
  params.append("d_rank",  document.getElementById("rankD").value || 999);
  params.append("y_field", document.getElementById("yFieldSelect").value);
  params.append("y_mode",  state.yMode);
 
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
 
  addMultiSelect("filterArea",     "area");
  addMultiSelect("filterSdwtProd", "sdwt_prod");
  addMultiSelect("filterEqpModel", "eqp_model");
  addMultiSelect("filterEqpId",    "eqp_id");
  addMultiSelect("filterPrcGroup", "prc_group");

  return result;
}
/**
 * Y Mode (min / pct) 전환
 */
function setYMode(mode) {
  state.yMode = mode;
  document.querySelectorAll(".sf-ymode-btn").forEach((btn) => {
    btn.classList.toggle("sf-ymode-btn--active", btn.dataset.mode === mode);
  });
  fetchReportData();
  // Top Show 가 열려있으면 y_mode 변경 즉시 재집계
  if (state.rawRows.length && state.detailMode === "top") renderTopPanel();
}

/**
 * 현재 선택된 필터 값을 백엔드에 보내 각 select의 옵션을 갱신한다.
 */
async function refreshFilterOptions() {
  const params  = new URLSearchParams();
  const filters = collectFiltersAsDict();

  for (const [field, values] of Object.entries(filters)) {
    for (const v of values) {
      params.append(field, v);
    }
  }

  let data;
  try {
    const res = await fetch(`${URLS.filterOptions}?${params.toString()}`);
    if (!res.ok) return;
    const json = await res.json();
    if (!json.ok) return;
    data = json.data;
  } catch {
    return;
  }

  _rebuildSelect("filterArea",      data.areas,      "area");
  _rebuildSelect("filterSdwtProd",  data.sdwt_prods, "sdwt_prod");
  _rebuildSelect("filterEqpModel",  data.eqp_models, "eqp_model");
  _rebuildSelect("filterEqpId",     data.eqp_ids,    "eqp_id");
  _rebuildSelect("filterPrcGroup",  data.prc_groups, "prc_group");
}

function _rebuildSelect(selectId, newValues, fieldName) {
  const el = document.getElementById(selectId);
  if (!el || !Array.isArray(newValues)) return;

  const prevSelected = new Set(
    Array.from(el.selectedOptions).map((o) => o.value).filter((v) => v !== ALL_VALUE)
  );

  el.innerHTML = `<option value="${ALL_VALUE}">ALL</option>` +
    newValues.map((v) => `<option value="${v}">${v}</option>`).join("");

  let restored = 0;
  Array.from(el.options).forEach((o) => {
    if (prevSelected.has(o.value)) {
      o.selected = true;
      restored++;
    }
  });

  if (restored === 0) {
    el.options[0].selected = true;
  }
}

function resetFilters() {
  ["filterArea", "filterSdwtProd", "filterEqpModel", "filterEqpId", "filterPrcGroup"]
    .forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      Array.from(el.options).forEach((o) => { o.selected = (o.value === ALL_VALUE); });
    });

  document.getElementById("rankM").value        = 3;
  document.getElementById("rankW").value        = 3;
  document.getElementById("rankD").value        = 7;
  document.getElementById("yFieldSelect").value = "stoploss";

  // y_mode 리셋
  setYMode("min");

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

  const yMode  = state.yMode;
  const yField = document.getElementById("yFieldSelect").value;

  const traces = series.map((s, idx) => ({
    type:          "bar",
    name:          s.name,
    x:             flagdates,
    y:             s.y,
    marker:        { color: COLORS[idx % COLORS.length] },
    hovertemplate: yMode === "pct"
      ? "<b>%{x}</b><br>%{y:.2f}%<extra>%{fullData.name}</extra>"
      : "<b>%{x}</b><br>%{y:,.1f} min<extra>%{fullData.name}</extra>",
  }));

  const yAxisLabel = yMode === "pct"
    ? `${yField} 정지율 (%)`
    : `${yField} (min)`;

  const isDark    = document.documentElement.getAttribute("data-theme") === "dark";
  const fontColor = isDark ? "#94a3b8" : "#64748b";
  const hoverBg   = isDark ? "#1e293b" : "#0f172a";

  const layout = {
    barmode: "group",
    margin:  { t: 8, b: 56, l: 50, r: 8 },
    xaxis:   { tickangle: -30, automargin: true, fixedrange: true },
    yaxis:   { title: { text: yAxisLabel, font: { size: 11 } }, automargin: true, fixedrange: true },
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
  state.ratioRows   = [];

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
    state.ratioRows  = json.data.ratio   || [];

    // reset sort state so previous column sort doesn't carry over to new data
    delete _sortState["rawTable"];
    delete _sortState["topRawTable"];

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
// 9. Detail 패널 렌더링 (Rawdata / Top Show / Ratio Analysis)
// ═══════════════════════════════════════════════════════════════

function renderDetailPanel() {
  const mode = state.detailMode;

  document.getElementById("rawDataPanel").style.display = mode === "raw"   ? "block" : "none";
  document.getElementById("topDataPanel").style.display = mode === "top"   ? "block" : "none";
  document.getElementById("ratioPanel").style.display   = mode === "ratio" ? "block" : "none";
  document.getElementById("topOptions").style.display   = mode === "top"   ? "flex"  : "none";

  const captureBtn = document.getElementById("chartCaptureBtn");
  if (captureBtn) captureBtn.style.display = mode === "top" ? "inline-flex" : "none";

  const rawExcelBtn = document.getElementById("rawExcelBtn");
  if (rawExcelBtn) rawExcelBtn.style.display = mode === "raw" ? "inline-flex" : "none";

  if (mode === "raw")        renderRawTable();
  else if (mode === "top")   renderTopPanel();
  else if (mode === "ratio") renderRatioPanel();
}

function onDetailModeChange(e) {
  state.detailMode = e.target.value;
  if (state.rawRows.length || state.ratioRows.length) renderDetailPanel();
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
    const th    = document.createElement("th");
    const label = COL_LABELS[col] || col;
    th.textContent = label;
    th.title       = label;
    if (NUMERIC_COLS.has(col)) th.style.textAlign = "right";
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);

  function _doRenderRawBody(rows) {
    tbody.innerHTML = "";
    const fragment = document.createDocumentFragment();
    rows.slice(0, MAX_RENDER_ROWS).forEach((row) => {
      const tr = document.createElement("tr");
      state.rawColumns.forEach((col) => {
        const td  = document.createElement("td");
        const val = row[col];
        if (NUMERIC_COLS.has(col)) {
          td.style.textAlign = "right";
          td.textContent = (val != null)
            ? Number(val).toLocaleString(undefined, { maximumFractionDigits: 2 })
            : "-";
        } else {
          td.textContent = (val != null && val !== "") ? val : "-";
        }
        tr.appendChild(td);
      });
      fragment.appendChild(tr);
    });
    tbody.appendChild(fragment);

    if (rows.length > MAX_RENDER_ROWS) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan     = state.rawColumns.length;
      td.className   = "sf-table-truncate-msg";
      td.textContent = `… 상위 ${MAX_RENDER_ROWS}건 표시 (전체 ${rows.length.toLocaleString()}건)`;
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
  }

  _attachSorting(thead, state.rawColumns, "rawTable", () => state.rawRows, _doRenderRawBody);

  const ss = _sortState["rawTable"];
  const initialRows = (ss && ss.col)
    ? _sortRows(state.rawRows, ss.col, ss.dir)
    : state.rawRows;
  _doRenderRawBody(initialRows);
}

// ── Top Show (report_stoploss 기반 그룹 집계) ────────────────

/**
 * state.rawRows(report_stoploss) 를 그룹별로 집계해 Top-N 차트 + 테이블을 렌더링한다.
 * - y_field : 현재 선택된 손실 컬럼 (stoploss/pm/qual/bm/eng/etc/stepchg/std_time/rd)
 * - y_mode  : "min" → 절대값(분) / "pct" → plan_time 대비 %
 */
function renderTopPanel() {
  if (!state.rawRows.length) return;

  const groupColStr = document.getElementById("topGroupSelect").value || "area";
  const groupCols   = groupColStr.split(",").map((c) => c.trim()).filter(Boolean);
  const topN        = Math.max(1, parseInt(document.getElementById("topNInput").value, 10) || 10);
  const yField      = document.getElementById("yFieldSelect")?.value || "stoploss";
  const yMode       = state.yMode;

  // ── 그룹별 집계 ───────────────────────────────────────────
  const aggMap = new Map();

  state.rawRows.forEach((row) => {
    const keyParts = groupCols.map((col) => (row[col] != null ? String(row[col]) : ""));
    const key      = keyParts.join("|");

    if (!aggMap.has(key)) {
      const entry = { y_sum: 0, plan_sum: 0, cnt: 0 };
      groupCols.forEach((col) => { entry[col] = row[col] != null ? String(row[col]) : ""; });
      aggMap.set(key, entry);
    }
    const entry = aggMap.get(key);
    entry.y_sum    += (row[yField] || 0);
    entry.plan_sum += (row.plan_time || 0);
    entry.cnt      += 1;
  });

  // ── 값 계산 → 정렬 → 상위 N ──────────────────────────────
  const sorted = Array.from(aggMap.values())
    .map((entry) => ({
      ...entry,
      display_val: yMode === "pct" && entry.plan_sum > 0
        ? Math.round(entry.y_sum / entry.plan_sum * 10000) / 100   // 소수점 2자리 %
        : Math.round(entry.y_sum * 10) / 10,
    }))
    .sort((a, b) => b.display_val - a.display_val)
    .slice(0, topN);

  if (!sorted.length) { showToast("집계 결과가 없습니다."); return; }

  const isDark    = document.documentElement.getAttribute("data-theme") === "dark";
  const fontColor = isDark ? "#94a3b8" : "#64748b";
  const unit      = yMode === "pct" ? "%" : " min";
  const xTitle    = yMode === "pct" ? `${yField.toUpperCase()} (%)` : `${yField.toUpperCase()} (min)`;

  const yLabels = sorted.map((r) => groupCols.map((c) => r[c] || "-").join(" / "));
  const xValues = sorted.map((r) => r.display_val);

  const traces = [{
    type:          "bar",
    orientation:   "h",
    x:             xValues,
    y:             yLabels,
    marker:        { color: yLabels.map((_, i) => COLORS[i % COLORS.length]) },
    text:          xValues.map((v) => v.toLocaleString(undefined, { maximumFractionDigits: 2 }) + unit),
    textposition:  "auto",
    hovertemplate: `<b>%{y}</b><br>${xTitle}: %{x:,.2f}${unit}<extra></extra>`,
  }];

  const layout = {
    margin:  { t: 8, b: 30, l: 160, r: 60 },
    xaxis: { title: { text: xTitle, font: { size: 11 } }, automargin: true, fixedrange: true },
    yaxis: { automargin: true, fixedrange: true, autorange: "reversed" },
    plot_bgcolor:  "transparent",
    paper_bgcolor: "transparent",
    font:      { family: "Inter, sans-serif", size: 11, color: fontColor },
    hoverlabel: { bgcolor: "#0f172a", font: { color: "#f1f5f9", size: 11 }, bordercolor: "#334155" },
  };

  Plotly.react("chartTop", traces, layout, { responsive: true, displayModeBar: false });

  // rank bar 클릭 → tpm_eqp_loss 조회
  const topEl = document.getElementById("chartTop");
  if (typeof topEl.removeAllListeners === "function") topEl.removeAllListeners("plotly_click");
  topEl.on("plotly_click", (eventData) => {
    if (!eventData?.points?.length) return;
    const clickedRow = sorted[eventData.points[0].pointIndex];
    if (clickedRow) onTopBarClick(clickedRow, groupCols);
  });

  _renderTopTable();
}

function _renderTopTable() {
  const thead = document.getElementById("topTableHead");
  const tbody = document.getElementById("topTableBody");
  thead.innerHTML = "";
  tbody.innerHTML = "";

  const rows = state.rawRows;
  if (!rows.length) return;

  const cols = ["eqp_id", "stoploss", "plan_time"];

  // 헤더
  const headerRow = document.createElement("tr");
  cols.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col.toUpperCase().replace("_", " ");
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);

  // 바디
  const fragment = document.createDocumentFragment();
  rows.slice(0, MAX_RENDER_ROWS).forEach((row) => {
    const tr = document.createElement("tr");
    cols.forEach((col) => {
      const td  = document.createElement("td");
      const val = row[col];
      td.textContent = val != null ? val : "";
      if (typeof val === "number") td.style.textAlign = "right";
      tr.appendChild(td);
    });
    fragment.appendChild(tr);
  });
  tbody.appendChild(fragment);
}

async function onTopBarClick(clickedRow, groupCols) {
  // 클릭된 그룹에 속하는 eqp_id 목록 수집
  const matchedRows = state.rawRows.filter((row) =>
    groupCols.every((col) => String(row[col] ?? "") === String(clickedRow[col] ?? ""))
  );
  const eqpIds = [...new Set(matchedRows.map((r) => r.eqp_id).filter(Boolean))];

  const badgeText = groupCols
    .map((col) => `${col}=${clickedRow[col] || "-"}`)
    .join(" / ");

  if (!state.selectedBar) {
    showToast("먼저 메인 차트의 bar를 클릭하세요.");
    return;
  }

  const { flag, yyyy, flagdate } = state.selectedBar;
  const params = new URLSearchParams({ flag, yyyy, flagdate });
  eqpIds.forEach((id) => params.append("eqp_id", id));

  try {
    const res  = await fetch(`${URLS.eqpLossDetail}?${params.toString()}`);
    const json = await res.json();
    if (!json.ok) { showToast(MSG.API_ERROR(json.error)); return; }
    _renderTopRaw(json.data.rows, badgeText, json.data.columns);
  } catch (err) {
    showToast(MSG.NET_ERROR(err.message));
  }
}

function _renderTopRaw(rows, badgeText, columns) {
  const panel   = document.getElementById("topRawPanel");
  const badge   = document.getElementById("topRawBadge");
  const countEl = document.getElementById("topRawCount");
  const thead   = document.getElementById("topRawTableHead");
  const tbody   = document.getElementById("topRawTableBody");

  if (!panel) return;

  if (!rows.length) {
    panel.style.display = "none";
    showToast("해당 그룹의 Raw 데이터가 없습니다.");
    return;
  }

  badge.textContent   = badgeText;
  countEl.textContent = `${rows.length.toLocaleString()}건`;
  panel.style.display = "block";

  thead.innerHTML = "";
  const cols      = columns || (rows.length ? Object.keys(rows[0]) : []);
  const headerRow = document.createElement("tr");
  cols.forEach((col) => {
    const th    = document.createElement("th");
    const label = COL_LABELS[col] || col;
    th.textContent = label;
    th.title       = label;
    if (NUMERIC_COLS.has(col)) th.style.textAlign = "right";
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);

  // keep a local copy of rows for sort callbacks
  let _topRawRows = rows;

  function _doRenderTopRawBody(sortedRows) {
    tbody.innerHTML = "";
    const fragment = document.createDocumentFragment();
    sortedRows.slice(0, MAX_RENDER_ROWS).forEach((row) => {
      const tr = document.createElement("tr");
      cols.forEach((col) => {
        const td  = document.createElement("td");
        const val = row[col];
        if (NUMERIC_COLS.has(col)) {
          td.style.textAlign = "right";
          td.textContent = (val != null)
            ? Number(val).toLocaleString(undefined, { maximumFractionDigits: 2 })
            : "-";
        } else {
          td.textContent = (val != null && val !== "") ? val : "-";
        }
        tr.appendChild(td);
      });
      fragment.appendChild(tr);
    });
    tbody.appendChild(fragment);

    if (sortedRows.length > MAX_RENDER_ROWS) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan     = cols.length;
      td.className   = "sf-table-truncate-msg";
      td.textContent = `… 상위 ${MAX_RENDER_ROWS}건 표시 (전체 ${sortedRows.length.toLocaleString()}건)`;
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
  }

  _attachSorting(thead, cols, "topRawTable", () => _topRawRows, _doRenderTopRawBody);

  const ss = _sortState["topRawTable"];
  const initialRows = (ss && ss.col)
    ? _sortRows(_topRawRows, ss.col, ss.dir)
    : _topRawRows;
  _doRenderTopRawBody(initialRows);
}

function closeTopRaw() {
  const panel = document.getElementById("topRawPanel");
  if (panel) panel.style.display = "none";
}

// ── Ratio Analysis ─────────────────────────────────────────────

/**
 * state.ratioRows 를 Ratio Analysis 테이블로 렌더링한다.
 *
 * 컬럼: state, loss_time_min,
 *        pct_vs_eqp, pct_vs_model, pct_vs_sdwt, pct_vs_area, pct_vs_total
 */
function renderRatioPanel() {
  const thead   = document.getElementById("ratioTableHead");
  const tbody   = document.getElementById("ratioTableBody");
  const emptyEl = document.getElementById("ratioTableEmpty");

  thead.innerHTML = "";
  tbody.innerHTML = "";

  const rows = state.ratioRows || [];
  if (!rows.length) {
    if (emptyEl) emptyEl.style.display = "block";
    return;
  }
  if (emptyEl) emptyEl.style.display = "none";

  const cols = [
    { key: "state",         label: "State"       },
    { key: "loss_time_min", label: "Loss (min)"  },
    { key: "pct_vs_eqp",   label: "vs EQP %"    },
    { key: "pct_vs_model", label: "vs Model %"  },
    { key: "pct_vs_sdwt",  label: "vs SDWT %"   },
    { key: "pct_vs_area",  label: "vs Area %"   },
    { key: "pct_vs_total", label: "vs Total %"  },
  ];

  // 헤더
  const headerRow = document.createElement("tr");
  cols.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col.label;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);

  // 바디
  const fragment = document.createDocumentFragment();
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    cols.forEach((col) => {
      const td  = document.createElement("td");
      const val = row[col.key];

      if (col.key.startsWith("pct_")) {
        if (val != null) {
          td.textContent     = val.toFixed(2) + "%";
          td.style.textAlign = "right";
          if (val > 10)     td.classList.add("pct-high");
          else if (val > 5) td.classList.add("pct-mid");
        } else {
          td.textContent     = "-";
          td.style.textAlign = "right";
          td.style.color     = "var(--sf-text-xmuted)";
        }
      } else if (col.key === "loss_time_min") {
        td.textContent     = val != null
          ? Number(val).toLocaleString(undefined, { maximumFractionDigits: 1 })
          : "-";
        td.style.textAlign = "right";
      } else {
        td.textContent = val != null ? val : "-";
      }

      tr.appendChild(td);
    });
    fragment.appendChild(tr);
  });
  tbody.appendChild(fragment);
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

  const body = {
    question,
    page_context:    "stoploss",
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


// ═══════════════════════════════════════════════════════════════
// 13. 차트 캡처
// ═══════════════════════════════════════════════════════════════

async function captureTopChart() {
  const btn     = document.getElementById("chartCaptureBtn");
  const chartEl = document.getElementById("chartTop");

  if (!chartEl || !chartEl._fullLayout) {
    showToast("캡처할 차트가 없습니다.");
    return;
  }

  const origHTML = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <circle cx="12" cy="12" r="10" stroke-dasharray="31.4" stroke-dashoffset="10">
          <animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur=".8s" repeatCount="indefinite"/>
        </circle>
      </svg>
      캡처 중…`;
  }

  try {
    const dataUrl = await Plotly.toImage("chartTop", {
      format: "png",
      width:  chartEl.offsetWidth  || 800,
      height: chartEl.offsetHeight || 380,
      scale:  2,
    });

    const res  = await fetch(dataUrl);
    const blob = await res.blob();

    if (!navigator.clipboard || !window.ClipboardItem) {
      const a       = document.createElement("a");
      a.href        = dataUrl;
      a.download    = `chart_${Date.now()}.png`;
      a.click();
      showToast("클립보드 API 미지원 — 파일로 다운로드했습니다.");
      return;
    }

    await navigator.clipboard.write([
      new ClipboardItem({ "image/png": blob }),
    ]);

    showToast("📋 차트가 클립보드에 복사됐습니다!");

  } catch (err) {
    console.error("[captureTopChart]", err);
    showToast(`캡처 실패: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled  = false;
      btn.innerHTML = origHTML;
    }
  }
}


// ═══════════════════════════════════════════════════════════════
// 14. Raw Data Excel 다운로드
// ═══════════════════════════════════════════════════════════════

function downloadRawExcel() {
  if (!state.rawRows || !state.rawRows.length) {
    showToast("다운로드할 데이터가 없습니다.");
    return;
  }

  if (typeof XLSX === "undefined") {
    showToast("Excel 라이브러리 로드 중입니다. 잠시 후 다시 시도해 주세요.");
    return;
  }

  const btn      = document.getElementById("rawExcelBtn");
  const origHTML = btn ? btn.innerHTML : "";
  if (btn) { btn.disabled = true; btn.innerHTML = "저장 중…"; }

  try {
    const columns = state.rawColumns.length
      ? state.rawColumns
      : Object.keys(state.rawRows[0]);

    const sheetData = [
      columns,
      ...state.rawRows.map((row) =>
        columns.map((col) => row[col] ?? "")
      ),
    ];

    const ws = XLSX.utils.aoa_to_sheet(sheetData);

    ws["!cols"] = columns.map((col) => {
      const maxLen = Math.max(
        col.length,
        ...state.rawRows.slice(0, 200).map((r) => String(r[col] ?? "").length)
      );
      return { wch: Math.min(maxLen + 2, 40) };
    });

    columns.forEach((_, ci) => {
      const cellAddr = XLSX.utils.encode_cell({ r: 0, c: ci });
      if (!ws[cellAddr]) return;
      ws[cellAddr].s = {
        font:      { bold: true, color: { rgb: "FFFFFF" } },
        fill:      { fgColor: { rgb: "6366F1" } },
        alignment: { horizontal: "center" },
      };
    });

    const wb        = XLSX.utils.book_new();
    const sheetName = "RawData";
    XLSX.utils.book_append_sheet(wb, ws, sheetName);

    const bar      = state.selectedBar;
    const barLabel = bar ? `${bar.flag}${bar.flagdate.replace("/", "")}` : "all";
    const now      = new Date();
    const ts       = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,"0")}${String(now.getDate()).padStart(2,"0")}_${String(now.getHours()).padStart(2,"0")}${String(now.getMinutes()).padStart(2,"0")}`;
    const fileName = `stoploss_rawdata_${barLabel}_${ts}.xlsx`;

    XLSX.writeFile(wb, fileName, { bookType: "xlsx", cellStyles: true });

    showToast(`📥 ${fileName} 다운로드 완료!`);

  } catch (err) {
    console.error("[downloadRawExcel]", err);
    showToast(`Excel 저장 실패: ${err.message}`);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = origHTML; }
  }
}
