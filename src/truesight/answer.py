"""The final answer, submitted through the submit_answer output tool."""

import re
from collections.abc import Collection
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TOOL_FIELD = (
    "Name of the tool you called whose output showed this, optionally followed by its "
    "arguments, e.g. GetLogs checkout."
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Location(_Frozen):
    kind: Literal["code", "config", "change", "resource", "dependency", "other"]
    address: str = Field(
        min_length=1, description="File and line, config key, commit, or resource name."
    )


class Evidence(_Frozen):
    tool: str = Field(min_length=1, description=TOOL_FIELD)
    finding: str = Field(min_length=1, description="What its output showed, quoted where possible.")


class RuledOut(_Frozen):
    explanation: str = Field(min_length=1)
    tool: str = Field(min_length=1, description=TOOL_FIELD)
    reason: str = Field(min_length=1)


class Answer(_Frozen):
    status: Literal["established", "not_established"] = Field(
        description="established if tool output shows how the cause produces the "
        "symptom and something else was ruled out; not_established if any link is "
        "inferred rather than seen. Either way, fill the other fields with your leading "
        "candidate."
    )
    summary: str = Field(
        min_length=1,
        description="One sentence: what is wrong and where. If not established, "
        "say what is missing.",
    )
    component: str = Field(
        min_length=1, description="The thing at fault, named as the system names it."
    )
    fault_type: str = Field(min_length=1, description="A short label for the kind of fault.")
    location: Location = Field(
        description="Where the fault is, as precisely as the evidence allows."
    )
    mechanism: str = Field(min_length=1, description="How the fault produces the symptom.")
    evidence: tuple[Evidence, ...] = Field(
        min_length=1, description="What tool output showed the fault."
    )
    ruled_out: tuple[RuledOut, ...] = Field(
        description="Other explanations you checked and why each was dropped."
    )


def answer_error(answer: Answer, called: Collection[str]) -> str | None:
    if answer.status == "established" and not answer.ruled_out:
        return (
            "ruled_out: empty, so nothing else was excluded; rule an explanation out "
            "or set status to not_established"
        )
    for field in ("evidence", "ruled_out"):
        for i, item in enumerate(getattr(answer, field)):
            name = re.match(r"[\w.-]*", item.tool.strip()).group()
            if name not in called:
                return (
                    f"{field}.{i}.tool: {item.tool!r} does not name a tool you called; "
                    f"tools called: {', '.join(sorted(called)) or 'none'}"
                )
    return None
