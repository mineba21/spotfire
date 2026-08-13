from django.urls import path
from . import views

app_name = "stoploss_ai"

urlpatterns = [
    path("",                            views.index,                    name="index"),
    path("api/report-data/",            views.api_report_data,          name="api_report_data"),
    path("api/filter-options/",         views.api_filter_options,       name="api_filter_options"),
    path("api/click-detail/",           views.api_click_detail,         name="api_click_detail"),
    path("api/click-detail-export/",    views.api_click_detail_export,  name="api_click_detail_export"),
    path("api/eqp-loss-detail/",        views.api_eqp_loss_detail,      name="api_eqp_loss_detail"),
    path("api/ask-ai/",                 views.api_ask_ai,               name="api_ask_ai"),

    # ── 설비 Loss 분석 (tpm_eqp_loss 드릴다운) ────────────────────
    path("lossraw/",                    views.lossraw_index,               name="lossraw_index"),
    path("lossraw/api/agg/",            views.api_lossraw_agg,             name="api_lossraw_agg"),
    path("lossraw/api/raw/",            views.api_lossraw_raw,             name="api_lossraw_raw"),
    path("lossraw/api/filter-options/", views.api_lossraw_filter_options,  name="api_lossraw_filter_options"),
]
