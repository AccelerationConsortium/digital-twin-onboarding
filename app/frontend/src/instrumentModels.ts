// Registered 3D models drawn in place of a twin's planning box. Every file is checked
// against its pinned sha256; a missing or changed file leaves the box in place.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { api } from "./api";
import type { Mesh, TwinSpec } from "./instrumentTypes";
import { footprint, top } from "./layoutGeometry";
import { HOME, type Deck } from "./workcellCase/cell";
import { buildBalance } from "./workcellCase/balanceModel";
import { buildOT2 } from "./workcellCase/ot2Model";
import { buildRobot } from "./workcellCase/robotModel";

type Registry = {
  base_path: string;
  assets: { id: string; file: string | null; sha256: string | null }[];
};

const ARM_REST = HOME.map((d) => (d * Math.PI) / 180);

const hex = (b: ArrayBuffer) =>
  [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");

async function download(url: string, sha256: string) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  const bytes = await response.arrayBuffer();
  if (hex(await crypto.subtle.digest("SHA-256", bytes)) !== sha256)
    throw new Error(`${url} does not match its pinned digest`);
  return bytes;
}

const files = new Map<string, Promise<ArrayBuffer>>();
function verified(url: string, sha256: string) {
  if (!files.has(url)) files.set(url, download(url, sha256));
  return files.get(url)!;
}

let registry: Promise<Registry> | null = null;
async function registered(id: string) {
  registry ??= api<Registry>("/workcell/assets");
  const reg = await registry;
  const asset = reg.assets.find((a) => a.id === id);
  if (!asset?.file || !asset.sha256)
    throw new Error(`${id} is not a file asset`);
  return verified(reg.base_path + asset.file, asset.sha256);
}

const templates = new Map<string, Promise<THREE.Object3D>>();
/** A shared Z-up template for an instrument model; clone it before adding it to a scene. */
export function instrumentModel(mesh: Mesh): Promise<THREE.Object3D> {
  const key =
    mesh.kind === "glb"
      ? mesh.url!
      : mesh.kind === "sketch"
        ? `sketch:${mesh.asset}`
        : mesh.kind;
  if (!templates.has(key))
    templates.set(
      key,
      (async () => {
        if (mesh.kind === "glb") {
          const bytes = await verified(mesh.url!, mesh.sha256!);
          return (await new GLTFLoader().parseAsync(bytes, "")).scene;
        }
        if (mesh.kind === "ot2") {
          const decks = JSON.parse(
            new TextDecoder().decode(await registered("opentrons-decks")),
          ) as { ot2: Deck };
          const ot2 = buildOT2(decks.ot2);
          // Parked a little further forward than the case's start, the gantry beam
          // stays inside the frame and so inside the twin's planning envelope.
          ot2.setNozzle([ot2.park[0], ot2.park[1] - 0.06, ot2.park[2]]);
          return ot2.group;
        }
        if (mesh.kind === "balance") return buildBalance().group;
        if (mesh.kind === "sketch") return buildSketch(mesh);
        throw new Error(`No instrument model for ${mesh.kind}`);
      })(),
    );
  return templates.get(key)!;
}

/**
 * A photo sketch's parts as a Z-up model: boxes, edged so that neighbours read apart,
 * and where the photo shows them, rounded bodies, upright cylinders and glass.
 */
function buildSketch(mesh: Mesh) {
  const group = new THREE.Group();
  for (const part of mesh.parts ?? []) {
    const [w, h, d] = part.size;
    const [x, y, z] = part.position;
    const round = (part.round ?? 0) * Math.min(w, h, d);
    const geometry =
      part.shape === "cylinder"
        ? new THREE.CylinderGeometry(0.5, 0.5, 1, 24)
            .rotateX(Math.PI / 2)
            .scale(w, d, h)
        : round
          ? new RoundedBoxGeometry(w, d, h, 3, round)
          : new THREE.BoxGeometry(w, d, h);
    const glass = (part.opacity ?? 1) < 1;
    const box = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({
        color: part.color,
        roughness: glass ? 0.2 : 0.7,
        transparent: glass,
        opacity: part.opacity ?? 1,
        depthWrite: !glass,
      }),
    );
    box.name = part.label;
    // The twin's front is +Z with Y up; a Z-up model's front is -Y.
    box.position.set(x, -z, y);
    if (!round)
      box.add(
        new THREE.LineSegments(
          new THREE.EdgesGeometry(geometry, 40),
          new THREE.LineBasicMaterial({
            color: 0x000000,
            transparent: true,
            opacity: glass ? 0.15 : 0.35,
          }),
        ),
      );
    group.add(box);
  }
  return group;
}

