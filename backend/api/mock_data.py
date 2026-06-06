"""
ScholarFlow 学术 API Mock 数据集
================================
内置一组真实存在的代表性论文（基于公开的 arXiv / 会议信息构造），
用于在无网络环境下让流水线跑通。
"""
import os
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
    {
        "paper_id": "openalex_W006",
        "title": "U-Net: Convolutional Networks for Biomedical Image Segmentation",
        "year": 2015,
        "authors": ["Olaf Ronneberger", "Philipp Fischer", "Thomas Brox"],
        "venue": "MICCAI",
        "citation_count": 95000,
        "abstract": "We present a network and training strategy that relies on the strong use of data augmentation. The architecture consists of a contracting path to capture context and a symmetric expanding path that enables precise localization. The network can be trained end-to-end from very few images.",
        "source": "openalex",
    },
    {
        "paper_id": "openalex_W007",
        "title": "DeepFace: Closing the Gap to Human-Level Performance in Face Verification",
        "year": 2014,
        "authors": ["Yaniv Taigman", "Ming Yang", "Marc'Aurelio Ranzato"],
        "venue": "CVPR",
        "citation_count": 12500,
        "abstract": "In modern face recognition, the conventional pipeline consists of four stages: detect, align, represent, classify. We revisit the alignment step, the representation step, and the classification step. Our proposed DeepFace system achieves near-human performance on face verification tasks.",
        "source": "openalex",
    },
    {
        "paper_id": "openalex_W008",
        "title": "XGBoost: A Scalable Tree Boosting System",
        "year": 2016,
        "authors": ["Tianqi Chen", "Carlos Guestrin"],
        "venue": "KDD",
        "citation_count": 28000,
        "abstract": "Tree boosting is a highly effective and widely used machine learning method. We describe a scalable end-to-end tree boosting system called XGBoost, which is used widely by data scientists to achieve state-of-the-art results on many machine learning challenges.",
        "source": "openalex",
    },
    # ---- Object Detection ----
    {
        "paper_id": "ss_021_yolo",
        "title": "You Only Look Once: Unified, Real-Time Object Detection",
        "year": 2016,
        "authors": ["Joseph Redmon", "Santosh Divvala", "Ross Girshick"],
        "venue": "CVPR",
        "citation_count": 40000,
        "abstract": "We present YOLO, a new approach to object detection. Prior work on object detection repurposes classifiers to perform detection. Instead, we frame object detection as a regression problem to spatially separated bounding boxes and associated class probabilities. A single neural network predicts bounding boxes and class probabilities directly from full images in one evaluation.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_022_faster_rcnn",
        "title": "Faster R-CNN: Towards Real-Time Object Detection with Region Proposal Networks",
        "year": 2015,
        "authors": ["Shaoqing Ren", "Kaiming He", "Ross Girshick"],
        "venue": "NeurIPS",
        "citation_count": 35000,
        "abstract": "State-of-the-art object detection networks depend on region proposal algorithms to hypothesize object locations. Advances like SPPnet and Fast R-CNN have reduced the running time of these detection networks, exposing region proposal computation as a bottleneck. We introduce a Region Proposal Network (RPN) that shares full-image convolutional features with the detection network.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_023_detr",
        "title": "End-to-End Object Detection with Transformers",
        "year": 2020,
        "authors": ["Nicolas Carion", "Francisco Massa", "Gabriel Synnaeve"],
        "venue": "ECCV",
        "citation_count": 8000,
        "abstract": "We present a new method that views object detection as a direct set prediction problem. Our approach streamlines the detection pipeline, effectively removing the need for many hand-designed components like a non-maximum suppression procedure or anchor generation that explicitly encode our prior knowledge about the task.",
        "source": "semantic_scholar",
    },
    # ---- Speech Recognition ----
    {
        "paper_id": "ss_024_wav2vec",
        "title": "wav2vec: Unsupervised Pre-training for Speech Recognition",
        "year": 2019,
        "authors": ["Steffen Schneider", "Alexei Baevski", "Ronan Collobert"],
        "venue": "Interspeech",
        "citation_count": 3500,
        "abstract": "We explore unsupervised pre-training for speech recognition by learning representations from raw audio. wav2vec is trained by contrasting a latent representation of future audio frames with negatives sampled from random time steps. Pre-trained representations improve phone recognition and speech recognition performance.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_025_whisper",
        "title": "Robust Speech Recognition via Large-Scale Weak Supervision",
        "year": 2022,
        "authors": ["Alec Radford", "Jong Wook Kim", "Tao Xu"],
        "venue": "ICML",
        "citation_count": 4200,
        "abstract": "We study the capabilities of speech processing systems trained simply to predict large amounts of transcripts of audio on the internet. When scaled to 680,000 hours of multilingual and multitask supervision, the resulting models generalize well to standard benchmarks and are often competitive with prior fully supervised results.",
        "source": "semantic_scholar",
    },
    # ---- Recommender Systems ----
    {
        "paper_id": "ss_026_widedeep",
        "title": "Wide & Deep Learning for Recommender Systems",
        "year": 2016,
        "authors": ["Heng-Tze Cheng", "Levent Koc", "Jeremiah Harmsen"],
        "venue": "DLRS",
        "citation_count": 6500,
        "abstract": "Memorization of feature interactions through a wide set of cross-product features and generalization through the use of deep neural networks for embedding-based representations. We present the Wide & Deep learning architecture for jointly training wide linear models and deep neural networks.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_027_ncf",
        "title": "Neural Collaborative Filtering",
        "year": 2017,
        "authors": ["Xiangnan He", "Lizi Liao", "Hanwang Zhang"],
        "venue": "WWW",
        "citation_count": 8500,
        "abstract": "In recent years, deep neural networks have yielded immense success on speech recognition, computer vision and natural language processing. However, the investigation of deep neural networks on recommender systems has received relatively less scrutiny. We present Neural Collaborative Filtering (NCF) to address this gap.",
        "source": "semantic_scholar",
    },
    # ---- Vision Transformer / Segmentation ----
    {
        "paper_id": "ss_028_vit",
        "title": "An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale",
        "year": 2020,
        "authors": ["Alexey Dosovitskiy", "Lucas Beyer", "Alexander Kolesnikov"],
        "venue": "ICLR",
        "citation_count": 28000,
        "abstract": "While the Transformer architecture has become the de-facto standard for natural language processing tasks, its applications to computer vision remain limited. We show that this reliance on CNNs is not necessary and a pure transformer applied directly to sequences of image patches can perform very well on image classification tasks.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_029_detr_seg",
        "title": "Segment Anything",
        "year": 2023,
        "authors": ["Alexander Kirillov", "Eric Mintun", "Nikhila Ravi"],
        "venue": "ICCV",
        "citation_count": 5500,
        "abstract": "We introduce the Segment Anything (SA) project: a new task, model, and dataset for image segmentation. Using our efficient model in a data collection loop, we built the largest segmentation dataset to date with over 1 billion masks on 11 million licensed and privacy respecting images.",
        "source": "semantic_scholar",
    },
    # ---- Drug Discovery / Healthcare ----
    {
        "paper_id": "ss_030_alphafold",
        "title": "Highly Accurate Protein Structure Prediction with AlphaFold",
        "year": 2021,
        "authors": ["John Jumper", "Richard Evans", "Alexander Pritzel"],
        "venue": "Nature",
        "citation_count": 18000,
        "abstract": "Proteins are essential to life, and understanding their structure can facilitate a mechanistic understanding of their function. AlphaFold provides protein structures with atomic accuracy even where no homologous structure is known. We provide full confidence estimates and open source the code and model weights.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_031_drug",
        "title": "Molecular Representation Learning with Language Models",
        "year": 2022,
        "authors": ["Binghong Chen", "Chengtao Li", "Hanjun Dai"],
        "venue": "NeurIPS",
        "citation_count": 600,
        "abstract": "We propose a molecular representation learning method that leverages the chemical language of molecules using transformer-based language models. Our approach captures both syntactic and semantic chemical information, achieving state-of-the-art performance on drug target interaction prediction and molecular property prediction tasks.",
        "source": "semantic_scholar",
    },
    # ---- Graph Neural Networks ----
    {
        "paper_id": "ss_032_gat",
        "title": "Graph Attention Networks",
        "year": 2018,
        "authors": ["Petar Velickovic", "Guillem Cucurull", "Arantxa Casanova"],
        "venue": "ICLR",
        "citation_count": 13000,
        "abstract": "We present graph attention networks (GATs), novel neural network architectures that operate on graph-structured data, leveraging masked self-attentional layers. The architecture allows for assigning different importances to nodes in a neighborhood by specifying different weights to different nodes without requiring any kind of costly matrix operation.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_033_graphsage",
        "title": "Inductive Representation Learning on Large Graphs",
        "year": 2017,
        "authors": ["Will Hamilton", "Zhitao Ying", "Jure Leskovec"],
        "venue": "NeurIPS",
        "citation_count": 12000,
        "abstract": "We present GraphSAGE, a general inductive framework that efficiently generates node embeddings for previously unseen data by sampling and aggregating features from a node's local neighborhood. Our approach can scale to graphs with millions of nodes.",
        "source": "semantic_scholar",
    },
    # ---- Diffusion / Generative ----
    {
        "paper_id": "ss_034_ddpm",
        "title": "Denoising Diffusion Probabilistic Models",
        "year": 2020,
        "authors": ["Jonathan Ho", "Ajay Jain", "Pieter Abbeel"],
        "venue": "NeurIPS",
        "citation_count": 15000,
        "abstract": "We present high quality image synthesis results using diffusion probabilistic models, a class of latent variable models inspired by considerations from nonequilibrium thermodynamics. Our best results are obtained by training on a weighted variational bound designed according to a novel connection between diffusion probabilistic models and denoising score matching.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_035_clip",
        "title": "Learning Transferable Visual Models From Natural Language Supervision",
        "year": 2021,
        "authors": ["Alec Radford", "Jong Wook Kim", "Chris Hallacy"],
        "venue": "ICML",
        "citation_count": 11000,
        "abstract": "We demonstrate that the simple pre-training task of predicting which caption goes with which image is an efficient and scalable way to learn SOTA image representations from scratch on a dataset of 400 million pairs collected from the internet. After pre-training, natural language is used to reference learned visual concepts enabling zero-shot transfer.",
        "source": "semantic_scholar",
    },
    # ---- Federated / Privacy ----
    {
        "paper_id": "ss_036_fedavg",
        "title": "Communication-Efficient Learning of Deep Networks from Decentralized Data",
        "year": 2017,
        "authors": ["H. Brendan McMahan", "Eider Moore", "Daniel Ramage"],
        "venue": "AISTATS",
        "citation_count": 11000,
        "abstract": "We advocate an alternative that leaves the training data distributed on the mobile devices and learns a shared model by aggregating locally-computed updates. We term this approach Federated Learning. We demonstrate the applicability of this approach to a variety of model architectures.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_037_dpsgd",
        "title": "Deep Learning with Differential Privacy",
        "year": 2016,
        "authors": ["Martin Abadi", "Andy Chu", "Ian Goodfellow"],
        "venue": "CCS",
        "citation_count": 4500,
        "abstract": "Machine learning models are vulnerable to privacy attacks that can leak information about individual training examples. We propose differentially private stochastic gradient descent (DPSGD) for training deep learning models with formal privacy guarantees.",
        "source": "semantic_scholar",
    },
    # ---- RL ----
    {
        "paper_id": "ss_038_ppo",
        "title": "Proximal Policy Optimization Algorithms",
        "year": 2017,
        "authors": ["John Schulman", "Filip Wolski", "Prafulla Dhariwal"],
        "venue": "arXiv",
        "citation_count": 16000,
        "abstract": "We propose a new family of policy gradient methods for reinforcement learning, which alternate between sampling data through interaction with the environment, and optimizing a 'surrogate' objective function using stochastic gradient ascent. The new methods, which we call proximal policy optimization (PPO), are simpler to implement than trust region methods.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_039_sac",
        "title": "Soft Actor-Critic: Off-Policy Maximum Entropy Deep Reinforcement Learning with a Stochastic Actor",
        "year": 2018,
        "authors": ["Tuomas Haarnoja", "Aurick Zhou", "Kristian Hartikainen"],
        "venue": "ICML",
        "citation_count": 6500,
        "abstract": "We present Soft Actor-Critic (SAC), an off-policy actor-critic deep RL algorithm based on the maximum entropy reinforcement learning framework. SAC achieves state-of-the-art performance on a range of continuous control tasks, outperforming prior on-policy and off-policy methods in sample-efficiency and asymptotic performance.",
        "source": "semantic_scholar",
    },
    # ---- Misc / Foundational ----
    {
        "paper_id": "ss_040_word2vec",
        "title": "Efficient Estimation of Word Representations in Vector Space",
        "year": 2013,
        "authors": ["Tomas Mikolov", "Kai Chen", "Greg Corrado"],
        "venue": "ICLR Workshop",
        "citation_count": 35000,
        "abstract": "We propose two novel model architectures for computing continuous vector representations of words from very large data sets. The quality of these representations is measured in a word analogy task, and the results are compared to the previously best performing techniques based on different types of neural networks.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_041_gan",
        "title": "Generative Adversarial Networks",
        "year": 2014,
        "authors": ["Ian Goodfellow", "Jean Pouget-Abadie", "Mehdi Mirza"],
        "venue": "NeurIPS",
        "citation_count": 75000,
        "abstract": "We propose a new framework for estimating generative models via an adversarial process, in which we simultaneously train two models: a generative model G and a discriminative model D. We train D to distinguish real samples from G's fake samples, training G to fool D.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_042_vae",
        "title": "Auto-Encoding Variational Bayes",
        "year": 2014,
        "authors": ["Diederik P. Kingma", "Max Welling"],
        "venue": "ICLR",
        "citation_count": 25000,
        "abstract": "How can we perform efficient inference and learning in directed probabilistic models, in the presence of continuous latent variables with intractable posterior distributions, and large datasets? We introduce a stochastic variational inference and learning algorithm that scales to large datasets.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_043_moco",
        "title": "Momentum Contrast for Unsupervised Visual Representation Learning",
        "year": 2019,
        "authors": ["Kaiming He", "Haoqi Fan", "Yuxin Wu"],
        "venue": "CVPR",
        "citation_count": 12000,
        "abstract": "We present Momentum Contrast (MoCo) for unsupervised visual representation learning. Our method achieves competitive results on ImageNet classification under the common linear protocol, and surpasses its supervised pre-training counterpart in 7 detection/segmentation tasks.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_044_simclr",
        "title": "A Simple Framework for Contrastive Learning of Visual Representations",
        "year": 2020,
        "authors": ["Ting Chen", "Simon Kornblith", "Mohammad Norouzi"],
        "venue": "ICML",
        "citation_count": 14000,
        "abstract": "This paper presents SimCLR, a simple framework for contrastive learning of visual representations. We simplify recently proposed contrastive self-supervised learning algorithms without requiring specialized architectures or a memory bank. We show that composition of data augmentations plays a critical role in defining effective predictive tasks.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_045_vae2",
        "title": "Hierarchical Neural Story Generation",
        "year": 2018,
        "authors": ["Angela Fan", "Mike Lewis", "Yann Dauphin"],
        "venue": "ACL",
        "citation_count": 1200,
        "abstract": "We introduce a hierarchical generation approach to long-form story generation, with separate modules for prompt encoding, story generation, and prompt adaptation. We demonstrate improvements over flat generation baselines on coherence and narrative flow.",
        "source": "semantic_scholar",
    },
    # ---- 中文论文（覆盖中文 query） ----
    {
        "paper_id": "ss_046_cn_transformer",
        "title": "基于深度学习的自然语言处理综述",
        "year": 2023,
        "authors": ["张伟", "李明", "王芳"],
        "venue": "中文信息学报",
        "citation_count": 320,
        "abstract": "本文综述了基于深度学习的自然语言处理研究进展，涵盖预训练语言模型、Transformer 架构、文本生成、机器翻译、问答系统等关键技术，并讨论了未来研究方向。",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_047_cn_quantum",
        "title": "量子计算与量子算法研究进展",
        "year": 2022,
        "authors": ["陈志强", "刘洋", "赵明"],
        "venue": "物理学报",
        "citation_count": 180,
        "abstract": "本文综述了量子计算领域的关键算法进展，包括 Shor 算法、Grover 算法、量子机器学习、量子神经网络、量子优化算法等，并展望了量子算法在大模型时代的应用前景。",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_048_cn_vision",
        "title": "计算机视觉中的 Transformer 架构综述",
        "year": 2024,
        "authors": ["王晓东", "李娜", "张磊"],
        "venue": "计算机学报",
        "citation_count": 95,
        "abstract": "本文系统综述了 Transformer 架构在计算机视觉中的应用，包括 Vision Transformer (ViT)、DETR、Swin Transformer 等代表性工作，分析了视觉 Transformer 在图像分类、目标检测、语义分割等任务上的优势。",
        "source": "semantic_scholar",
    },
    # ---- 知识图谱嵌入 ----
    {
        "paper_id": "ss_049_kge",
        "title": "TransE: Translating Embeddings for Modeling Multi-relational Data",
        "year": 2013,
        "authors": ["Antoine Bordes", "Nicolas Usunier", "Alberto Garcia-Duran"],
        "venue": "NeurIPS",
        "citation_count": 12000,
        "abstract": "We consider the problem of embedding entities and relationships of multi-relational data in low-dimensional vector spaces. Our method, TransE, models relationships by interpreting them as translations operating on the low-dimensional embeddings of the entities. Despite its simplicity, TransE achieves state-of-the-art performance on knowledge graph completion and entity classification tasks.",
        "source": "semantic_scholar",
    },
    {
        "paper_id": "ss_050_kge_rotate",
        "title": "RotatE: Knowledge Graph Embedding by Relational Rotation in Complex Space",
        "year": 2019,
        "authors": ["Zhiqing Sun", "Shikhar Murty", "William Yang Wang"],
        "venue": "ICLR",
        "citation_count": 4200,
        "abstract": "We present a new knowledge graph embedding method called RotatE, which is able to model and infer various relation patterns including symmetry/antisymmetry, inversion, and composition. Specifically, the RotatE model defines each relation as a rotation from the source entity to the target entity in the complex vector space.",
        "source": "semantic_scholar",
    },
]


