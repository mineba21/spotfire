# Spotfire AI Dashboard

Django 기반 설비 이상(인터락) 현황 분석 웹 대시보드.  
TIBCO Spotfire Report 형식의 M/W/D Chart + AI Copilot(LLM) 통합.


## 협업 문서

- Codex/Claude Code 공용 협업 가이드: `COLLAB_CODEFLOW.md`

---

## 업데이트 필요 파일 목록

GitHub 원본 대비 이번 작업에서 변경된 파일입니다.  
아래 파일들을 프로젝트에 복사 후 `git push` 하세요.

### Python (Backend)

| 파일 | 경로 | 주요 변경 내용 |
|------|------|----------------|
| `models.py` | `spotfire_ai/` | `act_time` 추가, `wafer_id` → `slot_no`, `yyyymmdd` max_length 수정, 불필요 컬럼 정리 |
| `views.py` | `spotfire_ai/` | `filter_options` LLM context 전달, `page_contexts` 제거, 로깅 강화 |
| `ai_service.py` | `spotfire_ai/services/` | `filter_options` 파라미터 추가, `_fix_filter_field_mapping()` 추가, TABLE_RAW 강제 고정, 상세 로깅 |
| `llm_interface.py` | `spotfire_ai/services/` | OpenAI 실제 연동(custom base_url + credential 헤더), Mock→LLM 전환, 현재 날짜 자동 주입, `max_tokens` 증가(4096/8192), `summarize_results` answer+table dict 반환, `yyyymmdd_range` 지원, `limit` 10000으로 변경 |
| `json_validator.py` | `spotfire_ai/services/` | `value`/`item_id`/`test_id` 제거, `param_name`/`unit_id`/`ppid`/`ch_step`/`lot_id`/`slot_no` 추가, `yyyy_filter`/`yyyymmdd_range` 추가, `MAX_LIMIT` 10000, Raw 테이블 `count` 전용 검증 |
| `detail_service.py` | `spotfire_ai/services/` | `act_time` → `yyyymmdd` 필터로 전환, M/W/D 날짜 계산 로직 수정(M 오프셋 제거, W 업무 기준 주차), D flagdate 다중 포맷 파싱, DB 하이픈 형식 자동 감지, `RAW_COLUMNS` 업데이트 |
| `query_builder.py` | `spotfire_ai/services/` | `act_time_range` → `yyyymmdd` 필터로 전환, `yyyy_filter`/`yyyymmdd_range` 추가, DB 형식 자동 감지(`_to_db_ymd`), `HARD_LIMIT` 10000 |

> `chart_service.py`, `filter_service.py`, `urls.py` 는 변경 없음

### Frontend

| 파일 | 경로 | 주요 변경 내용 |
|------|------|----------------|
| `dashboard.js` | `spotfire_ai/static/spotfire_ai/js/` | Top Show cnt 기반 그룹 집계 재설계, `topGroupSelect` 고정 옵션, Top Show bar 클릭 → Rawdata 표시(`onTopBarClick`, `_renderTopRaw`), `pageContextSelect` 제거 |
| `index.html` | `spotfire_ai/templates/spotfire_ai/` | `topGroupSelect` 드롭다운, Top Rawdata 패널(`topRawPanel`), 하단 Page Tab Bar(Spotfire 스타일), `pageContextSelect` 제거, overflow 스타일 수정 |

### Config

| 파일 | 경로 | 주요 변경 내용 |
|------|------|----------------|
| `settings.py` | `config/` | LLM 설정 블록 추가(`LLM_BACKEND`, `LLM_MODEL`, `LLM_API_BASE_URL`, `LLM_CREDENTIAL_KEY`, `LLM_USER_ID`), LOGGING 설정 추가 |

> `settings.py` 는 직접 편집 필요 — `settings_llm_snippet.py`, `settings_logging_snippet.py` 참고

---

## 프로젝트 구조

```
spotfire/
├── config/
│   ├── settings.py          # Django 설정 (LLM, DB, Logging)
│   ├── urls.py              # 루트 URL (/spotfire-ai/ 마운트)
│   ├── wsgi.py
│   └── asgi.py
├── spotfire_ai/             # 인터락 분석 앱
│   ├── models.py            # SpotfireReport, SpotfireRaw
│   ├── views.py             # API 엔드포인트
│   ├── urls.py              # 앱 URL 라우팅
│   ├── services/
│   │   ├── ai_service.py       # AI Copilot 오케스트레이션
│   │   ├── chart_service.py    # M/W/D 차트 데이터 생성
│   │   ├── detail_service.py   # Bar 클릭 Raw 데이터 조회
│   │   ├── filter_service.py   # Sidebar 필터 파싱
│   │   ├── json_validator.py   # LLM 쿼리 JSON 검증 (allowlist)
│   │   ├── llm_interface.py    # LLM 클라이언트 (OpenAI/Mock)
│   │   └── query_builder.py    # ORM QuerySet 생성
│   ├── static/spotfire_ai/
│   │   ├── css/dashboard.css   # 대시보드 스타일 (다크/라이트 모드)
│   │   └── js/dashboard.js     # 클라이언트 로직 (Plotly, AI Copilot)
│   └── templates/spotfire_ai/
│       ├── index.html           # 메인 대시보드
│       └── partials/sidebar.html
├── manage.py
├── run.sh                   # 서버 실행 (port 8100)
└── seed_data.py             # 테스트 데이터 삽입
```

