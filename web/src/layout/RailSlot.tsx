import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

/**
 * 详情页把「同题还出现在哪些平台」交给右栏槽位。
 * 右栏现在挂在 App 外壳上（要能在 1920 常驻、在 1440 变抽屉），
 * 而 siblings 只有 ItemPage 取得到，所以用一层很薄的上下文传过去。
 */

export interface RailSibling {
  id: string;
  platform: string;
  title: string;
}

interface RailSlotValue {
  siblings: RailSibling[];
  setSiblings: (next: RailSibling[]) => void;
}

const RailSlotCtx = createContext<RailSlotValue | null>(null);

export function RailSlotProvider({ children }: { children: ReactNode }) {
  const [siblings, setSiblings] = useState<RailSibling[]>([]);
  const value = useMemo(() => ({ siblings, setSiblings }), [siblings]);
  return <RailSlotCtx.Provider value={value}>{children}</RailSlotCtx.Provider>;
}

export function useRailSlot(): RailSlotValue {
  const value = useContext(RailSlotCtx);
  if (!value) throw new Error("useRailSlot 要在 RailSlotProvider 里用");
  return value;
}
