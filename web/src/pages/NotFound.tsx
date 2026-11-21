import { useEffect } from "react";
import { Link } from "react-router-dom";

/** 没有匹配路由时的落点：以前是一条空白页，只剩顶栏 */
export default function NotFound() {
  useEffect(() => {
    document.title = "没有这个页面 · OneFeed";
  }, []);
  return (
    <div className="flex min-h-[60vh] flex-col items-start justify-center gap-3">
      <div className="text-[12px] uppercase tracking-[0.16em] text-fade">404</div>
      <h1 className="font-display text-[24px] font-semibold tracking-tight">这个地址没有内容</h1>
      <p className="text-[13px] text-muted">可能是链接拼错了，或者条目已经被删掉。</p>
      <div className="mt-2 flex gap-2">
        <Link to="/" className="rounded-full bg-solid px-4 py-2 text-[13px] text-solid-fg">
          回到信息流
        </Link>
        <button
          onClick={() => window.history.back()}
          className="rounded-full border border-line px-4 py-2 text-[13px] text-muted transition hover:border-ink/25 hover:text-ink"
        >
          返回上一页
        </button>
      </div>
    </div>
  );
}
