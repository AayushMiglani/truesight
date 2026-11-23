import pytest

from truesight.answer import SUBMIT_ANSWER, Answer, Evidence, Location, RuledOut, parse_answer

VALID = {
    "status": "established",
    "summary": "The payments Service selector matches no pods.",
    "component": "app/payments",
    "fault_type": "service_selector_mismatch",
    "location": {"kind": "config", "address": "Service payments spec.selector app=payment"},
    "mechanism": "No endpoints, so callers get connection refused.",
    "evidence": [{"tool": "GetResources endpoints", "finding": "payments   <none>"}],
    "ruled_out": [{"explanation": "pod crash", "reason": "pods Running, 0 restarts"}],
}


def test_valid_arguments_become_an_answer():
    assert parse_answer(VALID) == Answer(
        status="established",
        summary="The payments Service selector matches no pods.",
        component="app/payments",
        fault_type="service_selector_mismatch",
        location=Location("config", "Service payments spec.selector app=payment"),
        mechanism="No endpoints, so callers get connection refused.",
        evidence=(Evidence("GetResources endpoints", "payments   <none>"),),
        ruled_out=(RuledOut("pod crash", "pods Running, 0 restarts"),),
    )


def test_not_established_is_allowed_with_empty_ruled_out():
    answer = parse_answer({**VALID, "status": "not_established", "ruled_out": []})
    assert answer.status == "not_established"
    assert answer.ruled_out == ()


@pytest.mark.parametrize(
    ("change", "path"),
    [
        ({"status": "maybe"}, "status"),
        ({"location": {"kind": "config"}}, "location"),
        ({"location": {"kind": "vibes", "address": "x"}}, "location.kind"),
        ({"evidence": []}, "evidence"),
        ({"extra": 1}, "(root)"),
        ({"summary": ""}, "summary"),
        ({"evidence": [{"tool": "x", "finding": ""}]}, "evidence.0.finding"),
    ],
)
def test_invalid_arguments_name_the_field(change, path):
    with pytest.raises(ValueError, match=rf"^{path.replace('(', '[(]').replace(')', '[)]')}:"):
        parse_answer({**VALID, **change})


def test_missing_field_is_reported():
    args = {k: v for k, v in VALID.items() if k != "mechanism"}
    with pytest.raises(ValueError, match="mechanism"):
        parse_answer(args)


def test_tool_schema_is_the_validation_schema():
    assert SUBMIT_ANSWER.name == "submit_answer"
    assert set(SUBMIT_ANSWER.parameters["required"]) == set(VALID)
