"""
seed_data.py

역할: 테스트용 SQLite 에 report/raw 테이블 생성 + 샘플 데이터 삽입
실행: python seed_data.py

- managed=False 모델은 Django migrate 가 테이블을 만들지 않으므로
  이 스크립트에서 직접 CREATE TABLE + INSERT 를 수행한다
- 실제 MySQL 운영환경에서는 이 파일 대신 DBA 제공 DDL을 사용한다
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import connection

# ─── 테이블 생성 ────────────────────────────────────────────────
DDL_REPORT = """
CREATE TABLE IF NOT EXISTS spotfire_report (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    yyyy       TEXT NOT NULL,
    flag       TEXT NOT NULL,
    flagdate   TEXT NOT NULL,
    line       TEXT NOT NULL DEFAULT '',
    sdwt_prod  TEXT NOT NULL DEFAULT '',
    eqp_id     TEXT NOT NULL DEFAULT '',
    eqp_model  TEXT NOT NULL DEFAULT '',
    param_type TEXT NOT NULL DEFAULT '',
    cnt        INTEGER NOT NULL DEFAULT 0,
    ratio      REAL    NOT NULL DEFAULT 0.0,
    rank       INTEGER NOT NULL DEFAULT 0
);
"""

DDL_RAW = """
CREATE TABLE IF NOT EXISTS spotfire_raw (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    act_time   TEXT NOT NULL,
    yyyymmdd   TEXT NOT NULL DEFAULT '',
    line       TEXT NOT NULL DEFAULT '',
    sdwt_prod  TEXT NOT NULL DEFAULT '',
    eqp_id     TEXT NOT NULL DEFAULT '',
    eqp_model  TEXT NOT NULL DEFAULT '',
    param_type TEXT NOT NULL DEFAULT '',
    item_id    TEXT NOT NULL DEFAULT '',
    test_id    TEXT NOT NULL DEFAULT '',
    value      REAL
);
"""

# ─── 샘플 Report 데이터 ─────────────────────────────────────────
# (yyyy, flag, flagdate, line, sdwt_prod, eqp_id, eqp_model, param_type, cnt, ratio, rank)
REPORT_ROWS = [
    # Monthly
    ("2024", "M", "M01", "L1", "PROD-A", "EQP-001", "MODEL-X", "interlock", 45, 12.5, 1),
    ("2024", "M", "M01", "L2", "PROD-B", "EQP-002", "MODEL-Y", "interlock", 30, 8.3,  2),
    ("2024", "M", "M02", "L1", "PROD-A", "EQP-001", "MODEL-X", "stoploss",  60, 16.7, 1),
    ("2024", "M", "M02", "L2", "PROD-B", "EQP-003", "MODEL-Y", "stoploss",  20, 5.6,  2),
    ("2024", "M", "M03", "L1", "PROD-A", "EQP-002", "MODEL-X", "interlock", 38, 10.5, 1),
    ("2024", "M", "M03", "L3", "PROD-C", "EQP-004", "MODEL-Z", "interlock", 15, 4.2,  3),
    # Weekly
    ("2024", "W", "W01", "L1", "PROD-A", "EQP-001", "MODEL-X", "interlock", 12, 3.3,  1),
    ("2024", "W", "W01", "L2", "PROD-B", "EQP-002", "MODEL-Y", "stoploss",   8, 2.2,  2),
    ("2024", "W", "W02", "L1", "PROD-A", "EQP-001", "MODEL-X", "interlock", 18, 5.0,  1),
    ("2024", "W", "W02", "L3", "PROD-C", "EQP-004", "MODEL-Z", "interlock",  5, 1.4,  2),
    ("2024", "W", "W03", "L2", "PROD-B", "EQP-002", "MODEL-Y", "stoploss",  22, 6.1,  1),
    ("2024", "W", "W03", "L1", "PROD-A", "EQP-003", "MODEL-X", "interlock",  9, 2.5,  2),
    # Daily
    ("2024", "D", "2024-01-15", "L1", "PROD-A", "EQP-001", "MODEL-X", "interlock", 5, 1.4, 1),
    ("2024", "D", "2024-01-16", "L1", "PROD-A", "EQP-001", "MODEL-X", "interlock", 7, 1.9, 1),
    ("2024", "D", "2024-01-16", "L2", "PROD-B", "EQP-002", "MODEL-Y", "stoploss",  3, 0.8, 2),
    ("2024", "D", "2024-01-17", "L1", "PROD-A", "EQP-002", "MODEL-X", "stoploss",  9, 2.5, 1),
    ("2024", "D", "2024-01-17", "L3", "PROD-C", "EQP-004", "MODEL-Z", "interlock", 2, 0.6, 2),
    ("2024", "D", "2024-01-18", "L2", "PROD-B", "EQP-003", "MODEL-Y", "interlock", 6, 1.7, 1),
]

# ─── 샘플 Raw 데이터 ─────────────────────────────────────────────
# (act_time, yyyymmdd, line, sdwt_prod, eqp_id, eqp_model, param_type, item_id, test_id, value)
RAW_ROWS = [
    ("2024-01-15 08:10:00", "20240115", "L1", "PROD-A", "EQP-001", "MODEL-X", "interlock", "ITEM-001", "TEST-A", 1.23),
    ("2024-01-15 09:25:00", "20240115", "L1", "PROD-A", "EQP-001", "MODEL-X", "interlock", "ITEM-002", "TEST-B", 2.45),
    ("2024-01-15 11:00:00", "20240115", "L1", "PROD-A", "EQP-001", "MODEL-X", "interlock", "ITEM-003", "TEST-A", 0.88),
    ("2024-01-15 14:30:00", "20240115", "L1", "PROD-A", "EQP-001", "MODEL-X", "interlock", "ITEM-004", "TEST-C", 3.11),
    ("2024-01-15 16:00:00", "20240115", "L1", "PROD-A", "EQP-001", "MODEL-X", "interlock", "ITEM-005", "TEST-A", 1.77),
    ("2024-01-16 08:05:00", "20240116", "L1", "PROD-A", "EQP-001", "MODEL-X", "interlock", "ITEM-006", "TEST-B", 2.09),
    ("2024-01-16 09:40:00", "20240116", "L1", "PROD-A", "EQP-001", "MODEL-X", "interlock", "ITEM-007", "TEST-A", 1.55),
    ("2024-01-16 10:15:00", "20240116", "L2", "PROD-B", "EQP-002", "MODEL-Y", "stoploss",  "ITEM-008", "TEST-D", 4.20),
    ("2024-01-16 13:00:00", "20240116", "L2", "PROD-B", "EQP-002", "MODEL-Y", "stoploss",  "ITEM-009", "TEST-D", 3.88),
    ("2024-01-16 15:30:00", "20240116", "L2", "PROD-B", "EQP-002", "MODEL-Y", "stoploss",  "ITEM-010", "TEST-E", 5.01),
    ("2024-01-17 07:55:00", "20240117", "L1", "PROD-A", "EQP-002", "MODEL-X", "stoploss",  "ITEM-011", "TEST-D", 2.33),
    ("2024-01-17 09:10:00", "20240117", "L1", "PROD-A", "EQP-002", "MODEL-X", "stoploss",  "ITEM-012", "TEST-D", 1.98),
    ("2024-01-17 11:45:00", "20240117", "L3", "PROD-C", "EQP-004", "MODEL-Z", "interlock", "ITEM-013", "TEST-F", 0.65),
    ("2024-01-17 14:00:00", "20240117", "L3", "PROD-C", "EQP-004", "MODEL-Z", "interlock", "ITEM-014", "TEST-F", 0.72),
    ("2024-01-18 08:30:00", "20240118", "L2", "PROD-B", "EQP-003", "MODEL-Y", "interlock", "ITEM-015", "TEST-G", 3.45),
]


def run():
    with connection.cursor() as cur:
        # 테이블 생성
        cur.execute(DDL_REPORT)
        cur.execute(DDL_RAW)

        # 기존 데이터 초기화 (중복 방지)
        cur.execute("DELETE FROM spotfire_report")
        cur.execute("DELETE FROM spotfire_raw")

        # Report 삽입
        cur.executemany(
            """INSERT INTO spotfire_report
               (yyyy,flag,flagdate,line,sdwt_prod,eqp_id,eqp_model,param_type,cnt,ratio,rank)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            REPORT_ROWS,
        )

        # Raw 삽입
        cur.executemany(
            """INSERT INTO spotfire_raw
               (act_time,yyyymmdd,line,sdwt_prod,eqp_id,eqp_model,param_type,item_id,test_id,value)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            RAW_ROWS,
        )

    print(f"✓ report: {len(REPORT_ROWS)}행 삽입")
    print(f"✓ raw:    {len(RAW_ROWS)}행 삽입")
    print("샘플 데이터 삽입 완료!")


if __name__ == "__main__":
    run()
