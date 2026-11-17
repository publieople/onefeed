import { PLATFORMS, platform } from "../platform";

interface Props {
  selected: string[];
  counts: Record<string, number>;
  total: number;
  onToggle: (id: string) => void;
  onClear: () => void;
}

export default function Chips({ selected, counts, total, onToggle, onClear }: Props) {
  const all = selected.length === 0;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        onClick={onClear}
        className={
          "flex h-8 items-center gap-1.5 rounded-full border px-3.5 text-[13px] transition " +
          (all ? "border-ink bg-solid text-solid-fg" : "border-line bg-paper text-ink hover:border-ink/30")
        }
      >
        全部
        <span className={all ? "text-solid-fg/60" : "text-fade"}>{total}</span>
      </button>
      {PLATFORMS.map((p) => {
        const on = selected.includes(p.id);
        return (
          <button
            key={p.id}
            onClick={() => onToggle(p.id)}
            className={
              "flex h-8 items-center gap-2 rounded-full border px-3 text-[13px] transition " +
              (on ? "border-ink/25 bg-wash text-ink" : "border-line bg-paper text-muted hover:border-ink/20")
            }
          >
            <span className="h-[7px] w-[7px] rounded-full" style={{ background: p.tint }} />
            {p.label}
            <span className="text-[11px] text-fade">{counts[p.id] ?? 0}</span>
          </button>
        );
      })}
      {selected.length ? (
        <span className="text-[12px] text-fade">
          已选 {selected.map((id) => platform(id).label).join(" + ")}
        </span>
      ) : null}
    </div>
  );
}
