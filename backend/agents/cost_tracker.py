"""
节点 ⑧ — 成本汇总
纯计算节点，输出 cost 报告。
"""
import logging
from backend.models.state import SearchState

logger = logging.getLogger(__name__)


def track_cost_node(state: SearchState) -> SearchState:
    """成本汇总日志（纯计算，无 IO 副作用）。"""

    total_cost = state.get("total_cost_usd", 0.0)
    total_tokens = state.get("total_tokens_used", 0)
    budget = state.get("budget_limit_usd", 2.0)
    iteration = state.get("iteration", 0)
    final_papers = len(state.get("ranked_papers", []))

    # ===== 成本报告：print + logger.info 双写 =====
    # print 保留 console 用户展示（uvicorn 启动时 logger 经常被静默）
    # logger.info 同时写日志文件供后续审计
    logger.info(
        "[cost_tracker] total_tokens=%d total_cost=$%.4f budget=$%.2f "
        "iteration=%d final_papers=%d",
        total_tokens, total_cost, budget, iteration, final_papers,
    )

    print("\n" + "=" * 60)
    print("  ScholarFlow 搜索完成 — 成本报告")
    print("=" * 60)
    print(f"  总 Token 使用量 : {total_tokens:,}")
    print(f"  总成本          : ${total_cost:.4f}")
    print(f"  预算上限        : ${budget:.2f}")
    print(f"  搜索迭代轮次    : {iteration}")
    print(f"  最终论文数量    : {final_papers}")
    print("\n  各模型用量：")
    for model, usage in (state.get("model_usage", {}) or {}).items():
        line = f"    {model:<40} {usage['tokens']:>8,} tokens  ${usage['cost']:.4f}"
        print(line)
        logger.info("[cost_tracker] model=%s tokens=%d cost=$%.4f",
                    model, usage['tokens'], usage['cost'])
    print("=" * 60 + "\n")

    return {**state, "status": "done"}
