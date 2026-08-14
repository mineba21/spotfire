/**
 * stoploss_ai/lossraw.js
 *
 * 역할: 설비 Loss 분석(tpm_eqp_loss 드릴다운) 페이지의 모든 클라이언트 로직
 *
 * 드릴다운:
 *   A(kind, 화면 표기는 State) → B(param_type) → C(param_name, Top10) → raw table
 *   bar 값 = loss_time_min 합 (수평 bar, 내림차순)
 *
 * 사이드바:
 *   기간(start/end, daterangepicker) + area(라인) / eqp_id(설비) / kind / param_type
 *   - 상위 필터 변경 시 하위 옵션 cascading 갱신
 *   - Apply 버튼 없이 change 즉시 재조회 (auto-apply)
 *   - 기간 기본값: 최근 3개월 (하한 LOWER_BOUND)
 */

"use strict";

// ═══════════════════════════════════════════════════════════════
// 1. 상수
// ═══════════════════════════════════════════════════════════════

const URLS      = window.LR_URLS || {};
const ALL_VALUE = "ALL";
const COLORS = [
  "#6366f1", "#06b6d4", "#10b981", "#f59e0b",
  "#ef4444", "#8b5cf6", "#ec4899", "#3b82f6",
  "#14b8a6", "#f97316",
];

const MAX_RENDER_ROWS = 500;   // 화면 표시 상한 (전체는 Excel)
const TOP_C_LIMIT     = 10;    // C 차트는 Top 10 만
const UNCLASSIFIED    = "(미분류)";

// 기간 필터 하한 — lossraw_service.LOSSRAW_START_YMD 와 맞춘다
const DATE_LOWER_BOUND = "2026-01-01";
const DATE_FMT         = "YYYY-MM-DD";

// 데이터 키는 kind 이지만 화면에는 State 로 표기한다.
const LEVEL_LABEL = { kind: "State", param_type: "Param Type", param_name: "Param Name" };

const COL_LABELS = {
  yyyymmdd:      "Date",
  area:          "라인",
  station:       "설비",
  eqp_id:        "EQP ID",
  start_time:    "Start",
  end_time:      "End",
  kind:          "State",
  state:         "State Detail",
  param_type:    "Param Type",
  param_name:    "Param Name",
  loss_time_min: "Loss (min)",
};
const NUMERIC_COLS = new Set(["loss_time_min"]);

// cascading 순서 = 배열 순서 (상위 → 하위)
const FILTER_ORDER = [
  { id: "filterArea",      field: "area",       dataKey: "areas"       },
  { id: "filterEqpId",     field: "eqp_id",     dataKey: "eqp_ids"     },
  { id: "filterKind",      field: "kind",       dataKey: "kinds"       },
  { id: "filterParamType", field: "param_type", dataKey: "param_types" },
];


// ═══════════════════════════════════════════════════════════════
// 2. state
// ═══════════════════════════════════════════════════════════════

/** 현재 드릴다운 선택 (null = 미선택) */
const sel = { kind: null, param_type: null, param_name: null };

let _rawRows = [];
let _rawCols = [];
let _rawBadge = "";
/** 서버 조회 상한(MAX_RAW_ROWS)에 걸렸는지 — 표시/Excel 문구를 정직하게 유지 */
let _rawTotal     = 0;
let _rawTruncated = false;
let _rawMaxRows   = 0;

/** select 별 직전 선택 상태 — ALL ↔ 개별값 전환 의도 판별용 */
const _prevSelected = {};

/** 차트별 마지막 렌더 내용 — 테마 전환 시 재조회 없이 다시 그리기 위함 */
const _lastRender = {};

/** 기간 필터 (moment 객체, daterangepicker 미로드 시 null) */
let _drpStart = null;
let _drpEnd   = null;

/** 설비(eqp_id) 검색 */
let _eqpIdMaster   = [];
const _eqpIdSelected = new Set();
let _eqpIdSearchTimer = null;


