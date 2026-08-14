"""
stoploss_ai/services/chart_service.py

역할:
- StoplossReport 테이블에서 M/W/D chart 용 JSON 데이터를 만든다
- y_field: LOSS_COLUMNS 중 하나 (default="stoploss")
- y_mode: "min" (절대값, 분) 또는 "pct" (plan_time 대비 %)
- rank 필터(상위 N개만 표시)를 적용한다
- yyyy_map 을 반환해 JS bar 클릭 시 정확한 연도 참조가 가능하다

[변경 이력]
  - area(DB) ↔ line(앱) 통일 — 모델 필드 line, DB 컬럼 area
  - LOSS_COLUMNS 에 eng, etc, stepchg, std_time, rd 추가
  - 결과 캐싱 추가 — checkdb.item_status 버전 마커로 무효화 (적재 시 자동 갱신)
"""

import json
import logging
import threading
import time
from collections import defaultdict

from django.db import connections   # 복수형 connections (단수 connection 아님)

from stoploss_ai.models import StoplossReport, LOSS_COLUMNS
from .filter_service import build_q

logger = logging.getLogger(__name__)

FLAGS             = ["M", "W", "D"]
DEFAULT_RANK_LIMIT = 999

# ─── 결과 캐싱 + 버전 마커 (checkdb.item_status) ──────────────────
CHECK_DB_ALIAS         = "checkdb"
DATA_VERSION_ITEM      = "report_stoploss"   # ★ 적재 마커 item_name (선결 확인 필요)
VERSION_CHECK_INTERVAL = 30   # 초

# 필터 조합마다 항목이 하나씩 쌓이므로 상한을 둔다 (초과 시 전체 비움).
MAX_CACHE_ENTRIES = 200

_chart_cache: dict       = {}
_chart_version: str      = ""
_chart_checked_at: float = 0.0
_chart_lock              = threading.Lock()


def _read_data_version():
    """checkdb 조회 실패 시 None — 캐시 유지 신호."""
    try:
        with connections[CHECK_DB_ALIAS].cursor() as cur:
            cur.execute(
                "SELECT last_update_time FROM item_status WHERE item_name = %s",
                [DATA_VERSION_ITEM],
            )
            row = cur.fetchone()
        return str(row[0]) if row else ""
    except Exception as exc:
        logger.warning("[StoplossChart] checkdb 버전 조회 실패 — 캐시 유지: %s", exc)
        return None


def _maybe_reset_cache():
    """버전이 바뀌었으면 캐시 전체를 비운다 (30초 주기로만 확인)."""
    global _chart_version, _chart_checked_at, _chart_cache
    now = time.time()
    if now - _chart_checked_at < VERSION_CHECK_INTERVAL:
        return
    version = _read_data_version()
    _chart_checked_at = now
    if version is not None and version != _chart_version:
        with _chart_lock:
            _chart_cache = {}
            _chart_version = version
            logger.info("[StoplossChart] 캐시 무효화 | version=%s", version)


def invalidate_chart_cache():
    """수동 강제 무효화용."""
    global _chart_cache, _chart_version
    with _chart_lock:
        _chart_cache = {}
        _chart_version = ""


def get_chart_data(filters, rank_limits, y_field="stoploss", y_mode="min"):
    """결과 캐싱 래퍼. 캐시 미스 시 _compute_chart_data 로 위임."""
    _maybe_reset_cache()
    key = json.dumps({
        "f":  {k: sorted(v) for k, v in filters.items() if v},
        "r":  rank_limits,
        "yf": y_field,
        "ym": y_mode,
    }, sort_keys=True, ensure_ascii=False)

    cached = _chart_cache.get(key)
    if cached is not None:
        return cached

    result = _compute_chart_data(filters, rank_limits, y_field, y_mode)
    with _chart_lock:
        if len(_chart_cache) >= MAX_CACHE_ENTRIES:
            _chart_cache.clear()
        _chart_cache[key] = result
    return result


def _compute_chart_data(
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
            "line", "sdwt_prod", "eqp_model", "eqp_id", "prc_group",
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
