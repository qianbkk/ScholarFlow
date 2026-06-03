"""
ScholarFlow 学术 API Mock 数据集
================================
内置一组真实存在的代表性论文（基于公开的 arXiv / 会议信息构造），
用于在无网络环境下让流水线跑通。
"""
from backend.models.paper import Paper


# 真实存在的标志性 ML/NLP 论文（标题、年份、作者、引用数、venue 均为公开信息）
_MOCK_PAPERS = [
    # ---- Transformer 与早期奠基 ----
    {
        "paper_id": "ss_001_transformer",
        "title": "Attention Is All You Need",
        "year": 2017,
        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit"],
        "venue": "NeurIPS",
        "citation_count": 95000,
        "abstract": "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely. Experiments on two machine translation tasks show these models to be superior in quality while being more parallelizable and requiring significantly less time to train.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_002_bert",
        "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "year": 2018,
        "authors": ["Jacob Devlin", "Ming-Wei Chang", "Kenton Lee", "Kristina Toutanova"],
        "venue": "NAACL",
        "citation_count": 55000,
        "abstract": "We introduce a new language representation model called BERT, which stands for Bidirectional Encoder Representations from Transformers. BERT is designed to pre-train deep bidirectional representations from unlabeled text by jointly conditioning on both left and right context in all layers.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_003_gpt3",
        "title": "GPT-3: Language Models are Few-Shot Learners",
        "year": 2020,
        "authors": ["Tom B. Brown", "Benjamin Mann", "Nick Ryder"],
        "venue": "NeurIPS",
        "citation_count": 32000,
        "abstract": "Recent work has demonstrated substantial gains on many NLP tasks and benchmarks by pre-training on a large corpus of text followed by fine-tuning on a specific task. We show that scaling up language models greatly improves task-agnostic, few-shot performance.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_004_llama2",
        "title": "Llama 2: Open Foundation and Fine-Tuned Chat Models",
        "year": 2023,
        "authors": ["Hugo Touvron", "Louis Martin", "Kevin Stone"],
        "venue": "arXiv",
        "citation_count": 8500,
        "abstract": "In this work, we develop and release Llama 2, a collection of pretrained and fine-tuned large language models (LLMs) ranging in scale from 7 billion to 70 billion parameters. Our fine-tuned LLMs, called Llama 2-Chat, are optimized for dialogue use cases.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_005_llm_survey",
        "title": "A Survey of Large Language Models",
        "year": 2023,
        "authors": ["Wayne Xin Zhao", "Kun Zhou", "Junyi Li"],
        "venue": "arXiv",
        "citation_count": 4500,
        "abstract": "Language is essentially a complex, intricate system of human expressions governed by grammatical rules. This survey focuses on large language models (LLMs), discussing their architectures, pre-training, adaptation tuning, utilization, and capacity evaluation.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_006_rag",
        "title": "Retrieval-Augmented Generation for Large Language Models: A Survey",
        "year": 2023,
        "authors": ["Yunfan Gao", "Yun Xiong", "Xinyu Gao"],
        "venue": "arXiv",
        "citation_count": 2200,
        "abstract": "Large Language Models (LLMs) have shown remarkable capabilities but face challenges like hallucination and outdated knowledge. Retrieval-Augmented Generation (RAG) integrates external knowledge retrieval to enhance LLM accuracy and reliability.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_007_chain_of_thought",
        "title": "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
        "year": 2022,
        "authors": ["Jason Wei", "Xuezhi Wang", "Dale Schuurmans"],
        "venue": "NeurIPS",
        "citation_count": 7500,
        "abstract": "We explore how generating a chain of thought - a series of intermediate reasoning steps - significantly improves the ability of large language models to perform complex reasoning. We show that the ability to perform chain-of-thought reasoning emerges naturally in sufficiently large language models.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_008_react",
        "title": "ReAct: Synergizing Reasoning and Acting in Language Models",
        "year": 2022,
        "authors": ["Shunyu Yao", "Jeffrey Zhao", "Dian Yu"],
        "venue": "ICLR",
        "citation_count": 4800,
        "abstract": "We introduce ReAct, a paradigm that combines reasoning and acting in language models for general task solving. ReAct prompts the model to generate both verbal reasoning traces and text actions interleaved, allowing the model to dynamically reason and act.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_009_agent_survey",
        "title": "A Survey on Large Language Model based Autonomous Agents",
        "year": 2023,
        "authors": ["Lei Wang", "Chen Ma", "Xueyang Feng"],
        "venue": "arXiv",
        "citation_count": 1500,
        "abstract": "The rise of large language models (LLMs) has opened new possibilities for constructing powerful autonomous agents. This survey provides a systematic review of LLM-based autonomous agents, covering their construction, application, and evaluation.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_010_toolformer",
        "title": "Toolformer: Language Models Can Teach Themselves to Use Tools",
        "year": 2023,
        "authors": ["Timo Schick", "Jane Dwivedi-Yu", "Roberto Dessi"],
        "venue": "NeurIPS",
        "citation_count": 3200,
        "abstract": "We introduce Toolformer, a model trained to decide which APIs to call, when to call them, what arguments to pass, and how to incorporate the results into future token prediction. Toolformer achieves substantially improved zero-shot performance.",
        "source": "semantic_scholar",
    },
    # ---- 代码生成 ----
    {
        "paper_id": "ss_011_codex",
        "title": "Evaluating Large Language Models Trained on Code",
        "year": 2021,
        "authors": ["Mark Chen", "Jerry Tworek", "Heewoo Jun"],
        "venue": "arXiv",
        "citation_count": 6800,
        "abstract": "We introduce Codex, a GPT language model fine-tuned on publicly available code from GitHub, and study its Python code-writing capabilities. Codex is a descendant of GPT-3 with additional training data from code repositories.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_012_codegen",
        "title": "CodeGen: An Open Large Language Model for Code with Multi-Turn Program Synthesis",
        "year": 2022,
        "authors": ["Erik Nijkamp", "Bo Pang", "Hiroaki Hayashi"],
        "venue": "ICLR",
        "citation_count": 1900,
        "abstract": "Program synthesis seeks to automatically generate programs based on user specifications. We present CodeGen, a family of large language models for code synthesis, and demonstrate its capabilities through training and benchmarking on multiple datasets.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_013_humaneval",
        "title": "HumanEval: Hand-Written Evaluation Set for Code Synthesis",
        "year": 2021,
        "authors": ["Mark Chen", "Jerry Tworek", "Heewoo Jun"],
        "venue": "arXiv",
        "citation_count": 3500,
        "abstract": "We propose HumanEval, a benchmark for measuring functional correctness of code synthesis. HumanEval consists of 164 handwritten programming problems covering language comprehension, algorithms, and simple mathematics.",
        "source": "semantic_scholar",
    },
    # ---- 多智能体强化学习 ----
    {
        "paper_id": "ss_014_maddpg",
        "title": "Multi-Agent Actor-Critic for Mixed Cooperative-Competitive Environments",
        "year": 2017,
        "authors": ["Ryan Lowe", "Yi Wu", "Aviv Tamar"],
        "venue": "NeurIPS",
        "citation_count": 7200,
        "abstract": "We explore deep reinforcement learning methods for multi-agent domains. We propose a multi-agent actor-critic method that considers the actions of other agents in the environment and uses a centralized critic to guide decentralized actors.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_015_emergent",
        "title": "Emergent Tool Use from Multi-Agent Interaction",
        "year": 2020,
        "authors": ["Bowen Baker", "Ingmar Kanitscheider", "Todor Markov"],
        "venue": "OpenAI",
        "citation_count": 2100,
        "abstract": "We show that agents in a multi-agent environment learn to use tools, including ramps and boxes, purely through reinforcement learning and social interaction. This emergence of tool use is observed in a setting with continuous partial observability.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_016_marl_survey",
        "title": "Multi-Agent Reinforcement Learning: A Survey of Methods and Applications",
        "year": 2021,
        "authors": ["Sven Gronauer", "Klaus Diepold"],
        "venue": "arXiv",
        "citation_count": 1100,
        "abstract": "Multi-agent systems are ubiquitous in our daily lives. Multi-agent reinforcement learning (MARL) is a sub-field of reinforcement learning that has been receiving increasing attention. This survey provides a comprehensive overview of MARL methods and applications.",
        "source": "semantic_scholar",
    },
    # ---- RAG / Agent 进阶 ----
    {
        "paper_id": "ss_017_langchain",
        "title": "LangChain: Building Applications with LLMs through Composability",
        "year": 2022,
        "authors": ["Harrison Chase"],
        "venue": "GitHub",
        "citation_count": 0,
        "abstract": "LangChain is a framework for developing applications powered by language models. It enables applications that are context-aware and can reason about how to answer questions by chaining together multiple sources of information.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_018_autogpt",
        "title": "Auto-GPT: An Autonomous GPT-4 Experiment",
        "year": 2023,
        "authors": ["Significant Gravitas"],
        "venue": "GitHub",
        "citation_count": 0,
        "abstract": "Auto-GPT is an experimental open-source application showcasing the capabilities of the GPT-4 language model. The program, driven by GPT-4, autonomously chains together LLM thoughts to achieve any goal set by the user.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_019_reflexion",
        "title": "Reflexion: Language Agents with Verbal Reinforcement Learning",
        "year": 2023,
        "authors": ["Noah Shinn", "Federico Cassano", "Edward Berman"],
        "venue": "NeurIPS",
        "citation_count": 1800,
        "abstract": "We propose Reflexion, an approach that reinforces language agents through linguistic feedback rather than weight updates. Agents reflect on task feedback, store reflective text in an episodic memory buffer, and use it to drive better decision-making in subsequent trials.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_020_graphrag",
        "title": "From Local to Global: A Graph RAG Approach to Query-Focused Summarization",
        "year": 2024,
        "authors": ["Microsoft Research"],
        "venue": "arXiv",
        "citation_count": 850,
        "abstract": "We propose GraphRAG, a method that combines graph-based retrieval with LLM generation. By constructing a knowledge graph from source documents, GraphRAG enables query-focused summarization over entire document collections.",
        "source": "semantic_scholar",
    },
    # ---- OpenAlex 视角的论文（不同 ID 前缀） ----
    {
        "paper_id": "openalex_W001",
        "title": "Deep Residual Learning for Image Recognition",
        "year": 2016,
        "authors": ["Kaiming He", "Xiangyu Zhang", "Shaoqing Ren"],
        "venue": "CVPR",
        "citation_count": 180000,
        "abstract": "Deeper neural networks are more difficult to train. We present a residual learning framework to ease the training of networks that are substantially deeper than those used previously. We explicitly reformulate the layers as learning residual functions.",
        "source": "openalex",
    },
    {
        "paper_id": "openalex_W002",
        "title": "Adam: A Method for Stochastic Optimization",
        "year": 2014,
        "authors": ["Diederik P. Kingma", "Jimmy Ba"],
        "venue": "ICLR",
        "citation_count": 130000,
        "abstract": "We introduce Adam, an algorithm for first-order gradient-based optimization of stochastic objective functions, based on adaptive estimates of lower-order moments. The method is straightforward to implement and computationally efficient.",
        "source": "openalex",
    },
    {
        "paper_id": "openalex_W003",
        "title": "Generative Adversarial Networks",
        "year": 2014,
        "authors": ["Ian J. Goodfellow", "Jean Pouget-Abadie"],
        "venue": "NeurIPS",
        "citation_count": 75000,
        "abstract": "We propose a new framework for estimating generative models via an adversarial process, in which we simultaneously train two models: a generative model G and a discriminative model D. We train D to distinguish real samples from G's fake samples.",
        "source": "openalex",
    },
    {
        "paper_id": "openalex_W004",
        "title": "Dropout: A Simple Way to Prevent Neural Networks from Overfitting",
        "year": 2014,
        "authors": ["Nitish Srivastava", "Geoffrey Hinton"],
        "venue": "JMLR",
        "citation_count": 48000,
        "abstract": "Dropout is a technique for addressing overfitting in deep neural networks by randomly dropping units during training. This prevents units from co-adapting too much and significantly reduces overfitting, giving major improvements over other regularization methods.",
        "source": "openalex",
    },
    {
        "paper_id": "openalex_W005",
        "title": "ImageNet Classification with Deep Convolutional Neural Networks",
        "year": 2012,
        "authors": ["Alex Krizhevsky", "Ilya Sutskever", "Geoffrey E. Hinton"],
        "venue": "NeurIPS",
        "citation_count": 140000,
        "abstract": "We trained a large, deep convolutional neural network to classify the 1.2 million high-resolution images in the ImageNet LSVRC-2010 contest into 1000 different classes. The network achieved top-1 error rate of 37.5% and top-5 error rate of 17.0%.",
        "source": "openalex",
    },
]


