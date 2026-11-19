/**
 * 转场里的「代位元素」：给共享元素补上它另一半缺失的那个盒子。
 *
 * 三处缺口都是同一类问题 —— 共享元素只在一侧存在，浏览器就没有两端可插值，
 * 转场退化成整页淡出：
 *   1. 从 Agent 抽屉里打开一条内容：信息流里没有那张卡，媒体框 / 标题没有起点；
 *   2. 从这条内容返回：回到信息流同样没有卡片接它（它是 Agent 自己找出来的）；
 *   3. 收起右栏 / 抽屉：唤起器要等收起之后才挂载，没有终点。
 *
 * 做法是临时往 body 里塞一个透明的 fixed 盒子，并给它挂上 viewTransitionName：
 *   - 先挂进 DOM 再开转场 → 它出现在「旧快照」里（返回时用）；
 *   - 在 apply 里挂 → 它只出现在「新快照」里（前进 / 收起时用）。
 * 转场结束后由 runNav 的 after 摘掉，不会留在 DOM 里。
 */

const CONTENT_MAX = 1180;
const GUTTER = 24;

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface Ghost {
  root: HTMLElement;
  media: HTMLElement | null;
  title: HTMLElement | null;
  mount: () => void;
  remove: () => void;
}

/** 内容栏的左右内沿：跟 App 里的 <main class="mx-auto max-w-[1180px] px-6"> 对齐 */
export function contentEdges(): { left: number; right: number; width: number } {
  const vw = document.documentElement.clientWidth;
  const outer = Math.min(CONTENT_MAX, vw);
  const left = (vw - outer) / 2;
  return { left: left + GUTTER, right: left + outer - GUTTER, width: outer - GUTTER * 2 };
}

function viewportHeight(): number {
  return document.documentElement.clientHeight;
}

function place(el: HTMLElement, name: string, box: Box): void {
  el.style.position = "fixed";
  el.style.left = box.left + "px";
  el.style.top = box.top + "px";
  el.style.width = box.width + "px";
  el.style.height = box.height + "px";
  el.style.viewTransitionName = name;
}

/** 图片 / 视频的起点与终点：贴内容栏右沿，落在唤起器上方 */
function mediaBox(): Box {
  const edges = contentEdges();
  const width = Math.min(320, Math.max(180, edges.width * 0.42));
  const height = Math.round((width * 9) / 16);
  return { left: edges.right - width, top: viewportHeight() - 96 - height, width, height };
}

/** 标题的起点与终点：媒体框正上方，一样贴右沿 */
function titleBox(): Box {
  const media = mediaBox();
  return { left: media.left, top: media.top - 10 - 44, width: media.width, height: 44 };
}

/** 唤起器的落点：信息流是底部胶囊，详情页是右下角的圆钮 */
export function launcherBox(kind: "pill" | "corner"): Box {
  const edges = contentEdges();
  const vh = viewportHeight();
  if (kind === "corner") {
    const width = 104;
    const height = 44;
    return { left: edges.right - width, top: vh - 20 - height, width, height };
  }
  const width = Math.min(760, edges.width);
  return { left: edges.left + (edges.width - width) / 2, top: vh - 16 - 48, width, height: 48 };
}

export function createGhost(opts: { media?: boolean; title?: boolean; agent?: "pill" | "corner" }): Ghost {
  const root = document.createElement("div");
  root.setAttribute("data-vt-ghost", "");
  root.style.position = "fixed";
  root.style.inset = "0";
  root.style.zIndex = "1";
  root.style.pointerEvents = "none";

  const media = opts.media ? document.createElement("div") : null;
  if (media) place(media, "of-media", mediaBox());
  const title = opts.title ? document.createElement("div") : null;
  if (title) place(title, "of-title", titleBox());
  const agent = opts.agent ? document.createElement("div") : null;
  if (agent && opts.agent) place(agent, "of-agent", launcherBox(opts.agent));

  for (const el of [media, title, agent]) {
    if (el) root.appendChild(el);
  }
  return {
    root,
    media,
    title,
    mount: () => {
      if (!root.isConnected) document.body.appendChild(root);
    },
    remove: () => root.remove(),
  };
}
