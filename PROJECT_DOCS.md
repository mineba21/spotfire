# Spotfire Dashboard — Project Documentation

> **목적**: 다른 AI(Codex 등)와 협업 시 프로젝트 구조, 데이터 흐름, 설계 원칙, 업데이트 이력을 빠르게 공유하기 위한 문서입니다.
>
> **최종 업데이트**: 2026-04-18

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [디렉토리 구조](#2-디렉토리-구조)
3. [앱별 역할](#3-앱별-역할)
4. [데이터베이스 스키마](#4-데이터베이스-스키마)
5. [전체 데이터 흐름 (Flow)](#5-전체-데이터-흐름-flow)
6. [API 엔드포인트](#6-api-엔드포인트)
7. [서비스 레이어](#7-서비스-레이어)
8. [프론트엔드 구조](#8-프론트엔드-구조)
9. [환경 설정 및 실행](#9-환경-설정-및-실행)
10. [업데이트 이력](#10-업데이트-이력)
11. [주요 설계 원칙 & 확장 가이드](#11-주요-설계-원칙--확장-가이드)

---

## 1. 프로젝트 개요

Django 기반의 제조 현장 데이터 분석 대시보드. 두 개의 독립 앱으로 구성됩니다.

| 앱 | URL | 분석 대상 | DB alias |
|----|-----|-----------|----------|
| `interlock_ai` | `/interlock-ai/` | 인터락(Interlock) 발생 건수 분석 | `default` |
| `stoploss_ai` | `/stoploss-ai/` | 정지로스(Stoploss) 시간 분석 | `tpm` |

**공통 기능**
- M(월) / W(주) / D(일) 3개 주기의 bar chart
- Sidebar 다중 필터 (라인, 설비 등)
- Bar 클릭 → 상세 Rawdata / Top Show / Ratio Analysis
- AI Copilot (LLM 기반 자연어 쿼리)

---

## 2. 디렉토리 구조

```
spotfire/
├── config/                        # Django 프로젝트 설정
│   ├── __init__.py                # pymysql.install_as_MySQLdb() 호출
│   ├── settings.py                # DB·LLM 설정 (env 변수 기반)
│   ├── urls.py                    # 루트 URL 라우팅
│   ├── db_router.py               # TpmRouter: stoploss_ai → "tpm" DB
│   ├── asgi.py
│   └── wsgi.py
│
├── interlock_ai/                   # 인터락 분석 앱
│   ├── models.py                  # SpotfireReport, SpotfireRaw
│   ├── views.py                   # API 뷰 함수
│   ├── urls.py                    # 앱 URL 설정
│   ├── services/
│   │   ├── filter_service.py      # 사이드바 필터 파싱 / Q 객체 생성
│   │   ├── chart_service.py       # M/W/D chart 데이터 생성
│   │   ├── detail_service.py      # bar 클릭 상세 데이터 (interlock_raw)
│   │   ├── ai_service.py          # AI Copilot 오케스트레이션
│   │   ├── llm_interface.py       # LLM 클라이언트 (mock / openai)
│   │   ├── json_validator.py      # LLM 응답 query_json 검증
│   │   └── query_builder.py       # query_json → Django ORM 실행
│   ├── static/interlock_ai/
│   │   ├── css/dashboard.css
│   │   └── js/dashboard.js        # 메인 프론트엔드 로직
│   └── templates/interlock_ai/
│       ├── index.html
│       └── partials/sidebar.html
│
├── stoploss_ai/                   # 정지로스 분석 앱
│   ├── models.py                  # StoplossReport, TpmEqpLoss
│   ├── views.py                   # API 뷰 함수
│   ├── urls.py                    # 앱 URL 설정
│   ├── services/
│   │   ├── filter_service.py      # 사이드바 필터 파싱 / Q 객체 생성
│   │   ├── chart_service.py       # M/W/D chart 데이터 생성 (y_field/y_mode 지원)
│   │   ├── detail_service.py      # bar 클릭 상세: report_stoploss + tpm_eqp_loss
│   │   ├── ratio_service.py       # state 기여도 분석 (Ratio Analysis)
│   │   ├── ai_service.py          # AI Copilot 오케스트레이션
│   │   ├── json_validator.py      # LLM 응답 검증
│   │   └── query_builder.py       # query_json → ORM 실행
│   ├── static/stoploss_ai/
│   │   ├── css/dashboard.css
│   │   └── js/dashboard.js        # 메인 프론트엔드 로직
│   └── templates/stoploss_ai/
│       ├── index.html
│       └── partials/sidebar.html
│
├── seed_data.py                   # interlock_ai용 시드 데이터 생성 스크립트
├── seed_stoploss.py               # stoploss_ai용 시드 데이터 생성 스크립트
├── manage.py
└── PROJECT_DOCS.md                # 이 문서
```

---

## 3. 앱별 역할

### 3-1. `interlock_ai` — 인터락 분석

- **분석 지표**: 인터락 발생 건수(`cnt`), 비율(`ratio`)
- **Y축 선택**: cnt 고정 (비율 표시는 ratio 컬럼 사용)
- **Top Show 집계 기준**: Line / Line+EQP_ID / Line+EQP_ID+PARAM_TYPE / Line+EQP_ID+PARAM_TYPE+PARAM_NAME
- **Rawdata**: `interlock_raw` 테이블 전체 컬럼
- **Ratio Analysis**: `param_type` / `param_name` 기준 기여도 분석

### 3-2. `stoploss_ai` — 정지로스 분석

- **분석 지표**: stoploss, pm, qual, bm, eng, etc, stepchg, std_time, rd (분 단위)
- **Y축 모드**: `min`(절대값, 분) / `pct`(plan_time 대비 %)
- **Top Show 집계 기준**: Area / Area+분임조 / Area+EQP Model / EQP Model / 분임조 (5가지)
- **Rawdata**: `report_stoploss`에서 EQP_ID, STOPLOSS, PLAN_TIME
- **Rank Bar 클릭**: `tpm_eqp_loss`에서 해당 EQP들의 상세 이벤트 조회
- **Ratio Analysis**: `tpm_eqp_loss.state` 기준 기여도 분석

---

## 4. 데이터베이스 스키마

### 4-1. `interlock_ai` — DB alias: `default`

#### `report_interlock`
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INT PK | |
| yyyy | VARCHAR | 연도 (예: "2026") |
| flag | VARCHAR(1) | M/W/D |
| flagdate | VARCHAR(20) | M01, W01, 20260114 등 |
| line | VARCHAR | 라인명 |
| sdwt_prod | VARCHAR | 분임조 |
| eqp_id | VARCHAR | 설비 ID |
| eqp_model | VARCHAR | 설비 기종 |
| param_type | VARCHAR | 인터락 종류 |
| cnt | INT | 발생 건수 |
| ratio | FLOAT | 비율 |
| rank | INT | 순위 |

#### `interlock_raw`
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INT PK | |
| yyyymmdd | VARCHAR | 날짜 |
| act_time | VARCHAR | 발생 시각 |
| line | VARCHAR | 라인명 |
| sdwt_prod | VARCHAR | 분임조 |
| eqp_id | VARCHAR | 설비 ID |
| unit_id | VARCHAR | 유닛 ID |
| eqp_model | VARCHAR | 기종 |
| param_type | VARCHAR | 인터락 종류 |
| param_name | VARCHAR | 파라미터명 |
| ppid | VARCHAR | 프로세스 레시피 |
| ch_step | VARCHAR | 단계 |
| lot_id | VARCHAR | 로트 ID |
| slot_no | VARCHAR | 슬롯 번호 |

---

### 4-2. `stoploss_ai` — DB alias: `tpm`

#### `report_stoploss`
| 컬럼 (DB) | Django 필드명 | 타입 | 설명 |
|-----------|--------------|------|------|
| id | id | INT PK | |
| yyyy | yyyy | VARCHAR | 연도 |
| flag | flag | VARCHAR(1) | M/W/D |
| flagdate | flagdate | VARCHAR(10) | M01, W01, 날짜 등 |
| area | area | VARCHAR | 라인 (구 line 컬럼) |
| sdwt_prod | sdwt_prod | VARCHAR | 분임조 |
| **station** | **eqp_id** | VARCHAR | 설비 ID (`db_column="station"`) |
| **machine_id** | **eqp_model** | VARCHAR | 기종 (`db_column="machine_id"`) |
| prc_group | prc_group | VARCHAR | 공정 그룹 |
| plan_time | plan_time | FLOAT | 계획 시간 (분) |
| stoploss | stoploss | FLOAT | 정지로스 (분) |
| pm | pm | FLOAT | PM 손실 |
| qual | qual | FLOAT | 품질 손실 |
| bm | bm | FLOAT | BM 손실 |
| eng | eng | FLOAT | ENG 손실 |
| etc | etc | FLOAT | 기타 손실 |
| stepchg | stepchg | FLOAT | 스텝 변경 손실 |
| std_time | std_time | FLOAT | 표준 시간 손실 |
| rd | rd | FLOAT | R&D 손실 |
| rank | rank | INT | 순위 |

> ⚠️ **중요**: `eqp_id`는 DB 컬럼명이 `station`, `eqp_model`은 DB 컬럼명이 `machine_id`입니다.  
> Django 모델에서 `db_column` 파라미터로 매핑되어 있으므로 ORM에서는 `eqp_id` / `eqp_model`로 사용합니다.

#### `tpm_eqp_loss`
| 컬럼 (DB) | Django 필드명 | 타입 | 설명 |
|-----------|--------------|------|------|
| id | id | INT PK | |
| yyyymmdd | yyyymmdd | VARCHAR | 날짜 |
| **station** | **eqp_id** | VARCHAR | 설비 ID (`db_column="station"`) |
| start_time | start_time | VARCHAR | 정지 시작 시각 (datetime 문자열) |
| end_time | end_time | VARCHAR | 정지 종료 시각 (datetime 문자열) |
| state | state | VARCHAR | 정지 원인 코드 |
| down_comment | down_comment | VARCHAR | 정지 코멘트 |

> ⚠️ `loss_time_min`은 DB 컬럼이 없습니다. `detail_service.py`의 `_calc_loss_min()`에서 `end_time - start_time`으로 Python 계산합니다.

---

## 5. 전체 데이터 흐름 (Flow)

### 5-1. 초기 페이지 로딩

```
브라우저 GET /stoploss-ai/
  └─ views.index()
       ├─ StoplossReport.distinct(area, sdwt_prod, eqp_model, eqp_id, prc_group)
       └─ render(index.html, filter_options=...)
            └─ dashboard.js: DOMContentLoaded
                 └─ fetchReportData()  ─────────────────────────────┐
                                                                    ↓
                                           GET /api/report-data/?y_field=stoploss&y_mode=min
                                             └─ chart_service.get_chart_data()
                                                  └─ StoplossReport.filter(q).values(...)
                                                       └─ JSON { M:{}, W:{}, D:{} }
                                           ←── renderBarChart(flag, data) × 3
```

### 5-2. Bar 클릭 → 상세 패널

```
사용자가 차트 bar 클릭
  └─ dashboard.js: onBarClick(flag, yyyy, flagdate)
       ├─ fetchClickDetail()  ──────────────────────────────────────┐
       │                                                            ↓
       │                          GET /api/click-detail/?flag=M&yyyy=2026&flagdate=M01
       │                            └─ views.api_click_detail()
       │                                 ├─ detail_service.get_report_detail()
       │                                 │    └─ StoplossReport.filter(flag/yyyy/flagdate + sidebar)
       │                                 │         └─ rows (REPORT_DETAIL_FIELDS 전체)
       │                                 └─ ratio_service.get_ratio_analysis()
       │                                      ├─ TpmEqpLoss.filter(date_range + eqp_id)
       │                                      ├─ StoplossReport → eqp_meta 맵 구축
       │                                      └─ state별 loss_time_min 집계 + pct 계산
       │                          ←── JSON { rows, ratio, columns }
       │
       ├─ state.rawRows   = rows     (report_stoploss 전체 필드)
       ├─ state.ratioRows = ratio    (state별 기여도)
       │
       ├─ renderDetailPanel("raw")   → _renderRawTable() [EQP_ID, STOPLOSS, PLAN_TIME]
       ├─ renderDetailPanel("top")   → renderTopPanel()  [집계 bar chart]
       └─ renderDetailPanel("ratio") → renderRatioPanel() [state 기여도 테이블]
```

### 5-3. Top Show Rank Bar 클릭

```
사용자가 Top Show bar 클릭
  └─ dashboard.js: onTopBarClick(clickedRow, groupCols)
       ├─ matchedRows = state.rawRows.filter(groupCols 조건 일치)
       ├─ eqpIds = matchedRows.map(r => r.eqp_id)  (unique)
       │
       └─ fetch(eqpLossDetail?flag=M&yyyy=2026&flagdate=M01&eqp_id=EQP-101&...)
            └─ views.api_eqp_loss_detail()
                 └─ detail_service.get_eqp_loss_detail(flag, yyyy, flagdate, eqp_ids)
                      └─ TpmEqpLoss.filter(date_range + eqp_id__in=eqp_ids)
                           └─ rows + loss_time_min 계산
            ←── JSON { rows, columns: [yyyymmdd, eqp_id, start_time, end_time, state, down_comment, loss_time_min] }
```

### 5-4. AI Copilot

```
사용자 자연어 질문 입력
  └─ POST /api/ask-ai/
       └─ ai_service.ask_ai()
            ├─ Step 1: LLM → query_json 생성
            │    { table, filters, group_by, aggregations, order_by, limit }
            ├─ Step 1c: 테이블명 교정
            ├─ Step 1v: json_validator.validate_query_json() 보안 검증
            ├─ Step 2: query_builder.execute_query() → Django ORM 실행
            └─ Step 3: LLM → 결과 요약 텍스트 생성
       ←── JSON { answer, data, query_json }
```

### 5-5. 날짜 범위 계산 (공통)

```python
# interlock_ai/services/detail_service.py: get_date_range(flag, yyyy, flagdate)
flag="M", flagdate="M01" → 해당 월의 1일~말일
flag="W", flagdate="W01" → 해당 연도 첫 번째 주 (월~일)
flag="D", flagdate="20260114" → 당일 하루
```

---

## 6. API 엔드포인트

### 6-1. `interlock_ai`

| Method | URL | 설명 | 주요 파라미터 |
|--------|-----|------|--------------|
| GET | `/interlock-ai/` | 대시보드 페이지 | - |
| GET | `/interlock-ai/api/report-data/` | M/W/D 차트 데이터 | `y_field`, `m_rank`, `w_rank`, `d_rank`, 필터들 |
| GET | `/interlock-ai/api/click-detail/` | Bar 클릭 상세 | `flag`, `yyyy`, `flagdate`, 필터들 |
| GET | `/interlock-ai/api/filter-options/` | 사이드바 선택지 갱신 | 필터들 |
| POST | `/interlock-ai/api/ask-ai/` | AI Copilot | `question`, `page_context`, `selected_bar`, `sidebar_filters` |

**interlock_ai 필터 파라미터**: `line`, `sdwt_prod`, `eqp_model`, `eqp_id`, `param_type`

---

### 6-2. `stoploss_ai`

| Method | URL | 설명 | 주요 파라미터 |
|--------|-----|------|--------------|
| GET | `/stoploss-ai/` | 대시보드 페이지 | - |
| GET | `/stoploss-ai/api/report-data/` | M/W/D 차트 데이터 | `y_field`, `y_mode`, `m_rank`, `w_rank`, `d_rank`, 필터들 |
| GET | `/stoploss-ai/api/click-detail/` | Bar 클릭 상세 + Ratio | `flag`, `yyyy`, `flagdate`, 필터들 |
| GET | `/stoploss-ai/api/eqp-loss-detail/` | Top Show 클릭 → tpm_eqp_loss | `flag`, `yyyy`, `flagdate`, `eqp_id`(복수) |
| GET | `/stoploss-ai/api/filter-options/` | 사이드바 선택지 갱신 | 필터들 |
| POST | `/stoploss-ai/api/ask-ai/` | AI Copilot | `question`, `page_context`, `selected_bar`, `sidebar_filters` |

**stoploss_ai 필터 파라미터**: `area`, `sdwt_prod`, `eqp_model`, `eqp_id`, `prc_group`

**y_field 허용값**: `stoploss`, `pm`, `qual`, `bm`, `eng`, `etc`, `stepchg`, `std_time`, `rd`  
**y_mode 허용값**: `min` (절대값, 분) / `pct` (plan_time 대비 %)

---

## 7. 서비스 레이어

### 7-1. 공통 패턴

```
views.py
  └─ filter_service.parse_*()  →  dict { field: [값, ...] }
  └─ filter_service.build_q()  →  Django Q 객체
  └─ chart/detail/ratio service → 결과 dict/list
  └─ JsonResponse { ok, data }
```

### 7-2. `chart_service.py`

| 함수 | 역할 |
|------|------|
| `get_chart_data(filters, rank_limits, y_field, [y_mode])` | M/W/D 각 flag의 시계열 데이터 반환 |
| `parse_rank_limits(get_params)` | `m_rank/w_rank/d_rank` → `{"M":3,"W":3,"D":7}` |
| `_build_series(rows, y_field, [y_mode])` | Plotly용 `{flagdates, yyyy_map, series}` 구성 |

**반환 구조**:
```json
{
  "M": {
    "flagdates": ["M01", "M02", ...],
    "yyyy_map":  {"M01": "2026"},
    "series":    [{"name": "ALL", "y": [값, ...]}]
  }
}
```

### 7-3. `detail_service.py` (stoploss_ai)

| 함수 | 역할 |
|------|------|
| `get_report_detail(flag, yyyy, flagdate, filters)` | `report_stoploss` 조회 → Top Show/Rawdata 공용 |
| `get_eqp_loss_detail(flag, yyyy, flagdate, eqp_ids)` | `tpm_eqp_loss` 조회 → Top Show rank bar 클릭용 |
| `_calc_loss_min(start_str, end_str)` | datetime 문자열 차이를 분 단위로 계산 |

**노출 컬럼 상수**:
```python
RAW_COLUMNS         = ["eqp_id", "stoploss", "plan_time"]
EQP_LOSS_COLUMNS    = ["yyyymmdd", "eqp_id", "start_time", "end_time", "state", "down_comment", "loss_time_min"]
REPORT_DETAIL_FIELDS = [area, sdwt_prod, eqp_id, eqp_model, prc_group, plan_time, stoploss, pm, ...]
```

### 7-4. `ratio_service.py` (stoploss_ai)

**입력**: `(flag, yyyy, flagdate, filters)`  
**출력**: `state`별 기여도 리스트 (loss_time_min 내림차순)

**알고리즘**:
1. `tpm_eqp_loss` → 날짜 범위 + eqp_id 필터로 이벤트 조회
2. `report_stoploss` → eqp_id 기준 메타 맵 구축 (area/eqp_model/sdwt_prod)
3. sidebar 위치 필터 적용 (area/eqp_model/sdwt_prod)
4. `state`별 `loss_time_min` 합산 및 연관 eqp_id/model/sdwt/area set 수집
5. `report_stoploss.stoploss` 레벨별 인덱스 구축 (eqp/model/sdwt/area/total)
6. `pct_vs_*` 계산 = `loss_time_min / stoploss_합 * 100`

**반환 필드**: `state`, `loss_time_min`, `pct_vs_eqp`, `pct_vs_model`, `pct_vs_sdwt`, `pct_vs_area`, `pct_vs_total`

### 7-5. `json_validator.py`

LLM이 생성한 `query_json`의 보안 검증 레이어.

- **허용 테이블**: `ALLOWED_TABLES` (whitelist)
- **허용 필드**: 테이블별 `ALLOWED_*_FIELDS` (whitelist)
- **위험 키워드 차단**: DROP, DELETE, UPDATE, INSERT, EXEC 등
- **최대 limit**: 10,000건

### 7-6. `query_builder.py`

검증된 `query_json` → Django ORM 실행.

```json
{
  "table": "interlock_raw",
  "filters": {"line": ["L1"]},
  "group_by": ["param_type"],
  "aggregations": [{"field": "pk", "func": "COUNT", "alias": "cnt"}],
  "order_by": ["-cnt"],
  "limit": 20
}
```

---

## 8. 프론트엔드 구조

### 8-1. 전역 상태 (`state` 객체)

```javascript
const state = {
  // 차트 데이터
  chartData: { M: null, W: null, D: null },
  
  // 선택된 bar
  selectedBar: null,  // { flag, yyyy, flagdate }
  
  // 상세 패널
  rawRows:    [],     // report_stoploss 전체 필드 (Top Show 집계에도 사용)
  ratioRows:  [],     // ratio_service 결과
  detailMode: "raw",  // "raw" | "top" | "ratio"
  
  // Y축 설정 (stoploss_ai)
  yField: "stoploss", // LOSS_COLUMNS 중 하나
  yMode:  "min",      // "min" | "pct"
};
```

### 8-2. 주요 함수 (stoploss_ai/dashboard.js)

| 함수 | 역할 |
|------|------|
| `fetchReportData()` | `/api/report-data/` 호출 → 3개 차트 렌더 |
| `renderBarChart(flag, data)` | Plotly horizontal bar chart 그리기 |
| `onBarClick(flag, yyyy, flagdate)` | bar 클릭 처리 |
| `fetchClickDetail()` | `/api/click-detail/` 호출 |
| `renderDetailPanel(mode)` | raw/top/ratio 패널 전환 |
| `renderTopPanel()` | Top Show: groupCols 기준 집계 bar + 우측 rawdata 테이블 |
| `onTopBarClick(clickedRow, groupCols)` | Top Show bar 클릭 → eqp-loss-detail API 호출 |
| `renderRatioPanel()` | Ratio Analysis 테이블 렌더 |
| `setYMode(mode)` | min/pct 토글 → 차트+Top Show 재렌더 |
| `setYField(field)` | y축 지표 변경 → 차트+Top Show 재렌더 |
| `collectFilters()` | URLSearchParams로 필터 수집 |
| `resetFilters()` | 모든 필터 초기화 |
| `refreshFilterOptions()` | 연동 필터 갱신 |

### 8-3. Top Show 집계 기준 옵션

```javascript
const TOP_GROUP_OPTIONS = [
  { value: "area",           label: "Line"             },
  { value: "area,sdwt_prod", label: "Line + 분임조"    },
  { value: "area,eqp_model", label: "Line + EQP Model" },
  { value: "eqp_model",      label: "EQP Model"        },
  { value: "sdwt_prod",      label: "분임조"            },
];
```

### 8-4. URL 상수 (index.html → JS 전달)

```javascript
const SF_URLS = {
  reportData:     "{% url 'stoploss_ai:api_report_data' %}",
  clickDetail:    "{% url 'stoploss_ai:api_click_detail' %}",
  filterOptions:  "{% url 'stoploss_ai:api_filter_options' %}",
  eqpLossDetail:  "{% url 'stoploss_ai:api_eqp_loss_detail' %}",
  askAi:          "{% url 'stoploss_ai:api_ask_ai' %}",
};
```

---

## 9. 환경 설정 및 실행

### 9-1. 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `LLM_BACKEND` | `"mock"` | `"mock"` 또는 `"openai"` |
| `OPENAI_API_KEY` | - | openai 사용 시 필수 |
| `TPM_DB_ENGINE` | `"django.db.backends.sqlite3"` | stoploss_ai DB 엔진 |
| `TPM_DB_NAME` | `"db.sqlite3"` | stoploss_ai DB 이름/경로 |
| `TPM_DB_USER` | `"root"` | MySQL 사용 시 |
| `TPM_DB_PASSWORD` | `""` | MySQL 사용 시 |
| `TPM_DB_HOST` | `"127.0.0.1"` | MySQL 사용 시 |
| `TPM_DB_PORT` | `"3306"` | MySQL 사용 시 |
| `TABLE_REPORT` | `"report_interlock"` | interlock_ai 리포트 테이블명 |
| `TABLE_RAW` | `"interlock_raw"` | interlock_ai raw 테이블명 |
| `TABLE_STOPLOSS_REPORT` | `"report_stoploss"` | stoploss_ai 리포트 테이블명 |
| `TABLE_EQP_LOSS` | `"tpm_eqp_loss"` | stoploss_ai 이벤트 테이블명 |

### 9-2. 개발 환경 실행

```bash
# 의존성 설치
pip3 install django pymysql

# 시드 데이터 생성 (SQLite 개발용)
python3 seed_data.py        # interlock_ai용
python3 seed_stoploss.py    # stoploss_ai용

# 서버 실행
python3 manage.py runserver 8000

# 접속
# 인터락: http://localhost:8000/interlock-ai/
# 정지로스: http://localhost:8000/stoploss-ai/
```

### 9-3. MySQL 운영 환경 전환

```bash
export TPM_DB_ENGINE=django.db.backends.mysql
export TPM_DB_NAME=tpm_db
export TPM_DB_USER=myuser
export TPM_DB_PASSWORD=mypassword
export TPM_DB_HOST=db-server-ip

python3 manage.py runserver
```

> `config/__init__.py`에 `pymysql.install_as_MySQLdb()`가 등록되어 있어  
> `mysqlclient` 없이 `PyMySQL`만으로 MySQL 연결이 가능합니다.

### 9-4. DB 라우팅 구조

```
Django ORM 쿼리
  └─ TpmRouter.db_for_read/write()
       ├─ model._meta.app_label == "stoploss_ai" → "tpm" DB
       └─ 나머지 (interlock_ai, auth, admin 등) → "default" DB
```

---

## 10. 업데이트 이력

### v0.1 — 초기 구현 (`interlock_ai`)
- Django 프로젝트 셋업 (config 패키지)
- `interlock_ai` 앱 생성
- `SpotfireReport` / `SpotfireRaw` 모델 (managed=False)
- M/W/D 차트 기본 구현 (Plotly.js horizontal bar)
- Sidebar 필터: Line, SDWT Prod, EQP Model, EQP ID, Param Type
- Bar 클릭 → Rawdata Show 패널
- AI Copilot 기본 구현 (mock LLM)

### v0.2 — Top Show / Ratio Analysis 추가 (`interlock_ai`)
- Bar 클릭 상세 패널에 Rawdata / Top Show / Ratio Analysis 탭 추가
- Top Show: Line / Line+EQP_ID / Line+PARAM_TYPE 집계 기준 드롭다운
- Ratio Analysis: `param_type` / `param_name` 기여도 테이블
- `yyyy_map` 도입: 연도 추측 로직 제거, 정확한 bar 클릭 파라미터 전달
- `SpotfireRaw.param_name` 컬럼 추가

### v0.3 — `stoploss_ai` 앱 신규 생성
- 정지로스 전용 앱 (`stoploss_ai`) 생성
- 별도 DB alias `"tpm"` 설정, `TpmRouter` 구현
- `StoplossReport` / `TpmEqpLoss` 모델 (managed=False)
  - `eqp_id` ← DB 컬럼 `station` (db_column 매핑)
  - `eqp_model` ← DB 컬럼 `machine_id` (db_column 매핑)
- `LOSS_COLUMNS`: stoploss, pm, qual, bm, eng, etc, stepchg, std_time, rd
- Y축 선택 (y_field) + Min/% 토글 (y_mode) 구현
- Sidebar 필터: Area, SDWT Prod, EQP Model, EQP ID, PRC Group
- `seed_stoploss.py` 작성 (개발용 시드 데이터)

### v0.4 — stoploss_ai Top Show / Rawdata 재설계
**배경**: Top Show 데이터 소스를 `tpm_eqp_loss`에서 `report_stoploss`로 변경

**변경 내용**:
- **Top Show 집계 기준**: 기존 방식 → 5가지 옵션 (Area / Area+분임조 / Area+EQP Model / EQP Model / 분임조)
- **Top Show Y값**: y_field/y_mode 설정을 따름 (min/pct 반영)
- **우측 Rawdata**: `report_stoploss`의 `EQP_ID`, `STOPLOSS`, `PLAN_TIME` 표시
- **Rank Bar 클릭**: `tpm_eqp_loss`에서 해당 EQP 이벤트 상세 조회 (별도 API)
- 신규 API `GET /stoploss-ai/api/eqp-loss-detail/` 추가
- `detail_service.py` 전면 재작성: `get_report_detail()` + `get_eqp_loss_detail()`

### v0.5 — interlock_ai Y축 단순화
- 인터락 페이지는 건수(count) 분석만 하므로 Y축 선택 UI 제거
- `y_field` 하드코딩: `"cnt"` 고정
- `dashboard.js`에서 `yFieldSelect` 관련 이벤트 핸들러 제거

### v0.6 — stoploss_ai Y축 토글 → Top Show 연동
- `setYMode()` 호출 시 Top Show 차트 재렌더 추가
- Y축 모드(min/%) 변경이 Bar Chart와 Top Show에 동시 반영

### v0.7 — stoploss_ai Ratio Analysis 재설계 (현재)
**배경**: 기존 `ratio_service.py`가 `param_type`/`param_name`/`loss_time`(DB 컬럼) 참조로 스키마 불일치

**변경 내용**:
- **Grouping Key 변경**: `param_type`/`param_name` → **`tpm_eqp_loss.state`**
- **Loss 시간 계산**: DB `loss_time` 컬럼 → **`start_time`/`end_time` 차이** (Python 계산)
- **분모 레벨 변경**: `pct_vs_line` → **`pct_vs_area`**
- **eqp 메타 연결**: `tpm_eqp_loss.eqp_id` → `report_stoploss`에서 area/model/sdwt 조회
- **Sidebar 필터 적용**: ratio 집계 시 area/eqp_model/sdwt_prod 필터 반영
- `ratio_service.py` 전면 재작성
- `views.py` ratio 활성화 (주석 해제)
- `dashboard.js` `renderRatioPanel()` 컬럼 업데이트

**Ratio Analysis 반환 컬럼**:

| 컬럼 | 설명 |
|------|------|
| `state` | 정지 원인 (예: MCC_TRIP, PM_SCHEDULED) |
| `loss_time_min` | 해당 state 총 정지 시간 (분) |
| `pct_vs_eqp` | 해당 EQP 합산 stoploss 대비 % |
| `pct_vs_model` | 해당 기종 합산 stoploss 대비 % |
| `pct_vs_sdwt` | 해당 분임조 합산 stoploss 대비 % |
| `pct_vs_area` | 해당 라인 합산 stoploss 대비 % |
| `pct_vs_total` | 전체 period stoploss 대비 % |

---

## 11. 주요 설계 원칙 & 확장 가이드

### 11-1. 모델 확장 시
```python
# stoploss_ai/models.py 하단에 추가
class NewTable(models.Model):
    yyyymmdd = models.CharField(max_length=10)
    eqp_id   = models.CharField(max_length=100, db_column="station")  # DB 컬럼명 주의
    # ...
    class Meta:
        managed  = False      # Django가 테이블 생성/변경하지 않음
        db_table = os.environ.get("TABLE_NEW", "new_table")  # env 오버라이드 가능
```

### 11-2. 새 필터 필드 추가 시
1. `filter_service.py` → `FILTER_FIELDS` 리스트에 추가
2. `sidebar.html` → 새 `<select>` 추가
3. `dashboard.js` → `collectFilters()`, `resetFilters()`, `refreshFilterOptions()` 업데이트

### 11-3. 새 Y축 지표 추가 시 (stoploss_ai)
1. `stoploss_ai/models.py` → `LOSS_COLUMNS` 리스트에 추가
2. `chart_service.py` → `values()` 안에 컬럼 추가
3. `index.html` → Y축 선택 드롭다운에 `<option>` 추가

### 11-4. 새 DB 추가 시
1. `config/settings.py` → `DATABASES`에 새 alias 추가
2. `config/db_router.py` → 해당 앱 → 새 alias 라우팅 추가
3. `DATABASE_ROUTERS` 리스트에 새 라우터 등록

### 11-5. Python 버전 호환성
- 이 프로젝트는 **Python 3.9** 기준으로 작성되었습니다.
- `X | None` 타입 힌트는 Python 3.10+ 전용이므로 **`Optional[X]`** (from typing) 사용.
- `pymysql`을 MySQL 드라이버로 사용 (`mysqlclient` 대신).

### 11-6. managed=False 모델의 마이그레이션
- `TpmRouter.allow_migrate()` → `stoploss_ai`는 항상 `False` 반환
- `python3 manage.py migrate`로 stoploss_ai 테이블은 절대 생성/변경되지 않음
- 테이블 생성은 `seed_stoploss.py` 또는 DBA가 직접 실행

---

*이 문서는 코드와 함께 최신 상태로 유지해 주세요. 새 기능 추가 시 10. 업데이트 이력 섹션에 버전을 추가하세요.*
