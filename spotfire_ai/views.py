"""
spotfire_ai/views.py

역할: request 파싱 + service 호출 + JSON/HTML response 반환
규칙:
  - 비즈니스 로직은 services/ 에 위임한다
  - 성공: {"ok": true,  "data":  ...}
  - 실패: {"ok": false, "error": "..."}
  - view 함수 자체는 짧게 유지한다
"""

import json
import logging

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from spotfire_ai.models import SpotfireReport
from spotfire_ai.services.filter_service import parse_sidebar_filters
from spotfire_ai.services.chart_service  import get_chart_data, parse_rank_limits
from spotfire_ai.services.detail_service import get_raw_detail
from spotfire_ai.services.ai_service     import ask_ai, VALID_PAGE_CONTEXTS

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# 에러 메시지 상수 (magic string 방지)
# ─────────────────────────────────────────────────────────────────
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
    """
    메인 대시보드 페이지.
    sidebar 초기 옵션을 context 로 전달한다.
    """
    filter_options = {
        "lines":       _get_distinct("line"),
        "sdwt_prods":  _get_distinct("sdwt_prod"),
        "eqp_models":  _get_distinct("eqp_model"),
        "eqp_ids":     _get_distinct("eqp_id"),
        "param_types": _get_distinct("param_type"),
    }
    # page_context 선택지도 template 에 전달
    context = {
        "filter_options": filter_options,
        "page_contexts":  sorted(VALID_PAGE_CONTEXTS),
    }
    return render(request, "spotfire_ai/index.html", context)


def _get_distinct(field: str) -> list:
    """Report 테이블에서 특정 컬럼의 distinct 값 목록 반환"""
    return list(
        SpotfireReport.objects
        .exclude(**{field: ""})
        .values_list(field, flat=True)
        .distinct()
        .order_by(field)
    )


# ─────────────────────────────────────────────────────────────────
# API: report-data
# ─────────────────────────────────────────────────────────────────
@require_GET
def api_report_data(request):
    """GET /spotfire-ai/api/report-data/"""
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
    """GET /spotfire-ai/api/click-detail/?flag=M&yyyy=2024&flagdate=M01"""
    flag     = request.GET.get("flag",     "").strip().upper()
    yyyy     = request.GET.get("yyyy",     "").strip()
    flagdate = request.GET.get("flagdate", "").strip()

    if not flag or not yyyy or not flagdate:
        return JsonResponse({"ok": False, "error": ERR_MISSING_PARAMS}, status=400)
    if flag not in VALID_FLAGS:
        return JsonResponse({"ok": False, "error": ERR_INVALID_FLAG}, status=400)

    filters = parse_sidebar_filters(request.GET)
    rows    = get_raw_detail(flag, yyyy, flagdate, filters)

    if rows is None:
        return JsonResponse({"ok": False, "error": ERR_DATE_PARSE}, status=400)

    columns = list(rows[0].keys()) if rows else []
    return JsonResponse({
        "ok": True,
        "data": {
            "columns": columns,
            "rows":    rows,
            "total":   len(rows),
            "context": {"flag": flag, "yyyy": yyyy, "flagdate": flagdate},
        }
    })


# ─────────────────────────────────────────────────────────────────
# API: filter-options
# ─────────────────────────────────────────────────────────────────
@require_GET
def api_filter_options(request):
    """GET /spotfire-ai/api/filter-options/"""
    return JsonResponse({"ok": True, "data": {
        "lines":       _get_distinct("line"),
        "sdwt_prods":  _get_distinct("sdwt_prod"),
        "eqp_models":  _get_distinct("eqp_model"),
        "eqp_ids":     _get_distinct("eqp_id"),
        "param_types": _get_distinct("param_type"),
    }})


# ─────────────────────────────────────────────────────────────────
# API: ask-ai  (AI Copilot)
# ─────────────────────────────────────────────────────────────────
@csrf_exempt   # JS fetch 에서 CSRF 토큰을 헤더로 전달 (X-CSRFToken)
@require_POST
def api_ask_ai(request):
    """
    POST /spotfire-ai/api/ask-ai/

    request body (JSON):
        {
            "question":        "EQP-001 의 interlock 발생 상위 설비는?",
            "page_context":    "interlock",
            "selected_bar":    {"flag": "M", "yyyy": "2024", "flagdate": "M01"},
            "sidebar_filters": {"line": ["L1"], "param_type": ["interlock"]}
        }

    성공 응답:
        {
            "ok": true,
            "data": {
                "answer":          "분석 결과: ...",
                "result_count":    10,
                "results_preview": [...],
                "query_json":      {...}
            }
        }

    실패 응답:
        {"ok": false, "error": "에러 메시지"}
    """
    # ── body 파싱 ─────────────────────────────────────────────
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": ERR_INVALID_JSON_BODY}, status=400)

    # ── 필수 파라미터 추출 ────────────────────────────────────
    question = (body.get("question") or "").strip()
    if not question:
        return JsonResponse({"ok": False, "error": ERR_MISSING_QUESTION}, status=400)

    # ── 선택 파라미터 추출 ────────────────────────────────────
    # page_context: "interlock" | "stoploss" | "down_history"
    page_context    = (body.get("page_context") or "interlock").strip()
    # selected_bar: {"flag", "yyyy", "flagdate"} or None
    selected_bar    = body.get("selected_bar")  or None
    # sidebar_filters: {"line": [...], ...}
    sidebar_filters = body.get("sidebar_filters") or {}

    logger.info(
        "ask-ai | question=%r | ctx=%s | bar=%s",
        question[:50], page_context, selected_bar
    )

    # ── 서비스 호출 ───────────────────────────────────────────
    result = ask_ai(question, page_context, selected_bar, sidebar_filters)

    if result["ok"]:
        return JsonResponse({"ok": True, "data": result["data"]})
    else:
        return JsonResponse({"ok": False, "error": result["error"]}, status=400)
