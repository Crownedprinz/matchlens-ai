from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from app.agents.contracts import ToolCall

_calls: ContextVar[list[ToolCall] | None] = ContextVar("matchlens_tool_calls", default=None)
_agent_context: ContextVar[tuple[str | None, str | None] | None] = ContextVar("matchlens_agent_context", default=None)
def begin() -> None: _calls.set([])
def calls() -> list[ToolCall]: return list(_calls.get() or [])
def record(call: ToolCall) -> None:
    current = _calls.get()
    if current is not None: current.append(call)
def _output_identifiers(value: Any) -> list[str]:
    identifiers: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"id", "match_id", "player_id", "team_id"} and isinstance(item, (str, int)):
                identifiers.append(str(item))
            else:
                identifiers.extend(_output_identifiers(item))
    elif isinstance(value, list):
        for item in value:
            identifiers.extend(_output_identifiers(item))
    return list(dict.fromkeys(identifiers))
@contextmanager
def agent_context(agent_name: str, agent_version: str):
    token = _agent_context.set((agent_name, agent_version))
    try:
        yield
    finally:
        _agent_context.reset(token)
def execute(name: str, fn, args: dict[str, Any], *, agent_name: str | None = None, agent_version: str | None = None, tool_call_id: str | None = None):
    import time
    from app.agents.diagnostics import event
    context = _agent_context.get()
    agent_name = agent_name or (context[0] if context else None)
    agent_version = agent_version or (context[1] if context else None)
    start = time.perf_counter()
    event("function_call_requested", tool=name, agent_name=agent_name, agent_version=agent_version, tool_call_id=tool_call_id)
    event("local_python_function_started", tool=name)
    try:
        value = fn(args)
        output_ids = _output_identifiers(value)
        record(ToolCall(name=name, agent_name=agent_name, agent_version=agent_version, arguments=args, tool_call_id=tool_call_id, duration_ms=round((time.perf_counter()-start)*1000), outcome="success", output_ids=output_ids))
        event("tool_execution_completed", tool=name, outcome="success", duration_ms=round((time.perf_counter()-start)*1000))
        event("tool_output_ready_for_agent_framework", tool=name, output_id_count=len(output_ids))
        event("continuation_request_boundary_started", tool=name, boundary="FoundryAgent_internal_function_loop", submitted=False)
        return value
    except Exception as exc:
        record(ToolCall(name=name, agent_name=agent_name, agent_version=agent_version, arguments=args, tool_call_id=tool_call_id, duration_ms=round((time.perf_counter()-start)*1000), outcome="error", error=str(exc)))
        event("tool_execution_completed", tool=name, outcome="error", duration_ms=round((time.perf_counter()-start)*1000), error_type=type(exc).__name__)
        raise
