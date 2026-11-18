/**
 * 兼容层：常量已经搬到 motion/tokens.ts 统一管理。
 * 老代码还有一堆 `from "../motion"` 的引用，这里转出去，别让一次搬家变成全站改 import。
 */
export { EASE, EASE_CSS, DUR, D, SPRING, SPRING_SOFT, SPRING_SNAPPY, listItem, pageVariants } from "./motion/tokens";
