"""
seed_stoploss.py

테이블:
  report_stoploss  → StoplossReport 모델
  tpm_eqp_loss     → TpmEqpLoss 모델

컬럼 매핑 (모델 ↔ DB):
  StoplossReport.eqp_id    ← DB: station
  StoplossReport.eqp_model ← DB: machine_id
  TpmEqpLoss.eqp_id        ← DB: station

실행:
  python seed_stoploss.py
"""

import os
import random
import datetime

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.db import connections, connection as default_conn

random.seed(99)

# ─── DB 연결 판별 ─────────────────────────────────────────────────
# "tpm" DB(MySQL)에 연결 가능하면 그쪽을 사용, 아니면 기본(SQLite) 사용
def _get_conn():
    try:
        c = connections["tpm"]
        c.ensure_connection()
        engine = c.settings_dict["ENGINE"]
        is_mysql = "mysql" in engine
        label = "tpm(MySQL)" if is_mysql else "tpm(SQLite)"
        print(f"[seed] {label} DB 사용")
        return c, is_mysql
    except Exception as e:
        print(f"[seed] tpm DB 연결 실패({e}), default(SQLite) 사용")
        return default_conn, False

conn, IS_MYSQL = _get_conn()

# ─── DDL ─────────────────────────────────────────────────────────

def _ddl_report():
    if IS_MYSQL:
        return """
        CREATE TABLE IF NOT EXISTS report_stoploss (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            yyyy       VARCHAR(4)   NOT NULL,
            flag       VARCHAR(1)   NOT NULL,
            flagdate   VARCHAR(10)  NOT NULL,
            area       VARCHAR(50)  NOT NULL DEFAULT '',
            sdwt_prod  VARCHAR(100) NOT NULL DEFAULT '',
            station    VARCHAR(100) NOT NULL DEFAULT '',
            machine_id VARCHAR(100) NOT NULL DEFAULT '',
            prc_group  VARCHAR(100) NOT NULL DEFAULT '',
            plan_time  DOUBLE       NOT NULL DEFAULT 0.0,
            stoploss   DOUBLE       NOT NULL DEFAULT 0.0,
            pm         DOUBLE       NOT NULL DEFAULT 0.0,
            qual       DOUBLE       NOT NULL DEFAULT 0.0,
            bm         DOUBLE       NOT NULL DEFAULT 0.0,
            eng        DOUBLE       NOT NULL DEFAULT 0.0,
            etc        DOUBLE       NOT NULL DEFAULT 0.0,
            stepchg    DOUBLE       NOT NULL DEFAULT 0.0,
            std_time   DOUBLE       NOT NULL DEFAULT 0.0,
            rd         DOUBLE       NOT NULL DEFAULT 0.0,
            `rank`     INT          NOT NULL DEFAULT 0
        ) CHARACTER SET utf8mb4
        """
    else:
        return """
        CREATE TABLE IF NOT EXISTS report_stoploss (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            yyyy       TEXT NOT NULL,
            flag       TEXT NOT NULL,
            flagdate   TEXT NOT NULL,
            area       TEXT NOT NULL DEFAULT '',
            sdwt_prod  TEXT NOT NULL DEFAULT '',
            station    TEXT NOT NULL DEFAULT '',
            machine_id TEXT NOT NULL DEFAULT '',
            prc_group  TEXT NOT NULL DEFAULT '',
            plan_time  REAL NOT NULL DEFAULT 0.0,
            stoploss   REAL NOT NULL DEFAULT 0.0,
            pm         REAL NOT NULL DEFAULT 0.0,
            qual       REAL NOT NULL DEFAULT 0.0,
            bm         REAL NOT NULL DEFAULT 0.0,
            eng        REAL NOT NULL DEFAULT 0.0,
            etc        REAL NOT NULL DEFAULT 0.0,
            stepchg    REAL NOT NULL DEFAULT 0.0,
            std_time   REAL NOT NULL DEFAULT 0.0,
            rd         REAL NOT NULL DEFAULT 0.0,
            rank       INTEGER NOT NULL DEFAULT 0
        )
        """


