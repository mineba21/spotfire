"""
services/llm_interface.py

역할:
- LLM 호출 추상 인터페이스 (BaseLLMClient)
- Mock 구현체 (MockLLMClient) — 개발/테스트 환경에서 API 키 없이 전체 flow 검증
- OpenAI 실제 구현체 (OpenAILLMClient) — custom base_url + credential 헤더 방식
- get_llm_client() 팩토리 함수 — settings.LLM_BACKEND 로 분기

[Raw 테이블 집계 원칙]
  Raw 테이블은 인터락 발생 이벤트 로그이다.
  숫자 측정값(value) 은 없고, 행 수 자체가 발생 건수를 의미한다.
  따라서 집계는 반드시 count(pk) 만 사용한다.

  권장 group_by 계층:
    1단계: ["line"]
    2단계: ["line", "eqp_id"]
    3단계: ["line", "eqp_id", "param_type"]
    4단계: ["line", "eqp_id", "param_type", "param_name"]

[다중 DB 확장 방법]
  Step 1. models.py 에 새 모델 클래스 추가
  Step 2. json_validator.py 의 ALLOWED_TABLES / ALLOWED_*_FIELDS 에 추가
  Step 3. query_builder.py 의 execute_query() 테이블 분기에 elif 추가
  Step 4. 이 파일의 _build_system_prompt() 에 새 테이블 스키마 추가
  Step 5. MockLLMClient 의 패턴 분기에 새 테이블 관련 키워드 추가

  예) 설비 가동률 DB, 정비 기록 DB 추가 시:
      - LLM 이 "EQP-001 의 가동률은?" → eqp_utilization 테이블 조회
      - LLM 이 "지난달 PM 횟수는?" → maintenance_record 테이블 조회
      - system prompt 에 두 테이블 스키마를 추가하면 LLM 이 자동으로 적절한 테이블을 선택
"""

import os
import uuid
import json as _json
import logging
from abc import ABC, abstractmethod

from django.conf import settings
from interlock_ai.models import TABLE_RAW, TABLE_REPORT

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# 추상 인터페이스
# ─────────────────────────────────────────────────────────────────
class BaseLLMClient(ABC):
    @abstractmethod
    def generate_query_json(self, question: str, context: dict) -> dict:
        ...

    @abstractmethod
    def summarize_results(self, question: str, results: list, context: dict) -> dict:
        ...


