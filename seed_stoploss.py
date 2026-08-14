"""
seed_stoploss.py

테이블:
  report_stoploss  → StoplossReport 모델
  tpm_eqp_loss     → TpmEqpLoss 모델

컬럼 매핑 (모델 ↔ DB):
  StoplossReport.eqp_id    ← DB: station
  StoplossReport.eqp_model ← DB: machine_id
  TpmEqpLoss.eqp_id        ← DB: eqp_id   (station 과 별개 컬럼 — 값도 다르게 생성)
  TpmEqpLoss.station       ← DB: station  (설비)

tpm_eqp_loss 생성 컬럼:
  yyyymmdd, station, eqp_id, area, start_time, end_time,
  state, kind, param_type, param_name, loss_time_min, down_comment
  · loss_time_min 은 적재측 규칙과 동일하게 (end - start) 분, 소수 1자리로 채운다.
  · param_type / param_name 이 빈 state 도 섞어 "(미분류)" 집계를 확인할 수 있다.

날짜 기준:
  실행 시점(오늘) 기준으로 최근 구간을 만든다.
  M = 최근 4개월 / W = 최근 16주 / D = 최근 14일,
  tpm_eqp_loss 는 그 전체 구간을 커버한다.
  (lossraw 페이지의 기본 기간이 "최근 3개월" 이라 고정 연도로 두면 빈 화면이 된다)

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
            id            INT AUTO_INCREMENT PRIMARY KEY,
            yyyymmdd      VARCHAR(10)  NOT NULL DEFAULT '',
            station       VARCHAR(100) NOT NULL DEFAULT '',
            eqp_id        VARCHAR(100) NOT NULL DEFAULT '',
            area          VARCHAR(100) NOT NULL DEFAULT '',
            start_time    VARCHAR(30)  NOT NULL DEFAULT '',
            end_time      VARCHAR(30)  NOT NULL DEFAULT '',
            state         VARCHAR(100) NOT NULL DEFAULT '',
            kind          VARCHAR(100) NOT NULL DEFAULT '',
            param_type    VARCHAR(100) NOT NULL DEFAULT '',
            param_name    VARCHAR(100) NOT NULL DEFAULT '',
            loss_time_min DOUBLE       NOT NULL DEFAULT 0.0,
            down_comment  VARCHAR(255) NOT NULL DEFAULT ''
        ) CHARACTER SET utf8mb4
        """
    else:
        return """
        CREATE TABLE IF NOT EXISTS tpm_eqp_loss (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            yyyymmdd      TEXT NOT NULL DEFAULT '',
            station       TEXT NOT NULL DEFAULT '',
            eqp_id        TEXT NOT NULL DEFAULT '',
            area          TEXT NOT NULL DEFAULT '',
            start_time    TEXT NOT NULL DEFAULT '',
            end_time      TEXT NOT NULL DEFAULT '',
            state         TEXT NOT NULL DEFAULT '',
            kind          TEXT NOT NULL DEFAULT '',
            param_type    TEXT NOT NULL DEFAULT '',
            param_name    TEXT NOT NULL DEFAULT '',
            loss_time_min REAL NOT NULL DEFAULT 0.0,
            down_comment  TEXT NOT NULL DEFAULT ''
        )
        """


# ─── 마스터 데이터 ────────────────────────────────────────────────

# 실행 시점 기준으로 최근 구간을 만든다 (lossraw 기본 기간 = 최근 3개월)
TODAY = datetime.date.today()
YYYY  = str(TODAY.year)


def _week_num(d: datetime.date) -> int:
    """get_date_range 와 같은 규칙: 1/1 부터 경과일 // 7 + 1"""
    return (d - datetime.date(d.year, 1, 1)).days // 7 + 1


def _recent_months(n=4):
    """올해 범위 안에서 최근 n개월 flagdate ("M08" 형식)."""
    first = max(1, TODAY.month - n + 1)
    return [f"M{m:02d}" for m in range(first, TODAY.month + 1)]


def _recent_weeks(n=16):
    """올해 범위 안에서 최근 n주 flagdate ("W33" 형식)."""
    cur = _week_num(TODAY)
    return [f"W{w:02d}" for w in range(max(1, cur - n + 1), cur + 1)]


