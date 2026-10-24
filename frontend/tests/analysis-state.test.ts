import assert from "node:assert/strict";
import test from "node:test";
import { shouldAcceptAnalysisResult, shouldReleaseAnalysisLoading } from "../src/lib/analysis-state.ts";

const inputs = { matchId: "match-001", audience: "fan" as const, minute: 14 };

test("accepts only the active match, audience, minute, and sequence", () => {
  assert.equal(shouldAcceptAnalysisResult(inputs, inputs, 4, 4), true);
  assert.equal(shouldAcceptAnalysisResult(inputs, { ...inputs, minute: 15 }, 4, 4), false);
  assert.equal(shouldAcceptAnalysisResult(inputs, inputs, 4, 5), false);
});

test("releases loading only for the active request", () => {
  assert.equal(shouldReleaseAnalysisLoading(4, 4), true);
  assert.equal(shouldReleaseAnalysisLoading(4, 5), false);
});
