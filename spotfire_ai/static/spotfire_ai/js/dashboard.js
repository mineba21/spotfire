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

/** API URL — index.html 의 window.SF_URLS 에서 주입됨 */
const URLS = window.SF_URLS || {};

/** sidebar multi-select 에서 "전체" 를 의미하는 값 */
const ALL_VALUE = "ALL";

/** 유효한 flag 목록 */
const VALID_FLAGS = ["M", "W", "D"];

/** Plotly chart div id 맵 */
const CHART_IDS = { M: "chartM", W: "chartW", D: "chartD" };

/** Plotly 색상 팔레트 */
const COLORS = [
  "#6366f1", "#06b6d4", "#10b981", "#f59e0b",
  "#ef4444", "#8b5cf6", "#ec4899", "#3b82f6",
  "#14b8a6", "#f97316",
];

/** raw 테이블 DOM 렌더 최대 행 수 (메모리/퍼포먼스 보호) */
const MAX_RENDER_ROWS = 500;

/** Top Show 에서 label 로 우선 사용할 컬럼 순서 */
const PREFERRED_LABEL_COLS = ["eqp_id", "item_id", "test_id", "line", "sdwt_prod", "param_type"];

/** 에러 메시지 상수 (magic string 방지) */
const MSG = {
  MISSING_BAR : "bar 를 먼저 클릭하세요.",
  NO_NUMERIC  : (col) => `"${col}" 컬럼에 유효한 숫자 데이터가 없습니다.`,
  NET_ERROR   : (msg) => `네트워크 오류: ${msg}`,
  API_ERROR   : (msg) => `API 오류: ${msg}`,
};


// ═══════════════════════════════════════════════════════════════
// 2. state 객체
//    컴포넌트 간 공유 상태를 한 곳에서 관리한다.
// ═══════════════════════════════════════════════════════════════

const state = {
  /**
   * 현재 클릭된 bar 컨텍스트.
   * null 이면 미선택.
   * @type {{ flag: string, yyyy: string, flagdate: string } | null}
   */
  selectedBar: null,

  /**
   * fetchReportData() 가 받아온 전체 chart 응답.
   * bar 클릭 시 yyyy_map 참조에 사용한다.
   * @type {{ M: object, W: object, D: object }}
   */
  chartData: {},

  /**
   * fetchClickDetail() 가 받아온 raw rows.
   * @type {object[]}
   */
  rawRows: [],

  /**
   * rawRows 의 컬럼 이름 목록.
   * @type {string[]}
   */
  rawColumns: [],

  /**
   * 현재 detail 표시 모드.
   * @type {"raw" | "top"}
   */
  detailMode: "raw",

  /**
   * AI Copilot 상태.
   */
  copilot: {
    open: false,   // 드로어 열림 여부
  },
};


// ═══════════════════════════════════════════════════════════════
// 3. 초기화
// ═══════════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
  // 테마 초기화
  initTheme();

  // 페이지 로드 시 chart 바로 조회
  fetchReportData();

  // sidebar Apply / Reset
  document.getElementById("applyFilterBtn").addEventListener("click", fetchReportData);
  document.getElementById("resetFilterBtn").addEventListener("click", resetFilters);

  // Y축 변경 → chart 재조회
  document.getElementById("yFieldSelect").addEventListener("change", fetchReportData);

  // detail 모드 radio 전환
  document.querySelectorAll('input[name="detailMode"]').forEach((radio) => {
    radio.addEventListener("change", onDetailModeChange);
  });

  // Top Show 옵션 변경 → 즉시 re-render
  document.getElementById("topFieldSelect").addEventListener("change", renderDetailPanel);
  document.getElementById("topNInput").addEventListener("change", renderDetailPanel);

  // 선택 초기화 버튼
  document.getElementById("contextClearBtn").addEventListener("click", clearSelectedBar);

  // sidebar 열기/닫기
  document.getElementById("sidebarCollapseBtn").addEventListener("click", () => toggleSidebar(false));
  document.getElementById("sidebarToggleBtn").addEventListener("click",   () => toggleSidebar(true));

  // 테마 토글
  document.getElementById("themeToggleBtn").addEventListener("click", toggleTheme);

  // ── AI Copilot ────────────────────────────────────────────
  document.getElementById("copilotToggleBtn").addEventListener("click", () => toggleCopilot(true));
  document.getElementById("copilotCloseBtn").addEventListener("click",  () => toggleCopilot(false));

  // 전송 버튼
  document.getElementById("aiSendBtn").addEventListener("click", sendAiQuestion);

  // Enter → 전송, Shift+Enter → 줄바꿈
  document.getElementById("aiInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendAiQuestion();
    }
  });

  // 빠른 질문 버튼
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


