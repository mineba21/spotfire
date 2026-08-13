"""
stoploss_ai/services/lossraw_service.py

tpm_eqp_loss 드릴다운 분석 (LOSSRAW_START_YMD 이후).
loss_time_min(float 컬럼) 을 DB Sum 으로 집계 — Python 계산/캐싱 불필요.

드릴다운: kind → param_type → param_name → raw

[컬럼 매핑 주의]
  "설비" 컬럼은 DB 상 station 하나이며 모델에서는 eqp_id 가
  db_column="station" 으로 매핑한다. 같은 컬럼에 두 개의 필드를 둘 수 없어
  (Django models.E007) 사이드바/테이블의 station 은 STATION_FIELD 를 통해
  eqp_id 로 변환해 조회하고, raw 응답에는 station / eqp_id 두 키로 노출한다.
  DB 에 station 과 별개의 설비 컬럼이 존재한다면 모델에 필드를 추가하고
  STATION_FIELD 만 바꾸면 된다.
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

# 사이드바/테이블의 논리 컬럼명 → 실제 모델 필드명
STATION_FIELD = "eqp_id"

RAW_COLUMNS = ["yyyymmdd", "area", "station", "eqp_id", "start_time", "end_time",
               "kind", "state", "param_type", "param_name", "loss_time_min"]

# .values() 에 넘길 실제 모델 필드 (station 은 eqp_id 와 같은 컬럼이라 제외)
RAW_QUERY_FIELDS = [c for c in RAW_COLUMNS if c != "station"]

MAX_RAW_ROWS = 5000

# yyyymmdd 표기 형식은 적재 규칙이라 런타임 중 바뀌지 않는다 — 1회만 조회한다.
_ymd_hyphen_cache = None


def _model_field(name: str) -> str:
    """논리 컬럼명 → 모델 필드명 (station → eqp_id)."""
    return STATION_FIELD if name == "station" else name


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
            qs = qs.filter(**{f"{_model_field(f)}__in": vals})
    return qs


def get_filter_options(start=None, end=None, constraints=None):
    qs = TpmEqpLoss.objects.filter(yyyymmdd__gte=_start_filter())
    qs = _apply_common_filters(qs, start, end, constraints)

    def _distinct(field):
        field = _model_field(field)
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
    qs = qs.values(*RAW_QUERY_FIELDS).order_by("yyyymmdd", "start_time")[:MAX_RAW_ROWS]
    return [_transform_raw_row(row) for row in qs]


def _transform_raw_row(row: dict) -> dict:
    """모델 row → 출력 dict. station 은 eqp_id 와 같은 컬럼."""
    out = dict(row)
    out["station"] = row.get(STATION_FIELD, "")
    return {col: out.get(col) for col in RAW_COLUMNS}
