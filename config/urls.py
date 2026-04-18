"""
config/urls.py  (프로젝트 루트 URL 설정)

URL 구조:
  /                → 메인 허브 페이지 (각 대시보드 링크)
  /interlock-ai/   → 인터락 분석 대시보드
  /stoploss-ai/    → 정지로스 분석 대시보드
"""
from django.contrib import admin
from django.urls import path, include
from config.views import home

urlpatterns = [
    # ── 메인 허브 페이지 ──────────────────────────────────────────
    path("", home, name="home"),

    path("admin/", admin.site.urls),

    # ── 인터락 분석 ───────────────────────────────────────────────
    path("interlock-ai/", include("interlock_ai.urls")),

    # ── 정지로스 분석 ─────────────────────────────────────────────
    path("stoploss-ai/", include("stoploss_ai.urls")),
]
