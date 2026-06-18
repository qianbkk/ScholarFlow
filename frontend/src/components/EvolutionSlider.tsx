/**
 * Phase 2: D3 图谱演化时间轴 (Evolution Slider)
 * 动态重现 AI 逼近真理的过程，展示每次迭代的图谱生长
 */
import { useMemo, useCallback } from 'react';
import type { CitationGraph } from '../types';

interface GraphSnapshot {
  iteration: number;
  graph: CitationGraph;
  node_count: number;
  link_count: number;
}

interface Props {
  snapshots: GraphSnapshot[];
  currentIteration: number;
  onIterationChange: (iteration: number) => void;
  disabled?: boolean;
}

export function EvolutionSlider({ snapshots, currentIteration, onIterationChange, disabled = false }: Props) {
  const maxIteration = useMemo(() => {
    if (snapshots.length === 0) return 0;
    return Math.max(...snapshots.map(s => s.iteration));
  }, [snapshots]);

  const currentSnapshot = useMemo(() => {
    return snapshots.find(s => s.iteration === currentIteration);
  }, [snapshots, currentIteration]);

  const handleSliderChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const newIteration = parseInt(e.target.value, 10);
    onIterationChange(newIteration);
  }, [onIterationChange]);

  if (snapshots.length === 0) {
    return null;
  }

  return (
    <div className="evolution-slider" style={{
      padding: '16px',
      backgroundColor: 'var(--sf-bg-elev)',
      borderTop: '1px solid var(--sf-border)',
    }}>
      {/* 标题栏 */}
      <div className="slider-header" style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '12px',
      }}>
        <span style={{
          fontSize: '12px',
          fontWeight: '600',
          color: 'var(--sf-text)',
          letterSpacing: '0.05em',
        }}>
          图谱演化时间轴 (Evolution Timeline)
        </span>
        {currentSnapshot && (
          <span style={{
            fontSize: '11px',
            color: 'var(--sf-muted)',
            fontFamily: 'monospace',
          }}>
            V{currentSnapshot.iteration}: {currentSnapshot.node_count} 节点 · {currentSnapshot.link_count} 边
          </span>
        )}
      </div>

      {/* 滑块控件 */}
      <div className="slider-control" style={{
        position: 'relative',
        padding: '0 10px',
      }}>
        <input
          type="range"
          min={0}
          max={maxIteration}
          step={1}
          value={currentIteration}
          onChange={handleSliderChange}
          disabled={disabled}
          style={{
            width: '100%',
            height: '6px',
            appearance: 'none',
            background: 'linear-gradient(to right, var(--sf-accent) 0%, var(--sf-accent) ' + 
                        ((currentIteration / maxIteration) * 100) + '%, var(--sf-border) ' +
                        ((currentIteration / maxIteration) * 100) + '%, var(--sf-border) 100%)',
            borderRadius: '3px',
            outline: 'none',
            cursor: disabled ? 'not-allowed' : 'pointer',
          }}
        />

        {/* 迭代标记点 */}
        <div className="iteration-marks" style={{
          position: 'relative',
          marginTop: '8px',
          display: 'flex',
          justifyContent: 'space-between',
        }}>
          {snapshots.map((snapshot) => (
            <button
              key={snapshot.iteration}
              onClick={() => onIterationChange(snapshot.iteration)}
              disabled={disabled}
              style={{
                position: 'relative',
                marginLeft: `${(snapshot.iteration / maxIteration) * 100}%`,
                transform: 'translateX(-50%)',
                background: 'none',
                border: 'none',
                cursor: disabled ? 'default' : 'pointer',
                padding: '4px 0',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                opacity: disabled ? 0.5 : 1,
              }}
            >
              {/* 标记点 */}
              <div
                style={{
                  width: '12px',
                  height: '12px',
                  borderRadius: '50%',
                  backgroundColor: snapshot.iteration <= currentIteration
                    ? 'var(--sf-accent)'
                    : 'var(--sf-border)',
                  border: '2px solid var(--sf-bg)',
                  transition: 'background-color 0.2s ease',
                }}
              />
              {/* 迭代标签 */}
              <span style={{
                fontSize: '10px',
                color: snapshot.iteration <= currentIteration
                  ? 'var(--sf-accent)'
                  : 'var(--sf-muted)',
                marginTop: '4px',
                fontFamily: 'monospace',
              }}>
                V{snapshot.iteration}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* 演化说明 */}
      <div className="evolution-hint" style={{
        marginTop: '12px',
        padding: '10px',
        backgroundColor: 'var(--sf-bg)',
        borderRadius: '4px',
        border: '1px dashed var(--sf-border)',
        fontSize: '11px',
        color: 'var(--sf-muted)',
        lineHeight: '1.6',
      }}>
        <span style={{ color: 'var(--sf-accent)', fontWeight: '600' }}>💡 演化洞察：</span>
        {currentIteration === 0 && "初始检索阶段 — 基于原始查询的核心文献"}
        {currentIteration === 1 && "第一次迭代 — AI 发现知识缺口，扩展相关子领域"}
        {currentIteration >= 2 && `第${currentIteration}次迭代 — 深度探索边缘交叉学科，构建完整知识网络`}
        <br />
        <span style={{ opacity: 0.8 }}>
          拖动滑块查看图谱如何从稀疏核心节点"爆裂"出完整的引用网络，
          这证明 AI 通过{maxIteration + 1}次严谨迭代找到这些文献。
        </span>
      </div>
    </div>
  );
}
