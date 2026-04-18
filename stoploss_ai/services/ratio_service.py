"""
stoploss_ai/services/ratio_service.py

정지로스 state 기여도 분석 서비스.

─── 설계 원칙 ────────────────────────────────────────────────────
  1. tpm_eqp_loss.state 를 grouping key 로 사용한다.
     → "어떤 state(원인)가 몇 분 정지로스를 유발했나" 분석.

  2. loss_time_min 은 start_time / end_time 차이(분)로 Python에서 계산한다.

  3. report_stoploss.stoploss 를 분모로 사용:
     - 위치 필터를 적용하지 않고 flag/flagdate 기준으로 인덱싱.
     - eqp_id / eqp_model / sdwt_prod / area / 전체 레벨별 stoploss 합을 사용.

  4. pct_vs_eqp  : state가 발생한 설비들의 stoploss 합 대비 %
     pct_vs_model: 해당 기종 stoploss 합 대비 %
     pct_vs_sdwt : 해당 분임조 stoploss 합 대비 %
     pct_vs_area : 해당 라인(area) stoploss 합 대비 %
     pct_vs_total: 전체 period stoploss 대비 %
────────────────────────────────────────────────────────────────
"""
import datetime
import logging
from collections import defaultdict
from typing import Optional

from django.db.models import Q, Sum

from stoploss_ai.models import TpmEqpLoss, StoplossReport
from interlock_ai.services.detail_service import get_date_range

logger = logging.getLogger(__name__)

_DATETIME_FMTS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y%m%d%H%M%S",
    "%Y%m%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
]


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


def _calc_loss_min(start_str, end_str) -> float:
    start = _parse_dt(start_str)
    end   = _parse_dt(end_str)
    if start is None or end is None:
        return 0.0
    diff = (end - start).total_seconds() / 60
    return max(0.0, round(diff, 1))


def get_ratio_analysis(flag: str, yyyy: str, flagdate: str, filters: dict) -> list:
    """
    (flag, yyyy, flagdate) + sidebar 필터 기준으로 state 기여도를 분석한다.

    반환: loss_time_min 내림차순 정렬된 dict 리스트
    """
    start_ymd, end_ymd = get_date_range(flag, yyyy, flagdate)
    if not start_ymd:
        return []

    # ── Step 1: tpm_eqp_loss 조회 ────────────────────────────────
    q_loss = Q(yyyymmdd__gte=start_ymd, yyyymmdd__lte=end_ymd)

    # eqp_id 필터만 적용 (area/model/sdwt 는 report_stoploss 메타에서 추출)
    eqp_ids_filter = filters.get("eqp_id", [])
    if eqp_ids_filter:
        q_loss &= Q(eqp_id__in=eqp_ids_filter)

    loss_qs = (
        TpmEqpLoss.objects
        .filter(q_loss)
        .values("eqp_id", "start_time", "end_time", "state")
        .order_by("yyyymmdd", "start_time")
    )

    # ── Step 2: report_stoploss 에서 eqp 메타 맵 구축 ──────────
    # eqp_id → (area, eqp_model, sdwt_prod)
    q_base = Q(yyyy=yyyy, flag=flag, flagdate=flagdate)
    meta_qs = (
        StoplossReport.objects
        .filter(q_base)
        .values("eqp_id", "area", "eqp_model", "sdwt_prod")
        .distinct()
    )
    eqp_meta: dict = {}
    for row in meta_qs:
        eqp_meta[row["eqp_id"]] = {
            "area":      row["area"]      or "",
            "eqp_model": row["eqp_model"] or "",
            "sdwt_prod": row["sdwt_prod"] or "",
        }

    # sidebar area / eqp_model / sdwt_prod 필터 — loss 결과 필터링용
    area_filter      = set(filters.get("area",      []))
    model_filter     = set(filters.get("eqp_model", []))
    sdwt_filter      = set(filters.get("sdwt_prod", []))
    prc_filter       = set(filters.get("prc_group", []))  # report 기준이라 loss에 직접 미적용

    # ── Step 3: state 별 집계 ────────────────────────────────────
    # state → { loss_time_min, eqp_ids, eqp_models, sdwt_prods, areas }
    combo: dict = defaultdict(lambda: {
        "loss_time": 0.0,
        "eqp_ids":   set(),
        "eqp_models": set(),
        "sdwt_prods": set(),
        "areas":      set(),
    })

    for row in loss_qs:
        eqp_id = row["eqp_id"] or ""
        meta   = eqp_meta.get(eqp_id, {"area": "", "eqp_model": "", "sdwt_prod": ""})
        area      = meta["area"]
        eqp_model = meta["eqp_model"]
        sdwt_prod = meta["sdwt_prod"]

        # sidebar 위치 필터 적용
        if area_filter  and area      not in area_filter:
            continue
        if model_filter and eqp_model not in model_filter:
            continue
        if sdwt_filter  and sdwt_prod not in sdwt_filter:
            continue

        state = row["state"] or "(unknown)"
        lt    = _calc_loss_min(row["start_time"], row["end_time"])

        combo[state]["loss_time"]   += lt
        combo[state]["eqp_ids"].add(eqp_id)
        combo[state]["eqp_models"].add(eqp_model)
        combo[state]["sdwt_prods"].add(sdwt_prod)
        combo[state]["areas"].add(area)

    if not combo:
        return []

    # ── Step 4: report_stoploss 레벨별 stoploss 인덱스 구축 ─────
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
    idx_area  = _index_by("area")
    total_stoploss = sum(idx_eqp.values())

    logger.debug(
        "[Ratio] period=%s/%s/%s | total_stoploss=%.2f | state_count=%d",
        flag, yyyy, flagdate, total_stoploss, len(combo),
    )

    # ── Step 5: 각 state 별 % 계산 ──────────────────────────────
    def _sum_denom(idx: dict, keys: set) -> float:
        return sum(idx.get(k, 0.0) for k in keys)

    def _pct(numerator: float, denominator: float) -> Optional[float]:
        if not denominator:
            return None
        return round(numerator / denominator * 100, 2)

    result = []
    for state_name, data in combo.items():
        lt = round(data["loss_time"], 1)

        denom_eqp   = _sum_denom(idx_eqp,   data["eqp_ids"])
        denom_model = _sum_denom(idx_model,  data["eqp_models"])
        denom_sdwt  = _sum_denom(idx_sdwt,   data["sdwt_prods"])
        denom_area  = _sum_denom(idx_area,   data["areas"])

        result.append({
            "state":         state_name,
            "loss_time_min": lt,
            "pct_vs_eqp":   _pct(lt, denom_eqp),
            "pct_vs_model": _pct(lt, denom_model),
            "pct_vs_sdwt":  _pct(lt, denom_sdwt),
            "pct_vs_area":  _pct(lt, denom_area),
            "pct_vs_total": _pct(lt, total_stoploss),
        })

    result.sort(key=lambda r: r["loss_time_min"], reverse=True)
    return result
