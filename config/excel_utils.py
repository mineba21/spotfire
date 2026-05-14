"""
config/excel_utils.py

Excel (.xlsx) 다운로드 응답 생성 유틸리티.

- openpyxl write_only 모드 + queryset.iterator() 로 메모리 효율적 생성
- stoploss_ai / interlock_ai 의 click-detail-export 등에서 공용 사용
- 헤더 행에 인디고 배경 + 흰색 볼드 스타일 적용 (JS 측 _downloadAsExcel 과 동일 룩)
"""
from urllib.parse import quote

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill


_HEADER_FONT  = Font(bold=True, color="FFFFFFFF")
_HEADER_FILL  = PatternFill("solid", fgColor="FF6366F1")
_HEADER_ALIGN = Alignment(horizontal="center")

_XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def xlsx_response(rows, columns, sheet_name="Sheet1", filename="export.xlsx",
                  transform=None):
    """
    iterable 한 rows 를 .xlsx 로 변환해 HttpResponse 로 반환한다.

    파라미터
        rows       : dict 의 iterable. queryset.iterator() 등 generator 도 허용.
        columns    : 출력할 컬럼 키 순서 (list of str).
        sheet_name : 워크시트 이름.
        filename   : 다운로드 파일명 (한글 OK — RFC 5987 인코딩 적용).
        transform  : (row_dict) -> dict 형태의 함수. None 이면 원본 그대로.

    메모리 특성
        write_only=Workbook 은 행을 즉시 디스크/메모리 버퍼로 흘려보낸다.
        queryset.iterator() 와 함께 쓰면 수만~수십만 행도 안전하게 처리 가능.
    """
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(sheet_name)

    # ── 헤더 행 (스타일 적용 — write_only 는 셀별 스타일을 WriteOnlyCell 로) ──
    header_cells = []
    for col in columns:
        cell = WriteOnlyCell(ws, value=col)
        cell.font      = _HEADER_FONT
        cell.fill      = _HEADER_FILL
        cell.alignment = _HEADER_ALIGN
        header_cells.append(cell)
    ws.append(header_cells)

    # ── 데이터 행 ──────────────────────────────────────────────
    if transform is None:
        for row in rows:
            ws.append([row.get(c, "") for c in columns])
    else:
        for row in rows:
            t = transform(row)
            ws.append([t.get(c, "") for c in columns])

    # ── 응답 생성 ──────────────────────────────────────────────
    response = HttpResponse(content_type=_XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{quote(filename)}"
    )
    wb.save(response)
    return response
