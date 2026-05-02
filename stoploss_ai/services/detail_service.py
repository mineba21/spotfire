"""
stoploss_ai/services/detail_service.py

역할:
  get_report_detail     : bar 클릭 → report_stoploss 행 반환 (Top Show 집계용)
  get_loss_event_detail : bar 클릭 → report_stoploss 로 eqp_id 선별 후 eqp_loss_tpm 행 반환
  get_eqp_loss_detail   : Top Show rank bar 클릭 → eqp_loss_tpm 행 반환
"""
import logging

from django.db.models import Q

from stoploss_ai.models import EqpLossTpm, StoplossReport
from stoploss_ai.services.filter_service import build_q
from interlock_ai.services.detail_service import get_date_range

logger = logging.getLogger(__name__)

# ── 노출 컬럼 ─────────────────────────────────────────────────────
# Top Show 집계/우측 table 에서 사용할 report_stoploss 표시 컬럼
#
# [컬럼 추가 방법]
#   1. 아래 REPORT_COLUMNS 리스트에 컬럼명 추가
#   2. 해당 컬럼이 REPORT_DETAIL_FIELDS 에도 포함되어야 함 (쿼리 대상)
#   3. 컬럼이 모델(StoplossReport)에 존재해야 함
#   4. 프론트(dashboard.js)의 COL_LABELS 에 표시 레이블 추가
#   5. (옵션) NUMERIC_COLS 에 추가하면 우측 정렬 + 천단위 포맷
REPORT_COLUMNS = [
    "flag", "flagdate",          # 여러 bar 선택 시 어느 기간 행인지 구분
    "eqp_id", "stoploss", "plan_time",
]

# 하위 호환: 기존 import 이름 유지
RAW_COLUMNS = REPORT_COLUMNS

# Top Show 집계에 사용할 report_stoploss 필드 (그룹키 + 손실값 + 메타)
# REPORT_COLUMNS 의 모든 항목이 여기에 포함되어야 한다.
REPORT_DETAIL_FIELDS = [
    "flag", "flagdate",
    "area", "sdwt_prod", "eqp_id", "eqp_model", "prc_group",
    "plan_time",
    "stoploss", "pm", "qual", "bm", "eng", "etc", "stepchg", "std_time", "rd",
    "rank",
]

# LOSS EVENT DATA / Top Show rank bar 클릭 → eqp_loss_tpm 컬럼
EQP_LOSS_COLUMNS = [
    "yyyymmdd", "act_time", "line", "sdwt_prod",
    "eqp_id", "eqp_model", "param_type", "param_name",
    "loss_time_min", "lot_id",
]

EQP_LOSS_QUERY_FIELDS = [
    "yyyymmdd", "act_time", "line", "sdwt_prod",
    "eqp_id", "eqp_model", "param_type", "param_name",
    "loss_time", "lot_id",
]

MAX_RAW_ROWS = 5000


# ── 내부 헬퍼 ─────────────────────────────────────────────────────

def _normalize_flagdates(flagdates) -> list:
    if isinstance(flagdates, str):
        flagdates = [flagdates]
    return [fd for fd in flagdates if fd]


def _eqp_loss_ymd_has_hyphen() -> bool:
    sample = EqpLossTpm.objects.values_list("yyyymmdd", flat=True).first()
    return "-" in str(sample) if sample else False


def _to_db_ymd(ymd8: str, has_hyphen: bool) -> str:
    if has_hyphen and len(ymd8) == 8 and ymd8.isdigit():
        return f"{ymd8[:4]}-{ymd8[4:6]}-{ymd8[6:8]}"
    return ymd8


