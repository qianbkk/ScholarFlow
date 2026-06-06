"""
Phase 3: 真实 LLM E2E 验证(直接 in-process,绕开 HTTP 120s timeout)

测试目标:
1. 真实 MiniMax-M3 LLM 跑通整条流水线
2. 报告内容与查询相关(AlphaFold/protein,不是 Transformer)
3. mock synthesis 函数独立验证(不依赖 backend 服务)
"""
import asyncio
import json
import os
import sys
import time

os.environ['PYTHONIOENCODING'] = 'utf-8'
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# ===== TEST A: Mock synthesis 独立验证 =====
def test_mock_synthesis_function():
    """直接调用 _mock_synthesis 函数,验证不再硬编码 Transformer"""
    print("=" * 70)
    print("TEST A: _mock_synthesis() 独立验证(不依赖 HTTP 服务)")
    print("=" * 70)

    from backend.utils.llm_client import _mock_synthesis

    # 构造一个真实 prompt 模拟 AlphaFold 查询
    fake_papers_text = """
**[Paper 1]** Highly Accurate Protein Structure Prediction with AlphaFold
Year: 2021 | Citations: 15000 | Venue: Nature | Relevance: 9.5 | URL: https://example.com/af2
Abstract: AlphaFold provides protein structures with atomic accuracy even where no homologous structure is known.

**[Paper 2]** RoseTTAFold: A Deep Learning Approach to Protein Structure Prediction
Year: 2021 | Citations: 2500 | Venue: Science | Relevance: 8.0 | URL: https://example.com/rtf
Abstract: RoseTTAFold uses a three-track network to predict protein structures.

**[Paper 3]** Evolutionary-scale prediction of atomic level protein structure
Year: 2020 | Citations: 800 | Venue: NeurIPS | Relevance: 7.5 | URL: https://example.com/af1
Abstract: AlphaFold architecture using attention and 1D/2D representations.
"""
    prompt = f"""根据以下学术论文列表，为研究问题生成一份结构化文献综述报告。

研究问题：AlphaFold protein structure prediction

检索论文列表：
{fake_papers_text}

请生成Markdown格式的综述报告，严格包含以下6个部分："""

    report = _mock_synthesis(prompt, ranked_count=3)

    print(f"\n报告长度: {len(report)} 字符")
    print("-" * 60)
    print(report[:1500])
    print("-" * 60)

    all_ok = True
    report_lower = report.lower()

    # 核心断言
    has_alphafold = "alphafold" in report_lower
    has_protein = "protein" in report_lower
    has_old_template = ("Attention Is All You Need" in report
                        and "BERT" in report
                        and "GPT-3" in report)
    no_paper1_in_alphafold = "alphafold" in report_lower and "rosettafold" in report_lower

    print()
    if has_alphafold:
        print("  [OK]   报告包含 'AlphaFold' 关键词")
    else:
        print("  [FAIL] 报告未含 'AlphaFold' 关键词")
        all_ok = False

    if has_protein:
        print("  [OK]   报告包含 'protein' 关键词")
    else:
        print("  [FAIL] 报告未含 'protein' 关键词")
        all_ok = False

    if not has_old_template:
        print("  [OK]   报告未使用旧的硬编码 Transformer 模板")
    else:
        print("  [FAIL] 报告仍是旧硬编码模板(Transformer/BERT/GPT-3)")
        all_ok = False

    if no_paper1_in_alphafold:
        print("  [OK]   报告使用真实传入的论文(RoseTTAFold/AlphaFold/Evolutionary)")
    else:
        print("  [WARN] 报告未明确引用传入的论文名")

    return all_ok


# ===== TEST B: 真实 LLM 跑完整 workflow =====
async def test_real_llm_inprocess():
    print("\n" + "=" * 70)
    print("TEST B: 真实 MiniMax-M3 LLM (in-process, no HTTP timeout)")
    print("=" * 70)

    from backend.workflow.graph import search_graph

    initial = {
        "original_query": "AlphaFold protein structure prediction",
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": 1,
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 0.5,
        "model_usage": {},
        "status": "decomposing",
        "error": None,
        "expanded_paper_ids": [],
    }

    t0 = time.time()
    try:
        # 240s 内部 timeout,避免 HTTP 层 120s
        final = await asyncio.wait_for(search_graph.ainvoke(initial), timeout=240.0)
    except asyncio.TimeoutError:
        print(f"  [FAIL] Pipeline 内部超时 (>240s) after {time.time()-t0:.1f}s")
        return False
    except Exception as e:
        print(f"  [FAIL] Pipeline error: {e}")
        import traceback
        traceback.print_exc()
        return False

    elapsed = time.time() - t0
    print(f"  Pipeline completed in {elapsed:.1f}s")
    print(f"  Status: {final.get('status')}")
    print(f"  Sub-queries: {len(final.get('sub_queries', []))}")
    print(f"  Raw papers: {len(final.get('raw_papers', []))}")
    print(f"  Ranked papers: {len(final.get('ranked_papers', []))}")
    print(f"  Total cost: ${final.get('total_cost_usd', 0):.4f}")
    print(f"  Total tokens: {final.get('total_tokens_used', 0)}")
    print(f"  Graph nodes: {len(final.get('citation_graph', {}).get('nodes', []))}")

    report = final.get("report", "")
    print(f"\n  Report length: {len(report)} chars")
    print("-" * 60)
    print(report[:2000])
    print("-" * 60)

    all_ok = True
    report_lower = report.lower()

    all_ok &= bool(report and len(report) > 200)
    if not (report and len(report) > 200):
        print("  [FAIL] 报告太短或为空")
        return False

    print()
    if "alphafold" in report_lower or "protein" in report_lower:
        print("  [OK]   报告含 'alphafold' 或 'protein' 关键词(与查询相关)")
    else:
        print("  [FAIL] 报告与查询不相关")
        all_ok = False

    if final.get("ranked_papers"):
        print(f"  [OK]   ranked_papers 非空 ({len(final['ranked_papers'])} 篇)")
    else:
        print("  [FAIL] ranked_papers 为空")
        all_ok = False

    if final.get("citation_graph", {}).get("nodes"):
        print(f"  [OK]   citation_graph.nodes 非空")
    else:
        print("  [FAIL] citation_graph.nodes 为空")
        all_ok = False

    # 反向断言
    if "Attention Is All You Need" in report and "alphafold" not in report_lower and "protein" not in report_lower:
        print("  [FAIL] 报告仍是硬编码 Transformer 模板")
        all_ok = False
    else:
        print("  [OK]   报告不是硬编码 Transformer 模板")

    # 保存供 Playwright 验证
    OUT_DIR = os.path.join(PROJECT_ROOT, "playwright_runs")
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "e2e_real_llm_response.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "query": initial["original_query"],
            "elapsed_seconds": elapsed,
            "response": final,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  完整响应已保存到: {out}")
    return all_ok


async def main():
    a_ok = test_mock_synthesis_function()
    b_ok = await test_real_llm_inprocess()
    print("\n" + "=" * 70)
    print(f"FINAL: MOCK_SYNTHESIS={'PASS' if a_ok else 'FAIL'}  REAL_LLM={'PASS' if b_ok else 'FAIL'}")
    print("=" * 70)
    return 0 if (a_ok and b_ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
