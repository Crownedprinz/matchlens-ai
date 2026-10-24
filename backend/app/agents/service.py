import os
from app.agents.contracts import AnalysisRequest, AnalysisResponse
from app.agents.mock_workflow import run_mock
async def run_analysis(request: AnalysisRequest) -> AnalysisResponse:
    mode = os.getenv("AGENT_MODE", "mock").lower()
    if mode == "mock": return run_mock(request)
    if mode == "foundry":
        from app.agents.foundry_workflow import run_foundry
        return await run_foundry(request)
    raise ValueError("AGENT_MODE must be 'mock' or 'foundry'")
