"""
services/llm_interface.py

역할:
- LLM 호출 추상 인터페이스 (BaseLLMClient)
- Mock 구현체 (MockLLMClient) — 개발/테스트 환경에서 API 키 없이 전체 flow 검증
- OpenAI / Anthropic 실제 구현체 플레이스홀더 (주석 해제로 활성화)
- get_llm_client() 팩토리 함수 — settings.LLM_BACKEND 로 분기

LLM 교체 방법:
  settings.py 에 아래 항목 추가 후 해당 클라이언트 클래스 주석 해제
    LLM_BACKEND  = "openai"          # "mock" | "openai" | "anthropic"
    LLM_API_KEY  = "sk-..."          # 또는 환경변수 OPENAI_API_KEY / ANTHROPIC_API_KEY
    LLM_MODEL    = "gpt-4o-mini"     # 사용할 모델명
"""

import os
from abc import ABC, abstractmethod

from django.conf import settings


# ─────────────────────────────────────────────────────────────────
# 추상 인터페이스
# ─────────────────────────────────────────────────────────────────
class BaseLLMClient(ABC):
    """
    LLM 클라이언트 공통 인터페이스.

    모든 구현체는 두 메서드를 반드시 구현한다:
      generate_query_json  : 질문 → DB 조회용 query JSON dict 생성
      summarize_results    : DB 결과 list → 한국어 자연어 답변 생성

    query JSON 스키마 (json_validator.py 의 allowlist 와 일치해야 함):
    {
        "table": "spotfire_raw",
        "filters": {
            "param_type": ["interlock"],
            "act_time_range": {"flag": "M", "yyyy": "2024", "flagdate": "M01"}
        },
        "group_by": ["eqp_id"],
        "aggregations": [
            {"field": "value", "func": "avg",   "alias": "avg_value"},
            {"field": "pk",    "func": "count",  "alias": "cnt"}
        ],
        "order_by": [{"field": "cnt", "direction": "desc"}],
        "limit": 10
    }
    """

    @abstractmethod
    def generate_query_json(self, question: str, context: dict) -> dict:
        """
        파라미터:
            question : 사용자의 자연어 질문
            context  : {
                "page_context"   : "interlock" | "stoploss" | "down_history",
                "selected_bar"   : {"flag", "yyyy", "flagdate"} or None,
                "sidebar_filters": {"line": [...], ...}
            }
        반환:
            query JSON dict (위 스키마 참조)
        """
        ...

    @abstractmethod
    def summarize_results(self, question: str, results: list, context: dict) -> str:
        """
        파라미터:
            question : 사용자의 원래 질문
            results  : DB 조회 결과 (list of dict)
            context  : generate_query_json 과 동일
        반환:
            사용자에게 보여줄 한국어 자연어 답변 문자열
        """
        ...


