"""
stoploss_ai/services/ai_service.py

LLM 공유: spotfire_ai.services.llm_interface.get_llm_client() 재사용
테이블: eqp_loss_tpm (상세 loss 이벤트)
"""
from stoploss_ai.models import TABLE_EQP_LOSS, TABLE_STOPLOSS_REPORT

PAGE_CONTEXT_DEFAULTS = {
    "stoploss": {},
}
VALID_PAGE_CONTEXTS = frozenset(PAGE_CONTEXT_DEFAULTS.keys())
MAX_RETRY = 2


def ask_ai(question: str, page_context: str, selected_bar, sidebar_filters: dict, filter_options=None):
    """
    LLM 에 질문을 보내고 결과를 반환한다.

    반환: {"ok": True, "data": {...}} 또는 {"ok": False, "error": "..."}
    """
    from spotfire_ai.services.llm_interface import get_llm_client
    from stoploss_ai.services.json_validator import validate_stoploss_query_json
    from stoploss_ai.services.query_builder import execute_stoploss_query
    import logging
    logger = logging.getLogger(__name__)

    if page_context not in VALID_PAGE_CONTEXTS:
        page_context = "stoploss"

    context = {
        "page_context":    page_context,
        "selected_bar":    selected_bar    or {},
        "sidebar_filters": sidebar_filters or {},
        "filter_options":  filter_options  or {},
        # stoploss 전용 스키마 힌트
        "schema_hint": f"""
테이블: {TABLE_EQP_LOSS} (설비 loss 이벤트 로그)
컬럼: yyyymmdd, act_time, line, sdwt_prod, eqp_id, unit_id, eqp_model, param_type, param_name, loss_time(분), lot_id
- param_type: MCC(모터 컨트롤), ERD(긴급 정지), SPC(통계적 공정 관리) 등
- loss_time: 설비 정지 시간(분)
- sum(loss_time)으로 정지로스 시간 집계

테이블: {TABLE_STOPLOSS_REPORT} (레포트 집계 테이블)
컬럼: yyyy, flag, flagdate, line, sdwt_prod, eqp_id, eqp_model, plan_time, stoploss, pm, qual, bm, rank
- plan_time: 계획 가동 시간(분)
- stoploss: 총 정지로스(분), pm+qual+bm 등의 합
- 정지율 = loss컬럼 / plan_time * 100
""",
    }

    llm = get_llm_client()
    query_json = None
    last_error = ""

    for attempt in range(1, MAX_RETRY + 1):
        try:
            raw_qj = llm.generate_query_json(question, context)
        except ValueError as exc:
            last_error = str(exc)
            context["previous_error"] = str(exc)
            continue
        except Exception as exc:
            last_error = str(exc)
            break

        # stoploss 테이블 강제 적용
        if raw_qj.get("table") not in (TABLE_EQP_LOSS, TABLE_STOPLOSS_REPORT):
            raw_qj["table"] = TABLE_EQP_LOSS

        is_valid, err_msg = validate_stoploss_query_json(raw_qj)
        if is_valid:
            query_json = raw_qj
            break
        else:
            last_error = err_msg
            context["previous_error"] = err_msg

    if query_json is None:
        return {"ok": False, "error": last_error or "query JSON 생성 실패"}

    try:
        results = execute_stoploss_query(query_json)
    except Exception as exc:
        return {"ok": False, "error": f"DB 조회 오류: {exc}"}

    try:
        summary = llm.summarize_results(question, results, context)
    except Exception as exc:
        summary = {"answer": f"요약 오류: {exc}", "table": []}

    return {
        "ok": True,
        "data": {
            "answer":          summary.get("answer", ""),
            "result_count":    len(results),
            "results_preview": summary.get("table", []) or results[:5],
            "query_json":      query_json,
        },
    }
