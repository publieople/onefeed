import { ArrowDown, ArrowUp, Loader2, Plus, Trash2, Zap } from "lucide-react";
import { useState } from "react";
import { aiTest, type AiProvider, type AiStatus, type AiTestResult } from "../api";

const PRESETS = [
  { name: "MiniMax", base_url: "https://api.minimaxi.com/v1", model: "MiniMax-M3.1-Flash" },
  { name: "DeepSeek", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
];

const MAX = 5;

interface Props {
  value: AiProvider[];
  onChange: (next: AiProvider[]) => void;
  status?: AiStatus | null;
}

/** 模型顺序表：排在上面的先用，挂了自动换下一个。key 只写不读。 */
export default function AiProviders({ value, onChange, status }: Props) {
  const [testing, setTesting] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, AiTestResult>>({});

  const update = (id: string, patch: Partial<AiProvider>) => {
    onChange(value.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  };

  const move = (index: number, delta: number) => {
    const next = [...value];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  const add = () => {
    if (value.length >= MAX) return;
    const used = new Set(value.map((p) => p.base_url));
    const preset = PRESETS.find((p) => !used.has(p.base_url)) ?? PRESETS[0];
    const id = "p" + Date.now().toString(36).slice(-5);
    onChange([
      ...value,
      { id, name: preset.name + (value.length ? " " + (value.length + 1) : ""), base_url: preset.base_url, model: preset.model, key: "", enabled: true },
    ]);
  };

  const test = async (row: AiProvider) => {
    setTesting(row.id);
    try {
      const result = await aiTest({ id: row.id, name: row.name, base_url: row.base_url, model: row.model, key: row.key ?? "" });
      setResults((prev) => ({ ...prev, [row.id]: result }));
    } catch (err) {
      setResults((prev) => ({ ...prev, [row.id]: { ok: false, error: (err as Error).message } }));
    } finally {
      setTesting(null);
    }
  };

  const chain = (status?.providers ?? []).map((p) => p.name);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-[12px]">
        <span className="text-fade">当前顺序</span>
        {chain.length ? (
          <span className="flex flex-wrap items-center gap-1.5">
            {chain.map((name, i) => (
              <span key={name} className="flex items-center gap-1.5">
                {i > 0 ? <span className="text-fade">→</span> : null}
                <span className={"rounded-full border px-2 py-0.5 " + (i === 0 ? "border-ink/25 bg-wash text-ink" : "border-line text-muted")}>
                  {name}
                </span>
              </span>
            ))}
          </span>
        ) : (
          <span className="text-muted">还没配，AI 只用本地规则解析</span>
        )}
        {status?.last && !status.last.ok && status.last.error ? (
          <span className="text-amber-600">上次失败：{status.last.provider} · {status.last.error.slice(0, 60)}</span>
        ) : null}
      </div>

      {value.map((row, index) => {
        const res = results[row.id];
        return (
          <div key={row.id} className="rounded-xl border border-line bg-white p-3.5">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-wash text-[12px] tabular-nums text-muted">
                {index + 1}
              </span>
              <input
                value={row.name}
                onChange={(e) => update(row.id, { name: e.target.value })}
                placeholder="给这个模型起个名"
                className="min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-1 py-0.5 text-[14px] font-medium outline-none hover:border-line focus:border-ink/30"
              />
              {row.key_set || row.key ? (
                <span className="rounded-full border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[11px] text-emerald-700">
                  key {row.key_hint || "已存"}
                </span>
              ) : (
                <span className="rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700">缺 key</span>
              )}
              <button
                onClick={() => update(row.id, { enabled: !row.enabled })}
                className={"h-5 w-9 shrink-0 rounded-full p-0.5 transition " + (row.enabled ? "bg-ink" : "bg-line")}
                title={row.enabled ? "点击停用（不上场）" : "点击启用"}
              >
                <span className={"block h-4 w-4 rounded-full bg-white shadow transition-transform duration-200 " + (row.enabled ? "translate-x-4" : "translate-x-0")} />
              </button>
              <button
                onClick={() => move(index, -1)}
                disabled={index === 0}
                className="rounded p-1 text-fade hover:text-ink disabled:opacity-30"
                title="上移（更优先）"
              >
                <ArrowUp size={13} />
              </button>
              <button
                onClick={() => move(index, 1)}
                disabled={index === value.length - 1}
                className="rounded p-1 text-fade hover:text-ink disabled:opacity-30"
                title="下移"
              >
                <ArrowDown size={13} />
              </button>
              <button
                onClick={() => onChange(value.filter((p) => p.id !== row.id))}
                className="rounded p-1 text-fade hover:text-red-600"
                title="删掉"
              >
                <Trash2 size={13} />
              </button>
            </div>

            <div className="mt-2.5 grid gap-2.5 sm:grid-cols-[1.6fr_1fr]">
              <label className="block">
                <span className="text-[11px] text-fade">接口地址</span>
                <input
                  value={row.base_url}
                  onChange={(e) => update(row.id, { base_url: e.target.value })}
                  placeholder="https://api.deepseek.com/v1"
                  className="mt-1 h-8 w-full rounded-lg border border-line bg-white px-2.5 font-mono text-[12px] outline-none focus:border-ink/40"
                />
              </label>
              <label className="block">
                <span className="text-[11px] text-fade">模型</span>
                <input
                  value={row.model}
                  onChange={(e) => update(row.id, { model: e.target.value })}
                  placeholder="deepseek-chat"
                  className="mt-1 h-8 w-full rounded-lg border border-line bg-white px-2.5 font-mono text-[12px] outline-none focus:border-ink/40"
                />
              </label>
            </div>

            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <input
                type="password"
                value={row.key ?? ""}
                onChange={(e) => update(row.id, { key: e.target.value })}
                placeholder={row.key_set ? "已保存，留空不改" : "sk-…"}
                autoComplete="off"
                className="h-8 min-w-[220px] flex-1 rounded-lg border border-line bg-white px-2.5 font-mono text-[12px] outline-none focus:border-ink/40"
              />
              <button
                onClick={() => void test(row)}
                disabled={testing === row.id}
                className="flex h-8 items-center gap-1.5 rounded-lg border border-line px-2.5 text-[12px] text-muted hover:border-ink/25 hover:text-ink disabled:opacity-50"
              >
                {testing === row.id ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
                测一下
              </button>
              {res ? (
                <span className={"text-[12px] " + (res.ok ? "text-emerald-600" : "text-amber-600")}>
                  {res.ok ? "通 · " + (res.ms ?? 0) + " ms" : "不通 · " + (res.error ?? "未知错误").slice(0, 80)}
                </span>
              ) : null}
            </div>
            {res?.ok && res.reply ? <p className="mt-1.5 truncate font-mono text-[11px] text-fade">返回：{res.reply}</p> : null}
          </div>
        );
      })}

      <button
        onClick={add}
        disabled={value.length >= MAX}
        className="flex h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-line text-[13px] text-muted hover:border-ink/25 hover:text-ink disabled:opacity-40"
      >
        <Plus size={14} />
        {value.length >= MAX ? "最多 " + MAX + " 个" : "添加模型"}
      </button>
    </div>
  );
}
