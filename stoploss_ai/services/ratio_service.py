"""
stoploss_ai/services/ratio_service.py

인터락(param_type / param_name) 기여도 분석 서비스.

─── 설계 원칙 ────────────────────────────────────────────────────
  1. eqp_loss_tpm 은 sidebar 필터(라인·설비·기종 등)를 적용해 조회한다.
     → "지금 보고 있는 범위의 인터락만" 분석.

  2. report_stoploss 분모 인덱스는 위치 필터를 적용하지 않는다(flag/flagdate 기준).
     → 각 레벨(eqp·model·sdwt·line·전체)의 '자연스러운 stoploss 합계'를 사용.
     → 특정 인터락이 일부 라인에서만 발생하면
        denom_line < denom_total 이 되어 레벨별 % 가 달라진다.

  3. pct_vs_eqp  : 이 인터락이 발생한 설비들의 stoploss 합 대비 %
     pct_vs_sdwt : 해당 설비 분임조 stoploss 합 대비 %
     pct_vs_model: 해당 기종 stoploss 합 대비 %
     pct_vs_line : 해당 라인 stoploss 합 대비 %
     pct_vs_total: 전체 period stoploss 대비 %
────────────────────────────────────────────────────────────────
"""
from collections import defaultdict
from django.db.models import Sum, Q

from stoploss_ai.models import EqpLossTpm, StoplossReport
from spotfire_ai.services.detail_service import get_date_range

import logging
logger = logging.getLogger(__name__)


def get_ratio_analysis(flag: str, yyyy: str, flagdate: str, filters: dict) -> list:
    """
    (flag, yyyy, flagdate) + sidebar 필터 기준으로 인터락 기여도를 분석한다.

    반환: loss_time_min 내림차순 정렬된 dict 리스트
    """
    start_ymd, end_ymd = get_date_range(flag, yyyy, flagdate)
    if not start_ymd:
        return []

    # ── Step 1: eqp_loss_tpm 세분화 집계 ─────────────────────────
    # 6-컬럼 group: (param_type, param_name, line, sdwt_prod, eqp_model, eqp_id)
    # → 어느 설비/라인에서 어떤 인터락이 몇 분 발생했는지 파악
    q_raw = _build_eqp_q(filters, start_ymd, end_ymd)
    detailed_qs = (
        EqpLossTpm.objects
        .filter(q_raw)
        .values("param_type", "param_name", "line", "sdwt_prod", "eqp_model", "eqp_id")
        .annotate(loss_sum=Sum("loss_time"))
    )

    # (param_type, param_name) → { loss_time, lines, sdwt_prods, eqp_models, eqp_ids }
    combo: dict = defaultdict(lambda: {
        "loss_time": 0.0,
        "lines":      set(),
        "sdwt_prods": set(),
        "eqp_models": set(),
        "eqp_ids":    set(),
    })
    for row in detailed_qs:
        key = (row["param_type"], row["param_name"])
        combo[key]["loss_time"]   += (row["loss_sum"] or 0.0)
        combo[key]["lines"].add(row["line"])
        combo[key]["sdwt_prods"].add(row["sdwt_prod"])
        combo[key]["eqp_models"].add(row["eqp_model"])
        combo[key]["eqp_ids"].add(row["eqp_id"])

    if not combo:
        return []

    # ── Step 2: report_stoploss 레벨별 stoploss 인덱스 구축 ──────
    # 위치 필터를 적용하지 않고 flag/flagdate 기준으로만 인덱싱
    # → 각 레벨의 '자연스러운' stoploss 합계를 사용
    q_base = Q(yyyy=yyyy, flag=flag, flagdate=flagdate)   # 위치 필터 없음

    def _index_by(field: str) -> dict:
        rows = (
            StoplossReport.objects
            .filter(q_base)
            .values(field)
            .annotate(s=Sum("stoploss"))
        )
        return {r[field]: (r["s"] or 0.0) for r in rows}

    idx_eqp   = _index_by("eqp_id")
    idx_model = _index_by("eqp_model")
    idx_sdwt  = _index_by("sdwt_prod")
    idx_line  = _index_by("line")
    total_stoploss = sum(idx_eqp.values())

    logger.debug(
        "[Ratio] period=%s/%s/%s | total_stoploss=%.2f | combo_count=%d",
        flag, yyyy, flagdate, total_stoploss, len(combo),
    )

    # ── Step 3: 각 조합별 % 계산 ─────────────────────────────────
    def _sum_denom(idx: dict, keys: set) -> float:
        """keys에 해당하는 index 합산. 없는 key는 0 처리"""
        return sum(idx.get(k, 0.0) for k in keys)

    def _pct(numerator: float, denominator: float):
        if not denominator:
            return None
        return round(numerator / denominator * 100, 2)

    result = []
    for (param_type, param_name), data in combo.items():
        lt = round(data["loss_time"], 2)

        denom_eqp   = _sum_denom(idx_eqp,   data["eqp_ids"])
        denom_model = _sum_denom(idx_model,  data["eqp_models"])
        denom_sdwt  = _sum_denom(idx_sdwt,   data["sdwt_prods"])
        denom_line  = _sum_denom(idx_line,   data["lines"])

        result.append({
            "param_type":    param_type,
            "param_name":    param_name,
            "loss_time_min": lt,
            "pct_vs_eqp":   _pct(lt, denom_eqp),
            "pct_vs_sdwt":  _pct(lt, denom_sdwt),
            "pct_vs_model": _pct(lt, denom_model),
            "pct_vs_line":  _pct(lt, denom_line),
            "pct_vs_total": _pct(lt, total_stoploss),
        })

    result.sort(key=lambda r: r["loss_time_min"], reverse=True)
    return result


# ─── 내부 헬퍼 ───────────────────────────────────────────────────

def _build_eqp_q(filters: dict, start_ymd: str, end_ymd: str) -> Q:
    """eqp_loss_tpm 용 날짜 범위 + sidebar 필터 Q 객체"""
    q = Q(yyyymmdd__gte=start_ymd, yyyymmdd__lte=end_ymd)
    for field in ["line", "sdwt_prod", "eqp_id", "eqp_model", "param_type"]:
        vals = filters.get(field, [])
        if vals:
            q &= Q(**{f"{field}__in": vals})
    return q
