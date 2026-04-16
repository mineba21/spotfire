"""
seed_stoploss.py
테이블: report_stoploss, eqp_loss_tpm
실행: python seed_stoploss.py
"""
import os, random, datetime

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.db import connection

random.seed(99)

DDL_REPORT = """
CREATE TABLE IF NOT EXISTS report_stoploss (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    yyyy       TEXT NOT NULL,
    flag       TEXT NOT NULL,
    flagdate   TEXT NOT NULL,
    line       TEXT NOT NULL DEFAULT '',
    sdwt_prod  TEXT NOT NULL DEFAULT '',
    eqp_id     TEXT NOT NULL DEFAULT '',
    eqp_model  TEXT NOT NULL DEFAULT '',
    plan_time  REAL NOT NULL DEFAULT 0.0,
    stoploss   REAL NOT NULL DEFAULT 0.0,
    pm         REAL NOT NULL DEFAULT 0.0,
    qual       REAL NOT NULL DEFAULT 0.0,
    bm         REAL NOT NULL DEFAULT 0.0,
    rank       INTEGER NOT NULL DEFAULT 0
);
"""

DDL_EQP_LOSS = """
CREATE TABLE IF NOT EXISTS eqp_loss_tpm (
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
    loss_time  REAL NOT NULL DEFAULT 0.0,
    lot_id     TEXT NOT NULL DEFAULT ''
);
"""

EQP_MAP = {
    "L1": [("EQP-101","MODEL-X","EQP-101-U1"),("EQP-102","MODEL-X","EQP-102-U1"),("EQP-103","MODEL-Y","EQP-103-U1"),("EQP-104","MODEL-Y","EQP-104-U1")],
    "L2": [("EQP-201","MODEL-Y","EQP-201-U1"),("EQP-202","MODEL-Y","EQP-202-U1"),("EQP-203","MODEL-Z","EQP-203-U1"),("EQP-204","MODEL-Z","EQP-204-U1")],
    "L3": [("EQP-301","MODEL-Z","EQP-301-U1"),("EQP-302","MODEL-W","EQP-302-U1"),("EQP-303","MODEL-W","EQP-303-U1")],
}
SDWT_MAP = {"L1": "PROD-ALPHA", "L2": "PROD-BETA", "L3": "PROD-GAMMA"}
YYYY = "2026"

# eqp_loss_tpm 전용 param
PARAM_NAMES_MAP = {
    "MCC": ["MOTOR_TRIP", "OVERLOAD", "PHASE_FAIL"],
    "ERD": ["EMG_STOP", "DOOR_OPEN", "SAFETY_FENCE"],
    "SPC": ["TEMP_OOC", "PRESSURE_OOC", "FLOW_OOC"],
    "ENG": ["PM_SCHEDULED", "UNSCHEDULED_MAINT"],
    "OPR": ["RECIPE_ERROR", "MATERIAL_WAIT", "OPERATOR_STOP"],
}

# 라인별 param_type 분포 가중치 (라인마다 주로 발생하는 인터락이 다름)
# → ratio 분석에서 레벨별 % 가 달라지도록 의도적으로 편향시킴
LINE_PARAM_WEIGHTS = {
    "L1": {"MCC": 50, "ERD": 20, "SPC": 15, "ENG": 10, "OPR":  5},  # L1: 주로 MCC
    "L2": {"MCC": 10, "ERD": 15, "SPC": 50, "ENG": 15, "OPR": 10},  # L2: 주로 SPC
    "L3": {"MCC":  5, "ERD": 20, "SPC": 10, "ENG": 25, "OPR": 40},  # L3: 주로 OPR·ENG
}

def _weighted_param_type(line: str) -> str:
    """라인별 가중치에 따라 param_type 을 선택한다."""
    weights = LINE_PARAM_WEIGHTS.get(line, {k: 20 for k in PARAM_NAMES_MAP})
    population = []
    for pt, w in weights.items():
        population.extend([pt] * w)
    return random.choice(population)


