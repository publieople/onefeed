import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 异步动作的三态：idle / pending / ok / error。
 *
 * 之前每个按钮各自 setXxxLoading，于是有了这些毛病：
 * 插件开关不检查 resp.ok（失败也显示「已启用」）、市场页共用一个 busy 字符串
 * （同时装两个插件时 spinner 互相覆盖）、失败只有一句「失败」没有重试入口。
 */

export type ActionState = "idle" | "pending" | "ok" | "error";

export interface ActionResult<T> {
  state: ActionState;
  pending: boolean;
  error: string;
  value: T | null;
  run: () => Promise<boolean>;
  reset: () => void;
}

export function useAction<T>(fn: () => Promise<T>): ActionResult<T> {
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const alive = useRef(true);
  const [state, setState] = useState<ActionState>("idle");
  const [error, setError] = useState("");
  const [value, setValue] = useState<T | null>(null);

  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );

  const run = useCallback(async () => {
    if (!alive.current) return false;
    setState("pending");
    setError("");
    try {
      const out = await fnRef.current();
      if (!alive.current) return true;
      setValue(out);
      setState("ok");
      return true;
    } catch (err) {
      if (!alive.current) return false;
      setError(err instanceof Error ? err.message : String(err));
      setState("error");
      return false;
    }
  }, []);

  const reset = useCallback(() => {
    setState("idle");
    setError("");
    setValue(null);
  }, []);

  return { state, pending: state === "pending", error, value, run, reset };
}

export interface BatchResult {
  ok: boolean;
  error: string;
}

/**
 * 一堆同类动作（每个插件一个开关、每行一个「测一下」）的 pending 集合。
 * key 用 id，各管各的，不会互相覆盖。
 */
export function useBatchAction<K extends string | number>() {
  const [pending, setPending] = useState<ReadonlySet<K>>(() => new Set<K>());
  const alive = useRef(true);

  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );

  const has = useCallback((key: K) => pending.has(key), [pending]);

  const run = useCallback(async (key: K, fn: () => Promise<unknown>): Promise<BatchResult> => {
    setPending((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
    try {
      await fn();
      return { ok: true, error: "" };
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) };
    } finally {
      if (alive.current) {
        setPending((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
    }
  }, []);

  return { has, run, pending };
}
