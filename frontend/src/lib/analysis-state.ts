export type AnalysisInputs = {
  matchId: string;
  audience: "fan" | "analyst" | "fantasy";
  minute: number;
};

export function sameAnalysisInputs(left: AnalysisInputs, right: AnalysisInputs): boolean {
  return left.matchId === right.matchId && left.audience === right.audience && left.minute === right.minute;
}

export function shouldAcceptAnalysisResult(request: AnalysisInputs, current: AnalysisInputs, requestSequence: number, activeSequence: number): boolean {
  return requestSequence === activeSequence && sameAnalysisInputs(request, current);
}

export function shouldReleaseAnalysisLoading(requestSequence: number, activeSequence: number): boolean {
  return requestSequence === activeSequence;
}