// ═══════════════════════════════════════════════════════════════
// 4. 필터 수집 유틸
// ═══════════════════════════════════════════════════════════════

/**
 * sidebar 의 모든 필터 값을 URLSearchParams 로 수집한다.
 *
 * multi-select 에서 ALL 이 선택되었거나 아무것도 선택하지 않으면
 * 해당 파라미터를 추가하지 않는다 → 서버가 전체 조회로 처리.
 *
 * 예) L1, L2 선택 → ?line=L1&line=L2
 *     ALL 선택   → (line 파라미터 없음) → 서버: 전체
 *
 * @returns {URLSearchParams}
 */
function collectFilters() {
  const params = new URLSearchParams();

  /** multi-select → querystring 헬퍼 */
  function addMultiSelect(selectId, paramName) {
    const el = document.getElementById(selectId);
    if (!el) return;

    const selected = Array.from(el.selectedOptions).map((o) => o.value);

    // ALL 포함 또는 선택 없음 → skip (서버에서 전체 조회)
    if (!selected.length || selected.includes(ALL_VALUE)) return;

    // 복수값: 동일 key 여러 번 append → ?key=v1&key=v2
    selected.forEach((v) => params.append(paramName, v));
  }

  addMultiSelect("filterLine",      "line");
  addMultiSelect("filterSdwtProd",  "sdwt_prod");
  addMultiSelect("filterEqpModel",  "eqp_model");
  addMultiSelect("filterEqpId",     "eqp_id");
  addMultiSelect("filterParamType", "param_type");

  // rank 상한 (m_rank / w_rank / d_rank)
  params.append("m_rank", document.getElementById("rankM").value || 999);
  params.append("w_rank", document.getElementById("rankW").value || 999);
  params.append("d_rank", document.getElementById("rankD").value || 999);

  // Y축 기준 컬럼
  params.append("y_field", document.getElementById("yFieldSelect").value);

  return params;
}

/**
 * sidebar 필터를 JSON body 용 plain object 로 수집한다.
 * ask-ai API 의 sidebar_filters 파라미터에 사용한다.
 *
 * collectFilters() 와 동일한 로직이지만 URLSearchParams 대신
 * { field: [values] } 형태의 dict 를 반환한다.
 *
 * @returns {object}  예) { "line": ["L1", "L2"], "param_type": ["interlock"] }
 */
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

/**
 * sidebar 필터를 초기 상태(ALL)로 리셋하고 chart 를 재조회한다.
 */
function resetFilters() {
  ["filterLine", "filterSdwtProd", "filterEqpModel", "filterEqpId", "filterParamType"]
    .forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      // 모든 option deselect 후 ALL 만 select
      Array.from(el.options).forEach((o) => { o.selected = (o.value === ALL_VALUE); });
    });

  document.getElementById("rankM").value       = 999;
  document.getElementById("rankW").value       = 999;
  document.getElementById("rankD").value       = 999;
  document.getElementById("yFieldSelect").value = "cnt";

  fetchReportData();
}


// ═══════════════════════════════════════════════════════════════
// 5. Report Data fetch (M/W/D chart)
// ═══════════════════════════════════════════════════════════════

/**
 * GET /spotfire-ai/api/report-data/
 *
 * 성공 시:
 *   - state.chartData 에 전체 응답 저장 (yyyy_map 포함)
 *   - M/W/D 각 flag 의 bar chart 를 Plotly 로 그린다
 *
 * 중요: state.chartData 는 bar 클릭 시 yyyy_map 참조에 쓰인다.
 */
