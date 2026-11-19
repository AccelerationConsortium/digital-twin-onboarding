// Moves the parts of a ChemLab-Assets model by its contract's own joints. The model's
// nodes keep the contract's component names, and a joint's axis and pivot are in the
// model's frame (Z up, +Y back), so a pose is applied to the nodes as loaded.
import * as THREE from "three";

export type Joint = {
  type: "revolute" | "prismatic";
  axis: [number, number, number];
  limits: [number, number];
  pivot: [number, number, number];
};
export type Motion = {
  node_prefix: string;
  joints: Record<string, Joint>;
  parts: { id: string; label: string; about: string; moves: boolean }[];
  states: {
    id: string;
    label: string;
    pose: Record<string, number>;
    says: string;
    shows: string | null;
  }[];
};
/** How far each joint is moved, from 0 (as modelled) to 1 (its far limit). */
export type Pose = Record<string, number>;

const HOVER = new THREE.Color(0x4f9a6c);

/** A joint's travel at `f`: towards whichever limit lies further from where it rests. */
const travel = ({ limits: [lo, hi] }: Joint, f: number) =>
  Math.max(0, Math.min(1, f)) * (Math.abs(lo) > Math.abs(hi) ? lo : hi);

export function rig(root: THREE.Object3D, motion: Motion) {
  root.updateMatrixWorld(true);
  const toRoot = root.matrixWorld.clone().invert();
  const inRoot = (o: THREE.Object3D) => toRoot.clone().multiply(o.matrixWorld);
  const nodes = new Map<string, THREE.Object3D>();
  root.traverse((o) => {
    if (o.name.startsWith(motion.node_prefix))
      nodes.set(o.name.slice(motion.node_prefix.length), o);
  });
  const moving = Object.entries(motion.joints).flatMap(([name, joint]) => {
    const node = nodes.get(name);
    if (!node?.parent) return [];
    // The node relative to its parent is re-derived from these rest frames, so a joint
    // inside another moving part follows it.
    return [
      {
        name,
        joint,
        node,
        rest: inRoot(node),
        parentRest: inRoot(node.parent).invert(),
      },
    ];
  });

  // Parts glow on their own materials, so lighting one never lights another.
  const glows = new Map<string, THREE.MeshStandardMaterial[]>();
  const anchors = new Map<string, THREE.Vector3>();
  const owned = new Map<THREE.Object3D, string>();
  const cloned = new Set<THREE.Mesh>();
  for (const part of motion.parts) {
    const node = nodes.get(part.id);
    if (!node) continue;
    const materials: THREE.MeshStandardMaterial[] = [];
    node.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      if (!owned.has(mesh)) owned.set(mesh, part.id);
      if (!cloned.has(mesh)) {
        cloned.add(mesh);
        mesh.material = Array.isArray(mesh.material)
          ? mesh.material.map((m) => m.clone())
          : mesh.material.clone();
      }
      for (const m of [mesh.material].flat())
        if ("emissive" in m) materials.push(m as THREE.MeshStandardMaterial);
    });
    glows.set(part.id, materials);
    // A label sits at the middle of the part and moves with it.
    const centre = new THREE.Box3()
      .setFromObject(node)
      .getCenter(new THREE.Vector3());
    anchors.set(part.id, node.worldToLocal(centre.clone()));
  }
  const base = new Map(
    [...glows.values()].flat().map((m) => [m, m.emissive.clone()]),
  );

  return {
    /** Puts every moving joint where `pose` says; unnamed joints rest. */
    set(pose: Pose) {
      const T = new THREE.Matrix4();
      const step = new THREE.Matrix4();
      for (const { name, joint, node, rest, parentRest } of moving) {
        const v = travel(joint, pose[name] ?? 0);
        const axis = new THREE.Vector3(...joint.axis).normalize();
        if (joint.type === "revolute") {
          const [x, y, z] = joint.pivot;
          T.makeTranslation(x, y, z)
            .multiply(step.makeRotationAxis(axis, v))
            .multiply(step.makeTranslation(-x, -y, -z));
        } else T.makeTranslation(axis.multiplyScalar(v));
        parentRest
          .clone()
          .multiply(T)
          .multiply(rest)
          .decompose(node.position, node.quaternion, node.scale);
      }
      root.updateMatrixWorld(true);
    },
    /** Lights the named parts: brighter for the one in focus. */
    light(hovered: string | null, selected: string | null) {
      for (const [id, materials] of glows)
        for (const m of materials) {
          m.emissive.copy(base.get(m)!);
          if (id === hovered || id === selected)
            m.emissive.lerp(HOVER, id === hovered ? 0.55 : 0.4);
        }
    },
    /** The part a mesh belongs to, walking up from it. */
    partOf(object: THREE.Object3D | null) {
      for (let o = object; o; o = o.parent) {
        const id = owned.get(o);
        if (id) return id;
        const named = o.name.startsWith(motion.node_prefix)
          ? o.name.slice(motion.node_prefix.length)
          : "";
        if (glows.has(named)) return named;
      }
      return null;
    },
    /** Where a part's label goes now, in world space. */
    anchor(id: string) {
      const local = anchors.get(id);
      const node = nodes.get(id);
      return local && node ? node.localToWorld(local.clone()) : null;
    },
    parts: [...glows.keys()],
  };
}

export type Rig = ReturnType<typeof rig>;

/** Eases one pose into another; reduced motion jumps straight there. */
export function blend(from: Pose, to: Pose, t: number): Pose {
  const e = t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
  const out: Pose = {};
  for (const key of new Set([...Object.keys(from), ...Object.keys(to)]))
    out[key] = (from[key] ?? 0) + ((to[key] ?? 0) - (from[key] ?? 0)) * e;
  return out;
}
