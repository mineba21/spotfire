"""
interlock_ai/views.py

역할: request 파싱 + service 호출 + JSON/HTML response 반환
규칙:
  - 비즈니스 로직은 services/ 에 위임한다
  - 성공: {"ok": true,  "data":  ...}
  - 실패: {"ok": false, "error": "..."}
"""

import json
import logging

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from interlock_ai.models import SpotfireReport, SpotfireRaw
from interlock_ai.services.filter_service import parse_sidebar_filters, build_filter_q
from interlock_ai.services.chart_service  import get_chart_data, parse_rank_limits
from interlock_ai.services.detail_service import get_raw_detail
from interlock_ai.services.ai_service     import ask_ai, VALID_PAGE_CONTEXTS

logger = logging.getLogger(__name__)

ERR_MISSING_PARAMS    = "flag, yyyy, flagdate 파라미터가 필요합니다."
ERR_INVALID_FLAG      = "flag 값은 M / W / D 중 하나여야 합니다."
ERR_DATE_PARSE        = "flagdate 로 날짜 범위를 계산할 수 없습니다."
ERR_MISSING_QUESTION  = "question 파라미터가 필요합니다."
ERR_INVALID_JSON_BODY = "요청 body 가 유효한 JSON 이 아닙니다."

VALID_FLAGS: set = {"M", "W", "D"}


# ─────────────────────────────────────────────────────────────────
# 페이지 뷰
# ─────────────────────────────────────────────────────────────────
def index(request):
    filter_options = {
        "lines":        _get_distinct("line"),
        "sdwt_prods":   _get_distinct("sdwt_prod"),
        "eqp_models":   _get_distinct("eqp_model"),
        "eqp_ids":      _get_distinct("eqp_id"),
        "param_types":  _get_distinct("param_type"),
        "param_names":  _get_distinct_raw("param_name"),
    }
    context = {
        "filter_options": filter_options,
    }
    return render(request, "interlock_ai/index.html", context)


def _get_distinct(field: str) -> list:
    values = (
        SpotfireReport.objects
        .exclude(**{field: ""})
        .values_list(field, flat=True)
        .distinct()
        .order_by(field)
    )
    return sorted({v for v in values if v})


def _get_distinct_raw(field: str) -> list:
    """SpotfireRaw 에서 distinct 값 목록을 반환한다 (param_name 등 Raw 전용 필드용)."""
    values = (
        SpotfireRaw.objects
        .exclude(**{field: ""})
        .values_list(field, flat=True)
        .distinct()
        .order_by(field)
    )
    return sorted({v for v in values if v})


# ─────────────────────────────────────────────────────────────────
# API: report-data
# ─────────────────────────────────────────────────────────────────
@require_GET
def api_report_data(request):
    filters     = parse_sidebar_filters(request.GET)
    rank_limits = parse_rank_limits(request.GET)
    y_field     = request.GET.get("y_field", "cnt")
    chart_data  = get_chart_data(filters, rank_limits, y_field)
    return JsonResponse({"ok": True, "data": chart_data})


# ─────────────────────────────────────────────────────────────────
# API: click-detail
# ─────────────────────────────────────────────────────────────────
@require_GET
def api_click_detail(request):
    flag      = request.GET.get("flag", "").strip().upper()
    yyyy      = request.GET.get("yyyy", "").strip()
    # 멀티 bar 지원: flagdate 가 여러 개 올 수 있음 (같은 flag 내)
    flagdates = [fd.strip() for fd in request.GET.getlist("flagdate") if fd.strip()]

    if not flag or not yyyy or not flagdates:
        return JsonResponse({"ok": False, "error": ERR_MISSING_PARAMS}, status=400)
    if flag not in VALID_FLAGS:
        return JsonResponse({"ok": False, "error": ERR_INVALID_FLAG}, status=400)

    filters = parse_sidebar_filters(request.GET)
    rows    = get_raw_detail(flag, yyyy, flagdates, filters)

    if rows is None:
        return JsonResponse({"ok": False, "error": ERR_DATE_PARSE}, status=400)

    columns = list(rows[0].keys()) if rows else []
    return JsonResponse({
        "ok": True,
        "data": {
            "columns": columns,
            "rows":    rows,
            "total":   len(rows),
            "context": {"flag": flag, "yyyy": yyyy, "flagdates": flagdates},
        }
    })


