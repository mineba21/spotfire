"""
stoploss_ai/services/ratio_service.py

정지로스 기여도 분석 서비스.

─── 설계 원칙 ────────────────────────────────────────────────────
  1. group_by 컬럼(기본: state) 을 grouping key 로 사용한다.
     → "어떤 원인(state/eqp_model/area 등)이 몇 분 정지로스를 유발했나" 분석.

  2. loss_time_min 은 start_time / end_time 차이(분)로 Python에서 계산한다.

  3. report_stoploss.stoploss 를 분모로 사용:
     - 위치 필터를 적용하지 않고 flag/flagdate 기준으로 인덱싱.
     - eqp_id / eqp_model / sdwt_prod / area / 전체 레벨별 stoploss 합을 사용.

  4. pct_vs_eqp  : group 이 발생한 설비들의 stoploss 합 대비 %
     pct_vs_model: 해당 기종 stoploss 합 대비 %
     pct_vs_sdwt : 해당 분임조 stoploss 합 대비 %
     pct_vs_area : 해당 라인(area) stoploss 합 대비 %
     pct_vs_total: 전체 period stoploss 대비 %

─── 컬럼(그룹) 추가 방법 ─────────────────────────────────────────
  [A] tpm_eqp_loss 자체 컬럼을 group_by 로 쓰는 경우 (state, eqp_id 등):
      1) RATIO_GROUP_BY_OPTIONS 에 컬럼명 추가
      2) VALID_GROUP_BY 에 컬럼명 추가
      3) tpm_eqp_loss.values() 에 컬럼명 추가
      4) 프론트(dashboard.js) RATIO_GROUP_OPTIONS 에 옵션 추가

  [B] report_stoploss 메타 컬럼을 group_by 로 쓰는 경우 (eqp_model, area, sdwt_prod):
      이미 eqp_meta 에서 lookup 가능 — (A)와 동일하게 추가만 하면 됨.

  [C] 외부 테이블(SpotfireRaw 의 param_type / param_name) 을 쓰려면:
      1) SpotfireRaw 에서 yyyymmdd + eqp_id + act_time 범위로 조인이 필요
      2) 현재 tpm_eqp_loss.start_time ~ end_time 구간과 교집합 판정 로직 추가
      3) _aggregate_by_group() 내부에서 해당 param_type / param_name 을 키로 사용

  (param_type / param_name 은 Raw 전용 컬럼이므로 [C] 구현 후 options 에 노출)
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

# ─────────────────────────────────────────────────────────────────
# group_by 로 사용 가능한 컬럼 허용 목록
#   - state      : tpm_eqp_loss.state (기본)
#   - eqp_id     : tpm_eqp_loss.eqp_id
#   - eqp_model  : report_stoploss 메타 조회
#   - area       : report_stoploss 메타 조회
#   - sdwt_prod  : report_stoploss 메타 조회
# ─────────────────────────────────────────────────────────────────
VALID_GROUP_BY = {"state", "eqp_id", "eqp_model", "area", "sdwt_prod"}

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


def _collect_date_ranges(flag: str, yyyy: str, flagdates: list):
    """여러 flagdate 에 대한 (start, end) 합집합 범위."""
    starts, ends = [], []
    for fd in flagdates:
        s, e = get_date_range(flag, yyyy, fd)
        if s and e:
            starts.append(s)
            ends.append(e)
    if not starts:
        return None, None
    return min(starts), max(ends)


def get_ratio_analysis(
    flag: str, yyyy: str, flagdates,
    filters: dict, group_by: str = "state",
) -> list:
    """
    (flag, yyyy, flagdates) + sidebar 필터 + group_by 기준으로 기여도를 분석한다.

    flagdates: 단일 str 또는 list[str] (멀티 bar 선택 지원)
    group_by : state / eqp_id / eqp_model / area / sdwt_prod

    반환: loss_time_min 내림차순 정렬된 dict 리스트
        [{ group: "...", loss_time_min, pct_vs_eqp, pct_vs_model,
           pct_vs_sdwt, pct_vs_area, pct_vs_total }, ...]
    """
    if isinstance(flagdates, str):
        flagdates = [flagdates]
    flagdates = [fd for fd in flagdates if fd]

    if group_by not in VALID_GROUP_BY:
        group_by = "state"

    start_ymd, end_ymd = _collect_date_ranges(flag, yyyy, flagdates)
    if not start_ymd:
        return []

    # ── Step 1: tpm_eqp_loss 조회 ────────────────────────────────
    q_loss = Q(yyyymmdd__gte=start_ymd, yyyymmdd__lte=end_ymd)

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
    q_base = Q(yyyy=yyyy, flag=flag, flagdate__in=flagdates)
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

    # sidebar 위치 필터 — loss 결과 필터링용
    area_filter  = set(filters.get("area",      []))
    model_filter = set(filters.get("eqp_model", []))
    sdwt_filter  = set(filters.get("sdwt_prod", []))

    # ── Step 3: group_by 기준 집계 ───────────────────────────────
    # group_key → { loss_time, eqp_ids, eqp_models, sdwt_prods, areas }
    combo: dict = defaultdict(lambda: {
        "loss_time":  0.0,
        "eqp_ids":    set(),
        "eqp_models": set(),
        "sdwt_prods": set(),
        "areas":      set(),
    })

    for row in loss_qs:
        eqp_id    = row["eqp_id"] or ""
        meta      = eqp_meta.get(eqp_id, {"area": "", "eqp_model": "", "sdwt_prod": ""})
        area      = meta["area"]
        eqp_model = meta["eqp_model"]
        sdwt_prod = meta["sdwt_prod"]

        # sidebar 위치 필터
        if area_filter  and area      not in area_filter:
            continue
        if model_filter and eqp_model not in model_filter:
            continue
        if sdwt_filter  and sdwt_prod not in sdwt_filter:
            continue

        # group_by 컬럼 결정
        group_key_map = {
            "state":     row["state"]   or "(unknown)",
            "eqp_id":    eqp_id         or "(unknown)",
            "eqp_model": eqp_model      or "(unknown)",
            "area":      area           or "(unknown)",
            "sdwt_prod": sdwt_prod      or "(unknown)",
        }
        group_key = group_key_map[group_by]
        lt        = _calc_loss_min(row["start_time"], row["end_time"])

        combo[group_key]["loss_time"]    += lt
        combo[group_key]["eqp_ids"].add(eqp_id)
        combo[group_key]["eqp_models"].add(eqp_model)
        combo[group_key]["sdwt_prods"].add(sdwt_prod)
        combo[group_key]["areas"].add(area)

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
        "[Ratio] period=%s/%s/%s group_by=%s | total_stoploss=%.2f | rows=%d",
        flag, yyyy, flagdates, group_by, total_stoploss, len(combo),
    )

    # ── Step 5: 각 그룹별 % 계산 ────────────────────────────────
    def _sum_denom(idx: dict, keys: set) -> float:
        return sum(idx.get(k, 0.0) for k in keys)

    def _pct(num: float, denom: float) -> Optional[float]:
        if not denom:
            return None
        return round(num / denom * 100, 2)

    result = []
    for group_name, data in combo.items():
        lt = round(data["loss_time"], 1)

        denom_eqp   = _sum_denom(idx_eqp,   data["eqp_ids"])
        denom_model = _sum_denom(idx_model, data["eqp_models"])
        denom_sdwt  = _sum_denom(idx_sdwt,  data["sdwt_prods"])
        denom_area  = _sum_denom(idx_area,  data["areas"])

        result.append({
            # group_by 키로 실제 컬럼명 반환 (프론트에서 동일 키 사용)
            group_by:        group_name,
            "loss_time_min": lt,
            "pct_vs_eqp":    _pct(lt, denom_eqp),
            "pct_vs_model":  _pct(lt, denom_model),
            "pct_vs_sdwt":   _pct(lt, denom_sdwt),
            "pct_vs_area":   _pct(lt, denom_area),
            "pct_vs_total":  _pct(lt, total_stoploss),
        })

    result.sort(key=lambda r: r["loss_time_min"], reverse=True)
    return result