def _build_selected_date_q(flag: str, yyyy: str, flagdates: list):
    """
    선택된 각 flagdate 범위를 OR 로 묶는다.
    min(start)~max(end) 단일 범위로 조회하면 선택하지 않은 중간 날짜가 섞일 수 있다.
    """
    has_hyphen = _eqp_loss_ymd_has_hyphen()
    date_q = Q()
    has_any = False

    for fd in flagdates:
        start_ymd, end_ymd = get_date_range(flag, yyyy, fd)
        if not start_ymd or not end_ymd:
            continue
        date_q |= Q(
            yyyymmdd__gte=_to_db_ymd(start_ymd, has_hyphen),
            yyyymmdd__lte=_to_db_ymd(end_ymd, has_hyphen),
        )
        has_any = True

    return date_q if has_any else None


# ── 공개 함수 ─────────────────────────────────────────────────────

def get_report_detail(flag: str, yyyy: str, flagdates, filters: dict) -> list:
    """
    bar 클릭 시 report_stoploss 에서 해당 (flag, yyyy, flagdate) 행을 반환한다.

    - flagdates: 단일 str 또는 list[str] (같은 flag 내 멀티 선택 지원)
    - Top Show 패널: area / sdwt_prod / eqp_model 등 그룹 컬럼 + 손실값으로 집계
    - LOSS EVENT DATA 는 get_loss_event_detail() 에서 eqp_loss_tpm 기준으로 별도 조회
    """
    flagdates = _normalize_flagdates(flagdates)
    if not flagdates:
        return []

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


def get_loss_event_detail(flag: str, yyyy: str, flagdates, filters: dict) -> list:
    """
    bar 클릭 시 LOSS EVENT DATA 에 표시할 eqp_loss_tpm 행을 반환한다.

    eqp_loss_tpm 에는 prc_group 등 report 메타가 없으므로, 먼저
    report_stoploss 에 sidebar 필터를 적용해 대상 eqp_id 를 선별한다.
    """
    flagdates = _normalize_flagdates(flagdates)
    if not flagdates:
        return []

    q_report = Q(flag=flag, yyyy=yyyy, flagdate__in=flagdates) & build_q(filters)
    eqp_ids = list(
        StoplossReport.objects
        .filter(q_report)
        .exclude(eqp_id="")
        .values_list("eqp_id", flat=True)
        .distinct()
    )

    if not eqp_ids:
        logger.info(
            "[LossEventDetail] flag=%s flagdates=%s filters=%s → eqp_id 없음",
            flag, flagdates, filters,
        )
        return []

    return get_eqp_loss_detail(flag, yyyy, flagdates, eqp_ids)


def get_eqp_loss_detail(flag: str, yyyy: str, flagdates, eqp_ids: list) -> list:
    """
    Top Show rank bar 클릭 시 eqp_loss_tpm 에서 해당 기간 + eqp_id 조건으로 행을 반환한다.

    - flagdates: 단일 str 또는 list[str]
    - eqp_ids 가 비어있으면 해당 기간 전체를 반환한다.
    """
    flagdates = _normalize_flagdates(flagdates)
    if not flagdates:
        return []

    date_q = _build_selected_date_q(flag, yyyy, flagdates)
    if date_q is None:
        return []

    q = date_q
    if eqp_ids:
        q &= Q(eqp_id__in=eqp_ids)

    qs = (
        EqpLossTpm.objects
        .filter(q)
        .values(*EQP_LOSS_QUERY_FIELDS)
        .order_by("yyyymmdd", "act_time")[:MAX_RAW_ROWS]
    )

    rows = []
    for row in qs:
        rows.append({
            "yyyymmdd":      row["yyyymmdd"],
            "act_time":      row["act_time"],
            "line":          row["line"],
            "sdwt_prod":     row["sdwt_prod"],
            "eqp_id":        row["eqp_id"],
            "eqp_model":     row["eqp_model"],
            "param_type":    row["param_type"],
            "param_name":    row["param_name"],
            "loss_time_min": row["loss_time"],
            "lot_id":        row["lot_id"],
        })

    logger.info(
        "[EqpLossDetail] flag=%s flagdates=%s eqp_ids=%s → %d건",
        flag, flagdates, eqp_ids, len(rows),
    )
    return rows
