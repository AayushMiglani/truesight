import pytest
from pydantic import ValidationError

from truesight.answer import Answer, answer_error

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
CALLED = {"GetResources", "GetPods"}


def answer(**change) -> Answer:
    return Answer.model_validate({**VALID, **change})


def test_not_established_is_allowed_with_empty_ruled_out():
    assert answer_error(answer(status="not_established", ruled_out=[]), CALLED) is None


@pytest.mark.parametrize(
    ("change", "loc"),
    [
        ({"status": "maybe"}, ("status",)),
        ({"location": {"kind": "config"}}, ("location", "address")),
        ({"location": {"kind": "vibes", "address": "x"}}, ("location", "kind")),
        ({"evidence": []}, ("evidence",)),
        ({"extra": 1}, ("extra",)),
        ({"summary": ""}, ("summary",)),
        ({"evidence": [{"tool": "x", "finding": ""}]}, ("evidence", 0, "finding")),
        ({"ruled_out": [{"explanation": "x", "reason": "y"}]}, ("ruled_out", 0, "tool")),
    ],
)
def test_invalid_arguments_name_the_field(change, loc):
    with pytest.raises(ValidationError) as info:
        answer(**change)
    assert info.value.errors()[0]["loc"] == loc


def test_established_needs_something_ruled_out():
    assert answer_error(answer(ruled_out=[]), CALLED).startswith("ruled_out: ")
    assert "not_established" in answer_error(answer(ruled_out=[]), CALLED)


def test_entries_must_name_a_called_tool():
    assert answer_error(answer(), CALLED) is None
    error = answer_error(answer(), {"GetPods", "GetLogs"})
    assert error.startswith("evidence.0.tool: ")
    assert error.endswith("called: GetLogs, GetPods")


def test_ruled_out_tool_must_have_been_called():
    assert answer_error(answer(), {"GetResources"}).startswith("ruled_out.0.tool: ")


@pytest.mark.parametrize("cited", ["GetPods; GetLogs x", "GetPods, GetLogs", "GetPods+GetLogs"])
def test_an_entry_citing_several_tools_is_checked_by_the_first(cited):
    assert answer_error(answer(evidence=[{"tool": cited, "finding": "x"}]), CALLED) is None
