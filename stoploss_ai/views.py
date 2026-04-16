"""
stoploss_ai/views.py
"""
import json
import logging
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from stoploss_ai.models import StoplossReport
from stoploss_ai.services.filter_service import parse_filters, build_q
from stoploss_ai.services.chart_service   import get_chart_data, parse_rank_limits
from stoploss_ai.services.detail_service  import get_loss_detail
from stoploss_ai.services.ratio_service   import get_ratio_analysis
from stoploss_ai.services.ai_service      import ask_ai, VALID_PAGE_CONTEXTS

logger = logging.getLogger(__name__)

VALID_FLAGS = {"M", "W", "D"}


def index(request):
    filter_options = {
        "lines":       _get_distinct("line"),
        "sdwt_prods":  _get_distinct("sdwt_prod"),
        "eqp_models":  _get_distinct("eqp_model"),
        "eqp_ids":     _get_distinct("eqp_id"),
        "param_types": _get_distinct_eqp_loss("param_type"),
    }
    return render(request, "stoploss_ai/index.html", {"filter_options": filter_options})


def _get_distinct(field):
    return list(
        StoplossReport.objects.exclude(**{field: ""})
        .values_list(field, flat=True).distinct().order_by(field)
    )


def _get_distinct_eqp_loss(field):
    from stoploss_ai.models import EqpLossTpm
    return list(
        EqpLossTpm.objects.exclude(**{field: ""})
        .values_list(field, flat=True).distinct().order_by(field)
    )


@require_GET
def api_report_data(request):
    filters     = parse_filters(request.GET)
    rank_limits = parse_rank_limits(request.GET)
    y_field     = request.GET.get("y_field", "stoploss")
    y_mode      = request.GET.get("y_mode",  "min")   # "min" or "pct"

    if y_field not in ("stoploss", "pm", "qual", "bm"):
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
            StoplossReport.objects.filter(q).exclude(**{field: ""})
            .values_list(field, flat=True).distinct().order_by(field)
        )

    return JsonResponse({"ok": True, "data": {
        "lines":       _filtered_distinct("line"),
        "sdwt_prods":  _filtered_distinct("sdwt_prod"),
        "eqp_models":  _filtered_distinct("eqp_model"),
        "eqp_ids":     _filtered_distinct("eqp_id"),
        "param_types": _get_distinct_eqp_loss("param_type"),
    }})


@require_GET
def api_click_detail(request):
    flag     = request.GET.get("flag", "")
    yyyy     = request.GET.get("yyyy", "")
    flagdate = request.GET.get("flagdate", "")

    if not all([flag, yyyy, flagdate]) or flag not in VALID_FLAGS:
        return JsonResponse(
            {"ok": False, "error": "flag, yyyy, flagdate 파라미터가 필요합니다"},
            status=400,
        )

    filters = parse_filters(request.GET)

    rows  = get_loss_detail(flag, yyyy, flagdate, filters)
    ratio = get_ratio_analysis(flag, yyyy, flagdate, filters)

    return JsonResponse({
        "ok": True,
        "data": {
            "rows":    rows,
            "ratio":   ratio,
            "columns": [
                "yyyymmdd", "act_time", "line", "sdwt_prod", "eqp_id", "unit_id",
                "eqp_model", "param_type", "param_name", "loss_time", "lot_id",
            ],
            "total": len(rows),
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
        "lines":       _get_distinct("line"),
        "sdwt_prods":  _get_distinct("sdwt_prod"),
        "eqp_models":  _get_distinct("eqp_model"),
        "param_types": _get_distinct_eqp_loss("param_type"),
    }

    result = ask_ai(question, page_context, selected_bar, sidebar_filters, filter_options)

    if result["ok"]:
        return JsonResponse(result)
    else:
        return JsonResponse(result, status=500)
