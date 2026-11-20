import { useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

/**
 * Pointer drag onto any element carrying `data-drop`. Works with mouse, pen
 * and touch; a press that does not move stays an ordinary click, so every
 * draggable item can also be picked up by clicking it and placed by clicking
 * a target.
 */
export function useDrag(onDrop: (item: string, target: string) => void) {
  const [ghost, setGhost] = useState<{
    label: string;
    x: number;
    y: number;
  } | null>(null);
  const dragged = useRef(false);
  const drop = useRef(onDrop);
  drop.current = onDrop;
  const start = (item: string, label: string) => (event: ReactPointerEvent) => {
    if (event.button !== 0) return;
    const x0 = event.clientX;
    const y0 = event.clientY;
    let moving = false;
    const move = (e: PointerEvent) => {
      if (!moving && Math.hypot(e.clientX - x0, e.clientY - y0) < 6) return;
      moving = true;
      setGhost({ label, x: e.clientX, y: e.clientY });
    };
    const end = (e: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      setGhost(null);
      if (!moving || e.type === "pointercancel") return;
      // Swallow only the click this drag itself produces.
      dragged.current = true;
      window.setTimeout(() => (dragged.current = false), 0);
      const target = document
        .elementFromPoint(e.clientX, e.clientY)
        ?.closest("[data-drop]")
        ?.getAttribute("data-drop");
      if (target) drop.current(item, target);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  };
  /** Wraps a click handler so the click that ends a drag is ignored. */
  const click = (handler: () => void) => () => {
    if (!dragged.current) handler();
  };
  return { ghost, start, click };
}

/** Per-viewer convenience storage; the page works the same without it. */
export function stored<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
  } catch {
    return fallback;
  }
}
export function store(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Progress then lasts until the page reloads.
  }
}
export const reducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Saved twin progress: a state object plus a list of finished challenges. */
export function useProgress<T extends { done: string[] }>(
  key: string,
  empty: T,
) {
  const [saved, setSaved] = useState(() => stored(key, empty));
  const change = (patch: (old: T) => Partial<T>) =>
    setSaved((old) => {
      const merged = { ...old, ...patch(old) };
      store(key, merged);
      return merged;
    });
  const update = (next: Partial<T>) => change(() => next);
  const finish = (task: string) =>
    change((old) =>
      old.done.includes(task)
        ? {}
        : ({ done: [...old.done, task] } as Partial<T>),
    );
  return { saved, update, change, finish };
}
