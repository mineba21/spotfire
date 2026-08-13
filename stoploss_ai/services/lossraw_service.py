"""
stoploss_ai/services/lossraw_service.py

tpm_eqp_loss 드릴다운 분석 (LOSSRAW_START_YMD 이후).
loss_time_min(float 컬럼) 을 DB Sum 으로 집계 — Python 계산/캐싱 불필요.

드릴다운: kind → param_type → param_name → raw

사이드바 필터의 "설비" 는 tpm_eqp_loss.station 컬럼이다.
station 과 eqp_id 는 별도 컬럼이며 추후 값이 달라질 예정이라 둘 다 노출한다.
"""
from django.db.models import Count, Q, Sum

from stoploss_ai.models import TpmEqpLoss

LOSSRAW_START_YMD = "20260101"   # 데이터 하한 (숫자형)

# 값이 비어있는 그룹의 표시 라벨. 프론트는 이 라벨을 그대로 되돌려 보내고
# (빈 문자열은 view 단계에서 탈락하므로) 서버가 다시 빈 값 조건으로 바꾼다.
UNCLASSIFIED = "(미분류)"

LEVEL_FIELD   = {"kind": "kind", "param_type": "param_type", "param_name": "param_name"}
LEVEL_PARENTS = {"kind": [], "param_type": ["kind"], "param_name": ["kind", "param_type"]}

LOSSRAW_FILTER_FIELDS = ["area", "station", "kind", "param_type"]

RAW_COLUMNS = ["yyyymmdd", "area", "station", "eqp_id", "start_time", "end_time",
               "kind", "state", "param_type", "param_name", "loss_time_min"]

MAX_RAW_ROWS = 5000

# yyyymmdd 표기 형식은 적재 규칙이라 런타임 중 바뀌지 않는다 — 1회만 조회한다.
_ymd_hyphen_cache = None


def _parent_q(field: str, value: str) -> "Q":
    """드릴다운 부모 조건. '(미분류)' 는 빈 값/NULL 그룹을 뜻한다."""
    if value == UNCLASSIFIED:
        return Q(**{field: ""}) | Q(**{f"{field}__isnull": True})
    return Q(**{field: value})


def _ymd_has_hyphen() -> bool:
    global _ymd_hyphen_cache
    if _ymd_hyphen_cache is not None:
        return _ymd_hyphen_cache
    sample = TpmEqpLoss.objects.values_list("yyyymmdd", flat=True).first()
    if not sample:
        return False   # 데이터 없음 — 캐시하지 않고 다음 호출에 다시 확인
    _ymd_hyphen_cache = "-" in str(sample)
    return _ymd_hyphen_cache


def _to_db(ymd_str):
    """'20260101' 또는 '2026-01-01' → DB 형식에 맞춘 값."""
    s = str(ymd_str).replace("-", "")
    if _ymd_has_hyphen():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _start_filter():
    return _to_db(LOSSRAW_START_YMD)


def _apply_common_filters(qs, start=None, end=None, filters=None):
    if start: qs = qs.filter(yyyymmdd__gte=_to_db(start))
    if end:   qs = qs.filter(yyyymmdd__lte=_to_db(end))
    for f in LOSSRAW_FILTER_FIELDS:
        vals = (filters or {}).get(f)
        if vals:
            qs = qs.filter(**{f"{f}__in": vals})
    return qs


def get_filter_options(start=None, end=None, constraints=None):
    qs = TpmEqpLoss.objects.filter(yyyymmdd__gte=_start_filter())
    qs = _apply_common_filters(qs, start, end, constraints)

    def _distinct(field):
        return sorted(
            v for v in qs.exclude(**{field: ""})
            .values_list(field, flat=True).distinct() if v is not None
        )
    return {
        "areas":       _distinct("area"),
        "stations":    _distinct("station"),
        "kinds":       _distinct("kind"),
        "param_types": _distinct("param_type"),
    }


def get_aggregate(level, parents, start=None, end=None, filters=None):
    """level(kind/param_type/param_name) 별 loss_time_min 합계 — 내림차순."""
    field = LEVEL_FIELD.get(level)
    if not field:
        return []
    allowed = set(LEVEL_PARENTS.get(level, []))
    clean_parents = {k: v for k, v in (parents or {}).items() if k in allowed}

    qs = TpmEqpLoss.objects.filter(yyyymmdd__gte=_start_filter())
    qs = _apply_common_filters(qs, start, end, filters)
    for k, v in clean_parents.items():
        if v not in (None, ""):
            qs = qs.filter(_parent_q(k, v))

    qs = (qs.values(field)
            .annotate(loss_time_min=Sum("loss_time_min"), cnt=Count("pk"))
            .order_by("-loss_time_min"))
    return [{level: r[field] or UNCLASSIFIED,
             "loss_time_min": round(r["loss_time_min"] or 0, 1),
             "cnt": r["cnt"]} for r in qs]


def get_raw_rows(parents, start=None, end=None, filters=None):
    """드릴다운 최하위(kind+param_type+param_name) 의 raw 행."""
    allowed = {"kind", "param_type", "param_name"}
    clean = {k: v for k, v in (parents or {}).items()
             if k in allowed and v not in (None, "")}
    qs = TpmEqpLoss.objects.filter(yyyymmdd__gte=_start_filter())
    qs = _apply_common_filters(qs, start, end, filters)
    for k, v in clean.items():
        qs = qs.filter(_parent_q(k, v))
    qs = qs.values(*RAW_COLUMNS).order_by("yyyymmdd", "start_time")[:MAX_RAW_ROWS]
    # 출력 순서를 RAW_COLUMNS 로 고정한다 (.values() 는 dict 순서를 보장하지 않음)
    return [{col: row.get(col) for col in RAW_COLUMNS} for row in qs]
