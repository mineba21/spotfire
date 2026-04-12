"""
config/urls.py  (프로젝트 루트 URL 설정)

spotfire_ai 앱의 URL을 /spotfire-ai/ 아래에 마운트한다.
앱이 늘어날 경우 이 파일에 include() 를 추가하면 된다.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),

    # spotfire_ai 앱: /spotfire-ai/ 하위 모든 URL
    path("spotfire-ai/", include("spotfire_ai.urls")),
]