/**
 * A Z-up model loaded on its own rather than kept, since browsing the whole library would
 * otherwise hold every file in memory. `release` frees what the model alone owns.
 */
export async function looseModel(
  mesh: Mesh,
): Promise<{ object: THREE.Object3D; release: () => void }> {
  if (mesh.kind === "ur5e") {
    const robot = await armModel();
    robot.pose(ARM_REST, 0.15);
    return { object: robot.group, release: () => release(robot.group) };
  }
  // Procedural models share their cached template's buffers.
  if (mesh.kind !== "glb")
    return { object: (await instrumentModel(mesh)).clone(true), release() {} };
  const bytes = await download(mesh.url!, mesh.sha256!);
  const scene = (await new GLTFLoader().parseAsync(bytes, "")).scene;
  return { object: scene, release: () => release(scene) };
}

function release(root: THREE.Object3D) {
  root.traverse((o) => {
    const mesh = o as THREE.Mesh;
    mesh.geometry?.dispose();
    const material = mesh.material as
      THREE.MeshStandardMaterial | THREE.MeshStandardMaterial[] | undefined;
    for (const m of Array.isArray(material)
      ? material
      : material
        ? [material]
        : []) {
      m.map?.dispose();
      m.normalMap?.dispose();
      m.roughnessMap?.dispose();
      m.metalnessMap?.dispose();
      m.dispose();
    }
  });
}

let robotFile: Promise<ArrayBuffer> | null = null;
/** A posable UR5e with Robotiq 2F-140, in the controller base frame (Z up). */
export async function armModel() {
  robotFile ??= registered("ur5e-robotiq-2f140");
  const gltf = await new GLTFLoader().parseAsync(await robotFile, "");
  return buildRobot(gltf);
}

/**
 * The box around what a model draws: visible meshes only, from their vertices, so an
 * invisible helper (a pipette tip waiting to be shown) or a turned node's loose bounds
 * cannot move or stretch the model.
 */
export function drawnBox(root: THREE.Object3D) {
  root.updateMatrixWorld(true);
  const box = new THREE.Box3();
  const point = new THREE.Vector3();
  root.traverseVisible((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    const position = mesh.geometry?.getAttribute("position");
    if (!position || (mesh as THREE.InstancedMesh).isInstancedMesh) {
      box.union(new THREE.Box3().setFromObject(mesh, true));
      return;
    }
    for (let i = 0; i < position.count; i++)
      box.expandByPoint(
        point.fromBufferAttribute(position, i).applyMatrix4(mesh.matrixWorld),
      );
  });
  return box;
}

const standing = new WeakMap<THREE.Object3D, Map<string, THREE.Box3>>();
/** The drawn box of a template stood Y up; kept, since a template never changes. */
function standingBox(template: THREE.Object3D, up: Mesh["up"]) {
  const key = up === "y" ? "y" : "z";
  const known = standing.get(template) ?? new Map<string, THREE.Box3>();
  standing.set(template, known);
  if (!known.has(key)) {
    const turned = new THREE.Group();
    if (key === "z") turned.rotation.x = -Math.PI / 2;
    turned.add(template.clone(true));
    known.set(key, drawnBox(turned));
  }
  return known.get(key)!;
}

/**
 * The model turned Y up and fitted to the twin's planning envelope, its footprint and
 * height, front toward the twin's +Z like the planning box. The planner's solid shapes
 * are measured as fractions of that same envelope, so what is drawn is what is checked.
 * `userData.scale` is how far the model was stretched on each axis to fit.
 */
export function fitted(
  template: THREE.Object3D,
  spec: TwinSpec,
  up: Mesh["up"] = "z",
) {
  const holder = new THREE.Group();
  const scaled = new THREE.Group();
  const upright = new THREE.Group();
  // A Z-up model's front, -Y, becomes +Z; a Y-up model already stands that way.
  if (up !== "y") upright.rotation.x = -Math.PI / 2;
  upright.add(template.clone(true));
  scaled.add(upright);
  holder.add(scaled);
  const box = standingBox(template, up);
  const size = box.getSize(new THREE.Vector3());
  const centre = box.getCenter(new THREE.Vector3());
  const { x0, x1, z0, z1 } = footprint(spec);
  const stretch = (want: number, have: number) =>
    want > 0 && have > 1e-6 ? want / have : 1;
  scaled.scale.set(
    stretch(x1 - x0, size.x),
    stretch(top(spec), size.y),
    stretch(z1 - z0, size.z),
  );
  upright.position.set(-centre.x, -box.min.y, -centre.z);
  scaled.position.set((x0 + x1) / 2, 0, (z0 + z1) / 2);
  holder.userData.scale = scaled.scale.toArray();
  return holder;
}
