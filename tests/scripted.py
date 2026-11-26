from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

ARGS = {
    "status": "established",
    "summary": "disk filled by logs",
    "component": "disk",
    "fault_type": "full",
    "location": {"kind": "resource", "address": "/var/log on db-1"},
    "mechanism": "log rotation stopped, disk filled",
    "evidence": [{"tool": "echo", "finding": "95%"}],
    "ruled_out": [{"explanation": "inode exhaustion", "tool": "echo", "reason": "1% inodes"}],
}


def call(name: str, args: dict, call_id: str = "call-1") -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(name, args, tool_call_id=call_id)])


def submit(args: dict = ARGS, call_id: str = "final") -> ModelResponse:
    return call("submit_answer", args, call_id)


class Scripted(FunctionModel):
    """Replies from a script and records what each request carried."""

    def __init__(self, replies: list[ModelResponse]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[list, AgentInfo]] = []
        super().__init__(self._reply)

    def _reply(self, messages: list, info: AgentInfo) -> ModelResponse:
        self.calls.append((list(messages), info))
        return self.replies.pop(0)

    def last_parts(self, index: int) -> list:
        return self.calls[index][0][-1].parts

    def tool_names(self, index: int) -> list[str]:
        info = self.calls[index][1]
        return [t.name for t in [*info.function_tools, *info.output_tools]]
