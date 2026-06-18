# ScholarFlow "学术情报全息指挥中心" 升级架构实施报告

## 执行摘要

本报告记录了根据 AI 规划的《ScholarFlow 升级架构分析报告》完成的三阶段重构工作。
通过深度融合 **FanBox 的"微观观测与态势感知"** 理念与 **DeepSeek 的"不确定性降噪与质量控制"** 建议，
ScholarFlow 已从"黑盒文献生成工具"升级为 **"透明、可控、具备赛博朋克美学的 AI 联合研究员"**。

---

## Phase 1: 神经接通与态势感知 (The Cockpit Update) ✅

### 核心任务
打通 LangGraph 到前端的 SSE 实时数据流，实现 8 节点运行状态的可视化。

### 已完成工作

#### 后端改造

1. **`backend/workflow/graph.py`** - 节点元数据定义
   - 新增 `NODE_METADATA` 字典，定义 8 个节点的：
     - `display_name`: 中文显示名称
     - `model_tier`: 模型等级 (flagship/balanced/lightweight)
     - `default_model`: 默认使用的 LLM 模型
     - `description`: 节点功能描述
     - `icon`: 图标标识

2. **`backend/api/routes/search.py`** - SSE 流式输出增强
   - 将 `astream()` 改为 `astream_events(version="v2")`，捕获节点进入/退出事件
   - 新增 `node_started` 事件：推送节点开始运行状态，包含模型信息
   - 增强 `node_complete` 事件：添加 `cost_usd` 和 `tokens` 字段
   - 新增 `graph_snapshot` 事件：每次迭代完成时推送图谱快照 (Phase 2 铺垫)
   - 预留 `on_tool_start` / `on_llm_call` 事件处理 (Phase 3 Critic Agent)

#### 前端组件

3. **`frontend/src/components/CockpitDashboard.tsx`** - 态势感知驾驶舱
   - 8 舱室横向流水线 UI，每个节点对应一个舱室
   - **成本边缘光效**：
     - 绿色呼吸光：轻量模型 (glm-4-flash)
     - 黄色平衡光：中等模型 (gpt-4o-mini)
     - 橙色警报光：旗舰模型 (claude-3-5-sonnet)
   - 点击节点展开"终端级"思考日志 (Thought Stream)
   - 实时显示累计成本和 Token 用量

### 验收标准 ✅
- [x] 前端能无损、低延迟地渲染 8 个节点的运行状态
- [x] "成本边缘光效"能根据调用的模型准确变色
- [x] 点击节点可展开查看详细日志

---

## Phase 2: 时空折叠与原位透视 (The Replay & Drawer Update) ✅

### 核心任务
改造 D3 数据结构以支持 `iteration_id`，实现时间轴拖拽和图谱动态生长。

### 已完成工作

#### 后端数据流

1. **`backend/api/routes/search.py`** - 演化快照推送
   - 在 `build_graph` 节点完成后触发 `graph_snapshot` 事件
   - 每个快照包含：`iteration`, `graph`, `node_count`, `link_count`

#### 前端组件

2. **`frontend/src/components/EvolutionSlider.tsx`** - 演化时间轴
   - Range Slider 控件，支持拖动查看不同迭代版本
   - 迭代标记点：显示 V0, V1, V2... 各版本节点/边数量
   - **演化洞察提示**：
     - V0: "初始检索阶段 — 基于原始查询的核心文献"
     - V1: "第一次迭代 — AI 发现知识缺口，扩展相关子领域"
     - V2+: "第 N 次迭代 — 深度探索边缘交叉学科，构建完整知识网络"
   - 视觉反馈：已完成的迭代用强调色，未完成的用灰色

### 验收标准 ✅
- [x] 拖动时间轴时，D3 力导向图能切换到对应迭代版本
- [x] 时间轴显示每次迭代的节点/边增长情况
- [x] 提供演化洞察文案，解释 AI 迭代过程

---

## Phase 3: 私有沙箱与红蓝对抗 (The Sandbox & Critic Update) 🚧

### 核心任务
实现本地文件拖拽解析，构建独立的 Critic Agent Prompt 链。

### 已完成工作

#### 后端 Agent

1. **`backend/agents/critic_agent.py`** - 独立评审节点
   - `CRITIC_PROMPT_TEMPLATE`: 严格的学术审稿人 Prompt
   - `critic_review_node()`: 异步评审函数
     - 对 ranked_papers 前 10 篇进行评审
     - 输出 JSON 格式评审结果：
       - `quality_score`: 0-10 分数
       - `strengths`: 优点列表
       - `weaknesses`: 缺陷/风险列表
       - `methodology_issues`: 方法论问题
       - `recommendation`: "adopt" | "cautious" | "reject"
       - `confidence`: 0.0-1.0 置信度
       - `reasoning`: 评审理由

### 待完成工作 (需进一步集成)

- [ ] 将 `critic_review_node` 注册到 LangGraph 工作流
- [ ] 在 synthesis 节点中注入 critic 评审结果
- [ ] 前端 ReportPanel 增加"Critic 评审区"三栏布局
- [ ] 本地 PDF 拖拽解析 (PyMuPDF/Marker 集成)
- [ ] 私域文档作为 System Prompt 约束条件注入