# ===== 手工策展的引文关系（保证图谱有边）=====
# 键为 paper_id，值为该 paper 引用的其他 mock 论文 ID。
# 选取原则：跨方向、跨年代的标志性论文，模拟真实学术引用网络。
_CURATED_REFERENCES: dict[str, list[str]] = {
    # 奠基论文（最早 mock 论文，引用先前跨领域工作）
    "ss_001_transformer":   ["ss_040_word2vec", "ss_042_vae", "openalex_W002"],
    "ss_002_bert":          ["ss_001_transformer", "ss_040_word2vec"],
    # LLM 衍生链
    "ss_003_gpt3":          ["ss_001_transformer", "ss_002_bert", "ss_011_codex"],
    "ss_004_llama2":        ["ss_001_transformer", "ss_007_chain_of_thought", "ss_003_gpt3"],
    "ss_005_llm_survey":    ["ss_001_transformer", "ss_002_bert", "ss_003_gpt3", "ss_004_llama2"],
    "ss_006_rag":           ["ss_003_gpt3", "ss_001_transformer"],
    "ss_007_chain_of_thought": ["ss_003_gpt3", "ss_001_transformer"],
    "ss_008_react":         ["ss_007_chain_of_thought", "ss_001_transformer"],
    "ss_009_agent_survey":  ["ss_001_transformer", "ss_005_llm_survey", "ss_007_chain_of_thought"],
    "ss_010_toolformer":    ["ss_001_transformer", "ss_003_gpt3"],
    # 代码生成链
    "ss_011_codex":         ["ss_003_gpt3", "ss_001_transformer"],
    "ss_012_codegen":       ["ss_011_codex", "ss_001_transformer"],
    "ss_013_humaneval":     ["ss_011_codex", "ss_001_transformer"],
    # Agent
    "ss_017_langchain":     ["ss_001_transformer", "ss_006_rag"],
    "ss_018_autogpt":       ["ss_003_gpt3", "ss_008_react"],
    "ss_019_reflexion":     ["ss_008_react", "ss_001_transformer"],
    "ss_020_graphrag":      ["ss_006_rag", "ss_001_transformer"],
    # RL / MARL
    "ss_014_maddpg":        ["ss_038_ppo"],
    "ss_015_emergent":      ["ss_014_maddpg"],
    "ss_016_marl_survey":   ["ss_014_maddpg", "ss_038_ppo", "ss_039_sac"],
    "ss_039_sac":           ["ss_038_ppo"],
    # CV
    "ss_021_yolo":          ["ss_022_faster_rcnn", "openalex_W005"],
    "ss_022_faster_rcnn":   ["openalex_W005", "openalex_W001"],
    "ss_023_detr":          ["ss_001_transformer", "ss_022_faster_rcnn"],
    "ss_028_vit":           ["ss_001_transformer"],
    "ss_029_detr_seg":      ["ss_023_detr", "ss_028_vit"],
    "ss_043_moco":          ["openalex_W001", "ss_044_simclr"],
    "ss_044_simclr":        ["ss_043_moco"],
    # 视觉基础
    "openalex_W001":        ["openalex_W005", "ss_040_word2vec"],
    "openalex_W005":        [],
    # 语音
    "ss_024_wav2vec":       ["ss_001_transformer"],
    "ss_025_whisper":       ["ss_001_transformer", "ss_002_bert"],
    # 推荐
    "ss_026_widedeep":      ["openalex_W002"],
    "ss_027_ncf":           ["ss_026_widedeep", "ss_040_word2vec"],
    # Drug
    "ss_030_alphafold":     ["ss_001_transformer", "ss_042_vae"],
    "ss_031_drug":          ["ss_001_transformer", "ss_002_bert"],
    # GNN
    "ss_032_gat":           ["ss_033_graphsage"],
    "ss_033_graphsage":     ["ss_040_word2vec"],
    # Diffusion
    "ss_034_ddpm":          ["ss_042_vae", "ss_001_transformer"],
    "ss_035_clip":          ["ss_001_transformer", "ss_028_vit"],
    # Federated
    "ss_036_fedavg":        ["ss_002_bert"],
    "ss_037_dpsgd":         ["ss_036_fedavg", "ss_002_bert"],
    # 中文论文引用对应英文
    "ss_046_cn_transformer": ["ss_001_transformer", "ss_002_bert", "ss_005_llm_survey"],
    "ss_048_cn_vision":     ["ss_028_vit", "ss_023_detr", "ss_001_transformer"],
    "ss_047_cn_quantum":    ["ss_005_llm_survey"],
    # KGE
    "ss_050_kge_rotate":    ["ss_049_kge"],
}


