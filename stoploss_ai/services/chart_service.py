"""
stoploss_ai/services/chart_service.py

역할:
- StoplossReport 테이블에서 M/W/D chart 용 JSON 데이터를 만든다
- y_field: LOSS_COLUMNS 중 하나 (default="stoploss")
- y_mode: "min" (절대값, 분) 또는 "pct" (plan_time 대비 %)
- rank 필터(상위 N개만 표시)를 적용한다
- yyyy_map 을 반환해 JS bar 클릭 시 정확한 연도 참조가 가능하다

[변경 이력]
  - line → area 반영
  - LOSS_COLUMNS 에 eng, etc, stepchg, std_time, rd 추가
"""

from collections import defaultdict
from stoploss_ai.models import StoplossReport, LOSS_COLUMNS
from .filter_service import build_q

FLAGS             = ["M", "W", "D"]
DEFAULT_RANK_LIMIT = 999


def get_chart_data(
    filters:     dict,
    rank_limits: dict,
    y_field:     str = "stoploss",
    y_mode:      str = "min",
) -> dict:
    """
    M / W / D 각 flag 에 대한 chart 데이터를 반환한다.

    파라미터:
        filters     : parse_filters() 결과
        rank_limits : {"M": 3, "W": 3, "D": 7}
        y_field     : LOSS_COLUMNS 중 하나
        y_mode      : "min" 또는 "pct"
    """
    if y_field not in LOSS_COLUMNS:
        y_field = "stoploss"

    q = build_q(filters)

    qs = (
        StoplossReport.objects
        .filter(q)
        .values(
            "flag", "yyyy", "flagdate",
            "area", "sdwt_prod", "eqp_model", "eqp_id", "prc_group",
            "plan_time",
            "stoploss", "pm", "qual", "bm",
            "eng", "etc", "stepchg", "std_time", "rd",
            "rank",
        )
        .order_by("flag", "flagdate")
    )

    result = {}
    for flag in FLAGS:
        rank_limit = rank_limits.get(flag, DEFAULT_RANK_LIMIT)
        flag_rows  = list(qs.filter(flag=flag, rank__lte=rank_limit))
        result[flag] = _build_series(flag_rows, y_field, y_mode)

    return result


def _build_series(rows: list, y_field: str, y_mode: str) -> dict:
    flagdates = sorted({row["flagdate"] for row in rows})

    yyyy_map: dict = {}
    for row in rows:
        fd = row["flagdate"]
        if fd not in yyyy_map:
            yyyy_map[fd] = row["yyyy"]

    agg: dict      = defaultdict(float)
    plan_agg: dict = defaultdict(float)

    for row in rows:
        fd       = row["flagdate"]
        val      = row.get(y_field) or 0
        plan_val = row.get("plan_time") or 0
        agg[fd]      += val
        plan_agg[fd] += plan_val

    if y_mode == "pct":
        y_values = [
            round(agg[fd] / plan_agg[fd] * 100, 4) if plan_agg.get(fd) else 0
            for fd in flagdates
        ]
    else:
        y_values = [round(agg[fd], 4) for fd in flagdates]

    return {
        "flagdates": flagdates,
        "yyyy_map":  yyyy_map,
        "series":    [{"name": "ALL", "y": y_values}],
    }


def parse_rank_limits(get_params) -> dict:
    def _safe_int(val, default):
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    return {
        "M": _safe_int(get_params.get("m_rank"), DEFAULT_RANK_LIMIT),
        "W": _safe_int(get_params.get("w_rank"), DEFAULT_RANK_LIMIT),
        "D": _safe_int(get_params.get("d_rank"), DEFAULT_RANK_LIMIT),
    }