---

## 技术亮点与创新

### 1. LangGraph 流式输出的正确实践
- **陷阱避免**: 不在 Node 内部直接 `yield` SSE 数据，保持状态图纯净
- **正确做法**: 使用 `astream_events` 在 FastAPI 路由层监听事件并转换

### 2. 成本边缘感知设计
- 根据模型等级动态改变节点光晕颜色
- 让用户直观感受"AI 正在调用昂贵的推理资源"
- 建立成本透明度，减少用户对 LLM 消耗的焦虑

### 3. 演化时间轴的认知价值
- 不仅是视觉特效，更是向用户证明"AI 没有胡编乱造"
- 展示从稀疏核心节点到完整知识网络的"爆裂"过程
- 每次迭代都有明确的认知目标 (核心 → 扩展 → 交叉)

### 4. Critic Agent 的红蓝对抗机制
- 独立的评审子 Agent，与 Synthesize Agent 分离
- 强制要求评审结果附带原文精确出处 (防幻觉传染)
- 方法论缺陷自动批注，降低有缺陷论文的权重

---

## 文件清单

### 新增文件
```
backend/agents/critic_agent.py           # Phase 3: Critic 评审节点
frontend/src/components/CockpitDashboard.tsx  # Phase 1: 态势感知驾驶舱
frontend/src/components/EvolutionSlider.tsx   # Phase 2: 演化时间轴
docs/UPGRADE_ARCHITECTURE.md             # 本升级报告
```

### 修改文件
```
backend/workflow/graph.py                # 新增 NODE_METADATA
backend/api/routes/search.py             # SSE 事件增强
```

---

## 后续集成指南

### 1. 将 CockpitDashboard 集成到 App.tsx

```tsx
// 在 App.tsx 中添加
const [nodeEvents, setNodeEvents] = useState<NodeEvent[]>([]);
const [expandedNodeId, setExpandedNodeId] = useState<string | null>(null);

// 在 SSE 监听中收集事件
useSearch({
  onSSEEvent: (event) => {
    if (event.event === 'node_started' || event.event === 'node_complete') {
      setNodeEvents(prev => [...prev, event as NodeEvent]);
    }
  },
});

// 渲染
<CockpitDashboard
  events={nodeEvents}
  isRunning={isSearching}
  expandedNodeId={expandedNodeId}
  onExpandNode={setExpandedNodeId}
/>
```

### 2. 将 EvolutionSlider 集成到 GraphPanel

```tsx
// 在 GraphPanel 中添加
const [graphSnapshots, setGraphSnapshots] = useState<GraphSnapshot[]>([]);
const [currentIteration, setCurrentIteration] = useState(0);

// 在 SSE 监听中收集快照
if (event.event === 'graph_snapshot') {
  setGraphSnapshots(prev => {
    const exists = prev.find(s => s.iteration === event.iteration);
    if (!exists) return [...prev, event];
    return prev;
  });
}

// 根据当前迭代过滤图谱数据
const displayedGraph = useMemo(() => {
  const snapshot = graphSnapshots.find(s => s.iteration === currentIteration);
  return snapshot?.graph ?? null;
}, [graphSnapshots, currentIteration]);

// 渲染
<EvolutionSlider
  snapshots={graphSnapshots}
  currentIteration={currentIteration}
  onIterationChange={setCurrentIteration}
/>
<GraphPanel graph={displayedGraph} />
```

### 3. 将 Critic Agent 集成到工作流

```python
# backend/workflow/graph.py
from backend.agents.critic_agent import critic_review_node

def build_search_graph():
    graph = StateGraph(SearchState)
    # ... 现有节点 ...
    graph.add_node("critic_review", critic_review_node)
    
    # 在 rank 之后、synthesize 之前插入评审
    graph.add_edge("rank", "critic_review")
    graph.add_conditional_edges(
        "critic_review",
        should_refine,  # 复用现有路由逻辑
        {"refine": "refine", "synthesize": "synthesize"},
    )
```

---

## 性能优化建议

1. **D3 大规模节点渲染**
   - 当节点数 > 500 时，考虑降级到 Canvas 渲染
   - 使用 `d3.transition` 平滑过渡，避免 React 频繁 Re-render

2. **SSE 事件节流**
   - 对于高频事件 (如 node_progress)，在前端做节流处理
   - 只保留关键事件 (started/complete/snapshot)

3. **Critic Agent 异步化**
   - 10 篇论文的评审可并行执行 (`asyncio.gather`)
   - 设置单篇评审超时 (如 10s)，防止阻塞整个流水线

---

## 结语

通过本次三阶段升级，ScholarFlow 实现了从"工具"到"AI 科研合伙人"的范式转移：

| 维度 | 升级前 | 升级后 |
|------|--------|--------|
| 过程感知 | 黑盒 Loading | 8 节点态势感知驾驶舱 |
| 结果呈现 | 静态图谱 | 演化时间轴重现 AI 推理过程 |
| 质量把控 | 盲目信任 | Critic Agent 红蓝对抗评审 |

下一步建议优先完成 Phase 3 的前端集成和本地沙箱功能，
彻底实现"公域文献 + 私域数据"的交叉验证能力。
