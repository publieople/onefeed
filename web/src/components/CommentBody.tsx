import { Heart } from "lucide-react";
import { type CommentItem } from "../api";
import { num, timeAgo } from "../format";

/** 一条评论（含前三条楼中楼）。详情页与列表抽屉共用，所以单独放一个文件。 */
export function CommentBody({ comment }: { comment: CommentItem }) {
  const p = "#6b7280";
  return (
    <div className="flex gap-2.5">
      <span
        className="mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full text-[11px] font-medium text-white"
        style={{ background: p }}
      >
        {(comment.author || "?").slice(0, 1)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[12px]">
          <span className="truncate font-medium">{comment.author || "匿名"}</span>
          {comment.created_at ? <span className="text-[11px] text-fade">{timeAgo(comment.created_at)}</span> : null}
          {comment.like_count ? (
            <span className="ml-auto flex items-center gap-1 text-[11px] text-fade">
              <Heart size={10} />
              {num(comment.like_count)}
            </span>
          ) : null}
        </div>
        <p className="mt-1 whitespace-pre-wrap text-[13px] leading-[1.75] text-muted">{comment.text}</p>
        {comment.replies?.length ? (
          <div className="mt-2 space-y-2 border-l border-line pl-3">
            {comment.replies.slice(0, 3).map((r) => (
              <div key={r.id}>
                <div className="text-[12px] font-medium">
                  {r.author || "匿名"}
                  {r.created_at ? <span className="ml-2 font-normal text-fade">{timeAgo(r.created_at)}</span> : null}
                </div>
                <p className="mt-0.5 whitespace-pre-wrap text-[12px] leading-[1.7] text-muted">{r.text}</p>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