// ═══════════════════════════════════════════════════════════════
// 3. 초기화
// ═══════════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
  initTheme();

  FILTER_ORDER.forEach((f) => {
    _prevSelected[f.id] = new Set(
      Array.from(document.getElementById(f.id)?.selectedOptions || []).map((o) => o.value)
    );
  });

  const eqpIdEl = document.getElementById("filterEqpId");
  if (eqpIdEl) {
    _eqpIdMaster = Array.from(eqpIdEl.options)
      .map((o) => o.value).filter((v) => v !== ALL_VALUE);
  }
  _syncEqpIdSelected();

  function on(id, event, handler) {
    const el = document.getElementById(id);
    if (el) el.addEventListener(event, handler);
    else console.warn(`[lossraw] element not found: #${id}`);
  }

  // 필터 change → 정규화 + 하위 옵션 갱신 + 즉시 재조회
  FILTER_ORDER.forEach((f, idx) => {
    on(f.id, "change", async () => {
      normalizeAll(f.id);
      if (f.id === "filterEqpId") _syncEqpIdSelected();
      await refreshFilterOptions(idx);
      loadA();
    });
  });

  initDateFilters();   // 기간 필터는 자체 apply 핸들러에서 재조회

  on("eqpIdSearch", "input", () => {
    clearTimeout(_eqpIdSearchTimer);
    _eqpIdSearchTimer = setTimeout(initEqpIdSearch, 200);
  });

  on("resetFilterBtn",     "click", resetFilters);
  on("lrRawExcelBtn",      "click", downloadRawExcel);
  on("sidebarCollapseBtn", "click", () => toggleSidebar(false));
  on("sidebarToggleBtn",   "click", () => toggleSidebar(true));
  on("themeToggleBtn",     "click", toggleTheme);

  loadA();
});


// ═══════════════════════════════════════════════════════════════
// 4. 필터 수집 / cascading
// ═══════════════════════════════════════════════════════════════