# ─────────────────────────────────────────────────────────────────
# Mock 구현체 (개발 / 테스트용)
# ─────────────────────────────────────────────────────────────────
class MockLLMClient(BaseLLMClient):
    """
    규칙 기반 Mock LLM. API 키 없이 전체 AI Copilot flow 를 검증한다.

    settings.py 에서 LLM_BACKEND = "mock" (기본값) 일 때 활성화된다.

    지원하는 질문 패턴:
        "top" / "상위" / "많은"   → 설비별 발생 건수 상위 Top-N
        "평균" / "average"        → 설비별 평균값 집계
        "라인" / "line별"         → 라인별 집계
        그 외                    → 전체 raw data 최신 50건
    """

    def generate_query_json(self, question: str, context: dict) -> dict:
        q      = question.lower()  # 소문자 변환 (패턴 매칭용)
        pctx   = context.get("page_context", "")       # 현재 page_context
        sbar   = context.get("selected_bar")  or {}    # 선택된 bar
        sfilts = context.get("sidebar_filters") or {}  # sidebar 필터

        # ── 기본 필터 구성 ──────────────────────────────────────
        # ai_service 의 _apply_page_context_defaults 가 나중에 강제 적용하지만,
        # Mock 에서도 미리 넣어두면 결과가 더 자연스럽다.
        base_filters: dict = {}
        if pctx in ("interlock", "stoploss"):
            base_filters["param_type"] = [pctx]
        for field in ("line", "sdwt_prod", "eqp_id", "eqp_model"):
            if sfilts.get(field):
                base_filters[field] = sfilts[field]
        if sbar.get("flag") and sbar.get("yyyy") and sbar.get("flagdate"):
            base_filters["act_time_range"] = {
                "flag":     sbar["flag"],
                "yyyy":     sbar["yyyy"],
                "flagdate": sbar["flagdate"],
            }

        # ── 질문 패턴 분기 ──────────────────────────────────────
        # ① Top 패턴
        if any(kw in q for kw in ["top", "상위", "많은", "worst", "highest"]):
            return {
                "table":    "spotfire_raw",
                "filters":  base_filters,
                "group_by": ["eqp_id"],
                "aggregations": [
                    {"field": "pk",    "func": "count", "alias": "cnt"},
                    {"field": "value", "func": "avg",   "alias": "avg_value"},
                ],
                "order_by": [{"field": "cnt", "direction": "desc"}],
                "limit": 10,
            }

        # ② 평균 패턴
        if any(kw in q for kw in ["평균", "average", "avg", "mean"]):
            return {
                "table":    "spotfire_raw",
                "filters":  base_filters,
                "group_by": ["eqp_id", "param_type"],
                "aggregations": [
                    {"field": "value", "func": "avg", "alias": "avg_value"},
                    {"field": "value", "func": "max", "alias": "max_value"},
                    {"field": "pk",    "func": "count", "alias": "cnt"},
                ],
                "order_by": [{"field": "avg_value", "direction": "desc"}],
                "limit": 20,
            }

        # ③ 라인별 패턴
        if any(kw in q for kw in ["라인", "line", "by line"]):
            return {
                "table":    "spotfire_raw",
                "filters":  base_filters,
                "group_by": ["line", "param_type"],
                "aggregations": [
                    {"field": "pk",    "func": "count", "alias": "cnt"},
                    {"field": "value", "func": "sum",   "alias": "sum_value"},
                ],
                "order_by": [{"field": "cnt", "direction": "desc"}],
                "limit": 20,
            }

        # ④ 기본: 전체 raw 최신 N건
        return {
            "table":        "spotfire_raw",
            "filters":      base_filters,
            "group_by":     [],
            "aggregations": [],
            "order_by":     [{"field": "act_time", "direction": "desc"}],
            "limit":        50,
        }

    def summarize_results(self, question: str, results: list, context: dict) -> str:
        """규칙 기반 한국어 요약 (실제 LLM 없이 템플릿으로 생성)"""
        if not results:
            return "📭 조회된 데이터가 없습니다.\n필터 조건이나 선택 기간을 확인해 주세요."

        count = len(results)
        first = results[0]

        # 집계 결과 (cnt 컬럼이 있으면 집계 쿼리로 판단)
        if "cnt" in first:
            top_item = max(results, key=lambda r: r.get("cnt", 0))
            total    = sum(r.get("cnt", 0) for r in results)

            lines = [f"[Mock 답변] 총 {count}개 그룹 조회 완료"]
            lines.append(f"• 최다 발생: {_fmt_row(top_item)} (건수: {top_item.get('cnt', 0):,})")
            lines.append(f"• 전체 합산: {total:,}건")

            if "avg_value" in first:
                vals = [r["avg_value"] for r in results if r.get("avg_value") is not None]
                if vals:
                    lines.append(f"• 평균값 범위: {min(vals):.3f} ~ {max(vals):.3f}")
            return "\n".join(lines)

        # 원본 raw 결과
        lines = [f"[Mock 답변] 총 {count}건의 원본 데이터가 조회되었습니다."]
        if "act_time" in first:
            lines.append(f"• 최초 발생: {first.get('act_time', '-')}")
            lines.append(f"• 최근 발생: {results[-1].get('act_time', '-')}")
        if "eqp_id" in first:
            eqps = sorted({r.get("eqp_id", "") for r in results if r.get("eqp_id")})
            lines.append(f"• 관련 설비: {', '.join(eqps[:5])}{' 외' if len(eqps)>5 else ''}")
        return "\n".join(lines)


def _fmt_row(row: dict) -> str:
    """dict row 를 'key=val, ...' 형태의 문자열로 변환"""
    return ", ".join(f"{k}={v}" for k, v in row.items() if v is not None)


