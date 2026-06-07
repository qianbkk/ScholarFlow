import { useState } from 'react';

/**
 * WhyScholarFlow — 5 大杀手场景 + 8 维对比折叠区
 *
 * M-19 (ScholarFlow 独特优势定位):
 *   - 默认折叠避免视觉负担 (用户可在结果页头部展开)
 *   - 4 大场景卡片 (emoji + 标题 + 1 句描述 + "其他工具 ✗" 对比)
 *   - "全网唯一" amber 标签凸显差异化
 */
const SCENES = [
  {
    emoji: '📚',
    title: '研究生综述周',
    desc: '1 周交方向综述, 1 个 query 出 8 节点流水线报告 (综述 + 引用追溯 + 图谱)',
    others: '知网 1 周 1 篇综述 / Google Scholar 不生成综述 / SS 单篇 TLDR',
  },
  {
    emoji: '🎓',
    title: '导师基金申请 (NSF/NSFC)',
    desc: 'Background 要 50 篇 2024-2026 最新预印本, 沿引用链 + forward citers 双向扩展',
    others: 'Connected Papers 5 图/月 收费 + 单 seed / 知网 / SS 无 forward',
  },
  {
    emoji: '🔍',
    title: '博士开题 + 跨 query 预算',
    desc: '实时 per-model token/cost 折叠面板, 写开题 1 个月后清楚知道哪些方向烧钱',
    others: 'Google Scholar / 知网 / SS 全部黑盒, 不知道查一次多少钱',
  },
  {
    emoji: '🇨🇳',
    title: '中文文献调研',
    desc: '唯一中英双语: 中文 query 拆英文子查询 → 双源并行 → 中文综述输出, 中文 sanitize 防注入',
    others: '知网 0 个 LLM 能力 / SS 0 个中文支持 / Connected Papers 不接中文',
  },
  {
    emoji: '🏢',
    title: '实验室 RAG 私有化',
    desc: 'docker-compose up 一键起 backend + frontend, 数据全在本地, 唯一外联是 SS/OpenAlex API',
    others: '知网 100 万+/年 + 闭源 / SS 全部走公网 / OpenAlex 走 OurResearch 公有云',
  },
];

export function WhyScholarFlow() {
  const [open, setOpen] = useState(false);

  return (
    <details
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      className="bg-white/80 dark:bg-slate-800/80 backdrop-blur rounded-lg border border-slate-200 dark:border-slate-700 mb-4 overflow-hidden"
    >
      <summary className="px-4 py-3 cursor-pointer flex items-center justify-between text-sm font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors">
        <span>
          💡 <span className="text-amber-600 dark:text-amber-400">为什么用 ScholarFlow?</span>
          <span className="text-xs font-normal text-slate-500 ml-2">(差异化 vs 知网/Google Scholar/SS)</span>
        </span>
        <span className="text-slate-400 text-xs">{open ? '收起' : '展开'}</span>
      </summary>
      {open && (
        <div className="px-4 pb-4 space-y-3 border-t border-slate-100 dark:border-slate-700 pt-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {SCENES.map((s) => (
              <div
                key={s.title}
                className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700/50 rounded-md p-3"
              >
                <div className="flex items-start gap-2">
                  <span className="text-2xl flex-shrink-0">{s.emoji}</span>
                  <div className="flex-1 min-w-0">
                    <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                      {s.title}
                    </h4>
                    <p className="text-xs text-slate-600 dark:text-slate-300 mt-1 leading-relaxed">
                      {s.desc}
                    </p>
                    <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-1.5 italic">
                      其他工具: {s.others}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="bg-amber-100 dark:bg-amber-900/40 border border-amber-300 dark:border-amber-700 rounded p-2.5 text-xs text-amber-900 dark:text-amber-100">
            <strong>全网唯一组合</strong>: LLM 综述 + 引用可核查 + Grounding 防幻觉 + 中文支持 + 私有化部署 + 成本可见
            — 5 项任意 1 项 Google Scholar / 知网 / SS / Connected Papers 都不做。
          </div>
        </div>
      )}
    </details>
  );
}