async function fetchReportData() {
  setChartLoading(true);

  const params = collectFilters();
  const url    = `${URLS.reportData}?${params.toString()}`;

  try {
    const res  = await fetch(url);
    const json = await res.json();

    if (!json.ok) {
      showToast(MSG.API_ERROR(json.error));
      return;
    }

    // ── 핵심: 전체 chart 데이터를 state 에 저장 ──────────────
    // bar 클릭 시 state.chartData[flag].yyyy_map[flagdate] 로
    // 정확한 연도를 조회한다. (현재연도 추측 로직 불필요)
    state.chartData = json.data;

    // 각 flag 별 chart 렌더링
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

/**
 * 단일 flag 의 bar chart 를 Plotly 로 그린다.
 *
 * @param {string} flag   - "M" | "W" | "D"
 * @param {object} data   - { flagdates, yyyy_map, series: [{name, y}] }
 */
function renderBarChart(flag, data) {
  const divId = CHART_IDS[flag];
  if (!divId) return;

  // ── 데이터 없음 처리 ──────────────────────────────────────
  if (!data || !data.flagdates || !data.flagdates.length) {
    Plotly.react(
      divId,
      [],
      {
        annotations: [{
          text: "데이터 없음",
          xref: "paper", yref: "paper",
          x: 0.5, y: 0.5,
          showarrow: false,
          font: { color: "#999", size: 13 },
        }],
        margin: { t: 10, b: 20, l: 20, r: 10 },
        paper_bgcolor: "transparent",
      },
      { displayModeBar: false }
    );
    return;
  }

  const { flagdates, series } = data;

  // ── Plotly trace 생성 ─────────────────────────────────────
  // series 가 1개(ALL 모드)이면 단색 bar
  // series 가 여러 개(grouped 모드)이면 색상 분리
  const traces = series.map((s, idx) => ({
    type:          "bar",
    name:          s.name,
    x:             flagdates,
    y:             s.y,
    marker:        { color: COLORS[idx % COLORS.length] },
    hovertemplate: "<b>%{x}</b><br>%{y:,.0f}<extra>%{fullData.name}</extra>",
  }));

  const yLabel   = document.getElementById("yFieldSelect").value;
  const isDark   = document.documentElement.getAttribute("data-theme") === "dark";
  const fontColor = isDark ? "#94a3b8" : "#64748b";
  const hoverBg   = isDark ? "#1e293b" : "#0f172a";

  const layout = {
    barmode: "group",
    margin:  { t: 8, b: 56, l: 46, r: 8 },
    xaxis: {
      tickangle:  -30,
      automargin: true,
      fixedrange: true,
    },
    yaxis: {
      title:      { text: yLabel, font: { size: 11 } },
      automargin: true,
      fixedrange: true,
    },
    legend: {
      orientation: "h",
      y:           -0.28,
      font:        { size: 10 },
    },
    plot_bgcolor:  "transparent",
    paper_bgcolor: "transparent",
    font:          { family: "Inter, sans-serif", size: 11, color: fontColor },
    hoverlabel:    { bgcolor: hoverBg, font: { color: "#f1f5f9", size: 11 }, bordercolor: "#334155" },
  };

  // ── Plotly.react → 초기/갱신 모두 이 함수로 처리 ─────────
  Plotly.react(divId, traces, layout, {
    responsive:     true,
    displayModeBar: false,
  });

  // ── click 이벤트 바인딩 ───────────────────────────────────
  // Plotly.react 호출 후 removeAllListeners 가 사용 가능하다.
  // 필터 변경으로 chart 가 재렌더될 때마다 중복 핸들러가 쌓이는 것을 방지한다.
  const el = document.getElementById(divId);
  if (typeof el.removeAllListeners === "function") {
    el.removeAllListeners("plotly_click");
  }
  el.on("plotly_click", (eventData) => onBarClick(flag, eventData));
}

/**
 * 모든 chart div 의 loading 오버레이를 표시/해제한다.
 * @param {boolean} isLoading
 */
function setChartLoading(isLoading) {
  VALID_FLAGS.forEach((flag) => {
    const el = document.getElementById(`loading${flag}`);
    if (el) el.style.display = isLoading ? "flex" : "none";
  });
}


// ═══════════════════════════════════════════════════════════════
// 7. Bar 클릭 핸들러
// ═══════════════════════════════════════════════════════════════

/**
 * Plotly bar 클릭 시 호출된다.
 *
 * 흐름:
 *   클릭된 bar 의 x(flagdate) → state.chartData[flag].yyyy_map[flagdate] 로 yyyy 조회
 *   → state.selectedBar 저장 → contextBar 업데이트 → fetchClickDetail()
 *
 * @param {string} flag        - "M" | "W" | "D"
 * @param {object} eventData   - Plotly plotly_click 이벤트 객체
 */
function onBarClick(flag, eventData) {
  if (!eventData?.points?.length) return;

  const point    = eventData.points[0];
  const flagdate = String(point.x);   // x축 값 = flagdate

  // ── yyyy 조회 (서버 응답 데이터 기반) ─────────────────────
  // state.chartData[flag].yyyy_map 에서 직접 가져온다.
  // 이전: extractYyyy() 로 현재연도를 추측 → 연도가 바뀌거나 과거 데이터 조회 시 오류 가능
  // 현재: 서버가 report 테이블에서 정확한 yyyy 를 반환 → 신뢰도 100%
  const yyyy = state.chartData?.[flag]?.yyyy_map?.[flagdate]
             ?? String(new Date().getFullYear());  // fallback: 현재연도

  // 상태 저장
  state.selectedBar = { flag, yyyy, flagdate };

  // 컨텍스트 배지 업데이트
  updateContextBar();

  // AI Copilot context hint 갱신
  updateCopilotContextHint();

  // raw detail 조회
  fetchClickDetail();
}

/**
 * bar 선택 및 detail 상태를 초기화한다.
 */
function clearSelectedBar() {
  state.selectedBar = null;
  state.rawRows     = [];
  state.rawColumns  = [];

  document.getElementById("contextBar").style.display = "none";
  document.getElementById("sfDetail").style.display   = "none";

  // AI Copilot context hint 도 초기화
  updateCopilotContextHint();
}


// ═══════════════════════════════════════════════════════════════
// 8. Click Detail fetch (raw 테이블 데이터 조회)
// ═══════════════════════════════════════════════════════════════

/**
 * GET /spotfire-ai/api/click-detail/
 *
 * 필수 파라미터 (state.selectedBar 에서 가져옴):
 *   flag, yyyy, flagdate
 *
 * 추가 파라미터 (sidebar 필터):
 *   line, sdwt_prod, eqp_model, eqp_id, param_type (multi-select)
 *
 * 성공 시:
 *   1. state.rawRows / rawColumns 갱신
 *   2. topFieldSelect 드롭다운 동적 업데이트
 *   3. 현재 detailMode 에 맞춰 렌더링
 */
async function fetchClickDetail() {
  const { flag, yyyy, flagdate } = state.selectedBar || {};

  // ── 필수 파라미터 누락 방어 ───────────────────────────────
  if (!flag || !yyyy || !flagdate) {
    showToast(MSG.MISSING_BAR);
    return;
  }

  // 로딩 상태 진입
  setDetailLoading(true);
  document.getElementById("sfDetail").style.display = "block";

  // ── querystring 구성 ──────────────────────────────────────
  const params = collectFilters();   // sidebar 필터 포함

  // 필수 파라미터 명시적 추가 (누락 없도록 항상 마지막에 append)
  params.append("flag",     flag);
  params.append("yyyy",     yyyy);
  params.append("flagdate", flagdate);

  const url = `${URLS.clickDetail}?${params.toString()}`;

  try {
    const res  = await fetch(url);
    const json = await res.json();

    if (!json.ok) {
      showToast(MSG.API_ERROR(json.error));
      return;
    }

    // 상태 갱신
    state.rawRows    = json.data.rows    || [];
    state.rawColumns = json.data.columns || [];

    // 건수 표시
    const countEl = document.getElementById("detailCount");
    if (countEl) {
      const total = (json.data.total || 0).toLocaleString();
      countEl.textContent = `총 ${total}건`;
    }

    // Top Field 드롭다운을 숫자 컬럼으로 동적 채우기
    // (renderDetailPanel 호출 전에 먼저 실행해야 renderTopPanel 이 올바른 컬럼 사용)
    populateTopFieldSelect();

    // 현재 모드에 맞게 렌더링
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

/**
 * state.detailMode 에 따라 rawDataPanel 또는 topDataPanel 을 표시한다.
 * radio 변경, Top 옵션 변경, 데이터 로드 후 모두 이 함수를 경유한다.
 */
function renderDetailPanel() {
  const isRaw = (state.detailMode === "raw");

  // 패널 전환
  document.getElementById("rawDataPanel").style.display = isRaw ? "block" : "none";
  document.getElementById("topDataPanel").style.display = isRaw ? "none"  : "block";

  // Top 옵션 toolbar 표시 여부
  document.getElementById("topOptions").style.display   = isRaw ? "none"  : "flex";

  if (isRaw) {
    renderRawTable();
  } else {
    renderTopPanel();
  }
}

/**
 * detail 모드 radio 변경 핸들러
 */
function onDetailModeChange(e) {
  state.detailMode = e.target.value;
  // 데이터가 있을 때만 re-render
  if (state.rawRows.length) renderDetailPanel();
}

// ── Rawdata Show ──────────────────────────────────────────────

/**
 * state.rawRows 전체를 HTML 테이블로 렌더링한다.
 *
 * DOM 성능 보호: MAX_RENDER_ROWS(500) 행까지만 렌더하고
 *               초과 시 안내 행을 표시한다.
 */
function renderRawTable() {
  const thead   = document.getElementById("rawTableHead");
  const tbody   = document.getElementById("rawTableBody");
  const emptyEl = document.getElementById("rawTableEmpty");

  thead.innerHTML = "";
  tbody.innerHTML = "";

  // ── 빈 데이터 ─────────────────────────────────────────────
  if (!state.rawColumns.length || !state.rawRows.length) {
    if (emptyEl) emptyEl.style.display = "block";
    return;
  }
  if (emptyEl) emptyEl.style.display = "none";

  // ── 헤더 ─────────────────────────────────────────────────
  const headerRow = document.createElement("tr");
  state.rawColumns.forEach((col) => {
    const th    = document.createElement("th");
    th.textContent = col;
    th.title       = col;    // 긴 컬럼명 tooltip
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);

  // ── 바디 ─────────────────────────────────────────────────
  const visibleRows = state.rawRows.slice(0, MAX_RENDER_ROWS);
  const fragment    = document.createDocumentFragment();

  visibleRows.forEach((row) => {
    const tr = document.createElement("tr");
    state.rawColumns.forEach((col) => {
      const td  = document.createElement("td");
      const val = row[col];
      td.textContent = (val != null) ? val : "";
      // 숫자 우측 정렬
      if (typeof val === "number") td.style.textAlign = "right";
      tr.appendChild(td);
    });
    fragment.appendChild(tr);
  });
  tbody.appendChild(fragment);

  // ── 행 수 초과 안내 ────────────────────────────────────────
  if (state.rawRows.length > MAX_RENDER_ROWS) {
    const tr  = document.createElement("tr");
    const td  = document.createElement("td");
    td.colSpan           = state.rawColumns.length;
    td.className         = "sf-table-truncate-msg";
    td.textContent       = `… 상위 ${MAX_RENDER_ROWS}건 표시 (전체 ${state.rawRows.length.toLocaleString()}건)`;
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
}

// ── Top Show ─────────────────────────────────────────────────

/**
 * topFieldSelect 에서 선택된 컬럼 기준으로
 * 상위 N 건의 수평 bar chart + 순위 테이블을 렌더링한다.
 *
 * 수평 bar (orientation: "h") 를 사용하는 이유:
 *   eqp_id, item_id 등 label 이 길어도 잘리지 않고 표시된다.
 */
function renderTopPanel() {
  const topField = document.getElementById("topFieldSelect").value;
  const topN     = Math.max(1, parseInt(document.getElementById("topNInput").value, 10) || 10);

  if (!state.rawRows.length) return;

  // ── 정렬 및 상위 N 추출 ────────────────────────────────────
  const sorted = [...state.rawRows]
    .filter((r) => r[topField] != null && !isNaN(Number(r[topField])))
    .sort((a, b) => Number(b[topField]) - Number(a[topField]))
    .slice(0, topN);

  if (!sorted.length) {
    showToast(MSG.NO_NUMERIC(topField));
    return;
  }

  // ── label 컬럼 선택 ────────────────────────────────────────
  // PREFERRED_LABEL_COLS 에서 raw 컬럼에 있는 첫 번째를 사용
  const labelCol = PREFERRED_LABEL_COLS.find((c) => state.rawColumns.includes(c)) ?? null;

  // y축 (수평 bar): label (문자열), x축: 숫자값
  const yLabels = sorted.map((r, i) => (labelCol ? String(r[labelCol]) : `#${i + 1}`));
  const xValues = sorted.map((r) => Number(r[topField]) || 0);

  // ── Plotly 수평 bar ──────────────────────────────────────
  const traces = [{
    type:          "bar",
    orientation:   "h",              // 수평
    x:             xValues,
    y:             yLabels,
    marker: {
      // 순위별로 색상 변화 (1위: COLORS[0], 2위: COLORS[1], ...)
      color: yLabels.map((_, i) => COLORS[i % COLORS.length]),
    },
    text:          xValues.map((v) => v.toLocaleString()),
    textposition:  "auto",
    hovertemplate: "<b>%{y}</b><br>%{x:,.0f}<extra></extra>",
  }];

  const layout = {
    margin:  { t: 8, b: 30, l: 120, r: 50 },
    xaxis: {
      title:      { text: topField, font: { size: 11 } },
      automargin: true,
      fixedrange: true,
    },
    yaxis: {
      automargin: true,
      fixedrange: true,
      autorange:  "reversed",        // 1위가 맨 위에 오도록
    },
    plot_bgcolor:  "transparent",
    paper_bgcolor: "transparent",
    font:          { family: "Inter, sans-serif", size: 11, color: "#64748b" },
    hoverlabel:    { bgcolor: "#0f172a", font: { color: "#f1f5f9", size: 11 }, bordercolor: "#334155" },
  };

  Plotly.react("chartTop", traces, layout, {
    responsive:     true,
    displayModeBar: false,
  });

  // ── 우측 순위 테이블 ─────────────────────────────────────
  _renderTopTable(sorted, topField);
}

/**
 * Top Show 오른쪽 순위 테이블을 렌더링하는 내부 헬퍼.
 *
 * @param {object[]} rows      - 정렬 완료된 상위 N 행
 * @param {string}   topField  - 하이라이트할 기준 컬럼명
 */
function _renderTopTable(rows, topField) {
  const thead = document.getElementById("topTableHead");
  const tbody = document.getElementById("topTableBody");
  thead.innerHTML = "";
  tbody.innerHTML = "";

  if (!rows.length) return;

  // ── 헤더: 순위(#) + 원본 컬럼들 ─────────────────────────
  const headerRow = document.createElement("tr");
  ["#", ...state.rawColumns].forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);

  // ── 바디 ─────────────────────────────────────────────────
  const fragment = document.createDocumentFragment();
  rows.forEach((row, idx) => {
    const tr = document.createElement("tr");

    // 순위 셀
    const rankTd       = document.createElement("td");
    rankTd.textContent = idx + 1;
    rankTd.className   = "sf-rank-cell";
    tr.appendChild(rankTd);

    // 데이터 셀
    state.rawColumns.forEach((col) => {
      const td  = document.createElement("td");
      const val = row[col];
      td.textContent = (val != null) ? val : "";
      if (typeof val === "number") td.style.textAlign = "right";
      // 기준 컬럼 하이라이트
      if (col === topField) td.classList.add("sf-highlight-cell");
      tr.appendChild(td);
    });

    fragment.appendChild(tr);
  });
  tbody.appendChild(fragment);
}

// ── Top Field 드롭다운 동적 업데이트 ────────────────────────────

/**
 * state.rawRows 의 첫 번째 row 를 분석해 숫자형 컬럼을 감지하고
 * topFieldSelect 드롭다운을 동적으로 채운다.
 *
 * 컬럼 추가 시: SpotfireRaw 에 FloatField/IntegerField 추가 →
 *              raw API 응답에 포함 → 이 함수가 자동으로 감지
 */
function populateTopFieldSelect() {
  const select = document.getElementById("topFieldSelect");
  if (!select) return;

  const prevVal    = select.value;             // 이전 선택값 보존
  const numericCols = _getNumericColumns();    // 숫자형 컬럼 목록

  if (!numericCols.length) return;

  // 드롭다운 재구성
  select.innerHTML = "";
  numericCols.forEach((col) => {
    const opt       = document.createElement("option");
    opt.value       = col;
    opt.textContent = col;
    if (col === prevVal) opt.selected = true;
    select.appendChild(opt);
  });

  // 이전 선택값이 새 목록에 없으면 "value" 우선, 없으면 첫 번째
  if (!numericCols.includes(prevVal)) {
    select.value = numericCols.includes("value") ? "value" : numericCols[0];
  }
}

/**
 * state.rawRows[0] 기준으로 숫자형(number) 컬럼 목록을 반환한다.
 *
 * JSON 응답에서 숫자가 아닌 문자열로 직렬화된 컬럼은 제외된다.
 * (FloatField, IntegerField → number | CharField → string)
 *
 * @returns {string[]}
 */
function _getNumericColumns() {
  if (!state.rawRows.length) return [];
  const firstRow = state.rawRows[0];
  return state.rawColumns.filter((col) => typeof firstRow[col] === "number");
}

// ── Detail 로딩 상태 ─────────────────────────────────────────

/**
 * detail 섹션의 로딩 오버레이를 표시/해제한다.
 * 로딩 중에는 detailBody 를 visibility:hidden 으로 가려
 * 이전 데이터가 잠깐 보이는 것을 방지한다.
 *
 * @param {boolean} isLoading
 */
function setDetailLoading(isLoading) {
  const loadingEl = document.getElementById("detailLoading");
  const bodyEl    = document.getElementById("detailBody");

  if (loadingEl) loadingEl.style.display    = isLoading ? "flex"    : "none";
  if (bodyEl)    bodyEl.style.visibility    = isLoading ? "hidden"  : "visible";
}


// ═══════════════════════════════════════════════════════════════
// 10. Sidebar / UI 유틸
// ═══════════════════════════════════════════════════════════════

/**
 * 저장된 테마(localStorage) 또는 시스템 설정을 읽어 적용한다.
 * <head> 의 인라인 스크립트와 동일한 로직 — DOMContentLoaded 시 재확인.
 */
function initTheme() {
  const saved = localStorage.getItem("sf-theme");
  const preferred = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  _applyTheme(saved || preferred);
}

/**
 * 현재 테마를 반전하여 적용하고 localStorage 에 저장한다.
 * Plotly 차트도 즉시 테마에 맞게 재렌더한다.
 */
function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  _applyTheme(current === "dark" ? "light" : "dark");

  // 테마 변경 후 차트 폰트/배경 색상 반영을 위해 재렌더
  VALID_FLAGS.forEach((flag) => {
    if (state.chartData[flag]) renderBarChart(flag, state.chartData[flag]);
  });
  if (state.rawRows.length && state.detailMode === "top") renderTopPanel();
}

/**
 * data-theme 속성 설정 + localStorage 저장.
 * @param {"light"|"dark"} theme
 */
function _applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("sf-theme", theme);
}

/**
 * sidebar 를 열거나 닫는다.
 * @param {boolean} open
 */
function toggleSidebar(open) {
  const sidebar = document.getElementById("sfSidebar");
  const main    = document.getElementById("sfMain");

  sidebar.classList.toggle("sf-sidebar--collapsed", !open);
  main.classList.toggle("sf-main--full", !open);
}

/**
 * 클릭 컨텍스트 배지 (state.selectedBar 정보 표시) 를 업데이트한다.
 */
function updateContextBar() {
  const { flag, yyyy, flagdate } = state.selectedBar || {};
  if (!flag) return;

  const barEl   = document.getElementById("contextBar");
  const badgeEl = document.getElementById("contextBadge");

  // 예) "D / 2024 / 2024-01-15"
  badgeEl.textContent = `${flag} / ${yyyy} / ${flagdate}`;
  barEl.style.display = "flex";
}


// ═══════════════════════════════════════════════════════════════
// 11. 에러 / 토스트 유틸
// ═══════════════════════════════════════════════════════════════

let _toastTimer = null;

/**
 * 화면 우하단에 토스트 메시지를 표시한다.
 *
 * @param {string} message
 * @param {number} duration - 표시 시간(ms), 기본 4000
 */
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

// ── 유틸 ────────────────────────────────────────────────────

/**
 * <meta name="csrf-token"> 에서 CSRF 토큰을 읽는다.
 * Django 가 template 에서 {{ csrf_token }} 으로 주입한다.
 *
 * @returns {string}
 */
function getCsrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.content || "";
}

// ── 드로어 토글 ─────────────────────────────────────────────

/**
 * AI Copilot 우측 드로어를 열거나 닫는다.
 *
 * open=true  → .sf-copilot--open 클래스 추가 → width 340px 전환 (CSS transition)
 * open=false → 클래스 제거 → width 0
 *
 * sf-main 은 flex:1 이므로 copilot 이 열릴 때 자동으로 줄어든다.
 *
 * @param {boolean} open
 */
function toggleCopilot(open) {
  state.copilot.open = open;
  document.getElementById("sfCopilot").classList.toggle("sf-copilot--open", open);

  // 드로어가 열릴 때 선택된 bar 컨텍스트 힌트 갱신
  if (open) updateCopilotContextHint();
}

// ── 컨텍스트 힌트 ────────────────────────────────────────────

/**
 * AI Copilot 입력창 위의 "현재 선택된 bar" 힌트를 업데이트한다.
 * bar 클릭 / 초기화 / 드로어 열기 시 항상 호출된다.
 */
function updateCopilotContextHint() {
  const el = document.getElementById("copilotContextHint");
  if (!el) return;

  if (state.selectedBar) {
    const { flag, yyyy, flagdate } = state.selectedBar;
    el.textContent  = `📍 선택된 bar: ${flag} / ${yyyy} / ${flagdate}`;
    el.style.display = "block";
  } else {
    el.textContent  = "";
    el.style.display = "none";
  }
}

// ── 채팅 메시지 렌더링 ───────────────────────────────────────

/**
 * 채팅 이력 div 에 메시지 버블을 추가하고 최하단으로 스크롤한다.
 *
 * @param {"user"|"ai"} role        - 메시지 발신자
 * @param {string}       text        - 표시할 텍스트 (\n → <br> 자동 변환)
 * @param {object[]|null} previewRows - AI 응답 results_preview (없으면 null)
 * @returns {HTMLElement} 생성된 메시지 div
 */
function appendChatMessage(role, text, previewRows) {
  const history = document.getElementById("copilotHistory");
  if (!history) return null;

  const msgDiv = document.createElement("div");
  msgDiv.className = `sf-chat-msg sf-chat-msg--${role}`;

  const bubble = document.createElement("div");
  bubble.className = "sf-chat-msg__bubble";

  // 개행 → <br>
  // textContent 대신 innerHTML 을 사용하므로 XSS 방지를 위해 직접 이스케이프
  bubble.innerHTML = _escapeHtml(text).replace(/\n/g, "<br>");
  msgDiv.appendChild(bubble);

  // AI 응답에 preview 데이터가 있으면 소형 테이블 첨부
  if (role === "ai" && previewRows && previewRows.length) {
    msgDiv.appendChild(_buildPreviewTable(previewRows));
  }

  history.appendChild(msgDiv);
  history.scrollTop = history.scrollHeight;

  return msgDiv;
}

/**
 * AI 응답 대기 중 "점 세 개 로딩" 버블을 추가한다.
 * removeChatLoading() 으로 제거한다.
 *
 * @returns {HTMLElement}
 */
function appendChatLoading() {
  const history = document.getElementById("copilotHistory");
  if (!history) return null;

  const msgDiv = document.createElement("div");
  msgDiv.id        = "copilotLoadingMsg";
  msgDiv.className = "sf-chat-msg sf-chat-msg--ai";

  const bubble = document.createElement("div");
  bubble.className = "sf-chat-msg__bubble";
  bubble.innerHTML = (
    '<span class="sf-chat-dots">' +
    '<span></span><span></span><span></span>' +
    '</span>'
  );
  msgDiv.appendChild(bubble);

  history.appendChild(msgDiv);
  history.scrollTop = history.scrollHeight;

  return msgDiv;
}

/**
 * 로딩 버블을 제거한다.
 */
function removeChatLoading() {
  const el = document.getElementById("copilotLoadingMsg");
  if (el) el.remove();
}

/**
 * AI results_preview 를 소형 HTML 테이블로 변환한다.
 *
 * @param {object[]} rows
 * @returns {HTMLElement}
 */
function _buildPreviewTable(rows) {
  const cols    = Object.keys(rows[0]);
  const wrapper = document.createElement("div");
  wrapper.className = "sf-chat-preview-wrap";

  const table = document.createElement("table");
  table.className = "sf-chat-preview-table";

  // 헤더
  const thead     = document.createElement("thead");
  const headerRow = document.createElement("tr");
  cols.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  // 바디
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

/**
 * HTML 특수문자를 이스케이프한다 (XSS 방지).
 * bubble.innerHTML 에 사용자 텍스트를 넣기 전에 반드시 호출한다.
 *
 * @param {string} str
 * @returns {string}
 */
function _escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ── 질문 전송 ────────────────────────────────────────────────

/**
 * AI Copilot 에 질문을 전송하고 응답을 채팅 이력에 추가한다.
 *
 * 흐름:
 *   1. 입력값 읽기 → 사용자 버블 추가 → 로딩 버블 표시
 *   2. POST /spotfire-ai/api/ask-ai/ (JSON body)
 *      { question, page_context, selected_bar, sidebar_filters }
 *   3. 응답 → 로딩 제거 → AI 버블 추가 (answer + preview table)
 *   4. 오류 → 오류 버블 표시
 */
async function sendAiQuestion() {
  const input    = document.getElementById("aiInput");
  const question = (input?.value || "").trim();
  if (!question) return;

  // 입력창 초기화
  input.value = "";

  // 사용자 버블 추가
  appendChatMessage("user", question);

  // 로딩 버블 표시
  appendChatLoading();

  // 전송 버튼 비활성화 (중복 전송 방지)
  const sendBtn = document.getElementById("aiSendBtn");
  if (sendBtn) sendBtn.disabled = true;

  // ── request body 구성 ────────────────────────────────────
  const pageContext = document.getElementById("pageContextSelect")?.value || "interlock";

  const body = {
    question,
    page_context:    pageContext,
    selected_bar:    state.selectedBar || null,
    sidebar_filters: collectFiltersAsDict(),
  };

  // ── POST 요청 ─────────────────────────────────────────────
  try {
    const res = await fetch(URLS.askAi, {
      method:  "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken":  getCsrfToken(),
      },
      body: JSON.stringify(body),
    });

    const json = await res.json();
    removeChatLoading();

    if (!json.ok) {
      appendChatMessage("ai", `⚠️ 오류: ${json.error}`);
      return;
    }

    const { answer, result_count, results_preview } = json.data;

    // 건수 suffix
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