def _make_report_rows():
    rows = []

    def _append(flag, flagdate, max_combos=5):
        combos = []
        for line, equips in EQP_MAP.items():
            for eqp_id, eqp_model, _ in equips[:2]:
                combos.append((line, eqp_id, eqp_model))
        random.shuffle(combos)
        combos = combos[:max_combos]

        rank = 1
        for line, eqp_id, eqp_model in combos:
            plan_time = random.uniform(600, 1440)   # 10h~24h in min
            stoploss  = random.uniform(10, plan_time * 0.3)
            pm   = stoploss * random.uniform(0.2, 0.4)
            qual = stoploss * random.uniform(0.1, 0.3)
            bm   = stoploss - pm - qual
            if bm < 0: bm = 0
            rows.append({
                "yyyy": YYYY, "flag": flag, "flagdate": flagdate,
                "line": line, "sdwt_prod": SDWT_MAP[line],
                "eqp_id": eqp_id, "eqp_model": eqp_model,
                "plan_time": round(plan_time, 2),
                "stoploss": round(stoploss, 2),
                "pm": round(pm, 2),
                "qual": round(qual, 2),
                "bm": round(bm, 2),
                "rank": rank,
            })
            rank += 1

    for m in range(1, 5):
        _append("M", f"M{m:02d}")
    for w in range(1, 17):
        _append("W", f"W{w:02d}")
    base = datetime.date(2026, 4, 1)
    for d in range(14):
        day = base + datetime.timedelta(days=d)
        _append("D", day.strftime("%m/%d"), max_combos=4)

    return rows


def _make_eqp_loss_rows():
    rows = []
    start = datetime.date(2026, 3, 1)
    end   = datetime.date(2026, 4, 14)
    lot_counter = 5000

    for d in range((end - start).days + 1):
        day      = start + datetime.timedelta(days=d)
        yyyymmdd = day.strftime("%Y%m%d")

        for line, equips in EQP_MAP.items():
            sdwt = SDWT_MAP[line]
            active = random.sample(equips, k=random.randint(1, len(equips)))

            for eqp_id, eqp_model, unit_id in active:
                n = random.randint(1, 5)
                for _ in range(n):
                    h, m, s = random.randint(6,22), random.randint(0,59), random.randint(0,59)
                    act_time   = f"{day} {h:02d}:{m:02d}:{s:02d}"
                    param_type = _weighted_param_type(line)   # 라인별 가중치 적용
                    param_name = random.choice(PARAM_NAMES_MAP[param_type])
                    loss_time  = round(random.uniform(5, 120), 2)
                    lot_id     = f"LOT-{lot_counter:04d}"
                    lot_counter += 1

                    rows.append((
                        yyyymmdd, act_time, line, sdwt,
                        eqp_id, unit_id, eqp_model,
                        param_type, param_name,
                        loss_time, lot_id,
                    ))
    return rows


def run():
    report_rows   = _make_report_rows()
    eqp_loss_rows = _make_eqp_loss_rows()

    with connection.cursor() as cur:
        cur.execute(DDL_REPORT)
        cur.execute(DDL_EQP_LOSS)
        cur.execute("DELETE FROM report_stoploss")
        cur.execute("DELETE FROM eqp_loss_tpm")

        cur.executemany(
            """INSERT INTO report_stoploss
               (yyyy,flag,flagdate,line,sdwt_prod,eqp_id,eqp_model,plan_time,stoploss,pm,qual,bm,rank)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(r["yyyy"],r["flag"],r["flagdate"],r["line"],r["sdwt_prod"],
              r["eqp_id"],r["eqp_model"],r["plan_time"],r["stoploss"],
              r["pm"],r["qual"],r["bm"],r["rank"]) for r in report_rows],
        )

        cur.executemany(
            """INSERT INTO eqp_loss_tpm
               (yyyymmdd,act_time,line,sdwt_prod,eqp_id,unit_id,eqp_model,param_type,param_name,loss_time,lot_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            eqp_loss_rows,
        )

    print(f"report_stoploss  : {len(report_rows):,}행")
    print(f"eqp_loss_tpm     : {len(eqp_loss_rows):,}행")
    print("샘플 데이터 삽입 완료!")


if __name__ == "__main__":
    run()
