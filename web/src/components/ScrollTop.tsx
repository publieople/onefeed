import { ArrowUp } from "lucide-react";
import { useEffect, useState } from "react";

/** 滚过一屏多之后才浮出来的回顶按钮：贴内容栏右沿，落在底部唤起器上方。 */
const SHOW_AFTER = 1.2;

export default function ScrollTop() {
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const read = () => setShown(window.scrollY > window.innerHeight * SHOW_AFTER);
    read();
    window.addEventListener("scroll", read, { passive: true });
    window.addEventListener("resize", read);
    return () => {
      window.removeEventListener("scroll", read);
      window.removeEventListener("resize", read);
    };
  }, []);

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-24 z-30 px-6">
      <div className="mx-auto flex max-w-[1180px] justify-end">
        <button
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          aria-label="回到顶部"
          title="回到顶部"
          tabIndex={shown ? 0 : -1}
          className={
            "flex h-9 w-9 items-center justify-center rounded-full border border-line/70 bg-paper/90 text-muted shadow-[0_4px_14px_rgba(20,20,20,0.08)] transition duration-200 hover:-translate-y-0.5 hover:border-ink/25 hover:text-ink " +
            (shown ? "pointer-events-auto opacity-100" : "pointer-events-none translate-y-2 opacity-0")
          }
        >
          <ArrowUp size={16} />
        </button>
      </div>
    </div>
  );
}
