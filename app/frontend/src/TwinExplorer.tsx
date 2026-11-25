import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import type { Mesh } from "./instrumentTypes";
import { stage } from "./modelViews";
import { cued, cues } from "./stepCues";
import { blend, rig, type Motion, type Pose, type Rig } from "./twinMotion";
import s from "./TwinExplorer.module.css";

const EASE_MS = 700;
const same = (a: Pose, b: Pose) =>
  [...new Set([...Object.keys(a), ...Object.keys(b)])].every(
    (k) => Math.abs((a[k] ?? 0) - (b[k] ?? 0)) < 1e-6,
  );

/** The state on show, the pose it sets and the part in focus, shared by every view of a twin. */
export function useTwin(motion: Motion | null) {
  const first = motion?.states[0];
  const [state, setState] = useState<string | null>(first?.id ?? null);
  const [pose, setPose] = useState<Pose>(first?.pose ?? {});
  const [part, setPart] = useState<string | null>(null);
  const press = useCallback(
    (id: string) => {
      const found = motion?.states.find((x) => x.id === id);
      if (!found) return;
      setState(id);
      setPose(found.pose);
      setPart(null);
    },
    [motion],
  );
  /** A part that moves opens or closes; any part comes into focus. */
  const pick = useCallback(
    (id: string) => {
      const found = motion?.parts.find((p) => p.id === id);
      if (!found) return;
      setPart(id);
      if (!found.moves) return;
      const next = { ...pose, [id]: (pose[id] ?? 0) > 0.5 ? 0 : 1 };
      setPose(next);
      // Opening a part may land on one of the named states.
      setState(motion!.states.find((x) => same(x.pose, next))?.id ?? null);
    },
    [motion, pose],
  );
  return { motion, state, pose, part, press, pick };
}
export type Twin = ReturnType<typeof useTwin>;

/**
 * A stand-in model a learner can turn, and, where its contract has joints, press a
 * state or click a labelled part to see it move. Without joints it is a plain view.
 */
