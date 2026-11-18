import { PLATFORMS } from "../platform";
import TabRail from "./ui/TabRail";

interface Props {
  selected: string[];
  counts: Record<string, number>;
  total: number;
  /** 空数组表示「全部」 */
  onChange: (ids: string[]) => void;
}

export default function Chips({ selected, counts, total, onChange }: Props) {
  return (
    <TabRail
      id="platform"
      label="按平台筛选（Ctrl 加减，Shift 选一段）"
      value={selected}
      onChange={onChange}
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
