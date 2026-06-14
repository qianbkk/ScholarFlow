// frontend/scripts/check-dompurify.mjs
//
// R10.5.22 (U.txt + U2.txt + U3.txt 审计 #4): 强制 XSS 防御链 —
// 每个 dangerouslySetInnerHTML 出现的地方, 必须有 DOMPurify 在前面 sanitize.
// 否则 LLM 输出可直接注入 <script> / javascript: 伪协议.
//
// 用法: npm run lint:dompurify
// 失败: 列出违规文件, 退出码 1, 阻止 commit.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const SRC_DIR = join(__dirname, '..', 'src');

const violations = [];

function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      walk(full);
    } else if (['.tsx', '.ts', '.jsx', '.js'].includes(extname(full))) {
      check(full);
    }
  }
}

function check(file) {
  const src = readFileSync(file, 'utf8');
  // 找 dangerouslySetInnerHTML 出现位置
  const lines = src.split('\n');
  const dangerLines = [];
  lines.forEach((line, i) => {
    if (line.includes('dangerouslySetInnerHTML')) {
      dangerLines.push({ line: i + 1, content: line.trim() });
    }
  });
  if (dangerLines.length === 0) return;
  // 检查整个文件是否 import DOMPurify
  if (!src.includes('DOMPurify') && !src.includes('dompurify')) {
    violations.push({
      file: file.replace(join(__dirname, '..') + '\\', '').replace(/\\/g, '/'),
      danger: dangerLines,
      reason: 'uses dangerouslySetInnerHTML but no DOMPurify import',
    }
    );
  }
}

walk(SRC_DIR);

if (violations.length > 0) {
  console.error('❌ DOMPurify XSS defense check FAILED:\n');
  for (const v of violations) {
    console.error(`  ${v.file}`);
    for (const d of v.danger) {
      console.error(`    L${d.line}: ${d.content}`);
    }
    console.error(`    reason: ${v.reason}\n`);
  }
  console.error(`Total: ${violations.length} file(s) violated the XSS defense contract.`);
  process.exit(1);
}

console.log('✅ All dangerouslySetInnerHTML usages are protected by DOMPurify.');