def _to_paper(item: dict) -> Paper:
    """把 mock 字典转 Paper 对象。"""
    p = Paper(
        paper_id=item["paper_id"],
        title=item["title"],
        year=item["year"],
        authors=item.get("authors", []),
        venue=item.get("venue", ""),
        citation_count=item.get("citation_count", 0),
        abstract=item.get("abstract", ""),
        url=f"https://arxiv.org/abs/{item['paper_id'].split('_')[-1]}" if "ss_" in item["paper_id"] else f"https://openalex.org/{item['paper_id']}",
        source=item.get("source", "semantic_scholar"),
    )
    # 模拟 references（每个 paper 引用 2-3 个其他 mock 论文）
    refs = []
    for other in _MOCK_PAPERS:
        if other["paper_id"] != p.paper_id and other["year"] < p.year:
            refs.append(other["paper_id"])
        if len(refs) >= 3:
            break
    p.__dict__["references"] = refs
    return p


def get_mock_papers(query: str = "", limit: int = 20) -> list[Paper]:
    """
    根据 query 关键词过滤 mock 论文。
    关键词优先匹配 title，包含更多 query 词者优先。
    """
    q = (query or "").lower().strip()
    if not q:
        papers = [_to_paper(item) for item in _MOCK_PAPERS]
        return papers[:limit]

    # 简单匹配
    query_words = set(q.split())
    scored = []
    for item in _MOCK_PAPERS:
        title_lower = item["title"].lower()
        abstract_lower = item.get("abstract", "").lower()
        match_count = sum(1 for w in query_words if w in title_lower or w in abstract_lower)
        if match_count > 0:
            scored.append((match_count, item))
    scored.sort(key=lambda x: x[0], reverse=True)

    papers = [_to_paper(item) for _, item in scored]
    return papers[:limit]


def get_all_mock_papers() -> list[Paper]:
    """返回全部 mock 论文（用于 get_references）。"""
    return [_to_paper(item) for item in _MOCK_PAPERS]


# 用于 is_expanded 标记的辅助
def mark_as_expanded(paper: Paper) -> Paper:
    paper.is_expanded = True
    return paper
