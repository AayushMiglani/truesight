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
    "ruled_out": [
        {"explanation": "pod crash", "tool": "GetPods", "reason": "pods Running, 0 restarts"}
    ],
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
        ruled_out=(RuledOut("pod crash", "GetPods", "pods Running, 0 restarts"),),
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
        ({"ruled_out": [{"explanation": "x", "reason": "y"}]}, "ruled_out.0"),
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


def test_established_needs_something_ruled_out():
    with pytest.raises(ValueError, match="^ruled_out: .*not_established"):
        parse_answer({**VALID, "ruled_out": []})


def test_entries_must_name_a_called_tool():
    """The tool field starts with the tool's name; arguments may follow it."""
    assert parse_answer(VALID, called={"GetResources", "GetPods"}).component == "app/payments"
    with pytest.raises(ValueError, match=r"^evidence\.0\.tool: .*called: GetLogs, GetPods$"):
        parse_answer(VALID, called={"GetPods", "GetLogs"})


def test_ruled_out_tool_must_have_been_called():
    with pytest.raises(ValueError, match=r"^ruled_out\.0\.tool: "):
        parse_answer(VALID, called={"GetResources"})


@pytest.mark.parametrize("cited", ["GetPods; GetLogs x", "GetPods, GetLogs", "GetPods+GetLogs"])
def test_an_entry_citing_several_tools_is_checked_by_the_first(cited):
    args = {**VALID, "evidence": [{"tool": cited, "finding": "x"}]}
    assert parse_answer(args, called={"GetPods", "GetResources"}).evidence[0].tool == cited
