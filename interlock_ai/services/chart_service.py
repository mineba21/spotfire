"""
services/chart_service.py

역할:
- Report 테이블 QuerySet 에서 M/W/D chart 용 JSON 데이터를 만든다
- legend 기준(line/sdwt_prod/eqp_id/eqp_model)으로 grouped bar 를 지원한다
- y축 기준(cnt/ratio)을 파라미터로 바꿀 수 있다
- rank 필터(상위 N개만 표시)를 적용한다
- yyyy_map 을 반환해 JS bar 클릭 시 정확한 연도 참조가 가능하다

컬럼 추가 시:
  - LEGEND_FIELDS 에 새 그룹 기준 컬럼명을 추가하면 된다
  - y_field 파라미터에 새 집계 컬럼명을 넘기면 바로 사용 가능
  - get_chart_data() 의 values() 에 새 컬럼을 추가하면 된다
"""

from collections import defaultdict
from interlock_ai.models import SpotfireReport
from .filter_service import build_filter_q, REPORT_EXCLUDED_FIELDS

# ─────────────────────────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────────────────────────
# legend 로 사용 가능한 컬럼 목록 (확장 시 여기에 추가)
LEGEND_FIELDS = ["line", "sdwt_prod", "eqp_model", "eqp_id", "param_type"]

# 기본 M/W/D 플래그
FLAGS = ["M", "W", "D"]

# rank 최대값 (이 값 초과인 row 는 차트에 포함하지 않음)
DEFAULT_RANK_LIMIT = 999  # 사실상 무제한


def get_chart_data(filters: dict, rank_limits: dict, y_field: str = "cnt") -> dict:
    """
    M / W / D 각 flag 에 대한 chart 데이터를 반환한다.

    파라미터:
        filters     : parse_sidebar_filters() 결과
        rank_limits : {"M": 3, "W": 3, "D": 7} 형태. 없으면 전체 포함
        y_field     : y축 값으로 사용할 컬럼명 ("cnt" 또는 "ratio")

    반환 구조:
        {
            "M": {
                "flagdates": [...],
                "yyyy_map":  {"M01": "2024", "M02": "2024"},   ← 추가됨
                "series":    [{"name": "ALL", "y": [...]}],
            },
            "W": {...},
            "D": {...},
        }

    yyyy_map 용도:
        JS 에서 bar 클릭 시 state.chartData[flag].yyyy_map[flagdate] 로
        정확한 연도를 참조한다. (현재연도 추측 로직 제거)

    컬럼 추가 시:
        values() 안에 원하는 컬럼명을 추가하면 된다.
        단, SpotfireReport 모델에도 해당 필드가 있어야 한다.
    """
    # SpotfireReport 에 없는 필드(param_name 등)를 필터에서 제외한다
    report_filters = {k: v for k, v in filters.items() if k not in REPORT_EXCLUDED_FIELDS}

    # sidebar 필터 Q 객체 생성
    q = build_filter_q(report_filters)

    # report 테이블 전체 조회 (필터 적용)
    # 컬럼 추가 시: values() 에 컬럼명을 추가하면 된다
    qs = (
        SpotfireReport.objects
        .filter(q)
        .values(
            "flag", "yyyy", "flagdate",
            "line", "sdwt_prod", "eqp_model", "eqp_id", "param_type",
            "cnt", "ratio", "rank",
            # 컬럼 추가 예시: "new_col",
        )
        .order_by("flag", "flagdate")
    )

    result = {}

    for flag in FLAGS:
        # 해당 flag 의 rank 상한 (없으면 무제한)
        rank_limit = rank_limits.get(flag, DEFAULT_RANK_LIMIT)

        # 해당 flag + rank 필터 적용
        flag_rows = list(qs.filter(flag=flag, rank__lte=rank_limit))

        result[flag] = _build_series(flag_rows, y_field)

    return result


