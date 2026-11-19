// Library model thumbnails and previews. Thumbnails are drawn one at a time on a single
// shared WebGL context, so a page of cards never opens one context per card.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { looseModel } from "./instrumentModels";
import type { Mesh } from "./instrumentTypes";

const THUMB = 360;
const VIEW = new THREE.Vector3(0.75, 0.55, 1).normalize();

export function lit(scene: THREE.Scene) {
  scene.add(new THREE.HemisphereLight(0xffffff, 0x445544, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(2, 4, 3);
  const fill = new THREE.DirectionalLight(0xffffff, 0.5);
  fill.position.set(-2, 1.5, -1);
  scene.add(sun, fill);
}

/** The model standing Y up on the floor at the origin, turned there when it is Z-up. */
export function upright(object: THREE.Object3D, up: Mesh["up"] = "z") {
  const holder = new THREE.Group();
  const turned = new THREE.Group();
  if (up !== "y") turned.rotation.x = -Math.PI / 2;
  turned.add(object);
  holder.add(turned);
  holder.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(turned);
  const centre = box.getCenter(new THREE.Vector3());
  turned.position.set(-centre.x, -box.min.y, -centre.z);
  holder.updateMatrixWorld(true);
  return holder;
}

/** Points the camera at the whole object from the front-right, filling the frame. */
export function aim(
  camera: THREE.PerspectiveCamera,
  object: THREE.Object3D,
  aspect: number,
) {
  const box = new THREE.Box3().setFromObject(object);
  const centre = box.getCenter(new THREE.Vector3());
  const radius = Math.max(0.05, box.getSize(new THREE.Vector3()).length() / 2);
  camera.aspect = aspect;
  const half = Math.atan(
    Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * Math.min(1, aspect),
  );
  const distance = (radius / Math.sin(half)) * 1.02;
  camera.position.copy(centre).addScaledVector(VIEW, distance);
  camera.near = distance / 100;
  camera.far = distance * 10;
  camera.lookAt(centre);
  camera.updateProjectionMatrix();
  return centre;
}

export type Stage = {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  /** The loaded model, in its own frame; `holder` stands it upright on the floor. */
  model: THREE.Object3D;
  holder: THREE.Object3D;
};

/**
 * A model drawn into `el` on a floor grid, turned with the mouse. `ready` runs once the
 * model is in the scene and `frame` before every render. Returns the teardown.
 */
export function stage(
  el: HTMLElement,
  mesh: Mesh,
  on: {
    state: (state: "loading" | "ready" | "failed") => void;
    ready?: (stage: Stage) => void;
    frame?: (stage: Stage) => void;
  },
) {
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  } catch {
    on.state("failed");
    return () => {};
  }
  let alive = true;
  on.state("loading");
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  el.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  lit(scene);
  const floor = new THREE.GridHelper(2, 20, 0x6f8a78, 0x3a4c42);
  scene.add(floor);
  const camera = new THREE.PerspectiveCamera(32, 1, 0.01, 50);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  let model: Awaited<ReturnType<typeof looseModel>> | null = null;
  let shown: Stage | null = null;
  const resize = () => {
    const { width, height } = el.getBoundingClientRect();
    renderer.setSize(width, height, false);
    if (shown)
      controls.target.copy(
        aim(camera, shown.holder, Math.max(1, width) / Math.max(1, height)),
      );
    controls.update();
  };
  looseModel(mesh)
    .then((loaded) => {
      if (!alive) return loaded.release();
      model = loaded;
      const holder = upright(loaded.object, mesh.up);
      scene.add(holder);
      const size = new THREE.Box3()
        .setFromObject(holder)
        .getSize(new THREE.Vector3());
      floor.scale.setScalar(Math.max(size.x, size.z) * 0.9);
      shown = { renderer, scene, camera, model: loaded.object, holder };
      resize();
      on.ready?.(shown);
      on.state("ready");
    })
    .catch((e) => {
      console.warn((e as Error).message);
      if (alive) on.state("failed");
    });
  const observer = new ResizeObserver(resize);
  observer.observe(el);
  let frame = 0;
  const tick = () => {
    controls.update();
    if (shown) on.frame?.(shown);
    renderer.render(scene, camera);
    frame = requestAnimationFrame(tick);
  };
  tick();
  return () => {
    alive = false;
    cancelAnimationFrame(frame);
    observer.disconnect();
    controls.dispose();
    model?.release();
    floor.geometry.dispose();
    (floor.material as THREE.Material).dispose();
    renderer.dispose();
    renderer.domElement.remove();
  };
}

let renderer: THREE.WebGLRenderer | null | undefined;
let queue: Promise<unknown> = Promise.resolve();
const thumbs = new Map<string, Promise<string | null>>();

/** A still of the model as an image URL, or null when it cannot be drawn. */
export function thumbnail(mesh: Mesh): Promise<string | null> {
  const key = mesh.url ?? mesh.kind;
  if (!thumbs.has(key)) {
    const drawn = queue.then(() => draw(mesh));
    queue = drawn.catch(() => undefined);
    thumbs.set(key, drawn);
  }
  return thumbs.get(key)!;
}

async function draw(mesh: Mesh) {
  if (renderer === undefined)
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        preserveDrawingBuffer: true,
      });
      renderer.setPixelRatio(1);
      renderer.setSize(THUMB, THUMB, false);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
    } catch {
      renderer = null;
    }
  if (!renderer) return null;
  let model;
  try {
    model = await looseModel(mesh);
  } catch (e) {
    console.warn((e as Error).message);
    return null;
  }
  const scene = new THREE.Scene();
  lit(scene);
  scene.add(upright(model.object, mesh.up));
  const camera = new THREE.PerspectiveCamera(30, 1, 0.01, 50);
  aim(camera, scene, 1);
  renderer.render(scene, camera);
  const url = renderer.domElement.toDataURL("image/webp", 0.86);
  model.release();
  return url;
}
