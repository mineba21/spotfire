"""
stoploss_ai/services/detail_service.py

역할:
  get_report_detail   : bar 클릭 → report_stoploss 행 반환 (Top Show / Rawdata 공용)
  get_eqp_loss_detail : Top Show rank bar 클릭 → tpm_eqp_loss 행 반환
  _calc_loss_min      : start_time ~ end_time 차이(분) Python 계산
"""
import logging
import datetime
from typing import Optional

from django.db.models import Q

from stoploss_ai.models import TpmEqpLoss, StoplossReport
from stoploss_ai.services.filter_service import build_q
from interlock_ai.services.detail_service import get_date_range

logger = logging.getLogger(__name__)

# ── 노출 컬럼 ─────────────────────────────────────────────────────
# Rawdata 패널: report_stoploss 에서 표시할 컬럼
#
# [컬럼 추가 방법]
#   1. 아래 RAW_COLUMNS 리스트에 컬럼명 추가
#   2. 해당 컬럼이 REPORT_DETAIL_FIELDS 에도 포함되어야 함 (쿼리 대상)
#   3. 컬럼이 모델(StoplossReport)에 존재해야 함
#   4. 프론트(dashboard.js)의 COL_LABELS 에 표시 레이블 추가
#   5. (옵션) NUMERIC_COLS 에 추가하면 우측 정렬 + 천단위 포맷
RAW_COLUMNS = [
    "flag", "flagdate",          # 여러 bar 선택 시 어느 기간 행인지 구분
    "eqp_id", "stoploss", "plan_time",
]

# Top Show 집계에 사용할 report_stoploss 필드 (그룹키 + 손실값 + 메타)
# RAW_COLUMNS 의 모든 항목이 여기에 포함되어야 한다.
REPORT_DETAIL_FIELDS = [
    "flag", "flagdate",
    "area", "sdwt_prod", "eqp_id", "eqp_model", "prc_group",
    "plan_time",
    "stoploss", "pm", "qual", "bm", "eng", "etc", "stepchg", "std_time", "rd",
    "rank",
]

# Top Show rank bar 클릭 → tpm_eqp_loss 컬럼
EQP_LOSS_COLUMNS = [
    "yyyymmdd", "eqp_id", "start_time", "end_time",
    "state", "down_comment", "loss_time_min",
]

MAX_RAW_ROWS = 5000

_DATETIME_FMTS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y%m%d%H%M%S",
    "%Y%m%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
]


# ── 내부 헬퍼 ─────────────────────────────────────────────────────

def _parse_dt(s: str) -> Optional[datetime.datetime]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in _DATETIME_FMTS:
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _calc_loss_min(start_str: str, end_str: str) -> Optional[float]:
    start = _parse_dt(start_str)
    end   = _parse_dt(end_str)
    if start is None or end is None:
        return None
    diff = (end - start).total_seconds() / 60
    return None if diff < 0 else round(diff, 1)


# ── 공개 함수 ─────────────────────────────────────────────────────

def get_report_detail(flag: str, yyyy: str, flagdates, filters: dict) -> list:
    """
    bar 클릭 시 report_stoploss 에서 해당 (flag, yyyy, flagdate) 행을 반환한다.

    - flagdates: 단일 str 또는 list[str] (같은 flag 내 멀티 선택 지원)
    - Rawdata 패널: eqp_id / stoploss / plan_time 표시 (RAW_COLUMNS)
    - Top Show 패널: area / sdwt_prod / eqp_model 등 그룹 컬럼 + 손실값으로 집계
    """
    # 단일 문자열도 허용 (하위 호환)
    if isinstance(flagdates, str):
        flagdates = [flagdates]
    flagdates = [fd for fd in flagdates if fd]

    q = Q(flag=flag, yyyy=yyyy, flagdate__in=flagdates) & build_q(filters)
    qs = (
        StoplossReport.objects
        .filter(q)
        .values(*REPORT_DETAIL_FIELDS)
        .order_by("flagdate", "rank")
    )
    rows = [dict(r) for r in qs]
    logger.info(
        "[ReportDetail] flag=%s flagdates=%s filters=%s → %d건",
        flag, flagdates, filters, len(rows),
    )
    return rows


def _collect_date_ranges(flag: str, yyyy: str, flagdates: list):
    """여러 flagdate 에 대한 (start, end) 합집합 범위를 반환한다."""
    starts, ends = [], []
    for fd in flagdates:
        s, e = get_date_range(flag, yyyy, fd)
        if s and e:
            starts.append(s)
            ends.append(e)
    if not starts:
        return None, None
    return min(starts), max(ends)


def get_eqp_loss_detail(flag: str, yyyy: str, flagdates, eqp_ids: list) -> list:
    """
    Top Show rank bar 클릭 시 tpm_eqp_loss 에서 해당 기간 + eqp_id 조건으로 행을 반환한다.

    - flagdates: 단일 str 또는 list[str]
    - eqp_ids 가 비어있으면 해당 기간 전체를 반환한다.
    """
    if isinstance(flagdates, str):
        flagdates = [flagdates]
    flagdates = [fd for fd in flagdates if fd]

    start_ymd, end_ymd = _collect_date_ranges(flag, yyyy, flagdates)
    if start_ymd is None:
        return []

    q = Q(yyyymmdd__gte=start_ymd, yyyymmdd__lte=end_ymd)
    if eqp_ids:
        q &= Q(eqp_id__in=eqp_ids)

    qs = (
        TpmEqpLoss.objects
        .filter(q)
        .values("yyyymmdd", "eqp_id", "start_time", "end_time", "state", "down_comment")
        .order_by("yyyymmdd", "start_time")[:MAX_RAW_ROWS]
    )

    rows = []
    for row in qs:
        rows.append({
            "yyyymmdd":      row["yyyymmdd"],
            "eqp_id":        row["eqp_id"],
            "start_time":    row["start_time"],
            "end_time":      row["end_time"],
            "state":         row["state"],
            "down_comment":  row["down_comment"],
            "loss_time_min": _calc_loss_min(row["start_time"], row["end_time"]),
        })

    logger.info(
        "[EqpLossDetail] flag=%s flagdates=%s eqp_ids=%s → %d건",
        flag, flagdates, eqp_ids, len(rows),
    )
    return rows
