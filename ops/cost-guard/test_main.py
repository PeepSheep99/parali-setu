import base64
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from google.cloud import run_v2

# Loaded by path under its own name: the API also has a main.py, and a plain
# `import main` would pick up whichever one pytest imported first.
_spec = importlib.util.spec_from_file_location("cost_guard_main", Path(__file__).with_name("main.py"))
main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(main)


def _encoded(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _event(payload: dict):
    event = MagicMock()
    event.data = {"message": {"data": _encoded(payload)}}
    return event


REAL_MONEY = {"budgetDisplayName": "Parali Setu - REAL money (net)", "budgetAmount": 100.0, "currencyCode": "INR"}


def test_parse_budget_message_roundtrip():
    assert main.parse_budget_message(_encoded({"costAmount": 1.5}))["costAmount"] == 1.5


@pytest.mark.parametrize(
    "notification, expected",
    [
        ({**REAL_MONEY, "costAmount": 100.0}, True),     # at budget -> act
        ({**REAL_MONEY, "costAmount": 250.0}, True),     # over budget -> act
        ({**REAL_MONEY, "costAmount": 99.99}, False),    # under budget -> no action
        ({**REAL_MONEY, "costAmount": "garbage"}, False),
        ({"budgetDisplayName": "Parali Setu - credit burn (gross)", "budgetAmount": 13000, "costAmount": 20000}, False),
        ({**REAL_MONEY, "budgetAmount": 0, "costAmount": 5}, False),
    ],
)
def test_should_throttle_only_on_trigger_budget_over_amount(notification, expected):
    assert main.should_throttle(notification) is expected


def test_dry_run_touches_nothing():
    run_client, usage_client = MagicMock(), MagicMock()
    actions = main.throttle(run_client, usage_client, dry_run=True)
    run_client.get_service.assert_not_called()
    run_client.update_service.assert_not_called()
    usage_client.disable_service.assert_not_called()
    assert actions["dry_run"] is True
    assert actions["ingress_internal"] == main.SERVICES


def test_real_run_sets_internal_ingress_and_disables_apis():
    run_client, usage_client = MagicMock(), MagicMock()
    services = []

    def fresh_public_service(name):
        svc = MagicMock()
        svc.ingress = run_v2.IngressTraffic.INGRESS_TRAFFIC_ALL
        services.append(svc)
        return svc

    run_client.get_service.side_effect = fresh_public_service

    actions = main.throttle(run_client, usage_client, dry_run=False)

    assert run_client.update_service.call_count == len(main.SERVICES)
    assert all(s.ingress == run_v2.IngressTraffic.INGRESS_TRAFFIC_INTERNAL_ONLY for s in services)
    assert actions["ingress_internal"] == main.SERVICES
    disabled = [c.kwargs["request"]["name"].rsplit("/", 1)[-1] for c in usage_client.disable_service.call_args_list]
    assert disabled == main.APIS_TO_DISABLE
    assert actions["apis_disabled"] == main.APIS_TO_DISABLE


def test_real_run_skips_services_already_internal():
    run_client, usage_client = MagicMock(), MagicMock()
    service = MagicMock()
    service.ingress = run_v2.IngressTraffic.INGRESS_TRAFFIC_INTERNAL_ONLY
    run_client.get_service.return_value = service

    actions = main.throttle(run_client, usage_client, dry_run=False)

    run_client.update_service.assert_not_called()
    assert actions["ingress_internal"] == []


def test_handler_ignores_gross_budget(monkeypatch, capsys):
    called = MagicMock()
    monkeypatch.setattr(main, "throttle", called)
    main.handle_budget_alert(_event({"budgetDisplayName": "Parali Setu - credit burn (gross)", "budgetAmount": 13000, "costAmount": 99999}))
    called.assert_not_called()
    assert "no action" in capsys.readouterr().out


def test_dry_run_is_the_default(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    assert main._dry_run() is True
    monkeypatch.setenv("DRY_RUN", "false")
    assert main._dry_run() is False
