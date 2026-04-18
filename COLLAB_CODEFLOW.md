# Spotfire 협업 가이드 (Codex + Claude Code 공용)

이 문서는 **Codex**와 **Claude Code**가 동일한 기준으로 협업할 수 있도록,
프로젝트의 코드 흐름, 주요 기능, 업데이트 이력 관리 방식을 정리한 문서입니다.

---

## 1) 빠른 실행 방법

### 로컬 실행
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # requirements 파일이 없다면 Django 수동 설치 필요
python3 manage.py migrate
python3 manage.py runserver 8100
```

또는 제공 스크립트 사용:

```bash
bash run.sh
```

접속 URL:
- `http://127.0.0.1:8100/spotfire-ai/`

> 참고: 현재 저장소 기준으로 `python3 manage.py check` 실행 시, Django 미설치 환경에서는
> `ModuleNotFoundError: No module named 'django'`가 발생할 수 있습니다.

---

## 2) 프로젝트 코드 플로우

## 2-1. 요청 진입
1. 브라우저에서 `/spotfire-ai/` 접속
2. `spotfire_ai/views.py`가 HTML 템플릿 반환
3. 프론트(`dashboard.js`)가 API 호출
   - `/api/filter-options/`
   - `/api/report-data/`
   - `/api/click-detail/`
   - `/api/ask-ai/`

## 2-2. 차트 데이터 플로우 (M/W/D)
1. `views.py` → `chart_service.py`
2. `chart_service.py`가 필터를 받아 `SpotfireReport` 집계 데이터 조회
3. 월/주/일 구조로 JSON 변환 후 프론트 반환
4. 프론트는 Plotly 차트 렌더링

## 2-3. 상세 Raw 데이터 플로우
1. 차트 bar 클릭
2. `views.py` → `detail_service.py`
3. 선택된 축(월/주/일) 및 필터 조건으로 `SpotfireRaw` 조회
4. Raw table 데이터를 JSON으로 반환

## 2-4. AI Copilot 플로우
1. 질문 입력 → `/api/ask-ai/` POST
2. `views.py` → `ai_service.py`
3. `ai_service.py`가 `llm_interface.py`를 통해 LLM 질의
4. 생성된 쿼리 JSON을 `json_validator.py`로 검증
5. `query_builder.py`로 ORM QuerySet 생성 및 실행
6. 결과를 요약(answer/table)하여 프론트 반환

---

## 3) 주요 기능 요약

- **M/W/D 인터락 대시보드**: 월/주/일 차트 기반 이상 발생 추이 분석
- **필터 기반 Drill-down**: line, 제품, 설비, 파라미터 기준 세분화 조회
- **Bar 클릭 상세조회**: 요약 차트 → Raw 이벤트 목록으로 즉시 전환
- **AI Copilot 질의**:
  - 자연어 질문을 안전한 JSON 쿼리로 변환
  - 허용 필드/조건 검증 후 DB 조회
  - answer + table 형태로 응답
- **2개 앱 공존 구조**:
  - `spotfire_ai`: 인터락 분석
  - `stoploss_ai`: 정지로스 분석

---

## 4) 협업 규칙 (Codex / Claude Code 공통)

## 4-1. 브랜치 & 커밋
- 기능 단위 브랜치 사용 (`feature/...`, `fix/...`, `docs/...`)
- 커밋 메시지 예시:
  - `docs: add shared collaboration codeflow guide`
  - `feat(spotfire_ai): add weekly filter option`

## 4-2. 변경 시 필수 문서화
코드 변경 시 아래를 함께 갱신합니다.
1. 이 문서의 **업데이트 이력**
2. 필요 시 `Readme.md`의 구조/흐름/실행 방법
3. API 스펙 변경 시 endpoint/파라미터/응답 예시

## 4-3. 리뷰 체크리스트
- [ ] 기존 API 계약 깨지지 않는가?
- [ ] 필터 키/컬럼 매핑이 validator allowlist와 일치하는가?
- [ ] UI 요소 변경 시 JS/템플릿/CSS가 함께 반영되었는가?
- [ ] 로그/에러 메시지가 운영 추적 가능한 수준인가?

---

## 5) 업데이트 이력 (공용)

| 날짜 (UTC) | 작성자(에이전트) | 범위 | 변경 내용 |
|---|---|---|---|
| 2026-04-18 | Codex | docs | Codex/Claude 공용 협업 문서(`COLLAB_CODEFLOW.md`) 신규 추가. 코드 플로우, 기능, 문서화 규칙, 이력 관리 방식 정리. |

---

## 6) 다음 권장 작업

1. `requirements.txt` 추가(또는 정비)로 실행 재현성 확보
2. `README`에 본 문서 링크 추가
3. `CONTRIBUTING.md`를 별도 생성해 PR 템플릿/리뷰 기준 분리
