/**
 * 페이지 간 공유 필터 모듈 (interlock_ai ↔ stoploss_ai).
 *
 * localStorage 에 line/sdwt_prod/eqp_model/eqp_id 선택 상태를 저장하고
 * 페이지 진입 시 복원한다. 옵션 목록에 없는 값은 무시 (graceful fallback).
 *
 * 사용처: 양 앱의 dashboard.js 에서 applySharedFiltersToSelects() /
 *         persistSharedFilters() 를 호출.
 */
window.SF_SHARED = (function () {
  const KEY    = "sf-shared-filters-v1";
  const FIELDS = ["line", "sdwt_prod", "eqp_model", "eqp_id"];

  function save(filtersDict) {
    const shared = {};
    FIELDS.forEach((f) => {
      const v = filtersDict[f];
      if (Array.isArray(v) && v.length) shared[f] = v;
    });
    try { localStorage.setItem(KEY, JSON.stringify(shared)); } catch (_) {}
  }

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY) || "{}"); }
    catch (_) { return {}; }
  }

  function clear() {
    try { localStorage.removeItem(KEY); } catch (_) {}
  }

  return { FIELDS, save, load, clear };
})();