def _ddl_eqp_loss():
    if IS_MYSQL:
        return """
        CREATE TABLE IF NOT EXISTS tpm_eqp_loss (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            yyyymmdd     VARCHAR(10)  NOT NULL DEFAULT '',
            station      VARCHAR(100) NOT NULL DEFAULT '',
            start_time   VARCHAR(30)  NOT NULL DEFAULT '',
            end_time     VARCHAR(30)  NOT NULL DEFAULT '',
            state        VARCHAR(100) NOT NULL DEFAULT '',
            down_comment VARCHAR(255) NOT NULL DEFAULT ''
        ) CHARACTER SET utf8mb4
        """
    else:
        return """
        CREATE TABLE IF NOT EXISTS tpm_eqp_loss (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            yyyymmdd     TEXT NOT NULL DEFAULT '',
            station      TEXT NOT NULL DEFAULT '',
            start_time   TEXT NOT NULL DEFAULT '',
            end_time     TEXT NOT NULL DEFAULT '',
            state        TEXT NOT NULL DEFAULT '',
            down_comment TEXT NOT NULL DEFAULT ''
        )
        """


# ─── 마스터 데이터 ────────────────────────────────────────────────

YYYY = "2026"

# area → [(station, machine_id), ...]
EQP_MAP = {
    "A1": [
        ("EQP-101", "MODEL-X"), ("EQP-102", "MODEL-X"),
        ("EQP-103", "MODEL-Y"), ("EQP-104", "MODEL-Y"),
    ],
    "A2": [
        ("EQP-201", "MODEL-Y"), ("EQP-202", "MODEL-Y"),
        ("EQP-203", "MODEL-Z"), ("EQP-204", "MODEL-Z"),
    ],
    "A3": [
        ("EQP-301", "MODEL-Z"), ("EQP-302", "MODEL-W"),
        ("EQP-303", "MODEL-W"),
    ],
}
SDWT_MAP    = {"A1": "PROD-ALPHA", "A2": "PROD-BETA",  "A3": "PROD-GAMMA"}
PRC_GRP_MAP = {"A1": "DEPO",       "A2": "ETCH",        "A3": "CVD"}

# tpm_eqp_loss state 값 → 한국어 down_comment
STATE_COMMENT = {
    "MCC_TRIP":          "MCC 트립 발생으로 설비 정지",
    "OVERLOAD":          "모터 과부하 감지",
    "EMG_STOP":          "비상정지 버튼 발동",
    "DOOR_OPEN":         "안전 도어 오픈 감지",
    "TEMP_OOC":          "온도 파라미터 OOC 발생",
    "PRESSURE_OOC":      "압력 파라미터 OOC 발생",
    "PM_SCHEDULED":      "계획 예방보전 작업",
    "UNSCHEDULED_MAINT": "비계획 보전 작업 발생",
    "RECIPE_ERROR":      "레시피 실행 오류",
    "MATERIAL_WAIT":     "자재 공급 대기",
    "OPERATOR_STOP":     "작업자 임의 정지",
}

# area별 state 분포 가중치 (area마다 주로 발생하는 정지 유형이 다름)
AREA_STATE_WEIGHTS = {
    "A1": {"MCC_TRIP": 40, "OVERLOAD": 20, "EMG_STOP": 15,
           "PM_SCHEDULED": 15, "OPERATOR_STOP": 10},
    "A2": {"TEMP_OOC": 40, "PRESSURE_OOC": 25, "DOOR_OPEN": 15,
           "RECIPE_ERROR": 10, "MATERIAL_WAIT": 10},
    "A3": {"PM_SCHEDULED": 25, "UNSCHEDULED_MAINT": 25, "OPERATOR_STOP": 25,
           "RECIPE_ERROR": 15, "DOOR_OPEN": 10},
}

def _weighted_state(area: str) -> str:
    weights = AREA_STATE_WEIGHTS.get(area, {s: 10 for s in STATE_COMMENT})
    population = [s for s, w in weights.items() for _ in range(w)]
    return random.choice(population)


# ─── report_stoploss 행 생성 ──────────────────────────────────────