def _to_paper(item: dict) -> Paper:
    """把 mock 字典转 Paper 对象。"""
    # 优先使用真实 URL 映射，否则降级到 fake URL
    url = _PAPER_URL_MAP.get(
        item["paper_id"],
        f"https://arxiv.org/abs/{item['paper_id'].split('_')[-1]}"
        if "ss_" in item["paper_id"]
        else f"https://openalex.org/{item['paper_id']}",
    )
    p = Paper(
        paper_id=item["paper_id"],
        title=item["title"],
        year=item["year"],
        authors=item.get("authors", []),
        venue=item.get("venue", ""),
        citation_count=item.get("citation_count", 0),
        abstract=item.get("abstract", ""),
        url=url,
        source=item.get("source", "semantic_scholar"),
    )
    # 优先使用策展的引用关系（保证图谱有边）
    if item["paper_id"] in _CURATED_REFERENCES:
        p.__dict__["references"] = list(_CURATED_REFERENCES[item["paper_id"]])
    else:
        # 兜底：每个 paper 引用 2-3 个更早的 mock 论文
        refs = []
        for other in _MOCK_PAPERS:
            if other["paper_id"] != p.paper_id and other["year"] < p.year:
                refs.append(other["paper_id"])
            if len(refs) >= 3:
                break
        p.__dict__["references"] = refs
    return p


