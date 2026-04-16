"""
seed_data.py

역할: 테스트용 SQLite에 report/raw 테이블 생성 + 샘플 데이터 삽입
실행: python seed_data.py

테이블명은 models.py 환경변수와 일치:
  TABLE_REPORT = "report_interlock"
  TABLE_RAW    = "interlock_raw"

Raw 컬럼 구성 (models.py SpotfireRaw 기준):
  yyyymmdd, act_time, line, sdwt_prod, eqp_id, unit_id,
  eqp_model, param_type, param_name, ppid, ch_step, lot_id, slot_no
"""

import os
import random
import datetime

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.db import connection

random.seed(42)

# ─── 테이블 DDL ─────────────────────────────────────────────────
DDL_REPORT = """
CREATE TABLE IF NOT EXISTS report_interlock (
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
CREATE TABLE IF NOT EXISTS interlock_raw (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    yyyymmdd   TEXT NOT NULL DEFAULT '',
    act_time   TEXT NOT NULL DEFAULT '',
    line       TEXT NOT NULL DEFAULT '',
    sdwt_prod  TEXT NOT NULL DEFAULT '',
    eqp_id     TEXT NOT NULL DEFAULT '',
    unit_id    TEXT NOT NULL DEFAULT '',
    eqp_model  TEXT NOT NULL DEFAULT '',
    param_type TEXT NOT NULL DEFAULT '',
    param_name TEXT NOT NULL DEFAULT '',
    ppid       TEXT NOT NULL DEFAULT '',
    ch_step    TEXT NOT NULL DEFAULT '',
    lot_id     TEXT NOT NULL DEFAULT '',
    slot_no    TEXT NOT NULL DEFAULT ''
);
"""

# ─── 마스터 데이터 ──────────────────────────────────────────────
YYYY = "2026"

# 라인별 설비 매핑: line → [(eqp_id, eqp_model, unit_id), ...]
EQP_MAP = {
    "L1": [
        ("EQP-101", "MODEL-X", "EQP-101-U1"),
        ("EQP-102", "MODEL-X", "EQP-102-U1"),
        ("EQP-103", "MODEL-Y", "EQP-103-U1"),
        ("EQP-104", "MODEL-Y", "EQP-104-U1"),
    ],
    "L2": [
        ("EQP-201", "MODEL-Y", "EQP-201-U1"),
        ("EQP-202", "MODEL-Y", "EQP-202-U1"),
        ("EQP-203", "MODEL-Z", "EQP-203-U1"),
        ("EQP-204", "MODEL-Z", "EQP-204-U1"),
    ],
    "L3": [
        ("EQP-301", "MODEL-Z", "EQP-301-U1"),
        ("EQP-302", "MODEL-W", "EQP-302-U1"),
        ("EQP-303", "MODEL-W", "EQP-303-U1"),
    ],
}

SDWT_MAP   = {"L1": "PROD-ALPHA", "L2": "PROD-BETA",  "L3": "PROD-GAMMA"}
PARAM_TYPES = ["interlock", "stoploss"]
PARAM_NAMES = [
    "TEMP_HIGH", "PRESSURE_LOW", "FLOW_OVER", "POWER_LIMIT",
    "SPEED_HIGH", "VACUUM_LOW",  "RF_ABNORMAL", "ENDPOINT_MISS",
    "GAS_FLOW",  "COOLANT_TEMP",
]
PPIDS    = ["RCP-001", "RCP-002", "RCP-003", "RCP-004", "RCP-005"]
CH_STEPS = ["STEP-01", "STEP-02", "STEP-03", "STEP-04"]
SLOT_NOS = [str(i) for i in range(1, 26)]


# ─── Report 데이터 생성 ─────────────────────────────────────────
def _make_report_rows():
    rows = []

    # ── Monthly: M01 ~ M04 ──────────────────────────────────────
    for m in range(1, 5):
        flagdate = f"M{m:02d}"
        _append_report_rows(rows, "M", flagdate)

    # ── Weekly: W01 ~ W16 ───────────────────────────────────────
    for w in range(1, 17):
        flagdate = f"W{w:02d}"
        _append_report_rows(rows, "W", flagdate)

    # ── Daily: 04/01 ~ 04/14 ────────────────────────────────────
    base = datetime.date(2026, 4, 1)
    for d in range(14):
        day      = base + datetime.timedelta(days=d)
        flagdate = day.strftime("%m/%d")       # "04/01" 형식
        _append_report_rows(rows, "D", flagdate, max_combos=4)

    return rows