# ─────────────────────────────────────────────────────────────────
# OpenAI 구현체 (custom base_url + credential 헤더)
# ─────────────────────────────────────────────────────────────────
class OpenAILLMClient(BaseLLMClient):

    def __init__(self):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai 패키지가 필요합니다: pip install openai")

        api_base_url   = getattr(settings, "LLM_API_BASE_URL",   os.environ.get("LLM_API_BASE_URL",   ""))
        credential_key = getattr(settings, "LLM_CREDENTIAL_KEY", os.environ.get("LLM_CREDENTIAL_KEY", ""))
        user_id        = getattr(settings, "LLM_USER_ID",         os.environ.get("LLM_USER_ID",         ""))

        if not api_base_url:
            raise ValueError("LLM_API_BASE_URL 이 설정되지 않았습니다.")
        if not credential_key:
            raise ValueError("LLM_CREDENTIAL_KEY 가 설정되지 않았습니다.")

        self.model           = getattr(settings, "LLM_MODEL", "gpt-oss-120b")
        self.user_id         = user_id
        self._OpenAI         = OpenAI
        self._api_base_url   = api_base_url
        self._credential_key = credential_key

    def _build_client(self):
        """호출마다 새 UUID 를 헤더에 실어 클라이언트를 반환한다."""
        return self._OpenAI(
            base_url=self._api_base_url,
            api_key="not-used",
            default_headers={
                "x-dep-ticket":      self._credential_key,
                "Send-System-Name":  "playground",
                "User-Id":           self.user_id,
                "User-Type":         "AD_ID",
                "Prompt-Msg-Id":     str(uuid.uuid4()),
                "Completion-Msg-Id": str(uuid.uuid4()),
            },
        )

    def generate_query_json(self, question: str, context: dict) -> dict:
        system_prompt = _build_system_prompt(context)
        client        = self._build_client()

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": question},
            ],
            temperature=0,
            max_tokens=4096,   # JSON 출력이 잘리지 않도록 충분히 확보
        )

        # ── 응답 전체 디버그 로깅 ────────────────────────────
        choice  = response.choices[0]
        message = choice.message

        logger.debug(
            "LLM 응답 전체 | finish_reason=%s | content=%r | refusal=%r",
            choice.finish_reason,
            message.content,
            getattr(message, "refusal", None),
        )

        # finish_reason 별 처리
        finish_reason = choice.finish_reason
        if finish_reason == "content_filter":
            raise ValueError("LLM 이 콘텐츠 정책으로 응답을 거부했습니다. 질문을 바꿔서 다시 시도해 주세요.")
        if finish_reason == "length":
            logger.warning("LLM 응답이 max_tokens 에 잘렸습니다. (finish_reason=length)")
        if finish_reason not in ("stop", "length"):
            logger.warning("예상치 못한 finish_reason: %s", finish_reason)

        raw_text = message.content or ""

        if not raw_text.strip():
            # content 가 비어있을 때 refusal 메시지가 있으면 그걸 에러로 올린다
            refusal = getattr(message, "refusal", None)
            if refusal:
                raise ValueError(f"LLM 이 응답을 거부했습니다: {refusal}")
            raise ValueError(
                f"LLM 이 빈 응답을 반환했습니다. (finish_reason={finish_reason}) "
                f"질문이 너무 복잡하거나 모델이 JSON 생성을 거부했을 수 있습니다."
            )

        # 마크다운 코드블록 제거
        clean = raw_text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
            clean = clean.strip()

        try:
            query_json = _json.loads(clean)
        except _json.JSONDecodeError as e:
            # finish_reason=length 이면 JSON 이 중간에 잘린 것 → 복구 불가, 재시도 유도
            if finish_reason == "length":
                logger.warning(
                    "JSON 이 max_tokens 에 잘려 파싱 불가 → 재시도합니다.\nraw: %s",
                    raw_text[:200],
                )
                raise ValueError(
                    "LLM 응답이 토큰 제한으로 잘렸습니다. "
                    "질문을 더 단순하게 바꾸거나 기간을 좁혀서 다시 시도해 주세요."
                ) from e
            logger.error(
                "generate_query_json JSON 파싱 실패: %s\n"
                "finish_reason=%s\n"
                "raw(전체): %s",
                e, finish_reason, raw_text,
            )
            raise ValueError(f"LLM 응답을 JSON 으로 파싱할 수 없습니다: {e}") from e

        # ── 테이블명 자동 교정 ───────────────────────────────────────
        # LLM 이 학습 데이터 기반으로 구 테이블명(spotfire_raw / spotfire_report)을
        # 출력하더라도 실제 환경변수 테이블명으로 자동 교정한다.
        TABLE_NAME_ALIASES = {
            "spotfire_raw":    TABLE_RAW,
            "spotfire_report": TABLE_REPORT,
            TABLE_RAW:         TABLE_RAW,
            TABLE_REPORT:      TABLE_REPORT,
        }
        llm_table = query_json.get("table", "")
        if llm_table in TABLE_NAME_ALIASES:
            corrected = TABLE_NAME_ALIASES[llm_table]
            if corrected != llm_table:
                logger.warning("테이블명 자동 교정: '%s' → '%s'", llm_table, corrected)
            query_json["table"] = corrected

        return query_json

    def summarize_results(self, question: str, results: list, context: dict) -> dict:
        """
        DB 조회 결과를 LLM 에게 넘겨 두 가지를 동시에 받는다:
          1. answer : 한국어 자연어 요약 (bullet point)
          2. table  : 질문에 맞게 가공된 결과 테이블 (LLM 이 컬럼을 추가/계산)
                      예) 2월/3월 비교 → cnt_feb, cnt_mar, increase 컬럼 추가

        LLM 은 반드시 아래 JSON 형식으로만 응답한다:
        {
            "answer": "한국어 요약...",
            "table": [
                {"eqp_id": "EQP-001", "cnt_feb": 10, "cnt_mar": 25, "increase": 15},
                ...
            ]
        }
        """
        # 결과가 많으면 상위 100건만 전달 (토큰 절약)
        preview     = results[:100]
        result_text = _json.dumps(preview, ensure_ascii=False, indent=2)
        total_count = len(results)

        prompt = f"""당신은 반도체 설비 이상 현황 분석 전문가입니다.
아래 DB 조회 결과를 바탕으로 사용자 질문에 답하세요.

사용자 질문: {question}

DB 조회 결과 (전체 {total_count}건{", 상위 100건만 표시" if total_count > 100 else ""}):
{result_text}

## 응답 규칙
1. 반드시 아래 JSON 형식으로만 응답한다. 마크다운 코드블록(```) 절대 금지.
2. answer: 한국어 요약. bullet point. 핵심 수치 포함. 간결하게.
3. table: 질문 의도에 맞게 자유롭게 컬럼을 구성한다.
   - 컬럼명은 영문 snake_case
   - 비교/증감 질문 → 기간별 cnt, 증가량, 증가율 등 계산해서 추가
   - Top N 질문 → rank 컬럼 추가, N건만 포함
   - 단순 조회 → 원본 컬럼 그대로 사용 가능
   - 의미 있는 컬럼만 포함 (불필요한 컬럼 제거)
   - table 이 불필요하면 빈 배열 []

{{"answer": "...", "table": [...]}}"""

        client   = self._build_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=8192,
        )

        choice      = response.choices[0]
        raw         = (choice.message.content or "").strip()
        fin_reason  = choice.finish_reason

        if fin_reason == "length":
            logger.warning("summarize_results max_tokens 초과로 잘림")

        # 마크다운 코드블록 제거
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            parsed = _json.loads(raw)
            return {
                "answer": parsed.get("answer", ""),
                "table":  parsed.get("table",  []),
            }
        except _json.JSONDecodeError:
            # JSON 파싱 실패 시: answer 는 텍스트로, table 은 원본 결과 상위 20건
            logger.warning(
                "summarize_results JSON 파싱 실패 (finish_reason=%s), fallback 처리\nraw: %s",
                fin_reason, raw[:300],
            )
            # raw 에서 answer 부분만 추출 시도
            answer_text = raw
            if '"answer"' in raw:
                try:
                    # answer 값만 파싱
                    idx = raw.index('"answer"')
                    snippet = raw[idx:].split('","table"')[0]
                    answer_text = snippet.split(':', 1)[1].strip().strip('"')
                except Exception:
                    pass
            return {"answer": answer_text, "table": results[:20]}


