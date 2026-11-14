// 知乎热榜示例插件：纯 http 引擎，验证「manifest + module.exports + ctx.http」最小闭环
const HOT_URL = "https://www.zhihu.com/api/v3/feed/topstory/hot-list-web";

module.exports = {
  async pull(ctx, { feedId, limit }) {
    const r = await ctx.http.request({
      url: HOT_URL,
      query: { limit: String(limit || 20), desktop: "true" },
      headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" },
      timeoutMs: 15000,
    });
    if (r.status !== 200) throw new Error("zhihu hot http " + r.status);

    const list = (r.json().data || []).map((entry) => {
      const t = entry.target || {};
      const title = t.title_area && t.title_area.text ? t.title_area.text : "";
      const excerpt = t.excerpt_area && t.excerpt_area.text ? t.excerpt_area.text : "";
      const img = t.image_area && t.image_area.url ? t.image_area.url : "";
      const heat = t.metrics_area && t.metrics_area.text ? t.metrics_area.text : "";
      return {
        native_id: String(t.id || t.link && t.link.url || title).slice(0, 64),
        kind: "list",
        title: title,
        text: excerpt,
        cover: img,
        url: (t.link && t.link.url) || "https://www.zhihu.com/hot",
        stats: { view: ctx.util.clamp(heat.replace("热度", "")) },
        extra: { heat_text: heat },
      };
    });

    return { items: list, next: null };
  },
};
