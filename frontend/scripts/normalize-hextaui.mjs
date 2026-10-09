#!/usr/bin/env node
/**
 * hextaUI コンポーネントの正規化取り込みスクリプト
 * (docs/fe-floor-orientation-redesign-plan.md §6.4 / D9)。
 *
 * hextaUI の shadcn レジストリはソースをそのまま配布しており、依存として
 * `cn` npm パッケージと `@tabler/icons-react` を要求する。本プロジェクトは
 * 依存追加ゼロの規約(cn = @/lib/utils.ts、アイコン = lucide-react / react-icons/fa6)
 * で運用しているため、registry JSON を取得して機械的に正規化してから配置する。
 * `shadcn add` の自動適用は theme.json 経由で index.css に 70 変数を投入するため
 * 使わない(--text-* 直値が --font-scale スケールと衝突する)。
 *
 * 使い方:
 *   node scripts/normalize-hextaui.mjs item empty spinner progress
 *   node scripts/normalize-hextaui.mjs --dry-run item
 *   node scripts/normalize-hextaui.mjs --url https://hextaui.com/r/card.json --name card-x
 *
 * 出力: src/components/ui/<name>.tsx (--dir で変更可)
 * 依存パッケージの追加が必要な場合は標準出力に警告し、exit code 1 で終了する
 * (呼び出し側が package.json を確認してから再実行する)。
 */
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

/** tabler アイコン → lucide-react の対応(使われた分だけ対応表を増やす) */
const ICON_MAP = {
  IconChevronRight: 'ChevronRight',
  IconChevronDown: 'ChevronDown',
  IconChevronLeft: 'ChevronLeft',
  IconChevronUp: 'ChevronUp',
  IconSelector: 'ChevronsUpDown',
  IconCheck: 'Check',
  IconCircleFilled: 'CircleDot',
  IconX: 'X',
  IconSearch: 'Search',
  IconLoader: 'Loader',
};

/** 依存追加が不要な既知パッケージ(プロジェクトに既にある) */
const KNOWN_DEPS = new Set([
  'react',
  'react-dom',
  '@base-ui/react',
  'class-variance-authority',
  'tailwind-merge',
  'clsx',
  'tw-animate-css',
  'shadcn',
  'cn', // 正規化で除去するため追加不要
  '@tabler/icons-react', // 正規化で lucide へ置換するため追加不要
]);

function parseArgs(argv) {
  const opts = { names: [], url: null, name: null, dir: 'src/components/ui', dryRun: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--url') opts.url = argv[++i];
    else if (arg === '--name') opts.name = argv[++i];
    else if (arg === '--dir') opts.dir = argv[++i];
    else if (arg.startsWith('-')) throw new Error(`未知のオプション: ${arg}`);
    else opts.names.push(arg);
  }
  if (!opts.url && opts.names.length === 0) {
    throw new Error('コンポーネント名または --url を指定してください');
  }
  return opts;
}

