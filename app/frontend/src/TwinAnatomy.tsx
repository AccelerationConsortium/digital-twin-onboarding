import { Weight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import type { Mesh } from "./instrumentTypes";
import { stage } from "./modelViews";
import s from "./TwinAnatomy.module.css";

export type Anatomy = {
  node_prefix: string;
  parts: {
    n: number;
    label: string;
    about: string;
    components: string[];
    toward: [number, number, number] | null;
  }[];
};

export type Mass = { value: number; range: [number, number] | null };
type Mark = "width" | "depth" | "height" | "weight";

const OPEN_MS = 1400;
// How far a part moves out, as a share of the model's largest side.
const REACH = 0.36;

/**
 * An instrument drawn as an exploded line drawing: its housing fades, the numbered parts
 * inside move out of it, and each number matches a row in the key beside it. Its outside
 * size is dimensioned on the bench, and where its weight is known it stands on a scale.
 */
export default function TwinAnatomy({
  mesh,
  anatomy,
  size,
  mass,
}: {
  mesh: Mesh;
  anatomy: Anatomy;
  /** Width, depth and height in metres. */
  size: [number, number, number];
  mass: Mass | null;
}) {
  const host = useRef<HTMLDivElement>(null);
  const tags = useRef(new Map<number, HTMLButtonElement>());
  const marks = useRef(new Map<Mark, HTMLSpanElement>());
  const leaders = useRef(new Map<number, SVGLineElement>());
  const [view, setView] = useState<"loading" | "ready" | "failed">("loading");
  const [apart, setApart] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  // Read by the render loop, which outlives renders.
  const live = useRef({ apart, picked, hovered: null as number | null });
  live.current.apart = apart;
  live.current.picked = picked;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)");
    const made: { dispose(): void }[] = [];
    let drawing: ReturnType<typeof draw> | null = null;
    let camera: THREE.Camera | null = null;
    let opened = 0;
    const ray = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const hit = (event: PointerEvent) => {
      if (!drawing || !camera) return null;
      const box = el.getBoundingClientRect();
      pointer.set(
        ((event.clientX - box.left) / box.width) * 2 - 1,
        -((event.clientY - box.top) / box.height) * 2 + 1,
      );
      ray.setFromCamera(pointer, camera);
      const first = ray
        .intersectObject(drawing.root, true)
        .find((x) => (x.object as THREE.Mesh).isMesh);
      return first ? drawing.partOf(first.object) : null;
    };
    let down: { x: number; y: number } | null = null;
    const onMove = (e: PointerEvent) => {
      live.current.hovered = hit(e);
      el.style.cursor = live.current.hovered ? "pointer" : "";
    };
    const onDown = (e: PointerEvent) => {
      down = { x: e.clientX, y: e.clientY };
    };
    const onUp = (e: PointerEvent) => {
      if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5) {
        const found = hit(e);
        setPicked((was) => (found === was ? null : found));
      }
      down = null;
    };
    const onLeave = () => {
      live.current.hovered = null;
    };
    const teardown = stage(el, mesh, {
      state: setView,
      ready: (st) => {
        camera = st.camera;
        // The drawing grid behind it stands in for the floor.
        st.scene.traverse((o) => {
          if (o instanceof THREE.GridHelper) o.visible = false;
        });
        drawing = draw(st.model, anatomy, made, mass !== null);
        // Framed again now that the unseen box round the parts taken apart is there.
        st.fit();
        el.addEventListener("pointermove", onMove);
        el.addEventListener("pointerdown", onDown);
        el.addEventListener("pointerup", onUp);
        el.addEventListener("pointerleave", onLeave);
        // It opens once by itself, so the first thing seen is the inside.
        opened = performance.now();
        if (still.matches) setApart(1);
      },
      frame: (st) => {
        if (!drawing) return;
        if (opened && !still.matches) {
          const t = Math.min(1, (performance.now() - opened) / OPEN_MS);
          const eased = 1 - (1 - t) ** 3;
          if (t >= 1) opened = 0;
          setApart(eased);
        }
        const { apart: f, picked: chosen, hovered } = live.current;
        drawing.set(f, chosen, hovered, getComputedStyle(el));
        // Each number sits a little out from its part, away from the model's middle.
        const box = el.getBoundingClientRect();
        const middle = drawing.middle().project(st.camera);
        const mx = ((middle.x + 1) / 2) * box.width;
        const my = ((1 - middle.y) / 2) * box.height;
        // The measurements go first; the numbers keep clear of them.
        const measured: { x: number; y: number; half: number }[] = [];
        for (const [name, at] of Object.entries(drawing.marks)) {
          const label = marks.current.get(name as Mark);
          if (!label) continue;
          const seen = drawing.root.localToWorld(at.clone()).project(st.camera);
          let x = ((seen.x + 1) / 2) * box.width;
          const y = ((1 - seen.y) / 2) * box.height;
          const half = label.offsetWidth / 2;
          // The scale's display stands out to the right of its front corner.
          if (name === "weight") x += 10 + half;
          x = Math.min(box.width - half - 4, Math.max(half + 4, x));
          measured.push({ x, y, half });
          label.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
        }
        const placed: { x: number; y: number }[] = [];
        for (const part of anatomy.parts) {
          const tag = tags.current.get(part.n);
          const line = leaders.current.get(part.n);
          const at = drawing.anchor(part.n);
          if (!tag || !line) continue;
          // A part the model does not draw has nothing to point at.
          tag.hidden = !at;
          line.style.display = at ? "" : "none";
          if (!at) continue;
          const seen = at.project(st.camera);
          const ax = ((seen.x + 1) / 2) * box.width;
          const ay = ((1 - seen.y) / 2) * box.height;
          const away = Math.hypot(ax - mx, ay - my) || 1;
          let x = ax + ((ax - mx) / away) * 34;
          let y = ay + ((ay - my) / away) * 34;
          for (const other of placed)
            if (Math.hypot(other.x - x, other.y - y) < 26) y = other.y + 26;
          for (const other of measured)
            if (
              Math.abs(other.x - x) < other.half + 13 &&
              Math.abs(other.y - y) < 22
            )
              y = other.y + 24;
          x = Math.min(box.width - 14, Math.max(14, x));
          y = Math.min(box.height - 14, Math.max(14, y));
          placed.push({ x, y });
          tag.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
          line.setAttribute("x1", `${ax}`);
          line.setAttribute("y1", `${ay}`);
          line.setAttribute("x2", `${x}`);
          line.setAttribute("y2", `${y}`);
        }
      },
    });
    return () => {
      teardown();
      for (const thing of made) thing.dispose();
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointerleave", onLeave);
    };
    // `key` identifies the model; the anatomy comes with it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mesh.url ?? mesh.kind]);

  const chosen = anatomy.parts.find((p) => p.n === picked);
  const mark = (name: Mark) => (label: HTMLSpanElement | null) => {
    if (label) marks.current.set(name, label);
    else marks.current.delete(name);
  };
  const [width, depth, height] = size.map((v) => `${v.toFixed(2)} m`);
  return (
    <div className={s.anatomy}>
      <div className={s.drawing} data-state={view}>
        <div ref={host} className={s.canvas} />
        {view === "ready" && (
          <>
            <svg className={s.leaders} aria-hidden="true">
              {anatomy.parts.map((p) => (
                <line
                  key={p.n}
                  ref={(line) => {
                    if (line) leaders.current.set(p.n, line);
                    else leaders.current.delete(p.n);
                  }}
                  data-picked={picked === p.n || undefined}
                />
              ))}
            </svg>
            <div className={s.marks}>
              <span ref={mark("width")} className={s.measure}>
                <span className={s.srOnly}>Width </span>
                {width}
              </span>
              <span ref={mark("depth")} className={s.measure}>
                <span className={s.srOnly}>Depth </span>
                {depth}
              </span>
              <span ref={mark("height")} className={s.measure}>
                <span className={s.srOnly}>Height </span>
                {height}
              </span>
              {mass && (
                <span ref={mark("weight")} className={s.readout}>
                  <Weight size={12} aria-hidden="true" />
                  <span className={s.srOnly}>Weight </span>
                  {mass.range
                    ? `${mass.range[0]}–${mass.range[1]}`
                    : mass.value}{" "}
                  kg
                </span>
              )}
            </div>
            <div className={s.tags}>
              {anatomy.parts.map((p) => (
                <button
                  key={p.n}
                  ref={(b) => {
                    if (b) tags.current.set(p.n, b);
                    else tags.current.delete(p.n);
                  }}
                  className={s.tag}
                  aria-label={p.label}
                  aria-pressed={picked === p.n}
                  onClick={() => setPicked(picked === p.n ? null : p.n)}
                >
                  {p.n}
                </button>
              ))}
            </div>
          </>
        )}
        {view === "loading" && <span className={s.status}>Loading model…</span>}
        {view === "failed" && (
          <span className={s.status} role="status">
            The 3D model could not be loaded.
          </span>
        )}
        <label className={s.apart}>
          <span>Assembled</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={apart}
            aria-label="Take apart"
            onChange={(e) => setApart(Number(e.target.value))}
          />
          <span>Apart</span>
        </label>
      </div>
      <div className={s.key}>
        <h3>Key to parts</h3>
        <ol>
          {anatomy.parts.map((p) => (
            <li key={p.n}>
              <button
                aria-pressed={picked === p.n}
                onClick={() => setPicked(picked === p.n ? null : p.n)}
              >
                <b>{p.n}</b>
                <span>{p.label}</span>
              </button>
            </li>
          ))}
        </ol>
        <p className={s.caption} aria-live="polite">
          {chosen ? (
            <>
              <strong>{chosen.label}.</strong> {chosen.about}
            </>
          ) : (
            "Pick a number to see what that part does."
          )}
        </p>
      </div>
    </div>
  );
}

