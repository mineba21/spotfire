"""
stoploss_ai/services/detail_service.py

역할:
- bar 클릭 시 전달되는 (flag, yyyy, flagdate) 로 날짜 범위를 계산한다
- EqpLossTpm 테이블에서 해당 기간의 raw data 를 조회한다

get_date_range() 는 spotfire_ai 에서 import 해 재사용한다.
"""

import logging
logger = logging.getLogger(__name__)

from stoploss_ai.models import EqpLossTpm
from stoploss_ai.services.filter_service import build_q
from spotfire_ai.services.detail_service import get_date_range  # 날짜 범위 계산 재사용

# ─────────────────────────────────────────────────────────────────
# raw detail 응답에 포함할 컬럼 목록
# ─────────────────────────────────────────────────────────────────
RAW_COLUMNS = [
    "yyyymmdd",
    "act_time",
    "line",
    "sdwt_prod",
    "eqp_id",
    "unit_id",
    "eqp_model",
    "param_type",
    "param_name",
    "loss_time",
    "lot_id",
]

# 조회 최대 row 수 (성능 보호)
MAX_RAW_ROWS = 5000


def get_loss_detail(flag: str, yyyy: str, flagdate: str, filters: dict) -> list:
    """
    (flag, yyyy, flagdate) + sidebar 필터 기준으로 eqp_loss_tpm 데이터를 조회한다.

    반환: dict list (각 dict 는 RAW_COLUMNS 에 정의된 컬럼만 포함)
    loss_time 기준 내림차순 정렬.
    """
    start_ymd, end_ymd = get_date_range(flag, yyyy, flagdate)

    if start_ymd is None:
        logger.warning(
            "get_date_range 반환 None | flag=%s yyyy=%s flagdate=%s",
            flag, yyyy, flagdate,
        )
        return []

    q = build_q(filters)

    qs = (
        EqpLossTpm.objects
        .filter(q)
        .filter(yyyymmdd__gte=start_ymd, yyyymmdd__lte=end_ymd)
        .values(*RAW_COLUMNS)
        .order_by("-loss_time")[:MAX_RAW_ROWS]
    )

    rows = list(qs)

    logger.info("[StoplossDetail] flag=%s flagdate=%s 조회 결과 %d건", flag, flagdate, len(rows))

    return rows
