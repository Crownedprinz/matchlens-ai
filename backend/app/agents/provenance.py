from contextvars import ContextVar
from typing import Any
from app.agents.contracts import ToolCall

_calls: ContextVar[list[ToolCall] | None] = ContextVar("matchlens_tool_calls", default=None)
def begin() -> None: _calls.set([])
def calls() -> list[ToolCall]: return list(_calls.get() or [])
def record(call: ToolCall) -> None:
    current = _calls.get()
    if current is not None: current.append(call)
def execute(name: str, fn, args: dict[str, Any], *, agent_name: str | None = None, agent_version: str | None = None, tool_call_id: str | None = None):
    import time
    from app.agents.diagnostics import event
    start = time.perf_counter()
    event("function_call_requested", tool=name, agent_name=agent_name, agent_version=agent_version, tool_call_id=tool_call_id)
    event("local_python_function_started", tool=name)
    try:
        value = fn(args)
        output_ids = []
        if isinstance(value, dict):
            if "match_id" in value: output_ids.append(str(value["match_id"]))
            for row in value.get("records", []):
                if isinstance(row, dict) and "id" in row: output_ids.append(str(row["id"]))
        record(ToolCall(name=name, agent_name=agent_name, agent_version=agent_version, arguments=args, tool_call_id=tool_call_id, duration_ms=round((time.perf_counter()-start)*1000), outcome="success", output_ids=output_ids))
        event("tool_execution_completed", tool=name, outcome="success", duration_ms=round((time.perf_counter()-start)*1000))
        event("tool_output_returned_to_agent_framework", tool=name)
        return value
    except Exception as exc:
        record(ToolCall(name=name, agent_name=agent_name, agent_version=agent_version, arguments=args, tool_call_id=tool_call_id, duration_ms=round((time.perf_counter()-start)*1000), outcome="error", error=str(exc)))
        event("tool_execution_completed", tool=name, outcome="error", duration_ms=round((time.perf_counter()-start)*1000), error_type=type(exc).__name__)
        raise