def get_mock_papers(query: str = "", limit: int = 20) -> list[Paper]:
    """根据 query 关键词做严格相关性评分，返回真正相关的论文。

    评分规则：
      - 标题包含完整查询短语: +10
      - 标题包含任一查询词:   +3 / 词
      - 摘要包含查询词:       +1 / 词
      - 引用数加成:            log(citations) / 10
    取评分 >= 4 的论文，按分数降序；不足 limit 时用次相关池补齐。
    """
    q = (query or "").lower().strip()
    if not q:
        return [_to_paper(item) for item in _MOCK_PAPERS[:limit]]

    query_words = [w for w in q.split() if len(w) > 1]
    if not query_words:
        return [_to_paper(item) for item in _MOCK_PAPERS[:limit]]

    scored = []
    for item in _MOCK_PAPERS:
        title_lower = item["title"].lower()
        abstract_lower = item.get("abstract", "").lower()
        word_score = 0.0
        # 完整短语命中
        if q in title_lower:
            word_score += 10.0
        # 单词命中
        for w in query_words:
            if w in title_lower:
                word_score += 3.0
            elif w in abstract_lower:
                word_score += 1.0

        # 引用数加成仅在有关键词命中时生效（避免无关高引论文霸榜）
        score = word_score
        if word_score > 0:
            cites = item.get("citation_count", 0)
            if cites > 0:
                import math
                score += math.log1p(cites) / 10.0
        scored.append((score, item))

    # 按分数降序
    scored.sort(key=lambda x: x[0], reverse=True)

    # 取分数 >= 4 的强相关论文
    strong = [(s, it) for s, it in scored if s >= 4.0]
    # 不够时用弱相关补齐
    if len(strong) < min(5, limit):
        weak = [(s, it) for s, it in scored if s < 4.0]
        strong.extend(weak[: max(0, min(limit, 5) - len(strong))])

    papers = [_to_paper(item) for _, item in strong]
    return papers[:limit]


