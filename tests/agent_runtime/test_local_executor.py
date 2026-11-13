from types import SimpleNamespace

from app.agent_runtime.runtime.local_executor import LocalExecutor


def test_local_sources_are_capped_and_tool_summary_contains_only_counts(planned):
    task, run = planned
    executor = LocalExecutor()
    sources = (
        SimpleNamespace(title=f"来源 {i}", source_label="资料", snippet="<mark>虚构摘要</mark>")
        for i in range(10)
    )
    candidate, call = executor.execute(task, run.id, "context-step", sources)
    executor.review(candidate)
    assert "来源 7" in candidate.body
    assert "来源 8" not in candidate.body
    assert "<mark>" not in candidate.body
    assert "8 条" in call.result_summary
    assert task.objective not in call.input_summary
    assert "虚构摘要" not in call.result_summary
