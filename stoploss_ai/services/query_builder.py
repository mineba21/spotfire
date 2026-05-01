"""
stoploss_ai/services/query_builder.py

stoploss 테이블에 대한 쿼리를 실행한다.
spotfire_ai 의 query_builder.py 와 동일한 execute_query 인터페이스.
"""
from django.db.models import Count, Avg, Sum, Max, Min, Q
from stoploss_ai.models import (
    EqpLossTpm,
    TpmEqpLoss,
    StoplossReport,
    TABLE_EQP_LOSS,
    TABLE_EQP_LOSS_TPM,
    TABLE_STOPLOSS_REPORT,
)

AGG_FUNC_MAP = {
    "count": Count,
    "avg":   Avg,
    "sum":   Sum,
    "max":   Max,
    "min":   Min,
}


def execute_stoploss_query(qj: dict) -> list:
    """
    validate_stoploss_query_json() 을 통과한 query JSON 을 실행하고 결과를 반환한다.

    반환: dict list (최대 limit 건)
    """
    table = qj.get("table")
    if table == TABLE_EQP_LOSS_TPM:
        qs = EqpLossTpm.objects.all()
    elif table == TABLE_EQP_LOSS:
        qs = TpmEqpLoss.objects.all()
    elif table == TABLE_STOPLOSS_REPORT:
        qs = StoplossReport.objects.all()
    else:
        raise ValueError(f"허용되지 않은 테이블: {table}")

    # filters 적용
    filters = qj.get("filters", {})
    q = _build_q(filters, table)
    qs = qs.filter(q)

    # aggregations
    aggregations = qj.get("aggregations", [])
    group_by     = qj.get("group_by", [])

    if aggregations:
        if group_by:
            qs = qs.values(*group_by)
        agg_kwargs = {}
        for agg in aggregations:
            func  = agg["func"]
            field = agg["field"]
            alias = agg["alias"]
            fn    = AGG_FUNC_MAP[func]
            agg_kwargs[alias] = fn(field if field != "pk" else "id")
        qs = qs.annotate(**agg_kwargs)
    elif group_by:
        qs = qs.values(*group_by)

    # order_by
    order_by = qj.get("order_by", [])
    if order_by:
        ordering = []
        for item in order_by:
            field     = item.get("field", "")
            direction = item.get("direction", "asc")
            ordering.append(f"-{field}" if direction == "desc" else field)
        qs = qs.order_by(*ordering)

    limit = qj.get("limit", 100)
    return list(qs[:limit])


def _build_q(filters: dict, table: str) -> Q:
    from interlock_ai.services.detail_service import get_date_range
    q = Q()

    for field, value in filters.items():
        if field == "yyyymmdd_range":
            start = value.get("start", "")
            end   = value.get("end",   "")
            if start:
                q &= Q(yyyymmdd__gte=start)
            if end:
                q &= Q(yyyymmdd__lte=end)

        elif field == "yyyy_filter":
            years = [value] if isinstance(value, str) else value
            if years:
                if len(years) == 1:
                    q &= Q(yyyymmdd__startswith=years[0])
                else:
                    q &= Q(yyyymmdd__regex=f"^({'|'.join(years)})")

        elif field == "act_time_range":
            flag     = value.get("flag")
            yyyy     = value.get("yyyy")
            flagdate = value.get("flagdate")
            start_ymd, end_ymd = get_date_range(flag, yyyy, flagdate)
            if start_ymd:
                q &= Q(yyyymmdd__gte=start_ymd, yyyymmdd__lte=end_ymd)

        else:
            vals = value if isinstance(value, list) else [value]
            if vals:
                q &= Q(**{f"{field}__in": vals})

    return q