function _esc(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/** 기본 기간 = 최근 3개월 (하한 DATE_LOWER_BOUND) ~ 오늘 */
function _defaultRange() {
  const today = moment();
  const lower = moment(DATE_LOWER_BOUND);
  let start = moment().subtract(3, "months");
  if (start.isBefore(lower)) start = lower.clone();
  return { start, today, lower };
}

/**
 * 기간 필터 초기화 — start / end 각각 단일 캘린더.
 * - autoApply: 적용 버튼 없이 날짜 클릭 즉시 반영
 * - start 확정 시 end 캘린더를 자동으로 띄운다 (반대는 무시)
 */
function initDateFilters() {
  if (typeof window.jQuery === "undefined" || typeof window.moment === "undefined") {
    console.warn("[lossraw] jQuery/moment 미로드 — 기간 필터 없이 동작합니다");
    return;
  }

  const { start, today, lower } = _defaultRange();
  _drpStart = start;
  _drpEnd   = today;

  const opts = (initial, minD, maxD) => ({
    singleDatePicker: true,
    autoUpdateInput: true,
    autoApply: true,                 // ← 적용 버튼 없이 클릭 즉시 반영
    startDate: initial,
    minDate: minD,
    maxDate: maxD,
    locale: { format: DATE_FMT },
  });

  $("#filterStart").daterangepicker(opts(start, lower, today));
  $("#filterEnd").daterangepicker(opts(today, lower, today));
  $("#filterStart").val(start.format(DATE_FMT));
  $("#filterEnd").val(today.format(DATE_FMT));

  // start 확정 → end minDate 좁히고 end 캘린더 자동 오픈
  $("#filterStart").on("apply.daterangepicker", (ev, picker) => {
    _drpStart = picker.startDate;
    if (_drpEnd.isBefore(_drpStart)) _drpEnd = _drpStart.clone();

    const endPicker = $("#filterEnd").data("daterangepicker");
    endPicker.minDate = _drpStart;
    endPicker.setStartDate(_drpEnd);
    $("#filterEnd").val(_drpEnd.format(DATE_FMT));

    refreshFilterOptions(-1);
    loadA();
    $("#filterEnd").click();         // ← end 캘린더 자동으로 띄우기
  });

  // end 확정 → start 는 건드리지 않음
  $("#filterEnd").on("apply.daterangepicker", (ev, picker) => {
    _drpEnd = picker.startDate;      // singleDatePicker 는 startDate 에 선택값
    refreshFilterOptions(-1);
    loadA();
  });
}

/** 기간 파라미터(start/end)를 params 에 싣는다. */
function _appendPeriod(params) {
  if (_drpStart) params.append("start", _drpStart.format("YYYYMMDD"));
  if (_drpEnd)   params.append("end",   _drpEnd.format("YYYYMMDD"));
  return params;
}

/** ALL 이 선택되어 있으면 빈 배열 (= 전체) */
function getSelectedValues(selectId) {
  const el = document.getElementById(selectId);
  if (!el) return [];
  const selected = Array.from(el.selectedOptions).map((o) => o.value);
  if (!selected.length || selected.includes(ALL_VALUE)) return [];
  return selected;
}

/** 기간 + 4개 필터를 항상 실어 보낸다. extra 는 드릴다운 부모 값. */
function collectFilters(extra) {
  const params = new URLSearchParams();

  _appendPeriod(params);

  FILTER_ORDER.forEach((f) => {
    getSelectedValues(f.id).forEach((v) => params.append(f.field, v));
  });

  Object.entries(extra || {}).forEach(([k, v]) => {
    if (v != null && v !== "") params.append(k, v);
  });

  return params;
}

/**
 * ALL + 개별값 동시선택 정리.
 * 방금 ALL 을 눌렀으면 ALL 만, 개별값을 눌렀으면 ALL 을 뗀다.
 * 아무것도 없으면 ALL.
 */
function normalizeAll(selectId) {
  const el = document.getElementById(selectId);
  if (!el) return;

  const prev = _prevSelected[selectId] || new Set([ALL_VALUE]);
  const now  = new Set(Array.from(el.selectedOptions).map((o) => o.value));

  if (!now.size) {
    now.add(ALL_VALUE);
  } else if (now.has(ALL_VALUE) && now.size > 1) {
    if (!prev.has(ALL_VALUE)) {
      now.clear();
      now.add(ALL_VALUE);
    } else {
      now.delete(ALL_VALUE);
    }
  }

  Array.from(el.options).forEach((o) => { o.selected = now.has(o.value); });
  _prevSelected[selectId] = now;
}

/**
 * 기간 + FILTER_ORDER[0..upToIdx] 선택값을 제약으로 옵션 목록을 조회한다.
 * upToIdx = -1 이면 기간만 제약 (최상위 필터용).
 */
async function _fetchFilterOptions(upToIdx) {
  const params = new URLSearchParams();
  _appendPeriod(params);

  FILTER_ORDER.forEach((f, idx) => {
    if (idx > upToIdx) return;
    getSelectedValues(f.id).forEach((v) => params.append(f.field, v));
  });

  try {
    const res = await fetch(`${URLS.filterOptions}?${params.toString()}`);
    if (!res.ok) return null;
    const json = await res.json();
    return json.ok ? json.data : null;
  } catch {
    return null;
  }
}

/**
 * 필터 옵션 재구성 (top-down cascading).
 *
 * @param {number} changedIdx 변경된 필터 인덱스. -1 이면 전체 재구성.
 *
 * 각 필터의 옵션은 "자기보다 상위인 필터" 로만 제약해야 한다.
 * 전체 재구성 때 모든 선택값을 제약으로 걸면 예컨대 라인 A1 선택 상태에서
 * 라인 옵션이 A1 하나만 남아, 기간만 바꿔도 다른 라인으로 못 옮기게 된다.
 * 그래서 전체 재구성은 단계별로 조회한다.
 */
async function refreshFilterOptions(changedIdx = -1) {
  if (changedIdx >= 0) {
    // 변경된 필터까지를 제약으로 한 번만 조회 → 그 아래 필터만 재구성
    const data = await _fetchFilterOptions(changedIdx);
    if (!data) return;
    FILTER_ORDER.forEach((f, idx) => {
      if (idx > changedIdx) rebuildSelect(f.id, data[f.dataKey] || []);
    });
    return;
  }

  // 전체 재구성: 필터마다 자기 상위 필터만 제약으로 걸어 순차 조회
  for (let idx = 0; idx < FILTER_ORDER.length; idx++) {
    const data = await _fetchFilterOptions(idx - 1);
    if (!data) continue;
    const f = FILTER_ORDER[idx];
    rebuildSelect(f.id, data[f.dataKey] || []);
  }
}

/** 옵션 교체 + 기존 선택 보존 (없으면 ALL). eqp_id 는 검색 master 도 갱신. */
function rebuildSelect(selectId, newValues) {
  const el = document.getElementById(selectId);
  if (!el || !Array.isArray(newValues)) return;

  if (selectId === "filterEqpId") {
    _eqpIdMaster = newValues.slice();
    // 새 옵션 목록에 없는 선택값은 버린다
    Array.from(_eqpIdSelected).forEach((v) => {
      if (!_eqpIdMaster.includes(v)) _eqpIdSelected.delete(v);
    });
    initEqpIdSearch();   // 검색어 + 선택 상태를 반영해 재구성
    return;
  }

  const prevSelected = new Set(
    Array.from(el.selectedOptions).map((o) => o.value).filter((v) => v !== ALL_VALUE)
  );

  el.innerHTML = `<option value="${ALL_VALUE}">ALL</option>` +
    newValues.map((v) => `<option value="${_esc(v)}">${_esc(v)}</option>`).join("");

  let restored = 0;
  Array.from(el.options).forEach((o) => {
    if (prevSelected.has(o.value)) { o.selected = true; restored++; }
  });
  if (restored === 0) el.options[0].selected = true;

  _prevSelected[selectId] = new Set(
    Array.from(el.selectedOptions).map((o) => o.value)
  );
}

/** 검색어 부분일치 + 이미 선택된 항목으로 #filterEqpId 옵션 재구성. */
function initEqpIdSearch() {
  const el = document.getElementById("filterEqpId");
  if (!el) return;

  const term = (document.getElementById("eqpIdSearch")?.value || "")
    .trim().toLowerCase();

  const visible = _eqpIdMaster.filter((v) =>
    (!term || String(v).toLowerCase().includes(term)) || _eqpIdSelected.has(v)
  );

  el.innerHTML = `<option value="${ALL_VALUE}">ALL</option>` +
    visible.map((v) => `<option value="${_esc(v)}">${_esc(v)}</option>`).join("");

  let restored = 0;
  Array.from(el.options).forEach((o) => {
    if (o.value !== ALL_VALUE && _eqpIdSelected.has(o.value)) {
      o.selected = true;
      restored++;
    }
  });
  if (restored === 0) el.options[0].selected = true;

  _prevSelected["filterEqpId"] = new Set(
    Array.from(el.selectedOptions).map((o) => o.value)
  );
}

/** select 선택 → 검색과 무관하게 유지되는 Set 동기화 (ALL 이면 clear). */
function _syncEqpIdSelected() {
  const el = document.getElementById("filterEqpId");
  if (!el) return;
  const selected = Array.from(el.selectedOptions).map((o) => o.value);
  _eqpIdSelected.clear();
  if (!selected.includes(ALL_VALUE)) {
    selected.forEach((v) => _eqpIdSelected.add(v));
  }
}

async function resetFilters() {
  FILTER_ORDER.forEach((f) => {
    const el = document.getElementById(f.id);
    if (!el) return;
    Array.from(el.options).forEach((o) => { o.selected = (o.value === ALL_VALUE); });
    _prevSelected[f.id] = new Set([ALL_VALUE]);
  });

  const searchEl = document.getElementById("eqpIdSearch");
  if (searchEl) searchEl.value = "";
  _eqpIdSelected.clear();
  initEqpIdSearch();          // 검색어 해제 상태로 옵션 재구성

  _resetDateFilters();

  await refreshFilterOptions(-1);
  loadA();
}

/** 기간 필터를 기본값(최근 3개월)으로 되돌린다. */
function _resetDateFilters() {
  if (!_drpStart || typeof window.jQuery === "undefined") return;

  const { start, today, lower } = _defaultRange();
  _drpStart = start;
  _drpEnd   = today;

  const startPicker = $("#filterStart").data("daterangepicker");
  const endPicker   = $("#filterEnd").data("daterangepicker");
  if (startPicker) startPicker.setStartDate(start);
  if (endPicker) {
    endPicker.minDate = lower;
    endPicker.setStartDate(today);
  }
  $("#filterStart").val(start.format(DATE_FMT));
  $("#filterEnd").val(today.format(DATE_FMT));
}


// ═══════════════════════════════════════════════════════════════
// 5. 데이터 조회
// ═══════════════════════════════════════════════════════════════

async function fetchAgg(level, parents) {
  const params = collectFilters(parents);
  params.append("level", level);
  try {
    const res  = await fetch(`${URLS.agg}?${params.toString()}`);
    const json = await res.json();
    if (!json.ok) { showToast(`API 오류: ${json.error}`); return []; }
    return json.data.rows || [];
  } catch (err) {
    showToast(`네트워크 오류: ${err.message}`);
    return [];
  }
}

async function fetchRaw(parents) {
  const params = collectFilters(parents);
  try {
    const res  = await fetch(`${URLS.raw}?${params.toString()}`);
    const json = await res.json();
    if (!json.ok) { showToast(`API 오류: ${json.error}`); return null; }
    return json.data;
  } catch (err) {
    showToast(`네트워크 오류: ${err.message}`);
    return null;
  }
}


// ═══════════════════════════════════════════════════════════════
// 6. 드릴다운 (A → B → C → raw)
// ═══════════════════════════════════════════════════════════════

async function loadA() {
  sel.kind = null;
  sel.param_type = null;
  sel.param_name = null;
  setActive(null);

  setChartLoading("A", true);
  const rows = await fetchAgg("kind", {});
  setChartLoading("A", false);

  setTitle("titleA", `${LEVEL_LABEL.kind} 별 Loss (min)`);
  renderBar("chartA", "kind", rows, onClickA);

  setTitle("titleB", `${LEVEL_LABEL.param_type} 별 Loss (min)`);
  setTitle("titleC", `${LEVEL_LABEL.param_name} 별 Loss (min)`);
  clearChart("chartB", "상위 bar 를 선택하세요");
  clearChart("chartC", "상위 bar 를 선택하세요");
  hideRaw();
}

async function onClickA(label) {
  sel.kind = label;
  sel.param_type = null;
  sel.param_name = null;
  setActive("A");

  setChartLoading("B", true);
  const rows = await fetchAgg("param_type", { kind: sel.kind });
  setChartLoading("B", false);

  setTitle("titleB", `${label} · ${LEVEL_LABEL.param_type} 별 Loss (min)`);
  renderBar("chartB", "param_type", rows, onClickB);

  setTitle("titleC", `${LEVEL_LABEL.param_name} 별 Loss (min)`);
  clearChart("chartC", "상위 bar 를 선택하세요");
  hideRaw();
}

async function onClickB(label) {
  sel.param_type = label;
  sel.param_name = null;
  setActive("B");

  setChartLoading("C", true);
  const rows = await fetchAgg("param_name", { kind: sel.kind, param_type: sel.param_type });
  setChartLoading("C", false);

  setTitle("titleC", `${label} · ${LEVEL_LABEL.param_name} Top ${TOP_C_LIMIT} (min)`);
  renderBar("chartC", "param_name", rows.slice(0, TOP_C_LIMIT), onClickC);
  hideRaw();
}

async function onClickC(label) {
  sel.param_name = label;
  setActive("C");

  const data = await fetchRaw({
    kind:       sel.kind,
    param_type: sel.param_type,
    param_name: sel.param_name,
  });
  if (!data) return;

  const badge = [sel.kind, sel.param_type, sel.param_name]
    .filter(Boolean).join(" / ");
  renderRaw(data.rows || [], data.columns || [], badge, {
    total:     data.total,
    truncated: !!data.truncated,
    maxRows:   data.max_rows,
  });
}


// ═══════════════════════════════════════════════════════════════
// 7. 차트 렌더링
// ═══════════════════════════════════════════════════════════════

function _chartFont() {
  const isDark = document.documentElement.getAttribute("data-theme") === "dark";
  return isDark ? "#94a3b8" : "#64748b";
}

/**
 * 수평 bar (x = loss_time_min, 내림차순). bar 클릭 시 onClick(label) 호출.
 * label 은 서버가 준 값 그대로 — 빈 값 그룹은 "(미분류)" 로 오고,
 * 그대로 되돌려 보내면 서버가 다시 빈 값 조건으로 해석한다.
 */
function renderBar(divId, level, rows, onClick) {
  const el = document.getElementById(divId);
  if (!el) return;

  if (!rows || !rows.length) {
    clearChart(divId, "데이터 없음");
    return;
  }

  _lastRender[divId] = { level, rows, onClick };

  const labels = rows.map((r) => r[level] || UNCLASSIFIED);
  const values = rows.map((r) => Number(r.loss_time_min) || 0);
  const fontColor = _chartFont();

  const traces = [{
    type: "bar", orientation: "h",
    x: values, y: labels,
    marker: { color: labels.map((_, i) => COLORS[i % COLORS.length]) },
    text: values.map((v) => v.toLocaleString(undefined, { maximumFractionDigits: 1 })),
    textposition: "auto",
    customdata: rows.map((r) => r.cnt || 0),
    hovertemplate: "<b>%{y}</b><br>Loss: %{x:,.1f} min<br>건수: %{customdata:,}<extra></extra>",
  }];

  const layout = {
    margin: { t: 8, b: 34, l: 130, r: 40 },
    xaxis: { title: { text: "Loss (min)", font: { size: 11 } }, automargin: true, fixedrange: true },
    yaxis: { automargin: true, fixedrange: true, autorange: "reversed" },
    plot_bgcolor: "transparent", paper_bgcolor: "transparent",
    font: { family: "Inter, sans-serif", size: 11, color: fontColor },
    hoverlabel: { bgcolor: "#0f172a", font: { color: "#f1f5f9", size: 11 }, bordercolor: "#334155" },
  };

  Plotly.react(divId, traces, layout, { responsive: true, displayModeBar: false });

  if (typeof el.removeAllListeners === "function") el.removeAllListeners("plotly_click");
  el.on("plotly_click", (eventData) => {
    if (!eventData?.points?.length) return;
    const row = rows[eventData.points[0].pointIndex];
    if (row && typeof onClick === "function") onClick(row[level] || UNCLASSIFIED);
  });
}

function clearChart(divId, message) {
  const el = document.getElementById(divId);
  if (!el) return;
  _lastRender[divId] = { message };
  if (typeof el.removeAllListeners === "function") el.removeAllListeners("plotly_click");
  Plotly.react(divId, [], {
    annotations: [{
      text: message, xref: "paper", yref: "paper",
      x: 0.5, y: 0.5, showarrow: false, font: { color: "#999", size: 13 },
    }],
    margin: { t: 10, b: 20, l: 20, r: 10 },
    xaxis: { visible: false }, yaxis: { visible: false },
    plot_bgcolor: "transparent", paper_bgcolor: "transparent",
  }, { displayModeBar: false });
}

function setTitle(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setChartLoading(which, isLoading) {
  const el = document.getElementById(`loading${which}`);
  if (el) el.style.display = isLoading ? "flex" : "none";
}

/** 선택된 단계 카드에 테두리 강조. which = "A" | "B" | "C" | null */
function setActive(which) {
  ["A", "B", "C"].forEach((k) => {
    const card = document.getElementById(`card${k}`);
    if (card) card.classList.toggle("lr-active", k === which);
  });
}


// ═══════════════════════════════════════════════════════════════
// 8. Raw 테이블
// ═══════════════════════════════════════════════════════════════

function renderRaw(rows, columns, badgeText, meta) {
  const section = document.getElementById("lrRawSection");
  const thead   = document.getElementById("lrRawTableHead");
  const tbody   = document.getElementById("lrRawTableBody");
  const emptyEl = document.getElementById("lrRawTableEmpty");
  const badgeEl = document.getElementById("lrRawBadge");
  const countEl = document.getElementById("lrRawCount");
  if (!section || !thead || !tbody) return;

  _rawRows  = rows || [];
  _rawCols  = (columns && columns.length) ? columns
            : (_rawRows.length ? Object.keys(_rawRows[0]) : []);
  _rawBadge = badgeText || "";
  // 서버가 MAX_RAW_ROWS 로 자를 수 있으므로 실제 건수를 함께 받는다
  _rawTotal     = (meta && meta.total != null) ? meta.total : _rawRows.length;
  _rawTruncated = !!(meta && meta.truncated);
  _rawMaxRows   = (meta && meta.maxRows) || _rawRows.length;

  section.style.display = "block";
  if (badgeEl) badgeEl.textContent = _rawBadge;
  if (countEl) {
    countEl.textContent = _rawTruncated
      ? `${_rawRows.length.toLocaleString()}건 / 전체 ${_rawTotal.toLocaleString()}건 (상한 초과)`
      : `${_rawRows.length.toLocaleString()}건`;
    countEl.title = _rawTruncated
      ? `조회 상한 ${_rawMaxRows.toLocaleString()}건을 넘어 일부만 불러왔습니다. 기간·필터를 좁혀 주세요.`
      : "";
  }

  thead.innerHTML = "";
  tbody.innerHTML = "";

  if (!_rawRows.length) {
    if (emptyEl) emptyEl.style.display = "block";
    return;
  }
  if (emptyEl) emptyEl.style.display = "none";

  const headerRow = document.createElement("tr");
  _rawCols.forEach((col) => {
    const th    = document.createElement("th");
    const label = COL_LABELS[col] || col;
    th.textContent = label;
    th.title       = label;
    if (NUMERIC_COLS.has(col)) th.style.textAlign = "right";
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);

  const fragment = document.createDocumentFragment();
  _rawRows.slice(0, MAX_RENDER_ROWS).forEach((row) => {
    const tr = document.createElement("tr");
    _rawCols.forEach((col) => {
      const td  = document.createElement("td");
      const val = row[col];
      if (NUMERIC_COLS.has(col)) {
        td.style.textAlign = "right";
        td.textContent = (val != null)
          ? Number(val).toLocaleString(undefined, { maximumFractionDigits: 1 })
          : "-";
      } else {
        td.textContent = (val != null && val !== "") ? val : "-";
      }
      tr.appendChild(td);
    });
    fragment.appendChild(tr);
  });
  tbody.appendChild(fragment);

  if (_rawRows.length > MAX_RENDER_ROWS || _rawTruncated) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan   = _rawCols.length;
    td.className = "sf-table-truncate-msg";
    td.textContent = _rawTruncated
      // Excel 도 불러온 만큼만 담기므로 "전체 다운로드" 라고 하지 않는다
      ? `… 상위 ${Math.min(MAX_RENDER_ROWS, _rawRows.length).toLocaleString()}건 표시 · ` +
        `Excel 은 불러온 ${_rawRows.length.toLocaleString()}건 (조회 상한 ${_rawMaxRows.toLocaleString()}건) — ` +
        `전체 ${_rawTotal.toLocaleString()}건을 보려면 기간·필터를 좁혀 주세요`
      : `… 상위 ${MAX_RENDER_ROWS}건 표시 (전체 ${_rawRows.length.toLocaleString()}건) — 전체는 Excel 다운로드`;
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
}

function hideRaw() {
  const section = document.getElementById("lrRawSection");
  if (section) section.style.display = "none";
  _rawRows      = [];
  _rawCols      = [];
  _rawBadge     = "";
  _rawTotal     = 0;
  _rawTruncated = false;
}

function downloadRawExcel() {
  if (!_rawRows.length) { showToast("다운로드할 데이터가 없습니다."); return; }
  if (typeof XLSX === "undefined") {
    showToast("Excel 라이브러리 로드 중입니다. 잠시 후 다시 시도해 주세요.");
    return;
  }

  const btn  = document.getElementById("lrRawExcelBtn");
  const orig = btn?.innerHTML;
  if (btn) { btn.disabled = true; btn.innerHTML = "저장 중…"; }

  try {
    const cols      = _rawCols.length ? _rawCols : Object.keys(_rawRows[0]);
    const sheetData = [
      cols.map((c) => COL_LABELS[c] || c),
      ..._rawRows.map((row) => cols.map((c) => row[c] ?? "")),
    ];

    const ws = XLSX.utils.aoa_to_sheet(sheetData);
    ws["!cols"] = cols.map((col) => {
      const maxLen = Math.max(
        String(COL_LABELS[col] || col).length,
        ..._rawRows.slice(0, 200).map((r) => String(r[col] ?? "").length)
      );
      return { wch: Math.min(maxLen + 2, 40) };
    });

    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "LossRaw");

    const now = new Date();
    const ts  = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}` +
                `${String(now.getDate()).padStart(2, "0")}_` +
                `${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}`;
    const label    = _rawBadge.replace(/[^\w가-힣]+/g, "_").replace(/^_|_$/g, "");
    const fileName = `lossraw_${label || "all"}_${ts}.xlsx`;

    XLSX.writeFile(wb, fileName, { bookType: "xlsx" });
    showToast(_rawTruncated
      ? `📥 ${fileName} — 조회 상한 ${_rawMaxRows.toLocaleString()}건까지만 포함됐습니다 ` +
        `(전체 ${_rawTotal.toLocaleString()}건). 기간·필터를 좁혀 주세요.`
      : `📥 ${fileName} 다운로드 완료!`, _rawTruncated ? 7000 : 4000);
  } catch (err) {
    console.error("[downloadRawExcel]", err);
    showToast(`Excel 저장 실패: ${err.message}`);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = orig; }
  }
}


// ═══════════════════════════════════════════════════════════════
// 9. 테마 / 사이드바 / 토스트
// ═══════════════════════════════════════════════════════════════

function initTheme() {
  const saved     = localStorage.getItem("sf-theme");
  const preferred = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  _applyTheme(saved || preferred);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  _applyTheme(current === "dark" ? "light" : "dark");

  // 폰트 색이 테마에 묶여 있어 다시 그린다 (드릴다운 선택은 유지)
  ["chartA", "chartB", "chartC"].forEach((divId) => {
    const last = _lastRender[divId];
    if (!last) return;
    if (last.rows) renderBar(divId, last.level, last.rows, last.onClick);
    else           clearChart(divId, last.message);
  });
}

function _applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("sf-theme", theme);
}

function toggleSidebar(open) {
  const sidebar = document.getElementById("sfSidebar");
  const main    = document.getElementById("sfMain");
  if (sidebar) sidebar.classList.toggle("sf-sidebar--collapsed", !open);
  if (main)    main.classList.toggle("sf-main--full", !open);
}

let _toastTimer = null;

function showToast(message, duration = 4000) {
  const el = document.getElementById("sfToast");
  if (!el) return;
  el.textContent = message;
  el.classList.add("sf-toast--show");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove("sf-toast--show"), duration);
}
