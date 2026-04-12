"""
spotfire_ai/urls.py  (앱 URL 설정)

엔드포인트 목록:
  GET  /spotfire-ai/                   → 메인 대시보드 페이지
  GET  /spotfire-ai/api/report-data/   → M/W/D chart 데이터 (JSON)
  GET  /spotfire-ai/api/click-detail/  → bar 클릭 후 raw detail (JSON)
  GET  /spotfire-ai/api/filter-options/→ sidebar 드롭다운 선택지 (JSON)
  POST /spotfire-ai/api/ask-ai/        → AI Copilot 질문 응답 (JSON)
"""
from django.urls import path
from . import views

app_name = "spotfire_ai"

urlpatterns = [
    # ── 페이지 ──────────────────────────────────────────────────
    path("", views.index, name="index"),

    # ── API: 기존 ────────────────────────────────────────────────
    path("api/report-data/",    views.api_report_data,    name="api_report_data"),
    path("api/click-detail/",   views.api_click_detail,   name="api_click_detail"),
    path("api/filter-options/", views.api_filter_options, name="api_filter_options"),

    # ── API: AI Copilot ──────────────────────────────────────────
    path("api/ask-ai/",         views.api_ask_ai,         name="api_ask_ai"),
]