def _make_report_rows():
    rows = []

    def _append(flag, flagdate, max_combos=5):
        combos = []
        for area, equips in EQP_MAP.items():
            for station, machine_id in equips[:2]:
                combos.append((area, station, machine_id))
        random.shuffle(combos)
        combos = combos[:max_combos]

        for rank, (area, station, machine_id) in enumerate(combos, start=1):
            plan_time = random.uniform(600, 1440)
            stoploss  = random.uniform(10, plan_time * 0.3)

            # 손실 시간을 9개 컬럼에 랜덤 분배
            fracs = [random.random() for _ in range(9)]
            total = sum(fracs)
            pm, qual, bm, eng, etc, stepchg, std_time, rd, _ = [
                round(stoploss * f / total, 2) for f in fracs
            ]

            rows.append((
                YYYY, flag, flagdate,
                area,
                SDWT_MAP[area],
                station,
                machine_id,
                PRC_GRP_MAP[area],
                round(plan_time, 2),
                round(stoploss, 2),
                pm, qual, bm, eng, etc, stepchg, std_time, rd,
                rank,
            ))

    for m in range(1, 5):
        _append("M", f"M{m:02d}")
    for w in range(1, 17):
        _append("W", f"W{w:02d}")
    base = datetime.date(2026, 4, 1)
    for d in range(14):
        day = base + datetime.timedelta(days=d)
        _append("D", day.strftime("%m/%d"), max_combos=4)

    return rows


# ─── tpm_eqp_loss 행 생성 ────────────────────────────────────────

def _make_eqp_loss_rows():
    rows = []
    start_date = datetime.date(2026, 1, 1)   # report_stoploss M01(1월)부터 커버
    end_date   = datetime.date(2026, 4, 14)

    for d in range((end_date - start_date).days + 1):
        day      = start_date + datetime.timedelta(days=d)
        yyyymmdd = day.strftime("%Y%m%d")

        for area, equips in EQP_MAP.items():
            active = random.sample(equips, k=random.randint(1, len(equips)))

            for station, _ in active:
                n = random.randint(1, 5)
                for _ in range(n):
                    # 정지 시작시각 (06:00 ~ 22:00 사이)
                    h   = random.randint(6, 21)
                    m   = random.randint(0, 59)
                    s   = random.randint(0, 59)
                    dt_start = datetime.datetime(day.year, day.month, day.day, h, m, s)

                    # 정지 지속시간: 5 ~ 120분
                    duration_min = random.uniform(5, 120)
                    dt_end = dt_start + datetime.timedelta(minutes=duration_min)

                    state        = _weighted_state(area)
                    down_comment = STATE_COMMENT[state]

                    rows.append((
                        yyyymmdd,
                        station,
                        dt_start.strftime("%Y-%m-%d %H:%M:%S"),
                        dt_end.strftime("%Y-%m-%d %H:%M:%S"),
                        state,
                        down_comment,
                    ))

    return rows


# ─── 실행 ─────────────────────────────────────────────────────────

def run():
    report_rows   = _make_report_rows()
    eqp_loss_rows = _make_eqp_loss_rows()

    ph = "%s" if IS_MYSQL else "?"   # placeholder

    with conn.cursor() as cur:
        # 구 테이블 정리 (스키마 변경된 경우를 대비)
        cur.execute("DROP TABLE IF EXISTS tpm_eqp_loss")
        cur.execute("DROP TABLE IF EXISTS report_stoploss")

        cur.execute(_ddl_report())
        cur.execute(_ddl_eqp_loss())

        # report_stoploss INSERT
        # 컬럼 수: yyyy flag flagdate area sdwt_prod station machine_id prc_group
        #           plan_time stoploss pm qual bm eng etc stepchg std_time rd rank = 19
        sql_report = (
            f"INSERT INTO report_stoploss"
            f" (yyyy, flag, flagdate,"
            f"  area, sdwt_prod, station, machine_id, prc_group,"
            f"  plan_time,"
            f"  stoploss, pm, qual, bm, eng, etc, stepchg, std_time, rd,"
            f"  {'`rank`' if IS_MYSQL else 'rank'})"
            f" VALUES ({','.join([ph]*19)})"
        )
        cur.executemany(sql_report, report_rows)

        # tpm_eqp_loss INSERT
        cur.executemany(
            f"""INSERT INTO tpm_eqp_loss
                (yyyymmdd, station, start_time, end_time, state, down_comment)
               VALUES ({",".join([ph]*6)})""",
            eqp_loss_rows,
        )

    print(f"report_stoploss : {len(report_rows):,}행")
    print(f"tpm_eqp_loss    : {len(eqp_loss_rows):,}행")
    print("샘플 데이터 삽입 완료!")


if __name__ == "__main__":
    run()
