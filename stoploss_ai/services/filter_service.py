"""
stoploss_ai/services/filter_service.py

역할:
- request.GET 에서 sidebar 필터 파라미터를 파싱한다
- Report / Raw QuerySet 에 공통으로 적용 가능한 Q 필터를 생성한다
- "ALL" 값이 들어오면 해당 필터를 건너뛴다 (전체 조회)

[변경 이력]
  - area(DB 컬럼) ↔ line(앱) 통일 — Django 모델 필드명만 line, DB 컬럼은 area 유지
    (StoplossReport.line = CharField(..., db_column="area"))
"""

from django.db.models import Q

# ─────────────────────────────────────────────────────────────────
# sidebar 에서 multi-select 로 넘어오는 필터 필드 목록
# 순서는 interlock_ai 와 맞춰 페이지간 공유 필터의 명칭/순서를 일관시킨다.
# ─────────────────────────────────────────────────────────────────
FILTER_FIELDS = [
    "line",
    "sdwt_prod",
    "eqp_model",
    "eqp_id",
    "prc_group",
]

ALL_VALUE = "ALL"


def parse_filters(get_params) -> dict:
    """
    request.GET 을 받아 필드별 선택 값 리스트를 반환한다.

    반환 예시:
        {
            "line":      ["A1", "A2"],
            "sdwt_prod": [],
            "eqp_model": ["MODEL-X"],
            "eqp_id":    [],
            "prc_group": [],
        }
    """
    result = {}
    for field in FILTER_FIELDS:
        values = get_params.getlist(field)
        if not values or ALL_VALUE in values:
            result[field] = []
        else:
            result[field] = values
    return result


def build_q(filters: dict) -> "Q":
    """
    parse_filters() 결과를 Django Q 객체로 변환한다.
    빈 리스트 필드는 조건에서 제외된다 (전체 허용).
    """
    q = Q()
    for field, values in filters.items():
        if values:
            q &= Q(**{f"{field}__in": values})
    return q