export default function TwinExplorer({
  mesh,
  twin,
  tall = false,
  step = null,
  access = "top",
}: {
  mesh: Mesh;
  twin: Twin;
  tall?: boolean;
  /** The step of a run on show: its action and its place in the run. */
  step?: { operation: string; at: number } | null;
  access?: "top" | "front";
}) {
  const { motion, state, pose, part, press, pick } = twin;
  const host = useRef<HTMLDivElement>(null);
  const labels = useRef(new Map<string, HTMLButtonElement>());
  const [view, setView] = useState<"loading" | "ready" | "failed">("loading");
  // Read by the render loop, which outlives renders.
  const target = useRef(pose);
  const focus = useRef({ hovered: null as string | null, selected: part });
  const pickRef = useRef(pick);
  pickRef.current = pick;
  focus.current.selected = part;
  const stepRef = useRef(step);
  stepRef.current = step;
  useEffect(() => {
    target.current = pose;
  }, [pose]);
  const key = mesh.url ?? mesh.kind;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let moved: Rig | null = null;
    let drawn: ReturnType<typeof cues> | null = null;
    let cueAt: number | null = null;
    let shown: Pose = target.current;
    let from: Pose = shown;
    let goal: Pose = shown;
    let since = 0;
    let frames = 0;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)");
    const ray = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let camera: THREE.PerspectiveCamera | null = null;
    let model: THREE.Object3D | null = null;
    const hit = (event: PointerEvent) => {
      if (!moved || !camera || !model) return null;
      const box = el.getBoundingClientRect();
      pointer.set(
        ((event.clientX - box.left) / box.width) * 2 - 1,
        -((event.clientY - box.top) / box.height) * 2 + 1,
      );
      ray.setFromCamera(pointer, camera);
      return moved.partOf(ray.intersectObject(model, true)[0]?.object ?? null);
    };
    let down: { x: number; y: number } | null = null;
    const onMove = (event: PointerEvent) => {
      const found = hit(event);
      focus.current.hovered = found;
      el.style.cursor = found ? "pointer" : "";
    };
    const onDown = (event: PointerEvent) => {
      down = { x: event.clientX, y: event.clientY };
    };
    // A click, not the end of a turn of the model, picks the part under the pointer.
    const onUp = (event: PointerEvent) => {
      if (
        down &&
        Math.hypot(event.clientX - down.x, event.clientY - down.y) < 5
      ) {
        const found = hit(event);
        if (found) pickRef.current(found);
      }
      down = null;
    };
    const onLeave = () => {
      focus.current.hovered = null;
    };
    const teardown = stage(el, mesh, {
      state: setView,
      ready: (st) => {
        camera = st.camera;
        model = st.model;
        drawn = cues(st.scene, st.holder, access);
        if (!motion) return;
        moved = rig(st.model, motion);
        moved.set(shown);
        el.addEventListener("pointermove", onMove);
        el.addEventListener("pointerdown", onDown);
        el.addEventListener("pointerup", onUp);
        el.addEventListener("pointerleave", onLeave);
      },
      frame: (st) => {
        // A new step of the run starts its cue; the same step plays on.
        const at = stepRef.current?.at ?? null;
        if (at !== cueAt) {
          cueAt = at;
          drawn?.play(stepRef.current?.operation ?? null);
        }
        drawn?.frame(still.matches);
        if (!moved) return;
        const now = performance.now();
        if (!same(goal, target.current)) {
          from = shown;
          goal = target.current;
          since = now;
        }
        if (!same(shown, goal)) {
          const t = still.matches ? 1 : Math.min(1, (now - since) / EASE_MS);
          shown = t >= 1 ? goal : blend(from, goal, t);
          moved.set(shown);
        }
        moved.light(focus.current.hovered, focus.current.selected);
        // Labels follow their parts; one covered by another part steps aside.
        const box = el.getBoundingClientRect();
        const check = frames++ % 12 === 0;
        const placed: { x: number; y: number; w: number; h: number }[] = [];
        for (const [id, label] of labels.current) {
          const at = moved.anchor(id);
          if (!at) continue;
          const seen = at.clone().project(st.camera);
          const x = ((seen.x + 1) / 2) * box.width;
          let y = ((1 - seen.y) / 2) * box.height;
          const w = label.offsetWidth + 6;
          const h = label.offsetHeight + 4;
          // Labels of parts close together stack instead of covering each other.
          if (label.dataset.behind !== "true")
            for (const other of placed)
              if (Math.abs(other.x - x) < (other.w + w) / 2)
                if (Math.abs(other.y - y) < (other.h + h) / 2)
                  y = other.y + (other.h + h) / 2;
          if (label.dataset.behind !== "true") placed.push({ x, y, w, h });
          label.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
          label.hidden = seen.z > 1;
          if (check) {
            const eye = st.camera.position;
            const toward = at.clone().sub(eye);
            ray.set(eye, toward.clone().normalize());
            const first = ray.intersectObject(st.model, true)[0];
            // Only another named part, such as a closed door, hides a label.
            const cover = first ? moved.partOf(first.object) : null;
            const behind =
              !!first &&
              first.distance < toward.length() - 0.02 &&
              cover !== null &&
              cover !== id;
            label.dataset.behind = behind ? "true" : "";
          }
        }
      },
    });
    return () => {
      teardown();
      drawn?.dispose();
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointerleave", onLeave);
    };
    // `key` identifies the model; the mesh and motion come with it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const current = motion?.states.find((x) => x.id === state);
  const inFocus = motion?.parts.find((p) => p.id === part);
  const caption = inFocus
    ? `${inFocus.label}: ${inFocus.about}`
    : (current?.says ?? "");
  return (
    <div className={s.explorer} data-tall={tall || undefined}>
      <div
        className={s.stage}
        data-state={view}
        data-cue={(step && cued(step.operation) && step.operation) || undefined}
      >
        <div ref={host} className={s.canvas} />
        {motion && view === "ready" && (
          <div className={s.labels}>
            {motion.parts.map((p) => (
              <button
                key={p.id}
                ref={(b) => {
                  if (b) labels.current.set(p.id, b);
                  else labels.current.delete(p.id);
                }}
                className={s.label}
                aria-pressed={part === p.id}
                onClick={() => pick(p.id)}
              >
                {p.label}
              </button>
            ))}
          </div>
        )}
        {view === "loading" && <span className={s.status}>Loading model…</span>}
        {view === "failed" && (
          <span className={s.status} role="status">
            The 3D model could not be loaded.
          </span>
        )}
      </div>
      {motion && (
        <div className={s.controls}>
          <div className={s.states} role="group" aria-label="State">
            {motion.states.map((x) => (
              <button
                key={x.id}
                aria-pressed={state === x.id}
                onClick={() => press(x.id)}
              >
                {x.label}
              </button>
            ))}
          </div>
          <p className={s.caption} aria-live="polite">
            {caption}
          </p>
        </div>
      )}
    </div>
  );
}