/** hextaUI ソース文字列 → 本プロジェクト規約へ正規化した文字列 */
export function normalizeSource(source) {
  let out = source;
  const notes = [];

  // 1. cn npm パッケージ → ローカル正本
  if (out.includes('from "cn"')) {
    out = out.replace(/from "cn"/g, 'from "@/lib/utils.ts"');
    notes.push('cn: "cn" → "@/lib/utils.ts"');
  }

  // 2. tabler アイコン → lucide-react(名前は対応表で変換)
  //    単一行 import と複数行 import の両方を扱う。`import {` から tabler の
  //    閉じ括弧までは他の import 文を跨ぎ得るため、行単位で境界を取る
  const lines = out.split('\n');
  const tablerEnd = lines.findIndex((l) => /from "@tabler\/icons-react"/.test(l));
  if (tablerEnd >= 0) {
    let tablerStart = tablerEnd;
    while (tablerStart >= 0 && !/^import \{/.test(lines[tablerStart])) tablerStart -= 1;
    if (tablerStart < 0) {
      throw new Error('tabler アイコン import の開始行が見つかりません');
    }
    const block = lines.slice(tablerStart, tablerEnd + 1).join('\n');
    const names = block
      .replace(/^import \{/, '')
      .replace(/\} from "@tabler\/icons-react";?$/, '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    const mapped = names.map((n) => {
      const lucide = ICON_MAP[n];
      if (!lucide) throw new Error(`アイコン対応表に無い tabler アイコン: ${n}(ICON_MAP へ追加してください)`);
      return lucide;
    });
    lines.splice(tablerStart, tablerEnd - tablerStart + 1, `import { ${mapped.join(', ')} } from "lucide-react";`);
    out = lines.join('\n');
    // JSX/変数参照も置換する(名前が変わる場合のみ)
    names.forEach((n, i) => {
      if (n !== mapped[i]) out = out.replace(new RegExp(`\\b${n}\\b`, 'g'), mapped[i]);
    });
    notes.push(`icons: ${names.join(', ')} → lucide(${mapped.join(', ')})`);
  }

  // 3. オーバーレイの z-index をプロジェクト規約へ寄せる。
  //    hextaUI はポップアップを z-50 で組む(単層アプリ前提)が、本プロジェクトは
  //    詳細パネル z-[1000] / モバイルシート z-[2100] / モーダル z-[9998-9999] の
  //    多層構成のため、z-50 のままだとパネルの下に隠れて操作不能になる
  //    (2026-10-10 の BuildingPanel 並び順セレクトで実害)。
  //    Positioner の `isolate z-50` を最上位の z-[10000](menu/tooltip/popover と同値)へ。
  if (out.includes('isolate z-50')) {
    out = out.replace(/isolate z-50/g, 'isolate z-[10000]');
    notes.push('overlay: isolate z-50 → isolate z-[10000](プロジェクトのオーバーレイ規約)');
  }

  // 4. 末尾の改行を 1 つに整える
  out = `${out.replace(/\s+$/, '')}\n`;
  return { code: out, notes };
}

async function fetchRegistry(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`registry 取得失敗: ${url} (${res.status})`);
  return res.json();
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const targets = opts.url
    ? [{ url: opts.url, name: opts.name }]
    : opts.names.map((n) => ({ url: `https://hextaui.com/r/${n}.json`, name: n }));

  const extraDeps = new Set();
  for (const target of targets) {
    const item = await fetchRegistry(target.url);
    const name = target.name ?? item.name;
    for (const dep of item.dependencies ?? []) {
      const bare = dep.replace(/@[\^~>].*$/, '');
      if (!KNOWN_DEPS.has(bare)) extraDeps.add(dep);
    }
    for (const file of item.files ?? []) {
      if (file.type !== 'registry:ui') continue;
      if (!name) throw new Error(`${target.url} のコンポーネント名が不明です(--name を指定)`);
      const { code, notes } = normalizeSource(file.content);
      const dest = path.join(process.cwd(), opts.dir, `${name}.tsx`);
      if (opts.dryRun) {
        console.log(`[dry-run] ${dest}`);
      } else {
        await mkdir(path.dirname(dest), { recursive: true });
        await writeFile(dest, code, 'utf8');
        console.log(`書き込み: ${dest}`);
      }
      for (const note of notes) console.log(`  - ${note}`);
      const hairlines = code.includes('--hairline');
      const animates = [...new Set(code.match(/animate-[a-z-]+/g) ?? [])];
      if (hairlines) console.log('  - 要 index.css: --hairline(未定義なら自動で 1px 扱い)');
      if (animates.length) {
        console.log(`  - 要 index.css keyframes: ${animates.join(', ')}`);
      }
    }
  }

  if (extraDeps.size > 0) {
    console.error(`\n追加依存が必要です(pnpm add を検討): ${[...extraDeps].join(', ')}`);
    process.exitCode = 1;
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    console.error(err.message);
    process.exitCode = 1;
  });
}