# ─────────────────────────────────────────────────────────────────
# API: filter-options
# ─────────────────────────────────────────────────────────────────
@require_GET
def api_filter_options(request):
    """
    GET /interlock-ai/api/filter-options/

    사이드바 선택값을 GET 파라미터로 받아
    해당 조건으로 필터링된 distinct 목록을 반환한다.

    예) ?line=L1&eqp_model=MODEL-X
        → line='L1' AND eqp_model='MODEL-X' 조건 하에
          각 컬럼의 distinct 값 반환

    rank 파라미터(m_rank/w_rank/d_rank)는 무시한다.
    """
    # FILTER_FIELDS 에 해당하는 파라미터만 읽어 Q 객체 생성
    # parse_sidebar_filters 는 ALL 값·미선택을 빈 리스트로 정규화해 준다
    filters = parse_sidebar_filters(request.GET)

    # SpotfireReport 에 없는 필드를 제외한 Q (chart/report용)
    from interlock_ai.services.filter_service import REPORT_EXCLUDED_FIELDS
    report_filters = {k: v for k, v in filters.items() if k not in REPORT_EXCLUDED_FIELDS}
    q_report = build_filter_q(report_filters)

    # SpotfireRaw 용 Q (param_name 포함 전체 필터)
    q_raw = build_filter_q(filters)

    def _filtered_distinct(field: str) -> list:
        values = (
            SpotfireReport.objects
            .filter(q_report)
            .exclude(**{field: ""})
            .values_list(field, flat=True)
            .distinct()
            .order_by(field)
        )
        return sorted({v for v in values if v})

    def _filtered_distinct_raw(field: str) -> list:
        values = (
            SpotfireRaw.objects
            .filter(q_raw)
            .exclude(**{field: ""})
            .values_list(field, flat=True)
            .distinct()
            .order_by(field)
        )
        return sorted({v for v in values if v})

    return JsonResponse({"ok": True, "data": {
        "lines":        _filtered_distinct("line"),
        "sdwt_prods":   _filtered_distinct("sdwt_prod"),
        "eqp_models":   _filtered_distinct("eqp_model"),
        "eqp_ids":      _filtered_distinct("eqp_id"),
        "param_types":  _filtered_distinct("param_type"),
        "param_names":  _filtered_distinct_raw("param_name"),
    }})


# ─────────────────────────────────────────────────────────────────
# API: ask-ai  (AI Copilot)
# ─────────────────────────────────────────────────────────────────
@csrf_exempt
@require_POST
def api_ask_ai(request):
    """
    POST /interlock-ai/api/ask-ai/

    디버깅 팁:
      - Django 로그(DEBUG 레벨)에서 "[AI] query_json" 을 검색하면
        LLM 이 생성한 쿼리 전체를 확인할 수 있다.
      - 에러 시 "[AI] 실패" 로그에서 어떤 테이블/필터가 문제였는지 확인 가능.
    """
    # ── body 파싱 ─────────────────────────────────────────────
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": ERR_INVALID_JSON_BODY}, status=400)

    question        = (body.get("question") or "").strip()
    page_context    = (body.get("page_context") or "interlock").strip()
    selected_bar    = body.get("selected_bar")  or None
    sidebar_filters = body.get("sidebar_filters") or {}

    if not question:
        return JsonResponse({"ok": False, "error": ERR_MISSING_QUESTION}, status=400)

    # ── 요청 정보 로깅 ────────────────────────────────────────
    logger.info(
        "[AI] 요청 | question=%r | page_context=%s | selected_bar=%s | sidebar_filters=%s",
        question[:80], page_context, selected_bar, sidebar_filters,
    )

    # ── filter_options: DB 실제 값 목록을 LLM context 에 전달 ──
    # LLM 이 "백호" 같은 자연어를 올바른 필드(sdwt_prod 등)에 매핑하기 위해
    # DB 에 존재하는 실제 값 목록을 함께 넘긴다.
    filter_options = {
        "lines":       _get_distinct("line"),
        "sdwt_prods":  _get_distinct("sdwt_prod"),
        "eqp_models":  _get_distinct("eqp_model"),
        "param_types": _get_distinct("param_type"),
    }

    # ── 서비스 호출 ───────────────────────────────────────────
    result = ask_ai(question, page_context, selected_bar, sidebar_filters, filter_options)

    # ── 결과 로깅 (성공/실패 모두) ────────────────────────────
    if result["ok"]:
        query_json = result["data"].get("query_json", {})
        logger.info(
            "[AI] 성공 | table=%s | filters=%s | group_by=%s | aggregations=%s | limit=%s",
            query_json.get("table"),
            query_json.get("filters"),
            query_json.get("group_by"),
            query_json.get("aggregations"),
            query_json.get("limit"),
        )
        return JsonResponse({"ok": True, "data": result["data"]})
    else:
        logger.error(
            "[AI] 실패 | error=%s",
            result["error"],
        )
        return JsonResponse({"ok": False, "error": result["error"]}, status=400)
