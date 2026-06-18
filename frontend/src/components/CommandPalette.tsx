/**
 * P1: 命令面板 (Command Palette)
 * 灵感来自 FanBox 的快捷操作菜单
 * 
 * 功能:
 * - Cmd+K / Ctrl+K 呼出
 * - 指令如/summarize、/critique、/export bibtex等
 * - 减少鼠标操作，提升极客体验
 */
import { useState, useEffect, useCallback, useMemo } from 'react';

interface Command {
  id: string;
  label: string;
  description: string;
  shortcut?: string;
  category: 'general' | 'filter' | 'export' | 'view' | 'agent';
  action: () => void;
}

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onExecuteCommand?: (commandId: string) => void;
}

export function CommandPalette({ isOpen, onClose, onExecuteCommand }: Props) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);

  // 定义可用命令
  const commands: Command[] = useMemo(() => [
    {
      id: 'summarize',
      label: '/summarize',
      description: '快速生成当前文献摘要',
      shortcut: '⌘S',
      category: 'agent',
      action: () => console.log('Executing: summarize'),
    },
    {
      id: 'critique',
      label: '/critique',
      description: '触发 Critic Agent 评审选中论文',
      shortcut: '⌘C',
      category: 'agent',
      action: () => console.log('Executing: critique'),
    },
    {
      id: 'compare',
      label: '/compare',
      description: '开启分屏对比模式',
      shortcut: '⌘D',
      category: 'view',
      action: () => console.log('Executing: compare'),
    },
    {
      id: 'export-bibtex',
      label: '/export bibtex',
      description: '导出参考文献为 BibTeX 格式',
      category: 'export',
      action: () => console.log('Executing: export bibtex'),
    },
    {
      id: 'export-ris',
      label: '/export ris',
      description: '导出参考文献为 RIS 格式',
      category: 'export',
      action: () => console.log('Executing: export ris'),
    },
    {
      id: 'export-csv',
      label: '/export csv',
      description: '导出文献元数据为 CSV',
      category: 'export',
      action: () => console.log('Executing: export csv'),
    },
    {
      id: 'filter-rct',
      label: '/filter rct',
      description: '快速过滤 RCT 研究',
      category: 'filter',
      action: () => console.log('Executing: filter rct'),
    },
    {
      id: 'filter-recent',
      label: '/filter recent',
      description: '只看近 3 年文献',
      category: 'filter',
      action: () => console.log('Executing: filter recent'),
    },
    {
      id: 'filter-high-quality',
      label: '/filter quality',
      description: '只看高质量论文 (评分≥8)',
      category: 'filter',
      action: () => console.log('Executing: filter quality'),
    },
    {
      id: 'toggle-dark-mode',
      label: '/toggle theme',
      description: '切换深色/浅色主题',
      shortcut: '⌘T',
      category: 'general',
      action: () => console.log('Executing: toggle theme'),
    },
    {
      id: 'reset-filters',
      label: '/reset filters',
      description: '重置所有过滤器',
      category: 'filter',
      action: () => console.log('Executing: reset filters'),
    },
    {
      id: 'expand-graph',
      label: '/expand graph',
      description: '扩展当前图谱节点',
      category: 'view',
      action: () => console.log('Executing: expand graph'),
    },
    {
      id: 'focus-query',
      label: '/focus query',
      description: '聚焦到查询输入框',
      shortcut: '⌘L',
      category: 'general',
      action: () => console.log('Executing: focus query'),
    },
  ], []);

  // 过滤命令
  const filteredCommands = useMemo(() => {
    if (!searchQuery.trim()) return commands;
    
    const query = searchQuery.toLowerCase();
    return commands.filter(cmd =>
      cmd.label.toLowerCase().includes(query) ||
      cmd.description.toLowerCase().includes(query) ||
      cmd.category.includes(query)
    );
  }, [commands, searchQuery]);

  // 按类别分组
  const groupedCommands = useMemo(() => {
    const groups: Record<string, Command[]> = {};
    filteredCommands.forEach(cmd => {
      if (!groups[cmd.category]) {
        groups[cmd.category] = [];
      }
      groups[cmd.category].push(cmd);
    });
    return groups;
  }, [filteredCommands]);

  // 键盘导航
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex(prev => 
          prev < filteredCommands.length - 1 ? prev + 1 : 0
        );
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex(prev => 
          prev > 0 ? prev - 1 : filteredCommands.length - 1
        );
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const selected = filteredCommands[selectedIndex];
        if (selected) {
          selected.action();
          onExecuteCommand?.(selected.id);
          onClose();
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, filteredCommands, selectedIndex, onClose, onExecuteCommand]);

  // 全局快捷键监听
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
      const modifierKey = isMac ? e.metaKey : e.ctrlKey;
      
      if (modifierKey && e.key === 'k') {
        e.preventDefault();
        // 如果已打开则关闭，否则不处理（由父组件控制）
        if (isOpen) {
          onClose();
        }
      }
    };

    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown);
  }, [isOpen, onClose]);

  // 重置搜索和选择索引
  useEffect(() => {
    if (isOpen) {
      setSearchQuery('');
      setSelectedIndex(0);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const categories: Record<string, { label: string; icon: string }> = {
    general: { label: '通用', icon: '⚙️' },
    filter: { label: '过滤', icon: '🔍' },
    export: { label: '导出', icon: '📤' },
    view: { label: '视图', icon: '👁️' },
    agent: { label: 'AI Agent', icon: '🤖' },
  };

  let globalIndex = 0;

  return (
    <div className="command-palette-overlay" style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.6)',
      backdropFilter: 'blur(4px)',
      zIndex: 9999,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
    }} onClick={onClose}>
      <div className="command-palette" style={{
        width: '560px',
        maxHeight: '70vh',
        backgroundColor: 'var(--sf-bg-elev)',
        borderRadius: '12px',
        border: '1px solid var(--sf-border)',
        boxShadow: '0 24px 48px rgba(0, 0, 0, 0.4)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }} onClick={e => e.stopPropagation()}>
        {/* 搜索输入框 */}
        <div className="command-input-wrapper" style={{
          padding: '16px',
          borderBottom: '1px solid var(--sf-border)',
        }}>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="输入命令或搜索... (例如：/export, /filter)"
            autoFocus
            style={{
              width: '100%',
              padding: '12px 16px',
              fontSize: '14px',
              backgroundColor: 'var(--sf-bg)',
              border: '1px solid var(--sf-border)',
              borderRadius: '8px',
              color: 'var(--sf-text)',
              outline: 'none',
              fontFamily: 'monospace',
            }}
          />
          <div style={{
            marginTop: '8px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: '11px',
            color: 'var(--sf-muted)',
          }}>
            <span>💡 提示：使用 ↑↓ 导航，Enter 执行，Esc 关闭</span>
            <span style={{ fontFamily: 'monospace' }}>⌘K 关闭</span>
          </div>
        </div>

        {/* 命令列表 */}
        <div className="command-list" style={{
          flex: 1,
          overflowY: 'auto',
          padding: '8px 0',
        }}>
          {Object.entries(groupedCommands).map(([category, cmds]) => (
            <div key={category} className="command-group">
              {/* 组标题 */}
              <div style={{
                padding: '8px 16px',
                fontSize: '11px',
                fontWeight: '600',
                color: 'var(--sf-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}>
                <span>{categories[category]?.icon}</span>
                <span>{categories[category]?.label}</span>
                <span style={{
                  marginLeft: 'auto',
                  fontSize: '10px',
                  opacity: 0.7,
                }}>
                  {cmds.length}
                </span>
              </div>

              {/* 命令项 */}
              {cmds.map((cmd) => {
                const index = globalIndex++;
                const isSelected = index === selectedIndex;

                return (
                  <button
                    key={cmd.id}
                    onClick={() => {
                      cmd.action();
                      onExecuteCommand?.(cmd.id);
                      onClose();
                    }}
                    onMouseEnter={() => setSelectedIndex(index)}
                    style={{
                      width: '100%',
                      padding: '10px 16px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '12px',
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      textAlign: 'left',
                      backgroundColor: isSelected ? 'var(--sf-accent)' : 'transparent',
                      color: isSelected ? 'white' : 'var(--sf-text)',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    {/* 命令标签 */}
                    <span style={{
                      fontFamily: 'monospace',
                      fontSize: '13px',
                      fontWeight: '600',
                      minWidth: '120px',
                    }}>
                      {cmd.label}
                    </span>

                    {/* 命令描述 */}
                    <span style={{
                      fontSize: '12px',
                      opacity: isSelected ? 0.9 : 1,
                      flex: 1,
                    }}>
                      {cmd.description}
                    </span>

                    {/* 快捷键 */}
                    {cmd.shortcut && (
                      <span style={{
                        fontSize: '10px',
                        fontFamily: 'monospace',
                        padding: '2px 6px',
                        backgroundColor: isSelected ? 'rgba(255,255,255,0.2)' : 'var(--sf-bg)',
                        borderRadius: '4px',
                        opacity: isSelected ? 1 : 0.7,
                      }}>
                        {cmd.shortcut}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}

          {filteredCommands.length === 0 && (
            <div style={{
              padding: '40px 16px',
              textAlign: 'center',
              color: 'var(--sf-muted)',
              fontSize: '13px',
            }}>
              <div style={{ fontSize: '24px', marginBottom: '8px' }}>🔍</div>
              <div>未找到匹配的命令</div>
              <div style={{ fontSize: '11px', marginTop: '4px', opacity: 0.8 }}>
                尝试搜索其他关键词，如 "export", "filter", "summarize"
              </div>
            </div>
          )}
        </div>

        {/* 底部状态栏 */}
        <div className="command-footer" style={{
          padding: '8px 16px',
          borderTop: '1px solid var(--sf-border)',
          backgroundColor: 'var(--sf-bg)',
          fontSize: '10px',
          color: 'var(--sf-muted)',
          display: 'flex',
          justifyContent: 'space-between',
        }}>
          <span>共 {filteredCommands.length} 个命令</span>
          <span>ScholarFlow Command Palette v1.0</span>
        </div>
      </div>
    </div>
  );
}

// Hook: 使用命令面板
export function useCommandPalette() {
  const [isOpen, setIsOpen] = useState(false);

  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);
  const toggle = useCallback(() => setIsOpen(prev => !prev), []);

  // 注册全局快捷键
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
      const modifierKey = isMac ? e.metaKey : e.ctrlKey;
      
      if (modifierKey && e.key === 'k') {
        e.preventDefault();
        toggle();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggle]);

  return {
    isOpen,
    open,
    close,
    toggle,
  };
}
