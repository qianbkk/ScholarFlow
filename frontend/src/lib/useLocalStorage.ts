/**
 * useLocalStorage — 统一封装 React 状态 + localStorage 持久化 (R10.5.9 落地)
 *
 * 4 处重复模式 (R10.5 code-review 标记):
 *   - useSearch.ts (loadRecent/saveRecent)
 *   - QueryPanel.tsx (loadStoredSettings/saveStoredSettings)
 *   - App.tsx (loadStoredTheme)
 *   - services/api.ts (getStoredApiKey/setStoredApiKey — 非 React, 用同名 plain util)
 *
 * 设计:
 *   1. 静默 try/catch: 隐私模式 / quota 超限 / SSR (无 window) 都不抛错,
 *      降级到内存 only — 旧实现 4 处都各写一份.
 *   2. JSON 序列化统一处理; 自定义 serializer 留给 LRU 这种带 cap 的特殊场景.
 *   3. cross-tab sync: storage 事件监听, 同一浏览器多 tab 状态一致 (旧实现无).
 *   4. 类型泛型 <T> + 初始值, 调用方零样板.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

interface UseLocalStorageOptions<T> {
  /** 反序列化失败时是否回退到 initialValue (默认 true) */
  fallbackOnError?: boolean;
  /** 跨 tab 同步 (storage 事件) — 默认 true */
  syncAcrossTabs?: boolean;
  /** 自定义校验: 反序列化后 run validate, 返回 false 则丢弃 */
  validate?: (v: unknown) => v is T;
}

/** 静态版本 — 非 React 上下文用 (services/api.ts) */
export function readLocalStorage<T>(
  key: string,
  initial: T,
  opts: { validate?: (v: unknown) => v is T } = {},
): T {
  if (typeof localStorage === 'undefined') return initial;
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return initial;
    const parsed: unknown = JSON.parse(raw);
    if (opts.validate && !opts.validate(parsed)) return initial;
    return parsed as T;
  } catch {
    return initial;
  }
}

export function writeLocalStorage<T>(key: string, value: T): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // quota / 隐私模式 / serialization fail — 静默
  }
}

export function removeLocalStorage(key: string): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.removeItem(key);
  } catch {
    // 静默
  }
}

/** React hook 版 — 状态变更自动持久化, 启动时自动恢复 */
export function useLocalStorage<T>(
  key: string,
  initial: T,
  opts: UseLocalStorageOptions<T> = {},
): [T, (v: T | ((prev: T) => T)) => void] {
  const { fallbackOnError = true, syncAcrossTabs = true, validate } = opts;
  const [value, setValue] = useState<T>(() =>
    readLocalStorage<T>(key, initial, { validate }),
  );
  // 用 ref 包 validate, 避免它引用变化触发 effect 重跑
  const validateRef = useRef(validate);
  validateRef.current = validate;

  const set = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const resolved =
          typeof next === 'function' ? (next as (p: T) => T)(prev) : next;
        writeLocalStorage(key, resolved);
        return resolved;
      });
    },
    [key],
  );

  // 跨 tab 同步: storage 事件在 *其他* tab 改时才 fire
  useEffect(() => {
    if (!syncAcrossTabs || typeof window === 'undefined') return;
    const onStorage = (e: StorageEvent) => {
      if (e.key !== key || e.newValue === null) {
        setValue(initial);
        return;
      }
      try {
        const parsed: unknown = JSON.parse(e.newValue);
        if (validateRef.current && !validateRef.current(parsed)) return;
        setValue(parsed as T);
      } catch {
        if (fallbackOnError) setValue(initial);
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [key, initial, fallbackOnError, syncAcrossTabs]);

  return [value, set];
}
