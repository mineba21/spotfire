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

from interlock_ai.services.filter_service import parse_sidebar_filters
from interlock_ai.services.chart_service  import (
    get_chart_data, parse_rank_limits,
    get_filter_options_from_cube, get_top_aggregate,
)
from interlock_ai.services.detail_service import get_raw_detail, iter_raw_detail_export, RAW_COLUMNS
from interlock_ai.services.ai_service     import ask_ai, VALID_PAGE_CONTEXTS

from config.excel_utils import xlsx_response

logger = logging.getLogger(__name__)

ERR_MISSING_PARAMS    = "flag, yyyy, flagdate 파라미터가 필요합니다."
ERR_INVALID_FLAG      = "flag 값은 M / W / D 중 하나여야 합니다."
ERR_DATE_PARSE        = "flagdate 로 날짜 범위를 계산할 수 없습니다."
ERR_MISSING_QUESTION  = "question 파라미터가 필요합니다."
ERR_INVALID_JSON_BODY = "요청 body 가 유효한 JSON 이 아닙니다."

VALID_FLAGS: set = {"M", "W", "D"}


def _parse_fd_pairs(GET) -> list:
    """
    bar 선택을 (flagdate, yyyy) 쌍 리스트로 파싱한다.

    신규: fd=M03@2026 (bar 마다 자기 연도) — 서로 다른 연도의 bar 를 함께 선택 가능
    구버전 하위 호환: flagdate=M03&flagdate=M10 + yyyy=2026 (모두 같은 연도)
    """
    pairs = []
    for raw in GET.getlist("fd"):
        if "@" in raw:
            fdate, fy = raw.rsplit("@", 1)
            if fdate.strip() and fy.strip():
                pairs.append((fdate.strip(), fy.strip()))
    if pairs:
        return pairs

    yyyy = GET.get("yyyy", "").strip()
    if not yyyy:
        return []
    return [(fd.strip(), yyyy) for fd in GET.getlist("flagdate") if fd.strip()]


# ─────────────────────────────────────────────────────────────────
# 페이지 뷰
# ─────────────────────────────────────────────────────────────────
def index(request):
    context = {
        "filter_options": get_filter_options_from_cube(),
    }
    return render(request, "interlock_ai/index.html", context)


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
    flag     = request.GET.get("flag", "").strip().upper()
    yyyy     = request.GET.get("yyyy", "").strip()
    # 멀티 bar 지원: bar 마다 자기 연도를 갖는 (flagdate, yyyy) 쌍
    fd_pairs = _parse_fd_pairs(request.GET)

    if not flag or not fd_pairs:
        return JsonResponse({"ok": False, "error": ERR_MISSING_PARAMS}, status=400)
    if flag not in VALID_FLAGS:
        return JsonResponse({"ok": False, "error": ERR_INVALID_FLAG}, status=400)

    filters = parse_sidebar_filters(request.GET)
    rows    = get_raw_detail(flag, yyyy, fd_pairs, filters)

    if rows is None:
        return JsonResponse({"ok": False, "error": ERR_DATE_PARSE}, status=400)

    columns = list(rows[0].keys()) if rows else []
    return JsonResponse({
        "ok": True,
        "data": {
            "columns": columns,
            "rows":    rows,
            "total":   len(rows),
            "context": {
                "flag":      flag,
                "yyyy":      yyyy,
                "flagdates": [fd for fd, _ in fd_pairs],
                "fd_pairs":  [f"{fd}@{fy}" for fd, fy in fd_pairs],
            },
        }
    })


# ─────────────────────────────────────────────────────────────────
# API: click-detail-export  (Excel 다운로드 — MAX_RAW_ROWS 제한 없음)
# ─────────────────────────────────────────────────────────────────
@require_GET
def api_click_detail_export(request):
    """
    Bar 클릭 → Raw Data 를 .xlsx 로 다운로드.

    click-detail 과 같은 파라미터를 받지만 MAX_RAW_ROWS 제한 없이 전체 행을 반환한다.
    openpyxl write_only + queryset.iterator() 로 메모리 효율적 스트리밍.
    """
    flag     = request.GET.get("flag", "").strip().upper()
    yyyy     = request.GET.get("yyyy", "").strip()
    fd_pairs = _parse_fd_pairs(request.GET)

    if not flag or not fd_pairs:
        return JsonResponse({"ok": False, "error": ERR_MISSING_PARAMS}, status=400)
    if flag not in VALID_FLAGS:
        return JsonResponse({"ok": False, "error": ERR_INVALID_FLAG}, status=400)

    filters  = parse_sidebar_filters(request.GET)
    rows_it  = iter_raw_detail_export(flag, yyyy, fd_pairs, filters)

    # 파일명: rawdata_<flag><flagdates>_YYYYMMDD_HHMM.xlsx
    import datetime as _dt
    bar_label = f"{flag}{'-'.join(fd.replace('/', '') for fd, _ in fd_pairs)}"
    ts        = _dt.datetime.now().strftime("%Y%m%d_%H%M")
    filename  = f"rawdata_{bar_label}_{ts}.xlsx"

    logger.info("[ClickDetailExport] flag=%s fd_pairs=%s filters=%s",
                flag, fd_pairs, filters)

    return xlsx_response(
        rows_it, RAW_COLUMNS, sheet_name="RawData", filename=filename,
    )


# ─────────────────────────────────────────────────────────────────
# API: filter-options
# ─────────────────────────────────────────────────────────────────
@require_GET
def api_filter_options(request):
    filters = parse_sidebar_filters(request.GET)
    return JsonResponse({"ok": True, "data": get_filter_options_from_cube(filters)})


# ─────────────────────────────────────────────────────────────────
# API: top-aggregate  (cube 전수 집계 — Top Show)
# ─────────────────────────────────────────────────────────────────
@require_GET
def api_top_aggregate(request):
    flag     = request.GET.get("flag", "").strip().upper()
    yyyy     = request.GET.get("yyyy", "").strip()
    fd_pairs = _parse_fd_pairs(request.GET)
    if not flag or not fd_pairs:
        return JsonResponse({"ok": False, "error": ERR_MISSING_PARAMS}, status=400)
    if flag not in VALID_FLAGS:
        return JsonResponse({"ok": False, "error": ERR_INVALID_FLAG}, status=400)
    group_cols = [c.strip() for c in
                  request.GET.get("group_cols", "line,eqp_id").split(",") if c.strip()]
    try:
        top_n = int(request.GET.get("top_n", 10))
    except ValueError:
        top_n = 10
    filters = parse_sidebar_filters(request.GET)
    rows = get_top_aggregate(flag, yyyy, fd_pairs, filters, group_cols, top_n)
    return JsonResponse({"ok": True, "data": {
        "rows": rows, "group_cols": group_cols, "total": len(rows)}})


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
    filter_options = get_filter_options_from_cube()

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
