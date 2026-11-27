import { platformList } from "../platform";
import TabRail from "./ui/TabRail";

interface Props {
  selected: string[];
  counts: Record<string, number>;
  total: number;
  /** 后端已安装的平台；不传表示还没拿到数据，先按静态清单显示 */
  platforms?: string[];
  /** 空数组表示「全部」 */
  onChange: (ids: string[]) => void;
}

export default function Chips({ selected, counts, total, platforms, onChange }: Props) {
  return (
    <TabRail
      id="platform"
      label="按平台筛选（Ctrl 加减，Shift 选一段）"
      value={selected}
      onChange={onChange}
      items={[
        { id: "all", label: "全部", count: total },
        ...platformList(platforms).map((p) => ({
          id: p.id,
          label: p.label,
          count: counts[p.id] ?? 0,
          tint: p.tint,
        })),
      ]}
    />
  );
}
