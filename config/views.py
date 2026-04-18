from django.shortcuts import render


def home(request):
    """메인 허브 페이지 — 각 분석 대시보드로의 링크"""
    return render(request, "home.html")
