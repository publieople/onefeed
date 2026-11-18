import type { SummaryPoint } from "./api";

/** 边生成边解析出来的半成品。行协议故意做得宽容：模型偶尔加空行、改成圆点，都照收。 */
export interface LiveSummary {
  tldr: string;
  points: SummaryPoint[];
  caveat: string;
}

const TLDR_LINE = /^\s*(?:tl;?dr|总览|一句话)\s*[:：]\s*(.+)$/i;
const CAVEAT_LINE = /^\s*(?:注|注意|caveat|备注)\s*[:：]\s*(.+)$/i;
const BULLET_LINE = /^\s*[-*·•]\s*(?:\[(\d{1,2}):(\d{2})\]\s*)?(.+?)\s*$/;

/**
 * 把已经收到的行按「一句话 / 要点 / 备注」拆开。
 * 最后一行没有换行符也照样算——不然打字机效果会卡在行尾，看着像卡住了。
 */
export function parseStreamText(raw: string): LiveSummary {
  let tldr = "";
  let caveat = "";
  const points: SummaryPoint[] = [];
  const stray: string[] = [];

  for (const rawLine of raw.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    const tldrHit = TLDR_LINE.exec(line);
    if (tldrHit && !tldr) {
      tldr = tldrHit[1].trim();
      continue;
    }
    const caveatHit = CAVEAT_LINE.exec(line);
    if (caveatHit) {
      caveat = (caveat + " " + caveatHit[1].trim()).trim();
      continue;
    }
    const bullet = BULLET_LINE.exec(line);
    if (bullet) {
      if (points.length >= 6) continue;
      const point: SummaryPoint = { text: bullet[3], t: null };
      if (bullet[1] !== undefined) point.t = Number(bullet[1]) * 60 + Number(bullet[2]);
      points.push(point);
      continue;
    }
    stray.push(line);
  }

  if (!tldr) {
    if (stray.length) tldr = stray[0].replace(/^[*_#]+/, "").trim();
    else if (points.length) tldr = points[0].text;
  }
  return { tldr, points, caveat };
}
