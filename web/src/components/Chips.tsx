import { PLATFORMS } from "../platform";
import TabRail from "./ui/TabRail";

interface Props {
  selected: string[];
  counts: Record<string, number>;
  total: number;
  /** 传 null 表示「全部」 */
  onChange: (id: string | null) => void;
}

export default function Chips({ selected, counts, total, onChange }: Props) {
  const value = selected.length === 1 ? selected[0] : "all";
  return (
    <TabRail
      id="platform"
      label="按平台筛选"
      value={value}
      onChange={(next) => onChange(next === "all" ? null : next)}
      items={[
        { id: "all", label: "全部", count: total },
        ...PLATFORMS.map((p) => ({
          id: p.id,
          label: p.label,
          count: counts[p.id] ?? 0,
          tint: p.tint,
        })),
      ]}
    />
  );
}
