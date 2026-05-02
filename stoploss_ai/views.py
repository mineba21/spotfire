"""
stoploss_ai/views.py

[변경 이력]
  - line → area 반영
  - y_field 허용값에 eng, etc, stepchg, std_time, rd 추가
"""
import json
import logging

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from stoploss_ai.models import StoplossReport, LOSS_COLUMNS
from stoploss_ai.services.filter_service import parse_filters, build_q
from stoploss_ai.services.chart_service   import get_chart_data, parse_rank_limits
from stoploss_ai.services.detail_service  import (
    get_report_detail, get_loss_event_detail, get_eqp_loss_detail,
    REPORT_COLUMNS, EQP_LOSS_COLUMNS,
)
from stoploss_ai.services.ratio_service import get_ratio_analysis
from stoploss_ai.services.ai_service      import ask_ai, VALID_PAGE_CONTEXTS

logger = logging.getLogger(__name__)

VALID_FLAGS = {"M", "W", "D"}


def index(request):
    filter_options = {
        "areas":       _get_distinct("area"),
        "sdwt_prods":  _get_distinct("sdwt_prod"),
        "eqp_models":  _get_distinct("eqp_model"),
        "eqp_ids":     _get_distinct("eqp_id"),
        "prc_groups":  _get_distinct("prc_group"),
    }
    return render(request, "stoploss_ai/index.html", {"filter_options": filter_options})


def _get_distinct(field):
    return list(
        StoplossReport.objects
        .exclude(**{field: ""})
        .values_list(field, flat=True)
        .distinct()
        .order_by(field)
    )


@require_GET
def api_report_data(request):
    filters     = parse_filters(request.GET)
    rank_limits = parse_rank_limits(request.GET)
    y_field     = request.GET.get("y_field", "stoploss")
    y_mode      = request.GET.get("y_mode",  "min")

    if y_field not in LOSS_COLUMNS:
        y_field = "stoploss"
    if y_mode not in ("min", "pct"):
        y_mode = "min"

    data = get_chart_data(filters, rank_limits, y_field, y_mode)
    return JsonResponse({"ok": True, "data": data})


@require_GET
def api_filter_options(request):
    filters = parse_filters(request.GET)
    q       = build_q(filters)

    def _filtered_distinct(field):
        return list(
            StoplossReport.objects
            .filter(q)
            .exclude(**{field: ""})
            .values_list(field, flat=True)
            .distinct()
            .order_by(field)
        )

    return JsonResponse({"ok": True, "data": {
        "areas":       _filtered_distinct("area"),
        "sdwt_prods":  _filtered_distinct("sdwt_prod"),
        "eqp_models":  _filtered_distinct("eqp_model"),
        "eqp_ids":     _filtered_distinct("eqp_id"),
        "prc_groups":  _filtered_distinct("prc_group"),
    }})


@require_GET
def api_click_detail(request):
    flag      = request.GET.get("flag", "")
    yyyy      = request.GET.get("yyyy", "")
    # 멀티 bar 지원: flagdate 가 복수로 올 수 있음 (동일 flag 내)
    flagdates = request.GET.getlist("flagdate")
    group_by  = request.GET.get("ratio_group_by", "state").strip() or "state"

    if not all([flag, yyyy]) or not flagdates or flag not in VALID_FLAGS:
        return JsonResponse(
            {"ok": False, "error": "flag, yyyy, flagdate 파라미터가 필요합니다"},
            status=400,
        )

    filters = parse_filters(request.GET)
    rows        = get_loss_event_detail(flag, yyyy, flagdates, filters)
    report_rows = get_report_detail(flag, yyyy, flagdates, filters)
    ratio       = get_ratio_analysis(flag, yyyy, flagdates, filters, group_by)

    return JsonResponse({
        "ok": True,
        "data": {
            "rows":            rows,
            "columns":         EQP_LOSS_COLUMNS,
            "total":           len(rows),
            "report_rows":     report_rows,
            "report_columns":  REPORT_COLUMNS,
            "ratio":           ratio,
            "ratio_group_by":  group_by,
        },
    })


@require_GET
def api_eqp_loss_detail(request):
    """Top Show rank bar 클릭 → eqp_loss_tpm 조회 (복수 flagdate 지원)"""
    flag      = request.GET.get("flag", "")
    yyyy      = request.GET.get("yyyy", "")
    flagdates = request.GET.getlist("flagdate")
    eqp_ids   = request.GET.getlist("eqp_id")

    if not all([flag, yyyy]) or not flagdates or flag not in VALID_FLAGS:
        return JsonResponse(
            {"ok": False, "error": "flag, yyyy, flagdate 파라미터가 필요합니다"},
            status=400,
        )

    rows = get_eqp_loss_detail(flag, yyyy, flagdates, eqp_ids)
    return JsonResponse({
        "ok": True,
        "data": {
            "rows":    rows,
            "columns": EQP_LOSS_COLUMNS,
            "total":   len(rows),
        },
    })


@csrf_exempt
@require_POST
def api_ask_ai(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "유효하지 않은 JSON"}, status=400)

    question        = (body.get("question") or "").strip()
    page_context    = (body.get("page_context") or "stoploss").strip()
    selected_bar    = body.get("selected_bar") or None
    sidebar_filters = body.get("sidebar_filters") or {}

    if not question:
        return JsonResponse({"ok": False, "error": "question이 필요합니다"}, status=400)

    filter_options = {
        "areas":       _get_distinct("area"),
        "sdwt_prods":  _get_distinct("sdwt_prod"),
        "eqp_models":  _get_distinct("eqp_model"),
        "eqp_ids":     _get_distinct("eqp_id"),
        "prc_groups":  _get_distinct("prc_group"),
    }

    result = ask_ai(question, page_context, selected_bar, sidebar_filters, filter_options)

    if result["ok"]:
        return JsonResponse(result)
    else:
        return JsonResponse(result, status=500)