def _append_report_rows(rows, flag, flagdate, max_combos=5):
    """
    (flag, flagdate) 에 대해 여러 (line, eqp, param_type) 조합 생성.
    rank 는 같은 (flag, flagdate) 그룹 내에서 cnt 내림차순.
    """
    combos = []
    for line, equips in EQP_MAP.items():
        for eqp_id, eqp_model, _ in equips[:2]:           # 라인당 최대 2개 설비
            for pt in PARAM_TYPES:
                combos.append((line, eqp_id, eqp_model, pt))

    random.shuffle(combos)
    combos = combos[:max_combos]

    # cnt: flagdate 뒤로 갈수록 약간 증가 추세
    month_factor = 1.0
    if flag == "M":
        month_factor = 0.8 + int(flagdate[1:]) * 0.1
    elif flag == "W":
        month_factor = 0.7 + int(flagdate[1:]) * 0.03
    elif flag == "D":
        month_factor = 0.9 + int(flagdate[3:]) * 0.01   # DD

    for line, eqp_id, eqp_model, pt in combos:
        base_cnt = {"interlock": 80, "stoploss": 40}.get(pt, 60)
        cnt      = max(1, int(base_cnt * month_factor * random.uniform(0.5, 1.8)))
        combos_for_rank = [(line, eqp_id, eqp_model, pt, cnt)]
        rows.append({
            "yyyy": YYYY, "flag": flag, "flagdate": flagdate,
            "line": line, "sdwt_prod": SDWT_MAP[line],
            "eqp_id": eqp_id, "eqp_model": eqp_model,
            "param_type": pt,
            "cnt": cnt, "ratio": 0.0, "rank": 0,
        })

    # ratio / rank 계산 (같은 flagdate 그룹)
    total = sum(r["cnt"] for r in rows if r["flag"] == flag and r["flagdate"] == flagdate)
    group = [r for r in rows if r["flag"] == flag and r["flagdate"] == flagdate]
    group.sort(key=lambda r: r["cnt"], reverse=True)
    for i, r in enumerate(group):
        r["ratio"] = round(r["cnt"] / total * 100, 2) if total else 0.0
        r["rank"]  = i + 1


# ─── Raw 데이터 생성 ─────────────────────────────────────────────
def _make_raw_rows():
    """
    2026-03-01 ~ 2026-04-14 범위의 이벤트 로그 생성.
    각 날짜 × 설비 조합에 2~6건의 이벤트.
    """
    rows = []

    start = datetime.date(2026, 3, 1)
    end   = datetime.date(2026, 4, 14)
    delta = (end - start).days + 1

    lot_counter = 1000

    for d in range(delta):
        day      = start + datetime.timedelta(days=d)
        yyyymmdd = day.strftime("%Y%m%d")

        for line, equips in EQP_MAP.items():
            sdwt_prod = SDWT_MAP[line]
            # 날짜마다 라인 전체 설비가 다 나오지 않도록 일부만 선택
            active_equips = random.sample(equips, k=random.randint(1, len(equips)))

            for eqp_id, eqp_model, unit_id in active_equips:
                n_events = random.randint(2, 7)

                for _ in range(n_events):
                    hour   = random.randint(6, 22)
                    minute = random.randint(0, 59)
                    second = random.randint(0, 59)
                    act_time  = f"{day} {hour:02d}:{minute:02d}:{second:02d}"
                    param_type = random.choice(PARAM_TYPES)
                    param_name = random.choice(PARAM_NAMES)
                    ppid       = random.choice(PPIDS)
                    ch_step    = random.choice(CH_STEPS)
                    lot_id     = f"LOT-{lot_counter:04d}"
                    slot_no    = random.choice(SLOT_NOS)
                    lot_counter += 1

                    rows.append((
                        yyyymmdd, act_time, line, sdwt_prod,
                        eqp_id, unit_id, eqp_model,
                        param_type, param_name,
                        ppid, ch_step, lot_id, slot_no,
                    ))

    return rows


# ─── 실행 ───────────────────────────────────────────────────────
def run():
    report_rows = _make_report_rows()
    raw_rows    = _make_raw_rows()

    with connection.cursor() as cur:
        cur.execute(DDL_REPORT)
        cur.execute(DDL_RAW)

        cur.execute("DELETE FROM report_interlock")
        cur.execute("DELETE FROM interlock_raw")

        # Report 삽입
        cur.executemany(
            """INSERT INTO report_interlock
               (yyyy, flag, flagdate, line, sdwt_prod, eqp_id, eqp_model,
                param_type, cnt, ratio, rank)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (r["yyyy"], r["flag"], r["flagdate"], r["line"], r["sdwt_prod"],
                 r["eqp_id"], r["eqp_model"], r["param_type"],
                 r["cnt"], r["ratio"], r["rank"])
                for r in report_rows
            ],
        )

        # Raw 삽입
        cur.executemany(
            """INSERT INTO interlock_raw
               (yyyymmdd, act_time, line, sdwt_prod, eqp_id, unit_id, eqp_model,
                param_type, param_name, ppid, ch_step, lot_id, slot_no)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            raw_rows,
        )

    print(f"✓ report_interlock : {len(report_rows):,}행 삽입")
    print(f"✓ interlock_raw    : {len(raw_rows):,}행 삽입")

    # 샘플 확인
    with connection.cursor() as cur:
        cur.execute("SELECT flag, COUNT(*) FROM report_interlock GROUP BY flag")
        for flag, cnt in cur.fetchall():
            print(f"  report [{flag}] : {cnt}행")
        cur.execute("SELECT COUNT(*) FROM interlock_raw")
        print(f"  raw 총계         : {cur.fetchone()[0]:,}건")

    print("\n샘플 데이터 삽입 완료!")


if __name__ == "__main__":
    run()