# ─────────────────────────────────────────────────────────────────
# Mock 구현체
# ─────────────────────────────────────────────────────────────────
class MockLLMClient(BaseLLMClient):
    """
    규칙 기반 Mock LLM.

    [Raw 집계 원칙 반영]
      - value 기반 집계 패턴 제거
      - 모든 집계는 count(pk) → alias "cnt"
      - group_by 계층: line → line+eqp_id → line+eqp_id+param_type
                      → line+eqp_id+param_type+param_name

    지원 질문 패턴:
        "param" / "파라미터"     → LINE+EQP_ID+PARAM_TYPE+PARAM_NAME 4단계 집계
        "top" / "상위" / "설비" → LINE+EQP_ID 2단계 Top-N
        "라인" / "line"          → LINE 1단계
        "유형" / "type"          → LINE+EQP_ID+PARAM_TYPE 3단계
        그 외                   → LINE+EQP_ID 2단계 기본
    """

    def generate_query_json(self, question: str, context: dict) -> dict:
        q      = question.lower()
        pctx   = context.get("page_context", "")
        sbar   = context.get("selected_bar")  or {}
        sfilts = context.get("sidebar_filters") or {}

        # 기본 필터
        # param_type 은 인터락 종류 분류값(A/E/T/M 등)이므로 page_context 로 강제하지 않는다.
        # sidebar_filters 에 param_type 이 있으면 그것을 그대로 사용한다.
        base_filters: dict = {}
        for field in ("line", "sdwt_prod", "eqp_id", "eqp_model", "param_type"):
            if sfilts.get(field):
                base_filters[field] = sfilts[field]
        if sbar.get("flag") and sbar.get("yyyy") and sbar.get("flagdate"):
            base_filters["act_time_range"] = {
                "flag":     sbar["flag"],
                "yyyy":     sbar["yyyy"],
                "flagdate": sbar["flagdate"],
            }

        # Raw 테이블은 항상 count(pk)
        cnt_agg = [{"field": "pk", "func": "count", "alias": "cnt"}]

        # ① 연도 비교 패턴
        if any(kw in q for kw in ["년도", "연간", "연도별", "년 대비", "년대비", "올해", "작년", "전년"]):
            return {
                "table":        TABLE_RAW,
                "filters":      {**base_filters, "yyyy_filter": ["2025", "2026"]},
                "group_by":     ["yyyymmdd", "line", "eqp_id"],
                "aggregations": cnt_agg,
                "order_by":     [{"field": "cnt", "direction": "desc"}],
                "limit":        10000,
            }

        # ② 4단계: PARAM_NAME 까지
        if any(kw in q for kw in ["param", "파라미터", "param_name", "파라미터명"]):
            return {
                "table":        TABLE_RAW,
                "filters":      base_filters,
                "group_by":     ["line", "eqp_id", "param_type", "param_name"],
                "aggregations": cnt_agg,
                "order_by":     [{"field": "cnt", "direction": "desc"}],
                "limit":        10000,
            }

        # ② Top-N 설비: LINE + EQP_ID
        if any(kw in q for kw in ["top", "상위", "많은", "worst", "highest", "설비"]):
            return {
                "table":        TABLE_RAW,
                "filters":      base_filters,
                "group_by":     ["line", "eqp_id"],
                "aggregations": cnt_agg,
                "order_by":     [{"field": "cnt", "direction": "desc"}],
                "limit":        10000,
            }

        # ③ 라인별: LINE 1단계
        if any(kw in q for kw in ["라인", "line", "by line", "라인별"]):
            return {
                "table":        TABLE_RAW,
                "filters":      base_filters,
                "group_by":     ["line"],
                "aggregations": cnt_agg,
                "order_by":     [{"field": "cnt", "direction": "desc"}],
                "limit":        10000,
            }

        # ④ 유형별: LINE + EQP_ID + PARAM_TYPE 3단계
        if any(kw in q for kw in ["param_type", "유형", "타입", "type"]):
            return {
                "table":        TABLE_RAW,
                "filters":      base_filters,
                "group_by":     ["line", "eqp_id", "param_type"],
                "aggregations": cnt_agg,
                "order_by":     [{"field": "cnt", "direction": "desc"}],
                "limit":        10000,
            }

        # ⑤ 기본: LINE + EQP_ID 2단계
        return {
            "table":        TABLE_RAW,
            "filters":      base_filters,
            "group_by":     ["line", "eqp_id"],
            "aggregations": cnt_agg,
            "order_by":     [{"field": "cnt", "direction": "desc"}],
            "limit":        10000,
        }

    def summarize_results(self, question: str, results: list, context: dict) -> dict:
        """
        Mock 요약: answer(텍스트) + table(가공 데이터) 반환
        실제 LLM 없이 규칙 기반으로 table 컬럼을 구성한다.
        """
        if not results:
            return {
                "answer": "📭 조회된 데이터가 없습니다.\n필터 조건이나 선택 기간을 확인해 주세요.",
                "table":  [],
            }

        count = len(results)
        first = results[0]
        q     = (context.get("question") or "").lower()

        if "cnt" in first:
            top_item  = max(results, key=lambda r: r.get("cnt", 0))
            total_cnt = sum(r.get("cnt", 0) for r in results)

            keys = set(first.keys()) - {"cnt"}
            if "param_name" in keys:
                level = "LINE+EQP_ID+PARAM_TYPE+PARAM_NAME"
            elif "param_type" in keys:
                level = "LINE+EQP_ID+PARAM_TYPE"
            elif "eqp_id" in keys:
                level = "LINE+EQP_ID"
            else:
                level = "LINE"

            answer_lines = [f"[Mock] 집계 기준: {level} / 총 {count}개 그룹"]
            answer_lines.append(f"• 최다 발생: {_fmt_row(top_item, exclude={'cnt'})} → {top_item.get('cnt', 0):,}건")
            answer_lines.append(f"• 전체 합산: {total_cnt:,}건")

            # ── 월 비교 질문 → 피벗 테이블 생성 ──────────────
            # yyyymmdd 컬럼이 있고 "대비/증가/비교" 키워드 있으면 월별 피벗
            if "yyyymmdd" in first and any(kw in q for kw in ["대비", "증가", "비교", "변화"]):
                table = _mock_pivot_by_month(results)
                if table:
                    answer_lines.append(f"• 증가량 기준 Top {min(5, len(table))}개 설비를 표시합니다.")
            else:
                # 기본: cnt 내림차순 Top 20, rank 컬럼 추가
                sorted_rows = sorted(results, key=lambda r: r.get("cnt", 0), reverse=True)[:20]
                table = [{"rank": i+1, **r} for i, r in enumerate(sorted_rows)]

            return {"answer": "\n".join(answer_lines), "table": table}

        # aggregation 없는 raw 목록
        answer_lines = [f"[Mock] 총 {count}건의 이벤트 로그가 조회되었습니다."]
        if "act_time" in first:
            answer_lines.append(f"• 최초 발생: {first.get('act_time', '-')}")
            answer_lines.append(f"• 최근 발생: {results[-1].get('act_time', '-')}")
        return {"answer": "\n".join(answer_lines), "table": results[:20]}


