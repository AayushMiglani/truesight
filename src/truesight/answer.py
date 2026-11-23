"""The final answer: a submit_answer tool whose schema is also the validation rule."""

from dataclasses import dataclass
from typing import Literal

from jsonschema import Draft202012Validator

from truesight.tools import Tool

LOCATION_KINDS = ("code", "config", "change", "resource", "dependency", "other")

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "status",
        "summary",
        "component",
        "fault_type",
        "location",
        "mechanism",
        "evidence",
        "ruled_out",
    ],
    "properties": {
        "status": {
            "type": "string",
            "enum": ["established", "not_established"],
            "description": "established if the evidence shows how the cause produces the "
            "symptom; not_established otherwise.",
        },
        "summary": {
            "type": "string",
            "minLength": 1,
            "description": "One sentence: what is wrong and where. If not established, "
            "say what is missing.",
        },
        "component": {
            "type": "string",
            "minLength": 1,
            "description": "The thing at fault, named as the system names it.",
        },
        "fault_type": {
            "type": "string",
            "minLength": 1,
            "description": "A short label for the kind of fault.",
        },
        "location": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "address"],
            "description": "Where the fault is, as precisely as the evidence allows.",
            "properties": {
                "kind": {"type": "string", "enum": list(LOCATION_KINDS)},
                "address": {
                    "type": "string",
                    "minLength": 1,
                    "description": "File and line, config key, commit, or resource name.",
                },
            },
        },
        "mechanism": {
            "type": "string",
            "minLength": 1,
            "description": "How the fault produces the symptom.",
        },
        "evidence": {
            "type": "array",
            "minItems": 1,
            "description": "What tool output showed the fault.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["tool", "finding"],
                "properties": {
                    "tool": {"type": "string", "minLength": 1, "description": "The tool call."},
                    "finding": {
                        "type": "string",
                        "minLength": 1,
                        "description": "What its output showed, quoted where possible.",
                    },
                },
            },
        },
        "ruled_out": {
            "type": "array",
            "description": "Other explanations you checked and why each was dropped.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["explanation", "reason"],
                "properties": {
                    "explanation": {"type": "string", "minLength": 1},
                    "reason": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}

_VALIDATOR = Draft202012Validator(SCHEMA)


@dataclass(frozen=True)
class Location:
    kind: str
    address: str


@dataclass(frozen=True)
class Evidence:
    tool: str
    finding: str


@dataclass(frozen=True)
class RuledOut:
    explanation: str
    reason: str


@dataclass(frozen=True)
class Answer:
    status: Literal["established", "not_established"]
    summary: str
    component: str
    fault_type: str
    location: Location
    mechanism: str
    evidence: tuple[Evidence, ...]
    ruled_out: tuple[RuledOut, ...]


def parse_answer(arguments: dict) -> Answer:
    """Validate submit_answer arguments. Raises ValueError naming the first bad field."""
    errors = sorted(
        _VALIDATOR.iter_errors(arguments), key=lambda e: [str(p) for p in e.absolute_path]
    )
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.absolute_path) or "(root)"
        raise ValueError(f"{path}: {first.message}")
    return Answer(
        status=arguments["status"],
        summary=arguments["summary"],
        component=arguments["component"],
        fault_type=arguments["fault_type"],
        location=Location(**arguments["location"]),
        mechanism=arguments["mechanism"],
        evidence=tuple(Evidence(**item) for item in arguments["evidence"]),
        ruled_out=tuple(RuledOut(**item) for item in arguments["ruled_out"]),
    )


def _not_called(**_: object) -> str:
    raise RuntimeError("submit_answer is handled by the loop, not called")


SUBMIT_ANSWER = Tool(
    name="submit_answer",
    description="Finish the investigation with your answer. Call it once, when the evidence "
    "shows how the cause produces the symptom or when more tool calls cannot change your answer.",
    parameters=SCHEMA,
    function=_not_called,
)
