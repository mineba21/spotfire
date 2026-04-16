"""
services/ai_service.py

역할:
- AI Copilot 의 전체 흐름을 오케스트레이션한다
- LLM 호출 / 검증 / DB 조회 / 요약을 순서대로 실행

디버깅 로그 확인 방법:
  settings.py 에 아래 설정이 있으면 콘솔에서 바로 확인 가능:
    LOGGING = {
        'version': 1,
        'handlers': {'console': {'class': 'logging.StreamHandler'}},
        'loggers': {'spotfire_ai': {'handlers': ['console'], 'level': 'DEBUG'}},
    }

  로그 검색 키워드:
    "[AI Step1]"  → LLM 이 생성한 query_json 원본 (교정 전)
    "[AI Step1c]" → 테이블명 교정 후 query_json
    "[AI Step1v]" → validate 결과
    "[AI Step2]"  → DB 조회 실행 직전 최종 query_json
    "[AI Step3]"  → 조회 결과 건수
    "[AI ERR]"    → 각 단계별 에러
"""

from __future__ import annotations

import copy
import json
import logging

from spotfire_ai.models import TABLE_RAW
from spotfire_ai.services.llm_interface import get_llm_client
from spotfire_ai.services.json_validator import validate_query_json
from spotfire_ai.services.query_builder  import execute_query

logger = logging.getLogger(__name__)

PAGE_CONTEXT_DEFAULTS: dict = {
    # page_context 는 현재 보고 있는 페이지를 나타낼 뿐,
    # param_type 필터를 강제하지 않는다.
    # param_type 은 A / E / T / M 등 인터락 종류 분류값이며
    # 사용자가 sidebar 에서 직접 선택하거나 LLM 이 질문에서 파악해 필터링한다.
    "interlock":    {},
    "stoploss":     {},
    "down_history": {},
}

VALID_PAGE_CONTEXTS: frozenset = frozenset(PAGE_CONTEXT_DEFAULTS.keys())
MAX_RETRY: int = 2