def _build_series(rows: list, y_field: str) -> dict:
    """
    단일 flag 의 row 목록을 Plotly 용 series 구조로 변환한다. (ALL 모드)

    반환 구조:
        {
            "flagdates": ["M01", "M02", ...],
            "yyyy_map":  {"M01": "2024", "M02": "2024"},
            "series":    [{"name": "ALL", "y": [75.0, 80.0, ...]}],
        }

    legend 모드 확장 시:
        get_chart_data() 에 legend_field 파라미터를 추가하고
        _build_series_grouped() 로 분기하면 된다. (함수는 아래에 구현됨)
    """
    # x축: flagdate 목록 (중복 제거, 정렬)
    flagdates = sorted({row["flagdate"] for row in rows})

    # ── yyyy_map 구성 ──────────────────────────────────────────
    # flagdate → yyyy 매핑 (동일 flagdate 에 yyyy 가 여러 개이면 첫 번째 사용)
    # 용도: JS bar 클릭 시 click-detail 파라미터 yyyy 를 정확히 전달하기 위함
    yyyy_map: dict = {}
    for row in rows:
        fd = row["flagdate"]
        if fd not in yyyy_map:
            # 첫 번째로 만나는 yyyy 를 해당 flagdate 의 대표 연도로 사용
            yyyy_map[fd] = row["yyyy"]

    # ── y값 합산 ───────────────────────────────────────────────
    agg: dict = defaultdict(float)  # {flagdate: sum(y_field)}
    for row in rows:
        fd  = row["flagdate"]
        val = row.get(y_field) or 0  # None 방어
        agg[fd] += val

    # Plotly 형식: x 순서에 맞춰 y 값 배열 생성
    y_values = [round(agg[fd], 4) for fd in flagdates]

    return {
        "flagdates": flagdates,
        "yyyy_map":  yyyy_map,   # ← 이번 단계 추가
        "series": [
            {"name": "ALL", "y": y_values}
        ],
    }


def _build_series_grouped(rows: list, y_field: str, legend_field: str) -> dict:
    """
    legend 필드 기준으로 grouped bar series 를 만든다.

    legend_field 예: "line", "eqp_model" 등

    활성화 방법:
        get_chart_data() 에 legend_field 파라미터를 추가하고
        _build_series(flag_rows, y_field) 호출을
        _build_series_grouped(flag_rows, y_field, legend_field) 로 교체한다.

    컬럼 추가 시:
        LEGEND_FIELDS 에 새 컬럼명을 추가하면 된다.
    """
    flagdates = sorted({row["flagdate"] for row in rows})

    # yyyy_map (grouped 모드에서도 동일하게 제공)
    yyyy_map: dict = {}
    for row in rows:
        fd = row["flagdate"]
        if fd not in yyyy_map:
            yyyy_map[fd] = row["yyyy"]

    # legend 값 목록 (정렬)
    legends = sorted({row.get(legend_field, "UNKNOWN") for row in rows})

    # {legend: {flagdate: sum}} 집계
    agg: dict = defaultdict(lambda: defaultdict(float))
    for row in rows:
        fd  = row["flagdate"]
        leg = row.get(legend_field, "UNKNOWN")
        val = row.get(y_field) or 0
        agg[leg][fd] += val

    series = []
    for leg in legends:
        y_values = [round(agg[leg][fd], 4) for fd in flagdates]
        series.append({"name": leg, "y": y_values})

    return {
        "flagdates": flagdates,
        "yyyy_map":  yyyy_map,
        "series":    series,
    }


def parse_rank_limits(get_params) -> dict:
    """
    querystring 에서 m_rank / w_rank / d_rank 를 파싱한다.

    예) ?m_rank=3&w_rank=3&d_rank=7
    → {"M": 3, "W": 3, "D": 7}

    값이 없거나 숫자가 아니면 DEFAULT_RANK_LIMIT 을 사용한다.
    """
    def _safe_int(val, default: int) -> int:
        # 숫자 변환 실패 시 default 반환
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    return {
        "M": _safe_int(get_params.get("m_rank"), DEFAULT_RANK_LIMIT),
        "W": _safe_int(get_params.get("w_rank"), DEFAULT_RANK_LIMIT),
        "D": _safe_int(get_params.get("d_rank"), DEFAULT_RANK_LIMIT),
    }
