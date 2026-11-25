// What a step of a teaching run looks like on a model: drawn over it, in the action's
// own colour, so a model with no joints still shows the step. The model is never moved.
import * as THREE from "three";

const COLOUR = {
  load: 0x7fb08a,
  heat: 0xd9682f,
  mix: 0x4f8fb5,
  read: 0xbfe3c8,
};
export type CueAction = keyof typeof COLOUR;
export const cued = (operation: string): operation is CueAction =>
  operation in COLOUR;

/** How long a cue stays on a model, fading out over its last part. */
const LASTS_MS = 2400;
const FADE_MS = 500;

export function cues(
  scene: THREE.Scene,
  holder: THREE.Object3D,
  access: "top" | "front",
) {
  const box = new THREE.Box3().setFromObject(holder);
  const size = box.getSize(new THREE.Vector3());
  const centre = box.getCenter(new THREE.Vector3());
  const group = new THREE.Group();
  scene.add(group);
  const paint = (action: CueAction) =>
    new THREE.MeshBasicMaterial({
      color: COLOUR[action],
      transparent: true,
      opacity: 0,
      depthWrite: false,
    });
  const made = (
    action: CueAction,
    geometry: THREE.BufferGeometry,
    at = centre,
  ) => {
    const mesh = new THREE.Mesh(geometry, paint(action));
    mesh.position.copy(at);
    mesh.visible = false;
    group.add(mesh);
    return mesh;
  };
  const small = Math.min(size.x, size.y, size.z);
  // A sample comes in through the loading face.
  const sample = made(
    "load",
    new THREE.BoxGeometry(small * 0.28, small * 0.16, small * 0.2),
  );
  const entry =
    access === "front"
      ? new THREE.Vector3(centre.x, centre.y, box.max.z)
      : new THREE.Vector3(centre.x, box.max.y, centre.z);
  const away =
    access === "front"
      ? new THREE.Vector3(0, 0, size.z * 0.6)
      : new THREE.Vector3(0, size.y * 0.6, 0);
  // Heat is a warm glow around the whole body.
  const glow = made(
    "heat",
    new THREE.BoxGeometry(size.x * 1.03, size.y * 1.03, size.z * 1.03),
  );
  // Mixing is a ring turning around the body.
  const reach = Math.hypot(size.x, size.z) * 0.56;
  const ring = made(
    "mix",
    new THREE.TorusGeometry(reach, small * 0.012, 8, 72),
  );
  ring.rotation.x = Math.PI / 2;
  const beads = [0, Math.PI].map((turn) => {
    const bead = made("mix", new THREE.SphereGeometry(small * 0.05, 16, 12));
    bead.userData.turn = turn;
    return bead;
  });
  // A reading is a sheet of light passing up and down through the body.
  const sheet = made(
    "read",
    new THREE.BoxGeometry(size.x * 1.05, small * 0.012, size.z * 1.05),
  );
  const all = [sample, glow, ring, ...beads, sheet];
  const show = (mesh: THREE.Mesh, opacity: number) => {
    mesh.visible = opacity > 0.004;
    (mesh.material as THREE.MeshBasicMaterial).opacity = opacity;
  };

  let action: CueAction | null = null;
  let since = 0;
  return {
    /** Starts the cue of a step, or clears the model when the step has none. */
    play(operation: string | null) {
      action = operation && cued(operation) ? operation : null;
      since = performance.now();
    },
    frame(still: boolean) {
      for (const mesh of all) show(mesh, 0);
      if (!action) return;
      const age = performance.now() - since;
      if (age > LASTS_MS) {
        action = null;
        return;
      }
      const fade = Math.min(1, (LASTS_MS - age) / FADE_MS);
      // Reduced motion holds each cue still where it says the most.
      const t = still ? 0.5 : age / 1000;
      if (action === "load") {
        const near = still ? 0.5 : Math.min(1, age / 900);
        const eased = 1 - (1 - near) ** 3;
        sample.position.copy(entry).addScaledVector(away, 1 - eased);
        // It goes in: gone once it reaches the face.
        show(sample, fade * Math.min(1, (1 - near) * 4) * 0.95);
      } else if (action === "heat") {
        show(glow, fade * (0.16 + 0.1 * Math.sin(t * 5)));
      } else if (action === "mix") {
        show(ring, fade * 0.45);
        for (const bead of beads) {
          const turn = bead.userData.turn + t * 5;
          bead.position.set(
            centre.x + Math.cos(turn) * reach,
            centre.y,
            centre.z + Math.sin(turn) * reach,
          );
          show(bead, fade * 0.95);
        }
      } else {
        sheet.position.y = centre.y + Math.sin(t * 3.2) * size.y * 0.48;
        show(sheet, fade * 0.5);
      }
    },
    dispose() {
      scene.remove(group);
      for (const mesh of all) {
        mesh.geometry.dispose();
        (mesh.material as THREE.Material).dispose();
      }
    },
  };
}
