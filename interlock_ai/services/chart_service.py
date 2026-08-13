"""
services/chart_service.py

[v2 변경]
- 데이터 소스: report_interlock → interlock_raw (cube 캐싱)
- 조회 기간 상한: 최근 12개월
- cube 갱신: checkdb.item_status.last_update_time 버전 마커 비교 (30초 주기 확인)
- m_rank/w_rank/d_rank: "최근 N개 기간 표시" 로 해석
"""
import datetime
import logging
import threading
import time
from collections import defaultdict

from django.db import connections
from django.db.models import Count

from interlock_ai.models import SpotfireRaw

logger = logging.getLogger(__name__)

# ─── 설정 ────────────────────────────────────────────────────────
RAW_CHART_MAX_MONTHS = 12
FLAGS = ["M", "W", "D"]
DEFAULT_PERIOD_LIMIT = 999

CUBE_DIMS = ["yyyymmdd", "line", "sdwt_prod", "eqp_model",
             "eqp_id", "param_type", "param_name"]
_DIM_IDX = {f: i for i, f in enumerate(CUBE_DIMS)}

# ─── 데이터 버전 마커 (checkdb.item_status) ──────────────────────
CHECK_DB_ALIAS         = "checkdb"
DATA_VERSION_ITEM      = "interlock_raw"
VERSION_CHECK_INTERVAL = 30   # 초

_cube_lock = threading.Lock()
_cube_data: list = None
_cube_version: str = ""
_version_checked_at: float = 0.0


def _read_data_version():
    """checkdb 조회 실패 시 None — 기존 큐브 유지 신호."""
    try:
        with connections[CHECK_DB_ALIAS].cursor() as cur:
            cur.execute(
                "SELECT last_update_time FROM item_status WHERE item_name = %s",
                [DATA_VERSION_ITEM],
            )
            row = cur.fetchone()
        return str(row[0]) if row else ""
    except Exception as exc:
        logger.warning("[Cube] checkdb 버전 조회 실패 — 기존 큐브 유지: %s", exc)
        return None


