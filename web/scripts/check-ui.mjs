import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/**
 * 交互质量门禁（静态）：规则都对应真实故障，不是审美偏好。
 *   1. color-token：颜色必须走主题变量，否则暗色模式会冒出白块 / 黑字。
 *   2. shadow-token：阴影必须走变量，暗色下要更深。
 *   3. motion-token：时长必须走 DUR.*，否则全站动效节奏会各写各的。
 * 例外：同一行或上一行写 ui-lint-ignore 即可豁免（图片、平台色底上的白字属于例外）。
 */
// 从脚本位置推 web/ 根，这样在仓库根或 web/ 里执行都行
const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const root = path.join(web, "src");
const walk = (d) =>
  fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(d, e.name);
    return e.isDirectory() ? walk(p) : /\.(tsx|ts)$/.test(p) ? [p] : [];
  });

const rel = (p) => path.relative(web, p).replaceAll("\\", "/");
const violations = [];
const add = (file, line, rule, text) => violations.push({ file: rel(file), line, rule, text: text.trim().slice(0, 120) });

for (const file of walk(root)) {
  const name = rel(file);
  if (name.endsWith("src/motion.ts")) continue; // 令牌源文件本身不查
  const lines = fs.readFileSync(file, "utf8").split("\n");
  const window = (i, back, forward = 1) => lines.slice(Math.max(0, i - back), i + forward + 1).join("\n");

  lines.forEach((line, i) => {
    const n = i + 1;
    const near = window(i, 5);
    if (/ui-lint-ignore/.test(near)) return;

    if (/\bbg-white\b/.test(line)) {
      add(file, n, "color-token", "用 bg-paper，不要 bg-white（暗色模式下会变成白块）");
    }
    if (/\btext-white\b/.test(line) && !/bg-black|bg-paper\/|style=/.test(near)) {
      add(file, n, "color-token", "text-white 只用在图片或深色遮罩上，其余用 text-solid-fg");
    }
    if (/rgba\(\s*20\s*,\s*2[02]\s*,\s*2[46]/.test(line)) {
      add(file, n, "shadow-token", "阴影用 shadow-card / shadow-pop，不要写死 rgba");
    }
    if (/duration:\s*0\.\d+/.test(line)) {
      add(file, n, "motion-token", "时长用 DUR.*，不要写死小数");
    }
  });
}

const byRule = violations.reduce((m, v) => ({ ...m, [v.rule]: (m[v.rule] ?? 0) + 1 }), {});
const payload = { ok: violations.length === 0, count: violations.length, byRule, violations };
if (process.argv.includes("--json")) {
  console.log(JSON.stringify(payload));
} else {
  for (const v of violations) console.log(v.file + ":" + v.line + "  [" + v.rule + "]  " + v.text);
  console.log("\n" + (payload.ok ? "OK：没有违规" : violations.length + " 处违规"));
}
process.exit(payload.ok ? 0 : 1);
