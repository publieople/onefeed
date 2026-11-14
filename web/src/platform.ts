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
  { id: "zhihu-hot", label: "知乎", tint: "#0084FF" },
];

const FALLBACK: PlatformMeta = { id: "unknown", label: "未知道", tint: "#6b7280" };

export function platform(id: string): PlatformMeta {
  return PLATFORMS.find((p) => p.id === id) ?? { ...FALLBACK, id, label: id };
}

export const KIND_LABEL: Record<string, string> = {
  video: "视频",
  images: "图文",
  article: "文章",
  short: "动态",
  list: "榜单",
};
