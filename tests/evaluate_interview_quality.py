import asyncio, json
from pathlib import Path
from statistics import mean
from app.services.interview_evaluator import InterviewEvaluator


async def main():
    cases = json.loads(Path(__file__).with_name("evaluation_cases.json").read_text(encoding="utf-8"))
    evaluator = InterviewEvaluator(); absolute_errors = []; verdict_hits = 0
    for case in cases:
        result = await evaluator.evaluate_answer(case["question"], case["answer"], case["role"], "中级", "技术面")
        absolute_errors.append(abs(result.overall_score - case["expected_score"]))
        verdict_hits += result.verdict == case["expected_verdict"]
    print(json.dumps({"cases": len(cases), "score_mae": round(mean(absolute_errors), 2), "verdict_accuracy": round(verdict_hits / len(cases), 3)}, ensure_ascii=False))


if __name__ == "__main__": asyncio.run(main())
