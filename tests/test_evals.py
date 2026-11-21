import json
from pathlib import Path

from truesight.evals import grade, load_case

L01 = Path(__file__).resolve().parent.parent / "evals" / "cases" / "L01"


def test_correct_report_passes():
    case = load_case(L01)
    report = (
        "Deploy d-449 set DB_POOL_SIZE from 20 to 2 on checkout-api. "
        "The connection pool then hit a timeout, and POST /v1/checkout returned 500."
    )
    result = grade(report, case)
    assert result.passed is True
    assert result.reason == "mentions the required evidence and does not name the decoy"


def test_report_missing_a_keyword_fails():
    case = load_case(L01)
    report = "The connection pool hit a timeout and checkout-api returned 500."
    result = grade(report, case)
    assert result.passed is False
    assert result.reason == "missing keyword: db_pool_size"


def test_report_blaming_the_decoy_fails():
    case = load_case(L01)
    report = (
        "catalog-service caused the checkout-api errors. "
        "It cut DB_POOL_SIZE, so the connection pool hit a timeout."
    )
    result = grade(report, case)
    assert result.passed is False
    assert result.reason == "names the decoy: catalog-service"


def test_l01_loads():
    case = load_case(L01)
    assert case.name == "L01"
    assert "5xx" in case.incident
    assert "checkout-api" in case.incident
    lines = case.logs.splitlines()
    assert 20 <= len(lines) <= 40
    for line in lines:
        entry = json.loads(line)
        assert entry["service"]
        assert entry["msg"]
    deploys = json.loads(case.deploys)
    assert len(deploys) == 3
    assert "db_pool_size" in case.deploys
    assert "catalog-service" in case.deploys
    assert "connection pool" in case.root_cause
    assert "db_pool_size" in case.root_cause
    assert case.must_mention == ["connection pool", "timeout", "db_pool_size"]
    assert case.decoy == ["catalog-service", "d-448"]
