"""
services/ai_service.py

역할:
- AI Copilot 의 전체 흐름을 오케스트레이션한다
- LLM 호출 / 검증 / DB 조회 / 요약을 순서대로 실행
- page_context 에 따른 기본 필터를 강제 적용해 안전성을 보장한다

흐름:
    ask_ai()
      → LLM.generate_query_json()       # 자연어 → query JSON
      → _apply_page_context_defaults()  # page_context 기본 필터 강제 적용
      → validate_query_json()           # allowlist 검증
      → execute_query()                 # DB 조회
      → LLM.summarize_results()         # DB 결과 → 자연어 요약
      → 반환

page_context 종류:
    "interlock"    : param_type=interlock 기본 필터 강제
    "stoploss"     : param_type=stoploss 기본 필터 강제
    "down_history" : 기본 필터 없음 (별도 테이블 연동 시 여기서 확장)
"""

from __future__ import annotations

import copy
import logging

from spotfire_ai.services.llm_interface import get_llm_client
from spotfire_ai.services.json_validator import validate_query_json
from spotfire_ai.services.query_builder  import execute_query

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# page_context 별 기본 필터 정의
# ─────────────────────────────────────────────────────────────────
PAGE_CONTEXT_DEFAULTS: dict = {
    # interlock: param_type 을 "interlock" 으로 강제
    "interlock": {
        "param_type": ["interlock"],
    },
    # stoploss: param_type 을 "stoploss" 으로 강제
    "stoploss": {
        "param_type": ["stoploss"],
    },
    # down_history: 현재는 기본 필터 없음
    # 추후 별도 테이블을 사용할 경우 "table" 도 여기서 강제할 수 있다
    "down_history": {},
}

# 허용 page_context 목록
VALID_PAGE_CONTEXTS: frozenset = frozenset(PAGE_CONTEXT_DEFAULTS.keys())

# LLM 재시도 최대 횟수 (validate 실패 시)
MAX_RETRY: int = 2


# ─────────────────────────────────────────────────────────────────
# 메인 함수
# ─────────────────────────────────────────────────────────────────

def ask_ai(
    question:        str,
    page_context:    str,
    selected_bar:    dict | None,
    sidebar_filters: dict,
) -> dict:
    """
    AI Copilot 메인 엔트리포인트.

    파라미터:
        question        : 사용자의 자연어 질문
        page_context    : "interlock" | "stoploss" | "down_history"
        selected_bar    : {"flag": "M", "yyyy": "2024", "flagdate": "M01"} | None
        sidebar_filters : {"line": ["L1"], "param_type": ["interlock"], ...}

    반환 (성공):
        {
            "ok": True,
            "data": {
                "answer":          "분석 결과: ...",
                "result_count":    10,
                "results_preview": [...],   # 최대 5행
                "query_json":      {...},   # 디버깅용
            }
        }

    반환 (실패):
        {"ok": False, "error": "에러 메시지"}
    """
    # ── page_context 기본값 처리 ──────────────────────────────
    if page_context not in VALID_PAGE_CONTEXTS:
        page_context = "interlock"  # 알 수 없는 컨텍스트 → 안전한 기본값

    # ── LLM context 구성 ─────────────────────────────────────
    context: dict = {
        "page_context":    page_context,
        "selected_bar":    selected_bar  or {},
        "sidebar_filters": sidebar_filters or {},
    }

    llm = get_llm_client()

    # ── Step 1: query JSON 생성 + 검증 (최대 MAX_RETRY 회) ───
    query_json: dict | None = None
    last_error: str         = ""

    for attempt in range(1, MAX_RETRY + 1):
        try:
            raw_qj = llm.generate_query_json(question, context)
        except Exception as exc:
            logger.error("LLM generate_query_json 오류 (시도 %d): %s", attempt, exc)
            last_error = f"LLM 쿼리 생성 오류: {exc}"
            break

        # page_context 기본 필터 강제 적용
        raw_qj = _apply_page_context_defaults(
            raw_qj, page_context, selected_bar, sidebar_filters
        )

        # 검증
        is_valid, err_msg = validate_query_json(raw_qj)
        if is_valid:
            query_json = raw_qj
            break
        else:
            last_error = f"Query 검증 실패 (시도 {attempt}): {err_msg}"
            logger.warning(last_error)
            # 다음 시도 시 context 에 에러 정보 추가 (실제 LLM 에서 재시도 유도)
            context["previous_error"] = err_msg

    if query_json is None:
        return {"ok": False, "error": last_error or "query JSON 생성에 실패했습니다."}

    # ── Step 2: DB 조회 ───────────────────────────────────────
    try:
        results = execute_query(query_json)
    except Exception as exc:
        logger.error("execute_query 오류: %s | query_json: %s", exc, query_json)
        return {"ok": False, "error": f"DB 조회 오류: {exc}"}

    # ── Step 3: 결과 요약 ─────────────────────────────────────
    try:
        answer = llm.summarize_results(question, results, context)
    except Exception as exc:
        logger.error("LLM summarize_results 오류: %s", exc)
        # 요약 실패 시 기본 텍스트 반환 (DB 조회는 성공했으므로 data 는 반환)
        answer = f"결과 요약 중 오류가 발생했습니다: {exc}"

    return {
        "ok": True,
        "data": {
            "answer":          answer,
            "result_count":    len(results),
            # 최대 5행 미리보기 (chat UI 에서 표 형태로 표시 가능)
            "results_preview": results[:5],
            # 디버깅용 (개발 환경에서 활용, 운영 시 숨기고 싶으면 None 으로)
            "query_json":      query_json,
        },
    }