def _mock_pivot_by_month(results: list) -> list:
    """
    yyyymmdd + eqp_id 기준으로 월별 cnt 를 피벗해 증가량을 계산한다.
    예) [{"eqp_id": "EQP-001", "yyyymmdd": "20260201", "cnt": 10}, ...]
     →  [{"eqp_id": "EQP-001", "cnt_prev": 10, "cnt_curr": 25, "increase": 15}, ...]
    """
    from collections import defaultdict

    # 월 추출: yyyymmdd → "YYYYMM"
    months = sorted({r["yyyymmdd"][:6] for r in results if r.get("yyyymmdd")})
    if len(months) < 2:
        return []

    prev_month, curr_month = months[0], months[-1]

    # eqp_id 기준 월별 cnt 집계
    pivot = defaultdict(lambda: {"cnt_prev": 0, "cnt_curr": 0})
    label_cols = [c for c in results[0].keys() if c not in ("yyyymmdd", "cnt")]

    for row in results:
        key = row.get("eqp_id", row.get("line", "UNKNOWN"))
        m   = row.get("yyyymmdd", "")[:6]
        if m == prev_month:
            pivot[key]["cnt_prev"] += row.get("cnt", 0)
        elif m == curr_month:
            pivot[key]["cnt_curr"] += row.get("cnt", 0)
        # label 컬럼 값 저장
        for c in label_cols:
            if c not in pivot[key]:
                pivot[key][c] = row.get(c, "")

    table = []
    for key, val in pivot.items():
        increase = val["cnt_curr"] - val["cnt_prev"]
        table.append({
            "eqp_id":   key,
            **{c: val.get(c, "") for c in label_cols if c != "eqp_id"},
            f"cnt_{prev_month}": val["cnt_prev"],
            f"cnt_{curr_month}": val["cnt_curr"],
            "increase":          increase,
        })

    # 증가량 내림차순, Top 5
    table = sorted(table, key=lambda r: r["increase"], reverse=True)[:5]
    for i, row in enumerate(table):
        row["rank"] = i + 1

    return table


