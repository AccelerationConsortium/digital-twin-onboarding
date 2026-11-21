import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Play, Repeat } from "lucide-react";
import { api } from "./api";
import type { Workflow } from "./discoveryContent";
import { instrumentModel } from "./instrumentModels";
import type { Mesh } from "./instrumentTypes";
import { lit, upright } from "./modelViews";
import { STAGES, STAGE_LABEL, type Stage } from "./skills";
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
const RAIL = PAD / 2 + 0.26; // the track the sample rides, in front of the stations
const LEVEL = 1.56; // the height the station numbers float at
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
    // The plate every station stands on, with rounded corners.
    const w = n * PITCH + 0.7;
    const d = PAD + 1.2;
    const r = 0.22;
    const outline = new THREE.Shape()
      .moveTo(-w / 2 + r, -d / 2)
      .lineTo(w / 2 - r, -d / 2)
      .quadraticCurveTo(w / 2, -d / 2, w / 2, -d / 2 + r)
      .lineTo(w / 2, d / 2 - r)
      .quadraticCurveTo(w / 2, d / 2, w / 2 - r, d / 2)
      .lineTo(-w / 2 + r, d / 2)
      .quadraticCurveTo(-w / 2, d / 2, -w / 2, d / 2 - r)
      .lineTo(-w / 2, -d / 2 + r)
      .quadraticCurveTo(-w / 2, -d / 2, -w / 2 + r, -d / 2);
    const bench = new THREE.Mesh(
      keep(
        new THREE.ExtrudeGeometry(outline, {
          depth: 0.1,
          bevelEnabled: true,
          bevelSize: 0.025,
          bevelThickness: 0.025,
          bevelSegments: 3,
          curveSegments: 12,
        }),
      ),
      keep(
        new THREE.MeshStandardMaterial({
          color: tone("--surface-1"),
          roughness: 0.85,
        }),
      ),
    );
    bench.rotation.x = -Math.PI / 2;
    bench.position.y = -0.125;
    scene.add(bench);
    // The track that carries the sample from station to station.
    const rail = new THREE.Mesh(
      keep(new THREE.BoxGeometry(n * PITCH - 0.1, 0.04, 0.12)),
      keep(new THREE.MeshStandardMaterial({ color: tone("--line-strong") })),
    );
    rail.position.set(0, 0.02, RAIL);
    scene.add(rail);
    // Each station's number, as in the list below the drawing.
    const badge = (i: number, colour: THREE.Color) => {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 128;
      const pen = canvas.getContext("2d")!;
      pen.fillStyle = `#${colour.getHexString()}`;
      pen.beginPath();
      pen.arc(64, 64, 54, 0, Math.PI * 2);
      pen.fill();
      pen.lineWidth = 8;
      pen.strokeStyle = `#${tone("--surface-1").getHexString()}`;
      pen.stroke();
      pen.fillStyle = `#${tone("--on-brand").getHexString()}`;
      pen.font = "700 64px system-ui, sans-serif";
      pen.textAlign = "center";
      pen.textBaseline = "middle";
      pen.fillText(String(i + 1), 64, 68);
      const texture = keep(new THREE.CanvasTexture(canvas));
      texture.colorSpace = THREE.SRGBColorSpace;
      const sprite = new THREE.Sprite(
        keep(new THREE.SpriteMaterial({ map: texture, depthTest: false })),
      );
      sprite.position.set(x(i), LEVEL, 0);
      sprite.renderOrder = 2;
      scene.add(sprite);
      return sprite;
    };
    const badges: THREE.Sprite[] = [];

    const pads: THREE.MeshStandardMaterial[] = [];
    const heights = cell.stations.map(() => LEVEL);
    // Numbers keep a readable size when a narrow view stands further back.
    let far = 1;
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
      badges.push(badge(i, colour));
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
        // The number sits just above whatever stands on the platform.
        heights[i] = 0.12 + size.y * model.scale.y + 0.26;
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

    // The sample: a vial on a carrier, parked in front of the station it is at.
    const sample = new THREE.Group();
    const carrier = new THREE.Mesh(
      keep(new THREE.CylinderGeometry(0.12, 0.13, 0.05, 32)),
      keep(new THREE.MeshStandardMaterial({ color: ink })),
    );
    carrier.position.y = 0.065;
    const vial = new THREE.Mesh(
      keep(new THREE.CylinderGeometry(0.06, 0.06, 0.2, 24)),
      keep(
        new THREE.MeshStandardMaterial({
          color: tone("--accent"),
          emissive: tone("--accent"),
          emissiveIntensity: 0.55,
        }),
      ),
    );
    vial.position.y = 0.19;
    const cap = new THREE.Mesh(
      keep(new THREE.CylinderGeometry(0.066, 0.066, 0.04, 24)),
      keep(new THREE.MeshStandardMaterial({ color: tone("--surface-1") })),
    );
    cap.position.y = 0.31;
    sample.add(carrier, vial, cap);
    sample.position.set(x(0), 0, RAIL);
    scene.add(sample);

    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const size = () => {
      const width = el.clientWidth;
      const height = el.clientHeight;
      if (!width || !height) return;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      // Far enough back that the whole row fits the width it is given.
      const span = n * PITCH + 0.7;
      const half = THREE.MathUtils.degToRad(camera.fov) / 2;
      const distance = Math.max(
        (span * 1.3) / 2 / (Math.tan(half) * camera.aspect),
        1.45 / Math.tan(half),
      );
      far = Math.min(distance / 5.75, 1.7);
      camera.position.set(distance * 0.28, distance * 0.42, distance * 0.86);
      controls.target.set(0, 0.6, 0);
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
      pads.forEach((material, i) => {
        const here = i === where.current;
        material.emissiveIntensity = here ? 0.55 : 0;
        const lift = here && !still ? Math.sin(time / 420) * 0.03 : 0;
        badges[i].position.y = heights[i] + lift;
        badges[i].scale.setScalar((here ? 0.34 : 0.24) * far);
        badges[i].material.opacity = here ? 1 : 0.8;
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
  const steps = cell.stations.flatMap((x) => x.steps);
  const readouts: { value: string; label: string; stage?: Stage }[] = [
    { value: String(cell.stations.length), label: "Stations" },
    { value: String(steps.length), label: "Steps" },
    ...STAGES.map((stage) => ({
      value: String(steps.filter((step) => step.stage === stage).length),
      label: STAGE_LABEL[stage],
      stage,
    })),
  ];
  return (
    <div className={s.cell}>
      <div className={s.stage}>
        <div
          ref={host}
          className={s.scene}
          role="img"
          aria-label={`${item.title} as a workcell of ${cell.stations.length} stations: ${cell.stations.map((x) => x.name).join(", ")}`}
        />
        <button
          className={s.play}
          disabled={playing}
          onClick={() => {
            setAt(0);
            setPlaying(true);
          }}
        >
          <Play size={15} /> Follow the sample
        </button>
      </div>
      <dl className={s.readouts}>
        {readouts.map((x) => (
          <div key={x.label} data-stage={x.stage}>
            <dd>{x.value}</dd>
            <dt>{x.label}</dt>
          </div>
        ))}
      </dl>
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
              <span>{String(i + 1).padStart(2, "0")}</span>
              <strong>{x.name}</strong>
              <small>{x.steps.map((step) => step.text).join(" · ")}</small>
            </button>
          </li>
        ))}
        {loop && (
          <li className={s.back}>
            <Repeat size={14} /> {item.question}
          </li>
        )}
      </ol>
      <p className={s.hidden} aria-live="polite">
        Station {at + 1}: {station.name}
      </p>
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