# ─────────────────────────────────────────────────────────────────
# OpenAI 구현체 플레이스홀더
# ─────────────────────────────────────────────────────────────────
class OpenAILLMClient(BaseLLMClient):
    """
    OpenAI GPT 기반 실제 LLM 클라이언트.

    활성화 방법:
      1. pip install openai
      2. settings.py 에 다음 추가:
           LLM_BACKEND = "openai"
           LLM_API_KEY = "sk-..."     # 또는 환경변수 OPENAI_API_KEY
           LLM_MODEL   = "gpt-4o-mini"
      3. 아래 __init__ / generate_query_json / summarize_results 주석 해제
    """

    def __init__(self):
        # import openai
        # api_key = getattr(settings, "LLM_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
        # self.client = openai.OpenAI(api_key=api_key)
        # self.model  = getattr(settings, "LLM_MODEL", "gpt-4o-mini")
        raise NotImplementedError(
            "OpenAI 클라이언트: settings.py 의 주석을 해제하고 LLM_API_KEY 를 설정하세요."
        )

    def generate_query_json(self, question: str, context: dict) -> dict:
        # import json as _json
        # system_prompt = _build_system_prompt(context)
        # resp = self.client.chat.completions.create(
        #     model=self.model,
        #     messages=[
        #         {"role": "system", "content": system_prompt},
        #         {"role": "user",   "content": question},
        #     ],
        #     response_format={"type": "json_object"},
        # )
        # return _json.loads(resp.choices[0].message.content)
        raise NotImplementedError

    def summarize_results(self, question: str, results: list, context: dict) -> str:
        # result_text = _json.dumps(results[:20], ensure_ascii=False, indent=2)
        # prompt = f"질문: {question}\n\n조회 결과:\n{result_text}\n\n위 결과를 한국어로 요약해 주세요."
        # resp = self.client.chat.completions.create(
        #     model=self.model,
        #     messages=[{"role": "user", "content": prompt}],
        # )
        # return resp.choices[0].message.content
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────
# Anthropic Claude 구현체 플레이스홀더
# ─────────────────────────────────────────────────────────────────
class AnthropicLLMClient(BaseLLMClient):
    """
    Anthropic Claude 기반 실제 LLM 클라이언트.

    활성화 방법:
      1. pip install anthropic
      2. settings.py 에 다음 추가:
           LLM_BACKEND = "anthropic"
           LLM_API_KEY = "sk-ant-..."  # 또는 환경변수 ANTHROPIC_API_KEY
           LLM_MODEL   = "claude-3-5-sonnet-20241022"
      3. 아래 주석 해제
    """

    def __init__(self):
        # import anthropic
        # api_key = getattr(settings, "LLM_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
        # self.client = anthropic.Anthropic(api_key=api_key)
        # self.model  = getattr(settings, "LLM_MODEL", "claude-3-5-sonnet-20241022")
        raise NotImplementedError(
            "Anthropic 클라이언트: settings.py 의 주석을 해제하고 LLM_API_KEY 를 설정하세요."
        )

    def generate_query_json(self, question: str, context: dict) -> dict:
        # import json as _json
        # system_prompt = _build_system_prompt(context)
        # msg = self.client.messages.create(
        #     model=self.model,
        #     max_tokens=1024,
        #     system=system_prompt,
        #     messages=[{"role": "user", "content": question}],
        # )
        # return _json.loads(msg.content[0].text)
        raise NotImplementedError

    def summarize_results(self, question: str, results: list, context: dict) -> str:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────
# 팩토리 함수
# ─────────────────────────────────────────────────────────────────
def get_llm_client() -> BaseLLMClient:
    """
    settings.LLM_BACKEND 에 따라 LLM 클라이언트 인스턴스를 반환한다.

    settings.py 예시:
        LLM_BACKEND = "mock"       # 기본값 (개발/테스트)
        LLM_BACKEND = "openai"     # OpenAI GPT
        LLM_BACKEND = "anthropic"  # Anthropic Claude
    """
    backend = getattr(settings, "LLM_BACKEND", "mock")

    if backend == "openai":
        return OpenAILLMClient()
    if backend == "anthropic":
        return AnthropicLLMClient()
    # 기본값: mock
    return MockLLMClient()


# ─────────────────────────────────────────────────────────────────
# 실제 LLM 용 system prompt 빌더 (OpenAI/Anthropic 에서 호출)
# ─────────────────────────────────────────────────────────────────
def _build_system_prompt(context: dict) -> str:
    """
    LLM 에 전달할 system prompt 를 구성한다.
    DB 스키마, query JSON 형식, 제약 사항을 포함한다.
    실제 LLM 구현체의 generate_query_json 에서 호출한다.
    """
    pc   = context.get("page_context", "")
    sbar = context.get("selected_bar") or {}

    return f"""당신은 반도체 제조 설비 이상 현황 분석 AI 어시스턴트입니다.
현재 사용자는 [{pc}] 페이지를 보고 있습니다.

## 현재 선택 기간
flag={sbar.get('flag','-')}, yyyy={sbar.get('yyyy','-')}, flagdate={sbar.get('flagdate','-')}

## 사용 가능한 테이블

### spotfire_raw (원본 이벤트 데이터)
컬럼: act_time(datetime), yyyymmdd, line, sdwt_prod, eqp_id, eqp_model,
      param_type, item_id, test_id, value(float)

### spotfire_report (M/W/D 집계 데이터)
컬럼: yyyy, flag, flagdate, line, sdwt_prod, eqp_id, eqp_model,
      param_type, cnt(int), ratio(float), rank(int)

## 응답 형식 (반드시 아래 JSON 만 반환, 설명 텍스트 불가)
{{
    "table": "spotfire_raw",
    "filters": {{
        "param_type": ["interlock"],
        "act_time_range": {{"flag": "M", "yyyy": "2024", "flagdate": "M01"}}
    }},
    "group_by": ["eqp_id"],
    "aggregations": [
        {{"field": "value", "func": "avg",   "alias": "avg_value"}},
        {{"field": "pk",    "func": "count",  "alias": "cnt"}}
    ],
    "order_by": [{{"field": "cnt", "direction": "desc"}}],
    "limit": 10
}}

## 제약 사항
- table: spotfire_raw 또는 spotfire_report 만 허용
- aggregations.func: count, avg, sum, max, min 만 허용
- count 집계 시 field 는 반드시 "pk" 로 지정
- limit: 1 ~ 500
- 반드시 JSON 만 반환 (마크다운 코드블록 불가)""".strip()
