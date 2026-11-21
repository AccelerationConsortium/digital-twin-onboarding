import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Play, Repeat } from "lucide-react";
import { api } from "./api";
import type { Workflow } from "./discoveryContent";
import { instrumentModel } from "./instrumentModels";
import type { Mesh } from "./instrumentTypes";
import { lit, upright } from "./modelViews";
import { STAGE_LABEL, type Stage } from "./skills";
import s from "./PaperCell.module.css";

type Station = {
  id: string;
  name: string;
  source: string;
  mesh: Mesh | null;
  credit: string | null;
  size_m: [number, number, number];
  steps: { index: number; text: string; stage: Stage }[];
};
type Cell = { stations: Station[]; statement: string };

const PITCH = 1.5; // distance between station centres
const PAD = 1.2; // a station's square platform
const FIT = 0.92; // the part of a platform a model may cover
const TONE: Record<Stage, string> = {
  prepare: "--ok",
  characterize: "--info",
  test: "--accent",
};
/** The stage a station is drawn in: what its last step does to the sample. */
const stageOf = (station: Station) => station.steps.at(-1)!.stage;

/** A published workflow as a 3D workcell: a platform and a twin for every station. */
export default function PaperCell({ item }: { item: Workflow }) {
  const host = useRef<HTMLDivElement>(null);
  const [cell, setCell] = useState<Cell | null>(null);
  const [failed, setFailed] = useState(false);
  const [at, setAt] = useState(0);
  const [playing, setPlaying] = useState(false);
  // The scene reads where the sample is from here, so a step never rebuilds it.
  const where = useRef(0);
  where.current = at;
  const loop = item.kind === "Closed loop";

  useEffect(() => {
    let current = true;
    setCell(null);
    setAt(0);
    setPlaying(false);
    api<Cell>(`/marketplace/${item.id}/cell`)
      .then((next) => current && setCell(next))
      .catch(() => current && setFailed(true));
    return () => {
      current = false;
    };
  }, [item.id]);

  // The sample visits each station in turn, then waits at the last.
  useEffect(() => {
    if (!playing || !cell) return;
    if (at >= cell.stations.length - 1) return setPlaying(false);
    const timer = window.setTimeout(() => setAt(at + 1), 1300);
    return () => window.clearTimeout(timer);
  }, [playing, at, cell]);

  useEffect(() => {
    const el = host.current;
    if (!el || !cell) return;
    let alive = true;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      el.dataset.flat = "true";
      return () => {
        delete el.dataset.flat;
      };
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    lit(scene);
    const camera = new THREE.PerspectiveCamera(32, 1, 0.05, 80);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.enablePan = false;
    // The wheel scrolls the page past the workcell; dragging turns it.
    controls.enableZoom = false;
    controls.maxPolarAngle = Math.PI / 2.15;
    const owned: { dispose: () => void }[] = [];
    const keep = <T extends { dispose: () => void }>(thing: T) => {
      owned.push(thing);
      return thing;
    };
    const css = getComputedStyle(el);
    const tone = (name: string) =>
      new THREE.Color(css.getPropertyValue(name).trim() || "#888888");
    const ink = tone("--ink");

    const n = cell.stations.length;
    const x = (i: number) => (i - (n - 1) / 2) * PITCH;
    // The bench every station stands on.
    const bench = new THREE.Mesh(
      keep(new THREE.BoxGeometry(n * PITCH + 0.5, 0.1, PAD + 0.7)),
      keep(new THREE.MeshStandardMaterial({ color: tone("--surface-3") })),
    );
    bench.position.y = -0.05;
    scene.add(bench);

    const pads: THREE.MeshStandardMaterial[] = [];
    cell.stations.forEach((station, i) => {
      const colour = tone(TONE[stageOf(station)]);
      const material = keep(
        new THREE.MeshStandardMaterial({
          color: colour,
          emissive: colour,
          emissiveIntensity: 0,
          roughness: 0.6,
        }),
      );
      pads.push(material);
      const pad = new THREE.Mesh(
        keep(new THREE.BoxGeometry(PAD, 0.12, PAD)),
        material,
      );
      pad.position.set(x(i), 0.06, 0);
      scene.add(pad);
      const stand = (model: THREE.Object3D) => {
        if (!alive) return;
        const size = new THREE.Box3()
          .setFromObject(model)
          .getSize(new THREE.Vector3());
        // Each twin fills its platform, so a meter is as easy to see as a furnace.
        model.scale.setScalar(
          Math.min((PAD * FIT) / Math.max(size.x, size.z), 1.15 / size.y),
        );
        model.position.set(x(i), 0.12, 0);
        scene.add(model);
      };
      const box = () => {
        const [w, h, d] = station.size_m;
        stand(
          upright(
            new THREE.Mesh(
              keep(new THREE.BoxGeometry(w, h, d)),
              keep(new THREE.MeshStandardMaterial({ color: tone("--muted") })),
            ),
            "y",
          ),
        );
      };
      if (!station.mesh) return box();
      instrumentModel(station.mesh)
        .then((template) =>
          stand(upright(template.clone(true), station.mesh!.up)),
        )
        .catch(box);
    });

    // The way the sample goes: an arrow to each next station, and back round if it loops.
    const arrowMaterial = keep(new THREE.MeshStandardMaterial({ color: ink }));
    const head = keep(new THREE.ConeGeometry(0.07, 0.16, 16));
    const shaft = keep(new THREE.BoxGeometry(PITCH - PAD + 0.16, 0.03, 0.05));
    for (let i = 0; i < n - 1; i++) {
      const mid = (x(i) + x(i + 1)) / 2;
      const bar = new THREE.Mesh(shaft, arrowMaterial);
      bar.position.set(mid - 0.04, 0.14, PAD / 2 - 0.12);
      const tip = new THREE.Mesh(head, arrowMaterial);
      tip.rotation.z = -Math.PI / 2;
      tip.position.set(mid + (PITCH - PAD) / 2 + 0.06, 0.14, PAD / 2 - 0.12);
      scene.add(bar, tip);
    }
    if (loop && n > 1) {
      const back = new THREE.CatmullRomCurve3([
        new THREE.Vector3(x(n - 1), 0.14, -PAD / 2 - 0.02),
        new THREE.Vector3(x(n - 1) - 0.3, 0.14, -PAD / 2 - 0.3),
        new THREE.Vector3(x(0) + 0.3, 0.14, -PAD / 2 - 0.3),
        new THREE.Vector3(x(0), 0.14, -PAD / 2 - 0.08),
      ]);
      const returnMaterial = keep(
        new THREE.MeshStandardMaterial({ color: tone("--muted") }),
      );
      scene.add(
        new THREE.Mesh(
          keep(new THREE.TubeGeometry(back, 48, 0.018, 8)),
          returnMaterial,
        ),
      );
      const tip = new THREE.Mesh(head, returnMaterial);
      tip.rotation.x = Math.PI / 2;
      tip.position.set(x(0), 0.14, -PAD / 2 - 0.02);
      scene.add(tip);
    }

    // The sample, hovering over the station it is at.
    const sample = new THREE.Mesh(
      keep(new THREE.SphereGeometry(0.09, 24, 16)),
      keep(
        new THREE.MeshStandardMaterial({
          color: tone("--accent"),
          emissive: tone("--accent"),
          emissiveIntensity: 0.6,
        }),
      ),
    );
    sample.position.set(x(0), 1.5, 0);
    scene.add(sample);

    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const size = () => {
      const width = el.clientWidth;
      const height = el.clientHeight;
      if (!width || !height) return;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      // Far enough back that the whole row fits the width it is given.
      const span = n * PITCH + 0.2;
      const half = THREE.MathUtils.degToRad(camera.fov) / 2;
      const distance = Math.max(
        (span * 1.18) / 2 / (Math.tan(half) * camera.aspect),
        1.25 / Math.tan(half),
      );
      camera.position.set(distance * 0.28, distance * 0.42, distance * 0.86);
      controls.target.set(0, 0.45, 0);
      camera.updateProjectionMatrix();
    };
    size();
    const watch = new ResizeObserver(size);
    watch.observe(el);
    let frame = 0;
    const draw = (time: number) => {
      frame = requestAnimationFrame(draw);
      const goal = x(Math.min(where.current, n - 1));
      sample.position.x = still
        ? goal
        : THREE.MathUtils.lerp(sample.position.x, goal, 0.09);
      sample.position.y = 1.5 + (still ? 0 : Math.sin(time / 420) * 0.04);
      pads.forEach((material, i) => {
        material.emissiveIntensity = i === where.current ? 0.55 : 0;
      });
      controls.update();
      renderer.render(scene, camera);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      watch.disconnect();
      controls.dispose();
      owned.forEach((thing) => thing.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [cell, loop]);

  if (failed)
    return (
      <p className={s.note} role="alert">
        The 3D workcell could not be loaded. Reload to try again.
      </p>
    );
  if (!cell) return <div className={s.cell} aria-busy="true" />;
  const station = cell.stations[at];
  return (
    <div className={s.cell}>
      <div
        ref={host}
        className={s.scene}
        role="img"
        aria-label={`${item.title} as a workcell of ${cell.stations.length} stations: ${cell.stations.map((x) => x.name).join(", ")}`}
      />
      <ol className={s.stations} aria-label="Stations">
        {cell.stations.map((x, i) => (
          <li key={x.id + i}>
            <button
              data-stage={stageOf(x)}
              aria-pressed={i === at}
              onClick={() => {
                setPlaying(false);
                setAt(i);
              }}
            >
              <span>{i + 1}</span>
              {x.name}
            </button>
          </li>
        ))}
        {loop && (
          <li className={s.back} title={item.question}>
            <Repeat size={14} /> next sample
          </li>
        )}
      </ol>
      <div className={s.now} aria-live="polite">
        <span className={s.chip} data-stage={stageOf(station)}>
          {STAGE_LABEL[stageOf(station)]}
        </span>
        <p>{station.steps.map((step) => step.text).join(" · ")}</p>
        <div className={s.actions}>
          <button
            className={s.quiet}
            disabled={playing}
            onClick={() => {
              setAt(0);
              setPlaying(true);
            }}
          >
            <Play size={15} /> Follow the sample
          </button>
        </div>
      </div>
      <details className={s.about}>
        <summary>What is drawn</summary>
        <p>{cell.statement}</p>
        <ul>
          {cell.stations.map((x, i) => (
            <li key={x.id + i}>{x.credit ?? `${x.name}: drawn as a box`}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