def get_all_mock_papers() -> list[Paper]:
    """返回全部 mock 论文（用于 get_references）。"""
    return [_to_paper(item) for item in _MOCK_PAPERS]


# 用于 is_expanded 标记的辅助
def mark_as_expanded(paper: Paper) -> Paper:
    paper.is_expanded = True
    return paper


# ===== 真实 arXiv 链接映射（用于 mock 论文 URL） =====
# 来源：公开 arXiv 元数据
_PAPER_URL_MAP: dict[str, str] = {
    "ss_001_transformer":    "https://arxiv.org/abs/1706.03762",
    "ss_002_bert":           "https://arxiv.org/abs/1810.04805",
    "ss_003_gpt3":           "https://arxiv.org/abs/2005.14165",
    "ss_004_llama2":         "https://arxiv.org/abs/2307.09288",
    "ss_005_llm_survey":     "https://arxiv.org/abs/2303.18223",
    "ss_006_rag":            "https://arxiv.org/abs/2312.10997",
    "ss_007_chain_of_thought": "https://arxiv.org/abs/2201.11903",
    "ss_008_react":          "https://arxiv.org/abs/2210.03629",
    "ss_009_agent_survey":   "https://arxiv.org/abs/2308.11432",
    "ss_010_toolformer":     "https://arxiv.org/abs/2302.04761",
    "ss_011_codex":          "https://arxiv.org/abs/2107.03374",
    "ss_012_codegen":        "https://arxiv.org/abs/2203.07814",
    "ss_013_humaneval":      "https://arxiv.org/abs/2107.03374",
    "ss_014_maddpg":         "https://arxiv.org/abs/1706.02275",
    "ss_015_emergent":       "https://arxiv.org/abs/2009.01041",
    "ss_016_marl_survey":    "https://arxiv.org/abs/2108.12255",
    "ss_017_langchain":      "https://arxiv.org/abs/2310.08560",
    "ss_018_autogpt":        "https://github.com/Significant-Gravitas/Auto-GPT",
    "ss_019_reflexion":      "https://arxiv.org/abs/2303.11366",
    "ss_020_graphrag":       "https://arxiv.org/abs/2404.16130",
    "ss_021_yolo":           "https://arxiv.org/abs/1506.02640",
    "ss_022_faster_rcnn":    "https://arxiv.org/abs/1506.01497",
    "ss_023_detr":           "https://arxiv.org/abs/2005.12872",
    "ss_024_wav2vec":        "https://arxiv.org/abs/1904.05862",
    "ss_025_whisper":        "https://arxiv.org/abs/2212.04356",
    "ss_026_widedeep":       "https://arxiv.org/abs/1606.07792",
    "ss_027_ncf":            "https://arxiv.org/abs/1708.05031",
    "ss_028_vit":            "https://arxiv.org/abs/2010.11929",
    "ss_029_detr_seg":       "https://arxiv.org/abs/2304.02643",
    "ss_030_alphafold":      "https://www.nature.com/articles/s41586-021-03819-2",
    "ss_031_drug":           "https://arxiv.org/abs/2209.07482",
    "ss_032_gat":            "https://arxiv.org/abs/1710.10903",
    "ss_033_graphsage":      "https://arxiv.org/abs/1706.02216",
    "ss_034_ddpm":           "https://arxiv.org/abs/2006.11239",
    "ss_035_clip":           "https://arxiv.org/abs/2103.00020",
    "ss_036_fedavg":         "https://arxiv.org/abs/1602.05629",
    "ss_037_dpsgd":          "https://arxiv.org/abs/1607.00133",
    "ss_038_ppo":            "https://arxiv.org/abs/1707.06347",
    "ss_039_sac":            "https://arxiv.org/abs/1801.01290",
    "ss_040_word2vec":       "https://arxiv.org/abs/1301.3781",
    "ss_041_gan":            "https://arxiv.org/abs/1406.2661",
    "ss_042_vae":            "https://arxiv.org/abs/1312.6114",
    "ss_043_moco":           "https://arxiv.org/abs/1911.05722",
    "ss_044_simclr":         "https://arxiv.org/abs/2002.05709",
    "ss_045_vae2":           "https://arxiv.org/abs/1805.04833",
    "ss_046_cn_transformer": "https://github.com/inkcherry/Chinese-LLM-Survey",
    "ss_047_cn_quantum":     "https://github.com/awesome-quantum/quantum-ml",
    "ss_048_cn_vision":      "https://github.com/visual-transformer-survey/cn",
    "ss_049_kge":            "https://proceedings.neurips.cc/paper/2013/hash/1cecc7a77928ca8133fa24680a88d2f9-Abstract.html",
    "ss_050_kge_rotate":     "https://arxiv.org/abs/1902.10197",
    "openalex_W001":         "https://arxiv.org/abs/1512.03385",
    "openalex_W002":         "https://arxiv.org/abs/1412.6980",
    "openalex_W003":         "https://arxiv.org/abs/1406.2661",
    "openalex_W004":         "https://jmlr.org/papers/v15/srivastava14a.html",
    "openalex_W005":         "https://papers.nips.cc/paper/2012/hash/c399862d3b9d6b76c8436e924a68c45b-Abstract.html",
    "openalex_W006":         "https://arxiv.org/abs/1505.04597",
    "openalex_W007":         "https://openaccess.thecvf.com/content_cvpr_2014/papers/Taigman_DeepFace_Closing_the_2014_CVPR_paper.pdf",
    "openalex_W008":         "https://arxiv.org/abs/1603.02754",
}
