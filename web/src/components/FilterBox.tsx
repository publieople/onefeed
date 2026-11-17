import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import type { ParsedQuery } from "../api";
import { platform } from "../platform";

interface Props {
  value: string;
  parsed: ParsedQuery | null;
  onSubmit: (text: string) => void;
}

export default function FilterBox({ value, parsed, onSubmit }: Props) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <div className="mt-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit(text);
        }}
        className="flex h-11 items-center gap-2 rounded-card border border-line bg-white px-3.5 transition focus-within:border-ink/25"
      >
        <Search size={15} className="text-fade" />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="用一句话筛，比如「只看今天 B 站的 AI」"
          className="h-full flex-1 bg-transparent text-[13px] outline-none placeholder:text-fade"
        />
        {text ? (
          <button type="button" onClick={() => { setText(""); onSubmit(""); }} className="text-[12px] text-fade hover:text-ink">
            清空
          </button>
        ) : null}
        <button type="submit" className="rounded-lg bg-ink px-3 py-1.5 text-[12px] text-white">
          筛选
        </button>
      </form>
      {/* 固定高度占位：解析结果出现时不把下面的内容整体推下去 */}
      <div className="mt-2 min-h-[22px]">
        {parsed && parsed.understood ? (
          <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
            <span className="text-fade">理解为</span>
            {parsed.platforms.map((id) => (
              <span key={id} className="rounded-full border border-line px-2 py-0.5">
                {platform(id).label}
              </span>
            ))}
            {parsed.kinds.map((k) => (
              <span key={k} className="rounded-full border border-line px-2 py-0.5">
                {k}
              </span>
            ))}
            {parsed.since ? <span className="rounded-full border border-line px-2 py-0.5">今天起</span> : null}
            {parsed.keyword ? <span className="rounded-full border border-line px-2 py-0.5">含「{parsed.keyword}」</span> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
