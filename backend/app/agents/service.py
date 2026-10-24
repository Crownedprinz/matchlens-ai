from app.agents.contracts import AnalysisRequest, AnalysisResponse
from app.agents.mock_workflow import run_mock
async def run_analysis(request: AnalysisRequest) -> AnalysisResponse:
    if request.mode == "demo": return run_mock(request)
    if request.mode == "foundry":
        from app.agents.foundry_workflow import run_foundry
        return await run_foundry(request)
    raise ValueError("mode must be 'demo' or 'foundry'")
