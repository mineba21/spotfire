"""
config/db_router.py

역할:
  stoploss_ai 앱의 모든 모델을 "tpm" DB alias 로 자동 라우팅한다.
  interlock_ai, admin, auth 등 나머지는 모두 "default" DB 를 사용한다.

DB alias:
  default → interlock 데이터 (report_interlock, interlock_raw 등)
  tpm     → stoploss 데이터 (report_stoploss, eqp_loss_tpm 등)

등록 방법 (settings.py):
  DATABASE_ROUTERS = ["config.db_router.TpmRouter"]

주의:
  managed = False 모델은 migrate 없이 사용하므로
  allow_migrate() 는 항상 False 를 반환해도 무방하다.
  (Django 가 stoploss_ai 테이블을 직접 생성/변경하지 않음)
"""


class TpmRouter:
    """
    stoploss_ai 앱 → "tpm" DB
    그 외 모든 앱  → "default" DB
    """

    # stoploss_ai 앱의 모델이 속한 app_label
    STOPLOSS_APP = "stoploss_ai"
    # tpm DB alias
    TPM_DB = "tpm"

    def db_for_read(self, model, **hints):
        """읽기 쿼리: stoploss_ai 면 tpm, 아니면 default"""
        if model._meta.app_label == self.STOPLOSS_APP:
            return self.TPM_DB
        return None   # None → Django 가 다음 라우터 또는 default 사용

    def db_for_write(self, model, **hints):
        """쓰기 쿼리: stoploss_ai 면 tpm, 아니면 default"""
        if model._meta.app_label == self.STOPLOSS_APP:
            return self.TPM_DB
        return None

    def allow_relation(self, obj1, obj2, **hints):
        """
        Cross-DB relation 허용 여부.
        stoploss_ai ↔ 다른 앱 간의 FK 는 없으므로
        같은 DB 끼리만 허용한다.
        """
        db_set = {self.TPM_DB, "default"}
        if (
            obj1._meta.app_label == self.STOPLOSS_APP
            and obj2._meta.app_label == self.STOPLOSS_APP
        ):
            return True
        if (
            obj1._meta.app_label != self.STOPLOSS_APP
            and obj2._meta.app_label != self.STOPLOSS_APP
        ):
            return True
        return False

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        managed = False 이므로 stoploss_ai 는 migrate 하지 않는다.
        다른 앱은 default DB 에서만 migrate 허용.
        """
        if app_label == self.STOPLOSS_APP:
            return False   # tpm DB 에 대해 migrate 안 함
        if db == self.TPM_DB:
            return False   # tpm DB 에는 다른 앱도 migrate 안 함
        return None        # default → Django 기본 동작