def _fmt_row(row: dict, exclude: set = None) -> str:
    exclude = exclude or set()
    return ", ".join(f"{k}={v}" for k, v in row.items() if k not in exclude and v is not None)


# ─────────────────────────────────────────────────────────────────
# Anthropic 플레이스홀더
# ─────────────────────────────────────────────────────────────────
class AnthropicLLMClient(BaseLLMClient):
    def __init__(self):
        raise NotImplementedError("Anthropic 클라이언트: settings.py 설정 후 주석 해제하세요.")
    def generate_query_json(self, question: str, context: dict) -> dict:
        raise NotImplementedError
    def summarize_results(self, question: str, results: list, context: dict) -> dict:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────
# 팩토리 함수
# ─────────────────────────────────────────────────────────────────
def get_llm_client() -> BaseLLMClient:
    backend = getattr(settings, "LLM_BACKEND", "mock")
    if backend == "openai":
        return OpenAILLMClient()
    if backend == "anthropic":
        return AnthropicLLMClient()
    return MockLLMClient()


# ─────────────────────────────────────────────────────────────────
# System Prompt 빌더
# ─────────────────────────────────────────────────────────────────
def _build_system_prompt(context: dict) -> str:
    """
    LLM 에 전달할 system prompt.

    [다중 DB 확장 시 — 새 테이블 추가 방법]
      아래 "## 사용 가능한 테이블" 섹션에 새 테이블 스키마 블록을 추가한다.
      LLM 이 질문을 보고 적절한 테이블을 자동으로 선택하게 된다.

      추가 예시:
        ### eqp_utilization (설비 가동률)
        컬럼: yyyymmdd, line, eqp_id, uptime_min(int), downtime_min(int), util_rate(float)
        집계 가능 func: count, avg, sum, max, min
        용도: "EQP-001 가동률", "라인별 평균 가동률" 질문 시 사용

        ### maintenance_record (설비 정비 기록)
        컬럼: maint_date, line, eqp_id, maint_type(PM/CM/EM), downtime_min(int), engineer, memo
        집계 가능 func: count, sum (downtime_min 합산 등)
        용도: "지난달 PM 횟수", "정비 다운타임 합계" 질문 시 사용

      ※ 새 테이블을 추가하면 json_validator.py 의 ALLOWED_TABLES 와
         query_builder.py 의 execute_query() 분기도 함께 업데이트 필요
    """
    pc             = context.get("page_context", "")
    sbar           = context.get("selected_bar") or {}
    filter_options = context.get("filter_options") or {}

    # 필드별 허용값 목록을 prompt 에 삽입
    def _fmt_list(items, max_n=30):
        if not items:
            return "(데이터 없음)"
        shown = items[:max_n]
        suffix = f" 외 {len(items)-max_n}개" if len(items) > max_n else ""
        return ", ".join(shown) + suffix

    filter_options_prompt = (
        f"- line 허용값: {_fmt_list(filter_options.get('lines', []))}\n"
        f"- sdwt_prod 허용값: {_fmt_list(filter_options.get('sdwt_prods', []))}\n"
        f"- eqp_model 허용값: {_fmt_list(filter_options.get('eqp_models', []))}\n"
        f"- param_type 허용값: {_fmt_list(filter_options.get('param_types', []))}"
    )

    # 현재 날짜를 prompt 에 주입 (LLM 이 연도/월을 추측하지 않도록)
    import datetime as _dt
    today     = _dt.date.today()
    cur_yyyy  = today.strftime("%Y")
    cur_mm    = today.strftime("%m")
    cur_yymm  = today.strftime("%Y%m")

    return f"""당신은 반도체 제조 설비 이상(인터락) 현황 분석 AI 어시스턴트입니다.
현재 사용자는 [{pc}] 페이지를 보고 있습니다.

## 오늘 날짜 (매우 중요 — 연도/월 추측 금지)
- 오늘: {today.strftime("%Y-%m-%d")} (현재 연도={cur_yyyy}, 현재 월={cur_mm})
- 질문에 연도가 없으면 반드시 현재 연도({cur_yyyy})를 사용한다. 2024 등 다른 연도 추측 절대 금지.
- "이번 달" → {cur_yymm}, "지난달" → {(today.replace(day=1) - _dt.timedelta(days=1)).strftime("%Y%m")}

## 현재 화면 컨텍스트 (참고용)
- 선택된 Bar: flag={sbar.get('flag', '-')}, yyyy={sbar.get('yyyy', '-')}, flagdate={sbar.get('flagdate', '-')}
- 이 값은 참고용 힌트이며, 질문에 기간이 명시되어 있으면 질문 내용을 우선한다.
- Bar 선택 없이 질문한 경우에도 질문 내용만으로 기간 필터를 구성해야 한다.
- 기간 필터가 필요 없는 질문(예: "전체 설비 목록")이면 act_time_range 를 생략한다.

## ⚠️ 필터 필드 매핑 규칙 (매우 중요)
아래 각 필드에 넣을 수 있는 값은 DB에 실제 존재하는 값만 허용된다.
사용자가 자연어로 말한 값(예: "백호")을 올바른 필드에 매핑해야 한다.

{filter_options_prompt}

매핑 규칙:
- 사용자가 말한 값이 "sdwt_prod 허용값 목록"에 있으면 → sdwt_prod 필터 사용
- 사용자가 말한 값이 "line 허용값 목록"에 있으면 → line 필터 사용
- 허용값 목록에 없는 값은 절대 필터에 넣지 않는다 (0건 조회 방지)
- 확실하지 않으면 해당 필터를 생략하고 전체 조회한다

## ⚠️ AI Copilot 테이블 사용 원칙
AI Copilot 은 반드시 {TABLE_RAW} 테이블만 사용한다.
{TABLE_REPORT} 는 차트 렌더링 전용이며 act_time 컬럼이 없어 AI 분석에 사용 불가.
어떤 질문이 들어와도 "table" 값은 반드시 "{TABLE_RAW}" 로 지정해야 한다.

## 사용 테이블 (단 하나)

### {TABLE_RAW} (인터락 발생 이벤트 로그) ← 항상 이 테이블만 사용
컬럼: act_time(datetime), yyyymmdd, line, sdwt_prod, eqp_id, eqp_model,
      param_type, param_name
  - param_type: 인터락 종류 분류값 (예: A, E, T, M 등) — "interlock" 고정값이 아님
  - param_name: 발생한 파라미터명
중요: 이 테이블은 이벤트 로그이므로 숫자 측정값이 없다.
      집계는 반드시 count(pk) 만 사용한다. avg/sum/max/min 사용 절대 불가.
      발생 건수(cnt) = 행의 수 = COUNT(pk)

## ⚠️ 기간 필터 규칙 (매우 중요)

### act_time_range (월/주/일 단위 조회)
- flag 허용값: "M"(월), "W"(주), "D"(일) — 이 세 가지만 허용
- "Y"(연), "Q"(분기) 등 다른 값은 절대 사용 불가

### yyyy_filter (연간 비교 조회) ← 연도 비교 시 반드시 이것을 사용
- 형식: {{"yyyy_filter": ["2025", "2026"]}}
- "2025년 대비 2026년 비교" → yyyy_filter + group_by 에 "yyyymmdd" 포함
- 단일 연도 전체 조회: {{"yyyy_filter": ["2026"]}}
- act_time_range 와 중복 사용 불가 — 둘 중 하나만 사용

### yyyymmdd_range (월 범위 조회) ← 여러 달에 걸친 기간 조회 시 사용
- 형식: {{"yyyymmdd_range": {{"start": "20260101", "end": "20260331"}}}}
- "1~3월" → yyyymmdd_range start="20260101", end="20260331"
- "상반기(1~6월)" → start="20260101", end="20260630"
- act_time_range(단일 달/주/일)와 yyyy_filter(연도 비교)로 커버 안 되는 구간에 사용

### 필터 선택 기준
| 질문 패턴 | 사용할 필터 |
|-----------|------------|
| "2월" / "M02" 단일 달 | act_time_range flag="M", flagdate="M02" |
| "1~3월" / "1월부터 3월" 범위 | yyyymmdd_range |
| "2025년 대비 2026년" 연도 비교 | yyyy_filter |
| "올해 전체" | yyyy_filter: ["{cur_yyyy}"] |

### 예시
- "2월 대비 3월 비교" → act_time_range flag="M", flagdate="M02"
- "1월부터 3월까지" → yyyymmdd_range start="{cur_yyyy}0101", end="{cur_yyyy}0331"
- "2025년 대비 2026년 비교" → yyyy_filter: ["2025", "2026"], group_by 에 "yyyymmdd" 추가

## Raw 테이블 group_by 권장 계층 (질문 의도에 맞게 선택)
  1단계 (라인별)         : ["line"]
  2단계 (설비별)         : ["line", "eqp_id"]
  3단계 (파라미터 유형별): ["line", "eqp_id", "param_type"]
  4단계 (파라미터명별)   : ["line", "eqp_id", "param_type", "param_name"]

## 응답 형식 (반드시 순수 JSON 만 반환, 마크다운 코드블록 ``` 절대 사용 금지)
{{
    "table": "{TABLE_RAW}",
    "filters": {{
        "param_type": ["A", "E"],
        "act_time_range": {{"flag": "M", "yyyy": "2024", "flagdate": "M01"}}
    }},
    "group_by": ["line", "eqp_id", "param_type", "param_name"],
    "aggregations": [
        {{"field": "pk", "func": "count", "alias": "cnt"}}
    ],
    "order_by": [{{"field": "cnt", "direction": "desc"}}],
    "limit": 10000
}}

## ⚠️ 테이블명 주의 (매우 중요)
사용 가능한 테이블명은 정확히 아래 두 개뿐이다. 다른 이름은 절대 사용 불가.
  - Raw 이벤트 로그 테이블: {TABLE_RAW}
  - 집계 요약 테이블:       {TABLE_REPORT}
"spotfire_raw", "spotfire_report" 등 다른 이름을 사용하면 오류가 발생한다.

## 제약 사항
- table: 반드시 {TABLE_RAW} 또는 {TABLE_REPORT} 중 하나 (다른 값 절대 불가)
- {TABLE_RAW} 의 aggregations.func: count 만 허용 (avg/sum/max/min 절대 불가)
- count 집계 시 field 는 반드시 "pk" 로 지정
- limit: 기본값 10000, 최대 10000 (특별한 이유 없으면 10000 으로 지정)
- 반드시 순수 JSON 만 반환
- 비교 분석(예: "2월 대비 3월 증가량")도 JSON 으로만 답한다
  → 두 기간을 각각 조회하는 것은 불가하므로, 더 넓은 기간(여러 flagdate 포함)으로
    단일 쿼리를 구성하고 집계 결과를 반환한다
  → 자연어 설명은 절대 하지 않는다. 반드시 JSON 만 출력한다""".strip()