---

## 전체 Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Browser (index.html)                         │
│                                                                       │
│  ┌─────────┐   ┌──────────────────────────────────────────────────┐  │
│  │ Sidebar │   │                   sf-main                        │  │
│  │ Filters │   │  ┌──────────┬──────────┬──────────┐             │  │
│  │ ─────── │   │  │ Monthly  │  Weekly  │  Daily   │  ← Plotly   │  │
│  │  line   │   │  │  Chart   │  Chart   │  Chart   │    Bar Chart │  │
│  │ sdwt_   │   │  └────┬─────┴────┬─────┴────┬─────┘             │  │
│  │  prod   │   │       │ bar click│          │                    │  │
│  │ eqp_id  │   │  ┌────▼──────────────────────────────────────┐  │  │
│  │ eqp_    │   │  │  Detail Panel                              │  │  │
│  │  model  │   │  │  [Rawdata] / [Top Show]                    │  │  │
│  │ param_  │   │  │  ┌─────────────────────────────────────┐  │  │  │
│  │  type   │   │  │  │ Top Show: 그룹별 cnt 집계 수평 bar  │  │  │  │
│  │ ─────── │   │  │  │ bar 클릭 → 하단 Rawdata 패널 표시   │  │  │  │
│  │  Apply  │   │  │  └─────────────────────────────────────┘  │  │  │
│  │  Reset  │   │  └───────────────────────────────────────────┘  │  │
│  └─────────┘   │                                                  │  │
│                │  ┌─────────────────── Page Tab Bar ───────────┐  │  │
│                │  │  [Interlock ●]  [Stoploss]  [...]          │  │  │
│                │  └────────────────────────────────────────────┘  │  │
│                └──────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ fetch (REST API)
┌──────────────────────────▼──────────────────────────────────────────┐
│                        Django Views (views.py)                       │
│                                                                       │
│  GET  /api/report-data/     GET  /api/click-detail/                  │
│  GET  /api/filter-options/  POST /api/ask-ai/                        │
└──────┬───────────────────────────────┬────────────────────────────────┘
       │                               │
       ▼                               ▼
┌──────────────────┐       ┌──────────────────────────────────────────┐
│  chart_service   │       │           ai_service (AI Copilot)        │
│  ─────────────   │       │  ─────────────────────────────────────   │
│  SpotfireReport  │       │  1. get_llm_client()                     │
│  .filter(Q)      │       │     └─ OpenAILLMClient                   │
│  .values()       │       │        (custom base_url + credential)    │
│  → M/W/D JSON   │       │                                           │
│                  │       │  2. generate_query_json(question)        │
│  detail_service  │       │     └─ system prompt에 포함:             │
│  ─────────────   │       │        · 현재 날짜 (자동)                │
│  SpotfireRaw     │       │        · DB 실제 허용값 목록             │
│  .filter(        │       │        · 필드 매핑 규칙                  │
│    yyyymmdd__gte │       │        · 테이블 스키마                   │
│    yyyymmdd__lte │       │                                           │
│  )               │       │  3. _apply_page_context_defaults()       │
│  → Raw rows      │       │     └─ TABLE_RAW 강제 고정               │
│                  │       │     └─ _fix_filter_field_mapping()       │
└──────────────────┘       │        (잘못된 필드 자동 교정)           │
                           │                                           │
                           │  4. validate_query_json()                │
                           │     └─ allowlist 검증                    │
                           │     └─ Raw: count만 허용                 │
                           │                                           │
                           │  5. execute_query() → ORM QuerySet       │
                           │     └─ yyyymmdd 형식 자동 감지           │
                           │        (하이픈/숫자 자동 변환)           │
                           │                                           │
                           │  6. summarize_results()                  │
                           │     └─ {"answer": "...", "table": [...]} │
                           └──────────────────────────────────────────┘
                                          │
                                          ▼
                              ┌───────────────────────┐
                              │  MySQL DB             │
                              │  ─────────────────    │
                              │  report_interlock     │
                              │  (M/W/D 집계)         │
                              │                       │
                              │  interlock_raw        │
                              │  (이벤트 로그)        │
                              │  yyyymmdd, line,      │
                              │  sdwt_prod, eqp_id,   │
                              │  param_type,          │
                              │  param_name, ...      │
                              └───────────────────────┘
