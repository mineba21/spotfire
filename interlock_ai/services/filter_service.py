"""
services/filter_service.py

역할:
- request.GET 에서 sidebar 필터 파라미터를 파싱한다
- Report / Raw QuerySet 에 공통으로 적용 가능한 Q 필터를 생성한다
- "ALL" 값이 들어오면 해당 필터를 건너뛴다 (전체 조회)

컬럼 추가 시:
  1. FILTER_FIELDS 에 새 필드명을 추가한다
  2. parse_sidebar_filters() 가 자동으로 처리한다
"""

from django.db.models import Q

# ─────────────────────────────────────────────────────────────────
# sidebar 에서 multi-select 로 넘어오는 필터 필드 목록
# 순서는 sidebar 표시 순서와 맞춘다
# ─────────────────────────────────────────────────────────────────
FILTER_FIELDS = [
    "line",
    "sdwt_prod",
    "eqp_model",
    "eqp_id",
    "param_type",
    "param_name",   # SpotfireRaw 전용 (SpotfireReport 필터에서는 제외)
]

# SpotfireReport 에 없는 필드 목록 — chart_service 에서 제외해야 한다
REPORT_EXCLUDED_FIELDS = {"param_name"}

# ALL 을 의미하는 특수 값
ALL_VALUE = "ALL"


def parse_sidebar_filters(get_params) -> dict:
    """
    request.GET 을 받아 필드별 선택 값 리스트를 반환한다.

    반환 예시:
        {
            "line": ["L1", "L2"],
            "sdwt_prod": [],          # ALL 이거나 미선택 → 빈 리스트
            "eqp_model": ["EQP-A"],
            "eqp_id": [],
            "param_type": ["interlock"],
        }

    빈 리스트는 "전체 선택" 을 의미한다 (필터 미적용).
    """
    result = {}

    for field in FILTER_FIELDS:
        # getlist: 동일 key 가 여러 번 오는 querystring 처리
        # 예) ?line=L1&line=L2 → ["L1", "L2"]
        values = get_params.getlist(field)

        # ALL 이 포함되어 있거나 아무것도 선택 안 한 경우 → 전체
        if not values or ALL_VALUE in values:
            result[field] = []
        else:
            result[field] = values

    return result


def build_filter_q(filters: dict) -> Q:
    """
    parse_sidebar_filters() 결과를 받아 Django Q 객체로 변환한다.
    빈 리스트 필드는 조건에서 제외된다 (전체 허용).

    사용 예:
        q = build_filter_q(filters)
        qs = SpotfireReport.objects.filter(q)
    """
    q = Q()  # 초기 Q (아무 조건 없음 = 전체)

    for field, values in filters.items():
        if values:  # 값이 있을 때만 필터 추가
            # field__in: SQL 의 WHERE field IN (v1, v2, ...) 에 해당
            q &= Q(**{f"{field}__in": values})

    return q