def ask_ai(
    question:        str,
    page_context:    str,
    selected_bar:    dict | None,
    sidebar_filters: dict,
    filter_options:  dict | None = None,
) -> dict:
    if page_context not in VALID_PAGE_CONTEXTS:
        page_context = "interlock"

    context: dict = {
        "page_context":    page_context,
        "selected_bar":    selected_bar    or {},
        "sidebar_filters": sidebar_filters or {},
        # DB 실제 값 목록: LLM 이 자연어를 올바른 필드에 매핑하는 데 사용
        # 예) "백호" → sdwt_prods 에 있으면 sdwt_prod 필터로, lines 에 있으면 line 필터로
        "filter_options":  filter_options  or {},
    }

    llm = get_llm_client()

    # ── Step 1: query JSON 생성 + 검증 ───────────────────────
    query_json: dict | None = None
    last_error: str         = ""

    for attempt in range(1, MAX_RETRY + 1):
        try:
            raw_qj = llm.generate_query_json(question, context)
        except ValueError as exc:
            # ValueError 는 빈 응답 / 거부 / JSON 파싱 실패 → 재시도 가능
            last_error = f"LLM 쿼리 생성 오류: {exc}"
            logger.warning("[AI ERR] Step1 재시도 가능 오류 (시도 %d): %s", attempt, exc)
            context["previous_error"] = str(exc)
            continue
        except Exception as exc:
            # 네트워크 오류 등 복구 불가 → 즉시 중단
            last_error = f"LLM 쿼리 생성 오류: {exc}"
            logger.error("[AI ERR] Step1 복구 불가 오류 (시도 %d): %s", attempt, exc)
            break

        # ── [디버그] LLM 생성 직후 query_json 전체 출력 ──────
        logger.info(
            "[AI Step1] 시도=%d | LLM 생성 query_json:\n%s",
            attempt,
            json.dumps(raw_qj, ensure_ascii=False, indent=2),
        )

        # page_context 기본 필터 강제 적용
        raw_qj = _apply_page_context_defaults(
            raw_qj, page_context, selected_bar, sidebar_filters,
            context.get("filter_options", {}),
        )

        logger.info(
            "[AI Step1c] 시도=%d | context 적용 후 query_json:\n%s",
            attempt,
            json.dumps(raw_qj, ensure_ascii=False, indent=2),
        )

        # 검증
        is_valid, err_msg = validate_query_json(raw_qj)

        logger.info(
            "[AI Step1v] 시도=%d | 검증결과=%s | 에러=%s",
            attempt, is_valid, err_msg,
        )

        if is_valid:
            query_json = raw_qj
            break
        else:
            last_error = f"Query 검증 실패 (시도 {attempt}): {err_msg}"
            logger.warning("[AI ERR] %s", last_error)
            context["previous_error"] = err_msg

    if query_json is None:
        return {"ok": False, "error": last_error or "query JSON 생성에 실패했습니다."}

    # ── Step 2: DB 조회 ───────────────────────────────────────
    logger.info(
        "[AI Step2] DB 조회 시작 | table=%s | filters=%s | group_by=%s",
        query_json.get("table"),
        query_json.get("filters"),
        query_json.get("group_by"),
    )

    try:
        results = execute_query(query_json)
    except Exception as exc:
        logger.error(
            "[AI ERR] Step2 DB 조회 실패 | error=%s | query_json:\n%s",
            exc,
            json.dumps(query_json, ensure_ascii=False, indent=2),
        )
        return {"ok": False, "error": f"DB 조회 오류: {exc}"}

    logger.info("[AI Step3] DB 조회 완료 | 결과 %d건", len(results))

    # ── Step 3: 결과 요약 + 가공 테이블 ────────────────────────
    # summarize_results 는 {"answer": str, "table": list} 를 반환한다.
    # table 은 LLM 이 질문에 맞게 가공한 결과 (비교 컬럼, rank 등 추가).
    try:
        summary = llm.summarize_results(question, results, context)
    except Exception as exc:
        logger.error("[AI ERR] Step3 요약 실패: %s", exc)
        summary = {"answer": f"결과 요약 중 오류가 발생했습니다: {exc}", "table": []}

    answer        = summary.get("answer", "")
    summary_table = summary.get("table",  [])

    logger.info(
        "[AI Step3] 요약 완료 | answer_len=%d | summary_table_rows=%d",
        len(answer), len(summary_table),
    )

    return {
        "ok": True,
        "data": {
            "answer":          answer,
            "result_count":    len(results),
            # summary_table: LLM 가공 결과 (비교/피벗/rank 등) → 프론트 테이블로 표시
            "results_preview": summary_table if summary_table else results[:5],
            "query_json":      query_json,
        },
    }


def _apply_page_context_defaults(
    query_json:      dict,
    page_context:    str,
    selected_bar:    dict | None,
    sidebar_filters: dict,
    filter_options:  dict | None = None,
) -> dict:
    qj      = copy.deepcopy(query_json)

    # ── 테이블 강제 고정 ─────────────────────────────────────
    # AI Copilot 은 항상 Raw 이벤트 로그(TABLE_RAW) 를 분석 대상으로 한다.
    # report 테이블은 차트 렌더링 전용이며 act_time 컬럼이 없어 조회 불가.
    # LLM 이 report 테이블을 선택해도 여기서 무조건 TABLE_RAW 로 교정한다.
    if qj.get("table") != TABLE_RAW:
        logger.warning(
            "[AI 교정] table '%s' → '%s' 강제 변경 (AI Copilot 은 Raw 테이블 전용)",
            qj.get("table"), TABLE_RAW,
        )
        qj["table"] = TABLE_RAW

    filters = qj.setdefault("filters", {})

    defaults = PAGE_CONTEXT_DEFAULTS.get(page_context, {})
    for field, value in defaults.items():
        filters[field] = value

    # selected_bar 는 context 힌트로만 전달하고 act_time_range 를 강제 주입하지 않는다.
    # LLM 이 질문 내용("2월에", "지난주", "오늘" 등)에서 직접 기간을 판단해 필터를 구성한다.
    # Bar 선택 없이 자유 질문도 정상 동작하도록 강제 주입 제거.
    # (selected_bar 는 system prompt 의 "현재 선택 기간" 힌트로만 사용됨)

    # ── filter_options 기반 필드 교정 ────────────────────────
    # LLM 이 자연어를 잘못된 필드에 매핑한 경우 (예: "백호" → line 필터)
    # DB 실제 값 목록과 대조해 올바른 필드로 교정한다.
    _fix_filter_field_mapping(qj, filter_options or {})

    for field in ("line", "sdwt_prod", "eqp_id", "eqp_model"):
        if sidebar_filters.get(field) and field not in filters:
            filters[field] = sidebar_filters[field]

    return qj


