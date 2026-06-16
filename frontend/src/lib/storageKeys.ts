/**
 * R10.5.30 (D7 P2-4): localStorage / sessionStorage key 集中.
 *
 * 之前 5 文件各自散落 const STORAGE_KEY = 'sf-xxx' (theme / api-key /
 * form-state / recent-searches / changelog-dismissed). typo 一个就破坏
 * 持久化, 集中后 grep 一处即可.
 *
 * 命名约定: sf-{module}-{key}. 改 key 后只改本文件.
 */
export const STORAGE_KEYS = {
  // theme — App.tsx loadStoredTheme
  theme: 'sf-theme',
  // API key — api.ts sessionStorage
  apiKey: 'sf-api-key',
  // form state (QueryPanel 输入框 + 滑块持久化)
  formState: 'sf-form-state',
  // recent searches (QueryPanel popover)
  recentSearches: 'sf-recent-searches',
  // 升级公告 sessionStorage 已阅 (R10.5.29 R10_5_28Banner)
  upgradeBannerDismissed: 'sf-r10_5_28-banner-dismissed',
  // R10.5.30 升级日志 modal 已阅
  changelogDismissed: 'sf-changelog-dismissed-30',
} as const;

export type StorageKey = (typeof STORAGE_KEYS)[keyof typeof STORAGE_KEYS];
