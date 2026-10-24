from types import SimpleNamespace

import mlflow
import pandas as pd

from optpred.zoo import promote as P


class Reg:
    def __init__(self, champion=None):
        self.alias = {"champion": champion} if champion else {}
        self.tags = {}

    def get_model_version_by_alias(self, name, alias):
        if alias not in self.alias:
            raise mlflow.exceptions.MlflowException("no alias")
        return SimpleNamespace(version=self.alias[alias])

    def set_registered_model_alias(self, name, alias, version):
        self.alias[alias] = version

    def set_model_version_tag(self, name, version, key, value):
        self.tags[(version, key)] = value


def test_failed_smoke_test_is_not_deployed(monkeypatch):
    monkeypatch.setattr(P, "smoke_test", lambda *a: "load/predict failed")
    reg = Reg(champion="1")
    out = P.promote(reg, "m", "2", pd.DataFrame())
    assert (
        not out["deployed"] and reg.alias == {"champion": "1"} and reg.tags[("2", "deploy_check")] == "failed"
    )


def test_passed_version_becomes_champion_and_old_one_previous(monkeypatch):
    monkeypatch.setattr(P, "smoke_test", lambda *a: None)
    reg = Reg(champion="1")
    out = P.promote(reg, "m", "2", pd.DataFrame())
    assert out["deployed"] and reg.alias == {"champion": "2", "previous": "1"}


def test_first_deployment_has_no_previous(monkeypatch):
    monkeypatch.setattr(P, "smoke_test", lambda *a: None)
    reg = Reg()
    P.promote(reg, "m", "1", pd.DataFrame())
    assert reg.alias == {"champion": "1"}