def _fix_filter_field_mapping(qj: dict, filter_options: dict) -> None:
    """
    LLM 이 자연어 값을 잘못된 필드에 넣었을 때 올바른 필드로 교정한다.
    예) "백호" 가 line 필터로 들어왔는데 sdwt_prods 에 있으면 → sdwt_prod 로 이동

    필드별 DB 실제 값 목록:
        lines      → line 필드 허용값
        sdwt_prods → sdwt_prod 필드 허용값
        eqp_models → eqp_model 필드 허용값
        param_types → param_type 필드 허용값

    교정 규칙:
        1. filters 의 각 필드값이 해당 필드의 허용값에 없으면 "잘못 매핑" 으로 판단
        2. 다른 필드의 허용값에서 찾아서 자동 이동
        3. 어느 필드에도 없으면 해당 필터값 제거 (DB에 없는 값은 결과 0건이므로)
    """
    if not filter_options:
        return

    filters = qj.get("filters", {})
    if not filters:
        return

    # 필드명 → 허용값 set 매핑
    allowed_map = {
        "line":       set(filter_options.get("lines",       [])),
        "sdwt_prod":  set(filter_options.get("sdwt_prods",  [])),
        "eqp_model":  set(filter_options.get("eqp_models",  [])),
        "param_type": set(filter_options.get("param_types", [])),
    }

    correctable_fields = list(allowed_map.keys())
    to_add    = {}
    to_remove = []

    for field in correctable_fields:
        if field not in filters:
            continue
        values = filters[field]
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue

        valid_vals   = [v for v in values if v in allowed_map[field]]
        invalid_vals = [v for v in values if v not in allowed_map[field]]

        if not invalid_vals:
            continue  # 모두 유효 → 교정 불필요

        # invalid_vals 를 다른 필드에서 찾기
        for inv_val in invalid_vals:
            moved = False
            for other_field, other_allowed in allowed_map.items():
                if other_field == field:
                    continue
                if inv_val in other_allowed:
                    # 올바른 필드로 이동
                    to_add.setdefault(other_field, []).append(inv_val)
                    logger.warning(
                        "[AI 필터 교정] '%s' 값 '%s' → 필드 '%s' 로 이동",
                        field, inv_val, other_field,
                    )
                    moved = True
                    break
            if not moved:
                logger.warning(
                    "[AI 필터 교정] '%s' 값 '%s' → DB에 없는 값, 필터에서 제거",
                    field, inv_val,
                )

        # 해당 필드에는 유효한 값만 남기거나, 없으면 필터 제거
        if valid_vals:
            filters[field] = valid_vals
        else:
            to_remove.append(field)

    for field in to_remove:
        filters.pop(field, None)

    for field, vals in to_add.items():
        existing = filters.get(field, [])
        if isinstance(existing, str):
            existing = [existing]
        filters[field] = list(set(existing + vals))

    qj["filters"] = filters