```

---

## API 엔드포인트

| Method | URL | 설명 |
|--------|-----|------|
| `GET` | `/spotfire-ai/` | 메인 대시보드 페이지 |
| `GET` | `/spotfire-ai/api/report-data/` | M/W/D 차트 데이터 (JSON) |
| `GET` | `/spotfire-ai/api/click-detail/` | Bar 클릭 Raw 데이터 (JSON) |
| `GET` | `/spotfire-ai/api/filter-options/` | Sidebar 드롭다운 옵션 (JSON) |
| `POST` | `/spotfire-ai/api/ask-ai/` | AI Copilot 질문/응답 (JSON) |

---

## DB 테이블

### `report_interlock` (집계 요약)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `yyyy` | VARCHAR | 연도 |
| `flag` | VARCHAR(1) | M(월)/W(주)/D(일) |
| `flagdate` | VARCHAR | M02, W03, 04/01 등 |
| `line` | VARCHAR | 라인 |
| `sdwt_prod` | VARCHAR | 제품군 |
| `eqp_id` | VARCHAR | 설비 ID |
| `eqp_model` | VARCHAR | 설비 모델 |
| `param_type` | VARCHAR | 파라미터 유형 (A/E/T/M 등) |
| `cnt` | INT | 발생 건수 |
| `ratio` | FLOAT | 비율(%) |
| `rank` | INT | 순위 |

### `interlock_raw` (이벤트 로그)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `yyyymmdd` | VARCHAR | 날짜 ("2026-04-01" 또는 "20260401") |
| `act_time` | VARCHAR | 발생 시각 |
| `line` | VARCHAR | 라인 |
| `sdwt_prod` | VARCHAR | 제품군 |
| `eqp_id` | VARCHAR | 설비 ID |
| `unit_id` | VARCHAR | 유닛 ID |
| `eqp_model` | VARCHAR | 설비 모델 |
| `param_type` | VARCHAR | 파라미터 유형 |
| `param_name` | VARCHAR | 파라미터명 |
| `ppid` | VARCHAR | PPID |
| `ch_step` | VARCHAR | 챔버 스텝 |
| `lot_id` | VARCHAR | Lot ID |
| `slot_no` | VARCHAR | Slot 번호 |

---

## AI Copilot 쿼리 JSON 스키마

LLM이 생성하는 쿼리 JSON 형식입니다.

```json
{
  "table": "interlock_raw",
  "filters": {
    "sdwt_prod": ["백호"],
    "yyyymmdd_range": {"start": "20260101", "end": "20260331"},
    "act_time_range": {"flag": "M", "yyyy": "2026", "flagdate": "M02"},
    "yyyy_filter": ["2025", "2026"],
    "param_type": ["A", "E"]
  },
  "group_by": ["line", "eqp_id", "param_type", "param_name"],
  "aggregations": [
    {"field": "pk", "func": "count", "alias": "cnt"}
  ],
  "order_by": [{"field": "cnt", "direction": "desc"}],
  "limit": 10000
}
```

### 기간 필터 선택 기준

| 질문 패턴 | 사용 필터 |
|-----------|-----------|
| "2월" / 단일 달 | `act_time_range` (flag=M, flagdate=M02) |
| "1~3월" / 월 범위 | `yyyymmdd_range` |
| "올해 전체" / 연도 | `yyyy_filter` |
| "2025년 대비 2026년" | `yyyy_filter` + group_by yyyymmdd |

---

## 설정

### settings.py LLM 설정

```python
LLM_BACKEND        = "openai"       # "mock" | "openai"
LLM_MODEL          = "gpt-oss-120b"
LLM_API_BASE_URL   = os.environ.get("LLM_API_BASE_URL",   "")
LLM_CREDENTIAL_KEY = os.environ.get("LLM_CREDENTIAL_KEY", "")
LLM_USER_ID        = os.environ.get("LLM_USER_ID",        "")
```

### settings.py DB 설정

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("DB_NAME", "spotfire"),
        "USER": os.environ.get("DB_USER", "root"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "3306"),
    }
}
```

### 로컬 실행

```bash
python seed_data.py   # 테스트 데이터 삽입 (SQLite)
bash run.sh           # http://127.0.0.1:8100/spotfire-ai/
```

---

## 향후 계획

- **Stoploss 페이지** — `stoploss_ai` 앱 추가 (`stoploss`, `report_stoploss` 테이블)
- **공통 모듈 분리** — `common/services/`로 chart/filter/AI 로직 공유
- **설비 가동률 분석** — `eqp_utilization` 테이블 AI Copilot 연동
- **설비 정비 기록** — `maintenance_record` 테이블 연동