# ─────────────────────────────────────────────────────────────────
# page_context 기본 필터 강제 적용
# ─────────────────────────────────────────────────────────────────

def _apply_page_context_defaults(
    query_json:      dict,
    page_context:    str,
    selected_bar:    dict | None,
    sidebar_filters: dict,
) -> dict:
    """
    LLM 이 생성한 query JSON 에 page_context 기본 필터를 강제 덮어쓴다.

    목적:
        LLM 이 실수로 잘못된 param_type 을 설정해도 page_context 가 우선한다.
        예) interlock 페이지에서 LLM 이 stoploss 를 넣으면 → interlock 으로 교정

    적용 순서:
        1. page_context 기본 필터 (PAGE_CONTEXT_DEFAULTS) — 최우선
        2. selected_bar → act_time_range (LLM 이 누락했을 경우 보완)
        3. sidebar_filters 의 주요 필드 (LLM 이 누락했을 경우 보완)
    """
    qj      = copy.deepcopy(query_json)  # 원본 변경 방지
    filters = qj.setdefault("filters", {})

    # ① page_context 기본 필터 강제 적용
    defaults = PAGE_CONTEXT_DEFAULTS.get(page_context, {})
    for field, value in defaults.items():
        filters[field] = value  # 무조건 덮어쓰기

    # ② selected_bar → act_time_range 보완 (LLM 이 누락했을 경우)
    if (
        selected_bar
        and selected_bar.get("flag")
        and selected_bar.get("yyyy")
        and selected_bar.get("flagdate")
        and "act_time_range" not in filters
    ):
        filters["act_time_range"] = {
            "flag":     selected_bar["flag"],
            "yyyy":     selected_bar["yyyy"],
            "flagdate": selected_bar["flagdate"],
        }

    # ③ sidebar_filters 보완 (LLM 이 누락했을 경우에만 추가)
    # — 이미 LLM 이 설정한 필드는 건드리지 않는다
    for field in ("line", "sdwt_prod", "eqp_id", "eqp_model"):
        if sidebar_filters.get(field) and field not in filters:
            filters[field] = sidebar_filters[field]

    return qj