/**
 * Turns a loaded model into a line drawing whose parts can be moved out of it. The parts'
 * components keep the contract's names, in the model's frame (Z up), so a part moves in
 * that frame and its children follow.
 */
function draw(
  root: THREE.Object3D,
  anatomy: Anatomy,
  made: { dispose(): void }[],
  weighed: boolean,
) {
  root.updateMatrixWorld(true);
  const toRoot = root.matrixWorld.clone().invert();
  const inRoot = (o: THREE.Object3D) => toRoot.clone().multiply(o.matrixWorld);
  const owner = new Map<THREE.Object3D, number>();
  const wanted = new Map<string, number>();
  for (const part of anatomy.parts)
    for (const c of part.components)
      wanted.set(anatomy.node_prefix + c, part.n);
  root.traverse((o) => {
    const n = wanted.get(o.name);
    if (n !== undefined) owner.set(o, n);
  });
  const partOf = (o: THREE.Object3D | null) => {
    for (let x = o; x && x !== root; x = x.parent)
      if (owner.has(x)) return owner.get(x)!;
    return null;
  };

  // Where everything is as modelled, in the model's frame.
  const whole = new THREE.Box3();
  const boxes = new Map<number, THREE.Box3>();
  const corner = new THREE.Vector3();
  root.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    mesh.geometry.computeBoundingBox();
    const box = mesh.geometry.boundingBox!.clone().applyMatrix4(inRoot(mesh));
    whole.union(box);
    const n = partOf(mesh);
    if (n === null) return;
    if (!boxes.has(n)) boxes.set(n, new THREE.Box3());
    boxes.get(n)!.union(box);
  });
  const middle = whole.getCenter(new THREE.Vector3());
  const side = Math.max(...whole.getSize(corner).toArray());
  // A part moves along its `toward`, or away from the middle and a little up. Parts sent
  // the same way go different distances, so they do not land on each other.
  const shared = new Map<string, number>();
  const offsets = new Map<number, THREE.Vector3>();
  const centres = new Map<number, THREE.Vector3>();
  for (const part of anatomy.parts) {
    const box = boxes.get(part.n);
    if (!box) continue;
    const centre = box.getCenter(new THREE.Vector3());
    centres.set(part.n, centre);
    let way: THREE.Vector3;
    if (part.toward) way = new THREE.Vector3(...part.toward);
    else {
      way = centre.clone().sub(middle);
      way.z = Math.max(way.z, 0) + side * 0.3;
    }
    way.normalize();
    const key = part.toward ? part.toward.join() : `auto${part.n}`;
    const rank = shared.get(key) ?? 0;
    shared.set(key, rank + 1);
    offsets.set(part.n, way.multiplyScalar(side * REACH * (1 + rank * 0.4)));
  }

  // An unseen box round the model taken apart, so the camera frames the parts at their
  // furthest as well as the model whole.
  const reach = whole.clone();
  for (const [n, box] of boxes)
    if (offsets.has(n)) reach.union(box.clone().translate(offsets.get(n)!));
  const extent = new THREE.BoxGeometry(...reach.getSize(corner).toArray());
  const frame = new THREE.Mesh(extent);
  frame.position.copy(reach.getCenter(corner));
  frame.visible = false;
  frame.raycast = () => {};
  root.add(frame);
  made.push(extent);

  // A part's top node is set from its rest frame, relative to where its parent has moved.
  const movers: {
    node: THREE.Object3D;
    rest: THREE.Matrix4;
    parentRest: THREE.Matrix4;
    n: number;
    under: number | null;
  }[] = [];
  for (const [node, n] of owner) {
    const under = partOf(node.parent);
    if (under === n || !node.parent) continue;
    movers.push({
      node,
      rest: inRoot(node),
      parentRest: inRoot(node.parent).invert(),
      n,
      under,
    });
  }

  // Every surface becomes paper with ink edges; the housing's fade as the parts come out.
  const fills = new Map<number | null, THREE.MeshStandardMaterial>();
  const inks = new Map<number | null, THREE.LineBasicMaterial>();
  const fill = (n: number | null) => {
    if (!fills.has(n)) {
      const m = new THREE.MeshStandardMaterial({
        roughness: 1,
        metalness: 0,
        transparent: n === null,
        polygonOffset: true,
        polygonOffsetFactor: 1,
        polygonOffsetUnits: 1,
      });
      fills.set(n, m);
      made.push(m);
    }
    return fills.get(n)!;
  };
  const ink = (n: number | null) => {
    if (!inks.has(n)) {
      const m = new THREE.LineBasicMaterial({ transparent: true });
      inks.set(n, m);
      made.push(m);
    }
    return inks.get(n)!;
  };
  const meshes: THREE.Mesh[] = [];
  root.traverse((o) => {
    if ((o as THREE.Mesh).isMesh && o !== frame) meshes.push(o as THREE.Mesh);
  });
  for (const mesh of meshes) {
    const n = partOf(mesh);
    for (const m of [mesh.material].flat()) m.dispose();
    mesh.material = fill(n);
    const edges = new THREE.EdgesGeometry(mesh.geometry, 28);
    made.push(edges);
    const lines = new THREE.LineSegments(edges, ink(n));
    lines.raycast = () => {};
    mesh.add(lines);
  }

  // Dimension lines on the bench: extension lines out from the model's bottom edges (and
  // its top front corner for the height), the measured line, and a slash at either end.
  const [x0, y0, z0] = whole.min.toArray();
  const [x1, y1, z1] = whole.max.toArray();
  const margin = side * 0.05;
  const gap = side * 0.09;
  const tick = side * 0.016;
  const yw = y0 - margin - gap;
  const xd = x1 + margin + gap;
  const xh = x0 - margin - gap;
  const ends: number[] = [];
  const line = (a: number[], b: number[]) => ends.push(...a, ...b);
  const slash = (p: number[], d: number[]) =>
    line(
      p.map((v, i) => v - d[i] * tick),
      p.map((v, i) => v + d[i] * tick),
    );
  line([x0, y0, z0], [x0, yw - tick, z0]);
  line([x1, y0, z0], [x1, yw - tick, z0]);
  line([x0, yw, z0], [x1, yw, z0]);
  slash([x0, yw, z0], [1, 1, 0]);
  slash([x1, yw, z0], [1, 1, 0]);
  line([x1, y0, z0], [xd + tick, y0, z0]);
  line([x1, y1, z0], [xd + tick, y1, z0]);
  line([xd, y0, z0], [xd, y1, z0]);
  slash([xd, y0, z0], [1, 1, 0]);
  slash([xd, y1, z0], [1, 1, 0]);
  line([x0, y0, z0], [xh - tick, y0, z0]);
  line([x0, y0, z1], [xh - tick, y0, z1]);
  line([xh, y0, z0], [xh, y0, z1]);
  slash([xh, y0, z0], [1, 0, 1]);
  slash([xh, y0, z1], [1, 0, 1]);
  const dims = new THREE.BufferGeometry();
  dims.setAttribute("position", new THREE.Float32BufferAttribute(ends, 3));
  const rule = new THREE.LineBasicMaterial({
    transparent: true,
    opacity: 0.75,
  });
  const rules = new THREE.LineSegments(dims, rule);
  rules.raycast = () => {};
  root.add(rules);
  made.push(dims, rule);
  const cx = (x0 + x1) / 2;
  const marks: Partial<Record<Mark, THREE.Vector3>> = {
    width: new THREE.Vector3(cx, yw, z0),
    depth: new THREE.Vector3(xd, (y0 + y1) / 2, z0),
    height: new THREE.Vector3(xh, y0, (z0 + z1) / 2),
  };
  // The bench under the model as a scale, read off its front.
  const plate = new THREE.MeshStandardMaterial({ roughness: 1, metalness: 0 });
  if (weighed) {
    const thick = side * 0.03;
    const slab = new THREE.BoxGeometry(
      x1 - x0 + margin * 2,
      y1 - y0 + margin * 2,
      thick,
    );
    const scale = new THREE.Mesh(slab, plate);
    // Just under the model, so the extension lines on it do not flicker.
    const top = z0 - side * 0.003;
    scale.position.set(cx, (y0 + y1) / 2, top - thick / 2);
    scale.raycast = () => {};
    const edges = new THREE.EdgesGeometry(slab);
    const outline = new THREE.LineSegments(edges, rule);
    outline.raycast = () => {};
    scale.add(outline);
    root.add(scale);
    made.push(slab, edges, plate);
    // Its front right corner, clear of the width beneath the middle.
    marks.weight = new THREE.Vector3(x1 + margin, y0 - margin, top - thick / 2);
  }

  const colour = new THREE.Color();
  const sheet = new THREE.Color();
  const T = new THREE.Matrix4();
  let painted = "";
  // The spread last drawn, which the numbers follow.
  let spread = 0;
  const at = (n: number | null, f: number) =>
    n === null
      ? new THREE.Vector3()
      : offsets.get(n)!.clone().multiplyScalar(f);
  return {
    root,
    partOf,
    /** Where each measurement's label sits, in the model's frame. */
    marks,
    set(
      f: number,
      picked: number | null,
      hovered: number | null,
      style: CSSStyleDeclaration,
    ) {
      spread = f;
      for (const { node, rest, parentRest, n, under } of movers) {
        if (!offsets.has(n)) continue;
        T.makeTranslation(at(n, f).sub(at(under, f)));
        parentRest
          .clone()
          .multiply(T)
          .multiply(rest)
          .decompose(node.position, node.quaternion, node.scale);
      }
      root.updateMatrixWorld(true);
      const paper = style.getPropertyValue("--anatomy-paper").trim();
      const pen = style.getPropertyValue("--anatomy-ink").trim();
      const accent = style.getPropertyValue("--anatomy-accent").trim();
      const key = `${f}|${picked}|${hovered}|${paper}|${pen}|${accent}`;
      if (key === painted || !paper || !pen || !accent) return;
      painted = key;
      rule.color.set(pen);
      plate.color.set(paper);
      for (const [n, m] of fills) {
        const lit = n !== null && (n === picked || n === hovered);
        sheet.set(paper);
        m.color.copy(lit ? colour.set(accent).lerp(sheet, 0.72) : sheet);
        if (n === null) {
          m.opacity = 1 - 0.92 * f;
          m.depthWrite = f < 0.05;
        }
      }
      for (const [n, m] of inks) {
        const lit = n !== null && (n === picked || n === hovered);
        m.color.set(lit ? accent : pen);
        m.opacity =
          n === null ? 1 - 0.7 * f : picked !== null && !lit ? 0.4 : 1;
      }
    },
    /** Where a part's number points now, in world space. */
    anchor(n: number) {
      const centre = centres.get(n);
      return centre
        ? root.localToWorld(centre.clone().add(at(n, spread)))
        : null;
    },
    middle: () => root.localToWorld(middle.clone()),
  };
}