def _recent_days(n=14):
    """올해 범위 안에서 최근 n일 (date 객체)."""
    days = [TODAY - datetime.timedelta(days=i) for i in range(n - 1, -1, -1)]
    return [d for d in days if d.year == TODAY.year]


def _loss_period():
    """tpm_eqp_loss 생성 구간 = 최근 4개월의 1일 ~ 오늘."""
    first_month = int(_recent_months()[0][1:])
    return datetime.date(TODAY.year, first_month, 1), TODAY

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

# tpm_eqp_loss state → (kind, param_type, param_name)
# kind 는 Loss Raw 페이지 A 차트(=화면 표기 State)의 집계 기준이다.
# param 이 빈 state 를 일부 섞어 "(미분류)" 집계를 확인할 수 있게 한다.
STATE_META = {
    "MCC_TRIP":          ("DOWN",  "ERD",  "MCC_TRIP"),
    "OVERLOAD":          ("DOWN",  "ERD",  "OVERLOAD"),
    "EMG_STOP":          ("DOWN",  "ERD",  "EMG_STOP"),
    "DOOR_OPEN":         ("DOWN",  "ERD",  "DOOR_OPEN"),
    "TEMP_OOC":          ("QUAL",  "SPC",  "TEMP_OOC"),
    "PRESSURE_OOC":      ("QUAL",  "SPC",  "PRESSURE_OOC"),
    "PM_SCHEDULED":      ("PM",    "PLAN", "PM_WEEKLY"),
    "UNSCHEDULED_MAINT": ("BM",    "PLAN", "BM_URGENT"),
    "RECIPE_ERROR":      ("SETUP", "RCP",  "RECIPE_ERROR"),
    "MATERIAL_WAIT":     ("ETC",   "",     ""),   # param 없음 → "(미분류)"
    "OPERATOR_STOP":     ("ETC",   "",     ""),   # param 없음 → "(미분류)"
}

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

    for flagdate in _recent_months():
        _append("M", flagdate)
    for flagdate in _recent_weeks():
        _append("W", flagdate)
    for day in _recent_days():
        _append("D", day.strftime("%m/%d"), max_combos=4)

    return rows


# ─── tpm_eqp_loss 행 생성 ────────────────────────────────────────

def _make_eqp_loss_rows():
    """
    report_stoploss 가 커버하는 전체 구간의 정지 이벤트 로그.

    · eqp_id  : report_stoploss.station 과 같은 값 (EQP-101) — 두 테이블 조인 키
    · station : 설비 코드 (STN-101) — eqp_id 와 다른 값으로 생성한다
                (두 컬럼은 추후 서로 다른 값을 갖게 될 예정)
    · loss_time_min : 적재측 규칙과 동일하게 (end - start) 분, 소수 1자리
    """
    rows = []
    start_date, end_date = _loss_period()

    for d in range((end_date - start_date).days + 1):
        day      = start_date + datetime.timedelta(days=d)
        yyyymmdd = day.strftime("%Y%m%d")

        for area, equips in EQP_MAP.items():
            active = random.sample(equips, k=random.randint(1, len(equips)))

            for eqp_id, _ in active:
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
                    kind, param_type, param_name = STATE_META[state]

                    rows.append((
                        yyyymmdd,
                        eqp_id.replace("EQP-", "STN-"),   # station (설비)
                        eqp_id,                           # eqp_id
                        area,
                        dt_start.strftime("%Y-%m-%d %H:%M:%S"),
                        dt_end.strftime("%Y-%m-%d %H:%M:%S"),
                        state,
                        kind,
                        param_type,
                        param_name,
                        round(duration_min, 1),           # loss_time_min
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

        # tpm_eqp_loss INSERT (12 컬럼)
        cur.executemany(
            f"""INSERT INTO tpm_eqp_loss
                (yyyymmdd, station, eqp_id, area, start_time, end_time,
                 state, kind, param_type, param_name, loss_time_min, down_comment)
               VALUES ({",".join([ph]*12)})""",
            eqp_loss_rows,
        )

    start_date, end_date = _loss_period()
    print(f"report_stoploss : {len(report_rows):,}행 "
          f"(M={','.join(_recent_months())} / W={len(_recent_weeks())}주 / D={len(_recent_days())}일)")
    print(f"tpm_eqp_loss    : {len(eqp_loss_rows):,}행 ({start_date} ~ {end_date})")
    print("샘플 데이터 삽입 완료!")


if __name__ == "__main__":
    run()
