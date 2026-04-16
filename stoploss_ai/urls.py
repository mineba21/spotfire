from django.urls import path
from . import views

app_name = "stoploss_ai"

urlpatterns = [
    path("",                     views.index,             name="index"),
    path("api/report-data/",     views.api_report_data,   name="api_report_data"),
    path("api/filter-options/",  views.api_filter_options, name="api_filter_options"),
    path("api/click-detail/",    views.api_click_detail,  name="api_click_detail"),
    path("api/ask-ai/",          views.api_ask_ai,        name="api_ask_ai"),
]