def _cutoff_ymd8(today=None) -> str:
    today = today or datetime.date.today()
    total = today.year * 12 + (today.month - 1) - (RAW_CHART_MAX_MONTHS - 1)
    return datetime.date(total // 12, total % 12 + 1, 1).strftime("%Y%m%d")


def _detect_hyphen() -> bool:
    sample = SpotfireRaw.objects.values_list("yyyymmdd", flat=True).first()
    return "-" in str(sample) if sample else False


def _build_cube() -> list:
    cutoff = _cutoff_ymd8()
    cutoff_db = (f"{cutoff[:4]}-{cutoff[4:6]}-{cutoff[6:8]}"
                 if _detect_hyphen() else cutoff)
    qs = (
        SpotfireRaw.objects
        .filter(yyyymmdd__gte=cutoff_db)
        .values(*CUBE_DIMS)
        .annotate(cnt=Count("pk"))
    )
    cube = []
    for row in qs.iterator(chunk_size=2000):
        ymd8 = str(row["yyyymmdd"]).replace("-", "")
        cube.append((
            ymd8, row["line"], row["sdwt_prod"], row["eqp_model"],
            row["eqp_id"], row["param_type"], row["param_name"], row["cnt"],
        ))
    return cube


def _get_cube() -> list:
    global _cube_data, _cube_version, _version_checked_at
    now = time.time()
    if _cube_data is not None and now - _version_checked_at < VERSION_CHECK_INTERVAL:
        return _cube_data
    version = _read_data_version()
    _version_checked_at = now
    if _cube_data is not None and (version is None or version == _cube_version):
        return _cube_data
    with _cube_lock:
        if _cube_data is not None and version is not None and version == _cube_version:
            return _cube_data
        _cube_data = _build_cube()
        if version is not None:
            _cube_version = version
        logger.info("[Cube] 재빌드 | version=%s | rows=%d", _cube_version, len(_cube_data))
        return _cube_data


def invalidate_cube():
    """수동 강제 갱신용."""
    global _cube_data, _cube_version
    with _cube_lock:
        _cube_data = None
        _cube_version = ""


# ─── 차트 데이터 ─────────────────────────────────────────────────
def get_chart_data(filters: dict, rank_limits: dict, y_field: str = "cnt") -> dict:
    cube = _get_cube()
    active = [(_DIM_IDX[f], set(v)) for f, v in filters.items()
              if v and f in _DIM_IDX]

    daily = defaultdict(int)
    for row in cube:
        if all(row[idx] in allowed for idx, allowed in active):
            daily[row[0]] += row[7]

    agg = {f: defaultdict(int) for f in FLAGS}
    yyyy_map = {f: {} for f in FLAGS}
    for ymd8, cnt in daily.items():
        yyyy, mm, dd = ymd8[:4], ymd8[4:6], ymd8[6:8]
        try:
            date = datetime.date(int(yyyy), int(mm), int(dd))
        except ValueError:
            continue
        m_key = f"M{mm}"
        agg["M"][m_key] += cnt
        yyyy_map["M"].setdefault(m_key, yyyy)
        w_num = (date - datetime.date(int(yyyy), 1, 1)).days // 7 + 1
        w_key = f"W{w_num:02d}"
        agg["W"][w_key] += cnt
        yyyy_map["W"].setdefault(w_key, yyyy)
        d_key = f"{mm}/{dd}"
        agg["D"][d_key] += cnt
        yyyy_map["D"].setdefault(d_key, yyyy)

    result = {}
    for flag in FLAGS:
        limit = rank_limits.get(flag, DEFAULT_PERIOD_LIMIT)
        keys = sorted(agg[flag].keys(),
                      key=lambda k: (yyyy_map[flag][k], k))[-limit:]
        result[flag] = {
            "flagdates": keys,
            "yyyy_map":  {k: yyyy_map[flag][k] for k in keys},
            "series":    [{"name": "ALL", "y": [agg[flag][k] for k in keys]}],
        }
    return result


def parse_rank_limits(get_params) -> dict:
    def _safe_int(val, default):
        try:
            return int(val)
        except (TypeError, ValueError):
            return default
    return {
        "M": _safe_int(get_params.get("m_rank"), DEFAULT_PERIOD_LIMIT),
        "W": _safe_int(get_params.get("w_rank"), DEFAULT_PERIOD_LIMIT),
        "D": _safe_int(get_params.get("d_rank"), DEFAULT_PERIOD_LIMIT),
    }


# ─── 사이드바 필터 옵션 (cube 기반) ──────────────────────────────
def get_filter_options_from_cube(constraints: dict = None) -> dict:
    cube = _get_cube()
    active = [(_DIM_IDX[f], set(v)) for f, v in (constraints or {}).items()
              if v and f in _DIM_IDX]
    out = {f: set() for f in CUBE_DIMS[1:]}
    for row in cube:
        if all(row[i] in a for i, a in active):
            for f in out:
                if row[_DIM_IDX[f]]:
                    out[f].add(row[_DIM_IDX[f]])
    return {
        "lines":       sorted(out["line"]),
        "sdwt_prods":  sorted(out["sdwt_prod"]),
        "eqp_models":  sorted(out["eqp_model"]),
        "eqp_ids":     sorted(out["eqp_id"]),
        "param_types": sorted(out["param_type"]),
        "param_names": sorted(out["param_name"]),
    }


# ─── Top Show 집계 (cube 전수) ───────────────────────────────────
TOP_ALLOWED_GROUP_COLS = frozenset(CUBE_DIMS) - {"yyyymmdd"}
TOP_MAX_N = 200


def get_top_aggregate(flag, yyyy, flagdates, filters, group_cols, top_n=10):
    # 순환 import 방지
    from interlock_ai.services.detail_service import get_date_range, normalize_fd_pairs

    # flagdates 는 (flagdate, yyyy) 쌍 리스트 권장 — bar 마다 연도가 다를 수 있다
    fd_pairs   = normalize_fd_pairs(flagdates, yyyy)
    group_cols = [c for c in group_cols if c in TOP_ALLOWED_GROUP_COLS]
    if not group_cols or not fd_pairs:
        return []
    top_n = max(1, min(int(top_n or 10), TOP_MAX_N))

    ranges = []
    for fd, fy in fd_pairs:
        s, e = get_date_range(flag, fy, fd)   # 쌍별 연도
        if s and e:
            ranges.append((s, e))
    if not ranges:
        return []

    cube = _get_cube()
    active = [(_DIM_IDX[f], set(v)) for f, v in filters.items()
              if v and f in _DIM_IDX]
    g_idx = [_DIM_IDX[c] for c in group_cols]

    agg = defaultdict(int)
    for row in cube:
        ymd = row[0]
        if not any(s <= ymd <= e for s, e in ranges):
            continue
        if not all(row[i] in allowed for i, allowed in active):
            continue
        agg[tuple(row[i] for i in g_idx)] += row[7]

    result = [{**dict(zip(group_cols, key)), "cnt": cnt}
              for key, cnt in agg.items()]
    result.sort(key=lambda r: r["cnt"], reverse=True)
    return result[:top_n]
