export interface PlatformMeta {
  id: string;
  label: string;
  tint: string;
}

export const PLATFORMS: PlatformMeta[] = [
  { id: "bilibili", label: "B 站", tint: "#00A1D6" },
  { id: "xiaohongshu", label: "小红书", tint: "#FF2442" },
  { id: "douyin", label: "抖音", tint: "#FE2C55" },
  { id: "juejin", label: "掘金", tint: "#1E80FF" },
  { id: "v2ex", label: "V2EX", tint: "#778087" },
  { id: "zhihu", label: "知乎", tint: "#0084FF" },
  { id: "zhihu-hot", label: "知乎热榜", tint: "#0084FF" },
];

const FALLBACK: PlatformMeta = { id: "unknown", label: "未知道", tint: "#6b7280" };

export function platform(id: string): PlatformMeta {
  return PLATFORMS.find((p) => p.id === id) ?? { ...FALLBACK, id, label: id };
}

/**
 * 实际可用的平台列表：传 undefined 表示还没拿到后端数据，保留静态清单；
 * 传数组就只保留其中的平台，后端新装/卸载插件后前端不用再改代码。
 */
export function platformList(ids?: string[]): PlatformMeta[] {
  if (!ids) return PLATFORMS;
  const known = PLATFORMS.filter((p) => ids.includes(p.id));
  const extras = ids.filter((id) => !PLATFORMS.some((p) => p.id === id)).map((id) => platform(id));
  return [...known, ...extras];
}

export const KIND_LABEL: Record<string, string> = {
  video: "视频",
  images: "图文",
  article: "文章",
  short: "动态",
  list: "榜单",
};
