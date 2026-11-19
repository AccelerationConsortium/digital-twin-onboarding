export type Operation = "load" | "transfer" | "mix" | "heat" | "read" | "wait";
export const operations: Operation[] = [
  "load",
  "transfer",
  "mix",
  "heat",
  "read",
  "wait",
];
export const operationLabels: Record<Operation, string> = {
  load: "Load sample",
  transfer: "Transfer sample",
  mix: "Mix",
  heat: "Heat",
  read: "Read",
  wait: "Wait",
};
export type Layer =
  | "volume"
  | "resource"
  | "geometry"
  | "container"
  | "consumable"
  | "state"
  | "constraint";
export const layers: Layer[] = [
  "volume",
  "resource",
  "geometry",
  "container",
  "consumable",
  "state",
  "constraint",
];
export const layerLabels: Record<Layer, string> = {
  volume: "Volume",
  resource: "Resources (slots)",
  geometry: "Geometry",
  container: "Container",
  consumable: "Consumables",
  state: "State / operations",
  constraint: "Constraints",
};
export type Vessel = "none" | "tube" | "vial" | "plate" | "reservoir";
export const vessels: Vessel[] = ["none", "tube", "vial", "plate", "reservoir"];
export type Consumable = {
  name: string;
  used_by: Operation;
  per_use: number;
  stock: number;
};
export type Vec = [number, number, number];
export type TwinSpec = {
  name: string;
  parts: { size: Vec; position: Vec; color: string }[];
  operations: Operation[];
  container: { vessel: Vessel; max_volume_ul: number };
  resource: { slots: number };
  consumables: Consumable[];
  limits: { min_temp_c: number; max_temp_c: number; max_duration_s: number };
  assumptions: string;
  /** Drawn deck slots in the twin's local frame (metres); empty: one top access point. */
  sites?: Site[];
  /** Transfer twins: the arm profile and joint limits narrowed by its connector. */
  arm?: ArmProfile | null;
  joint_limits_deg?: number[];
  /** Where labware goes in, and how high above the bench it then sits (metres). */
  access?: Access | null;
  level_m?: number | null;
  /** The part of one face an enclosure is entered through; left out, its whole front. */
  opening?: Opening | null;
  /** How far a drawer comes out of that face to take labware (metres). */
  drawer_m?: number | null;
};
export type Site = { key: string; x: number; z: number };
export type ArmProfile = "ur3e" | "ur5e" | "ur10e";
export const armProfiles: { key: ArmProfile; name: string; reach: number }[] = [
  { key: "ur3e", name: "UR3e", reach: 0.5 },
  { key: "ur5e", name: "UR5e", reach: 0.85 },
  { key: "ur10e", name: "UR10e", reach: 1.3 },
];
/** Slot names a sample can take: drawn slots, else numbered ones. */
export const siteKeys = (spec: TwinSpec) =>
  spec.sites?.length
    ? spec.sites.map((s) => s.key)
    : Array.from({ length: spec.resource.slots }, (_, i) => String(i + 1));
export type Residual = {
  id: string;
  created_at: string;
  layer: Layer;
  step: number | null;
  predicted: string;
  observed: string;
  note: string;
  revision: number;
  resolved_in: number | null;
  evidence: "learner_observation";
};
/** The registered model drawn in place of the planning box. */
export type Mesh = {
  kind: "glb" | "ot2" | "balance" | "ur5e";
  url?: string;
  sha256?: string;
  /** The axis the model stands on; a Z-up model is turned to the scene's Y up. */
  up?: "y" | "z";
  asset?: string;
};
export type SimReadyProvenance = {
  id: string;
  mesh?: Mesh | null;
  label: string;
  provider: string;
  license: string;
  attribution: string;
  repo: string;
  revision: string;
  path: string;
  url: string;
};
export type SimReadyAsset = Omit<SimReadyProvenance, "id"> & {
  spec: TwinSpec;
};
export type LibraryEntry = {
  collection: "workcell" | "simready" | "chemlab" | "cloudlab";
  id: string;
  name: string;
  label: string;
  provider: string;
  domain: string;
  license: string;
  attribution: string;
  size_m: [number, number, number];
  operations: Operation[];
  /** Instrument lesson in Meet the instruments, when there is one. */
  lesson?: "flex" | "ot2" | null;
};
export type LibraryResults = {
  size: number;
  total: number;
  results: LibraryEntry[];
};
/** A library entry drawn with its own 3D model, for the model library page. */
export type ModelEntry = LibraryEntry & { mesh: Mesh; url: string };
export type ModelResults = {
  size: number;
  total: number;
  domains: Record<string, number>;
  results: ModelEntry[];
};
export type LibraryMatch = LibraryEntry & {
  suggested_by: "astra" | "label_text";
  verified: boolean;
};
export type Identification = {
  library_id: string;
  alternatives: string[];
  maker: string;
  model: string;
  confidence: "high" | "medium" | "low";
  evidence: string;
};
export type Twin = {
  id: string;
  status:
    | "starting"
    | "generating"
    | "draft"
    | "ready"
    | "failed"
    | "submission_unknown";
  confirmed: boolean;
  mode: "mock" | "real";
  source:
    | "astra_image"
    | "academy_template"
    | "simready_asset"
    | "chemlab_asset"
    | "cloudlab_asset"
    | "workcell_asset";
  asset?: SimReadyProvenance | null;
  identification?: Identification | null;
  matches?: LibraryMatch[];
  spec: TwinSpec | null;
  message: string;
  evidence: "synthetic";
  revision: number;
  residuals: Residual[];
  /** Where the dimensions come from; a layout is as trustworthy as its weakest twin. */
  size_basis?: "checked" | "datasheet" | "catalogued" | "estimated";
};
export type Step = {
  device_id: string;
  operation: Operation;
  source_id: string | null;
  target_id: string | null;
  value: number;
  /** Tracked sample the step acts on; "sample" when the workflow tracks one. */
  sample?: string;
  /** Slots used; empty takes the first free one. */
  site?: string;
  source_site?: string;
  target_site?: string;
};
export const DEFAULT_SAMPLE = "sample";
export type Access = "top" | "front";
export type Opening = {
  face: "front" | "left" | "right";
  /** Fractions along the face: back to front on a side, left to right at the front. */
  start: number;
  end: number;
};
export type Placement = {
  twin_id: string;
  x: number;
  z: number;
  yaw: number;
  access: Access;
  /** Stays put when layouts are searched. */
  kept?: boolean;
};
export type Bench = { width: number; depth: number };
export type Layout = { bench: Bench; placements: Placement[] };
/** World points (y-up, metres) of the arm base, six joints and the grasp point. */
export type ArmFrame = Vec[];
export type MotionSummary = {
  step: number;
  actor_id: string;
  source_id: string;
  target_id: string;
  arm: string;
  planner: "swing" | "joint" | "rrt_connect";
  length_m: number;
  clearance_m: number;
  /** Arm time at the connector's default speed, simulated when `simulation` is present. */
  seconds?: number;
  source_site?: string | null;
  target_site?: string | null;
  /** Least elbow bend while lowering into a station. */
  elbow_deg?: number;
  /** Present when the path was run in the rigid-body simulation. */
  simulation?: {
    engine: "mujoco";
    version: string;
    speed: number;
    payload_kg: number;
    tracking_deg: number;
    torque_ratio: number;
    self_clearance_m: number;
    nearest: string | null;
    kinematic_seconds: number;
    kinematic_clearance_m: number;
  };
};
export type Motion = MotionSummary & {
  frames: ArmFrame[];
  /** Joint angles (rad) of the same frames. */
  joints: number[][];
  /** For each frame: how far along the path, which segment, and the arm's clearance. */
  profile?: {
    progress: number[];
    segment: number[];
    segments: string[];
    clearance_m: number[];
    nearest: string[];
  };
};
/** One workflow step in time, with where every sample and consumable is once it ends. */
export type TimelineStep = {
  step: number;
  device_id: string;
  operation: Operation;
  sample: string;
  location: string | null;
  site: string | null;
  samples: Record<
    string,
    {
      location: string | null;
      site: string | null;
      volume_ul: number;
      temperature_c: number;
      mixed: boolean;
    }
  >;
  consumables: Record<string, Record<string, number>>;
  start_s: number;
  end_s: number;
};
export type BlockedMotion = {
  step: number;
  actor_id: string;
  source_id: string;
  target_id: string;
  arm: string;
  blocked_by: string | null;
  link: string | null;
  frames: ArmFrame[];
  joints: number[][];
};
export type LayoutPreview = {
  arm: string;
  reach_m: number;
  motions: Motion[];
  error: { message: string; layer: string } | null;
  blocked: BlockedMotion | null;
  /** The saved workflow in time; empty when it could not be planned. */
  timeline?: TimelineStep[];
  /** Joint angles each arm waits in, clear of every instrument; null when none is. */
  rest?: Record<string, number[] | null>;
  /** What arm paths are simulated with; null when only the geometry is checked. */
  simulation: {
    engine: "mujoco";
    version: string;
    speed: number;
    payload_kg: number;
  } | null;
};
export type LayoutMetrics = {
  run_s: number;
  arm_s: number;
  /** When the last step ends if steps on separate instruments overlap. */
  finish_s: number;
  path_m: number;
  clearance_m: number;
  reach_margin_m: number;
  elbow_deg: number;
  area_m2: number;
  /** Smallest clearance or reach margin over every workflow the layout was checked for. */
  margin_m?: number;
};
export type LayoutCandidate = LayoutMetrics & {
  layout: Layout;
  motions: MotionSummary[];
  /** Slots the arm reaches on instruments with a slot preference. */
  slots: Record<string, string[]>;
};
/** One chunk of moving a layout's instruments toward chosen objectives. */
export type LayoutImprovement = LayoutCandidate & {
  next: number | null;
  idle: number;
  tried: number;
  kept: number;
};
export type Diagnosis = { kind: string; count: number; hint: string };
export type Consolidation = {
  drop_id: string;
  into_id: string;
  extra_slots: number;
  free_slots: number;
  transfers_saved: number;
  message: string;
};
export type LayoutSearchChunk = {
  arm: string;
  reach_m: number;
  total: number;
  next: number | null;
  candidates: LayoutCandidate[];
  checked: number;
  failure: string | null;
  diagnosis: Diagnosis[];
  /** Only on the first chunk. */
  consolidation?: Consolidation[];
};
export type Side = "left" | "right" | "front" | "back";
export type Constraint = {
  kind: "reach_slots" | "zone" | "near" | "apart" | "exclude";
  twin_id: string;
  other_id?: string | null;
  count?: number;
  side?: Side | null;
  metres?: number;
};
/** What a plain-language request changes in a layout, for the learner to review. */
export type Refinement = Layout & {
  constraints: Constraint[];
  applied: string[];
  skipped: string[];
  unclear: string;
  search: boolean;
  model: string;
};
export type ExampleCell = {
  id: string;
  name: string;
  summary: string;
  instruments: string[];
  placed: boolean;
};
export type BriefRole = {
  key: string;
  name: string;
  operations: Operation[];
  vessel: Vessel;
  query: string;
  /** The maker or model the description names for this role, when it names one. */
  model?: string;
  reach_slots?: number;
};
export type BriefStep = {
  role: string;
  operation: Operation;
  source_role: string;
  target_role: string;
  value: number;
  sample?: string;
};
export type BriefPreference = {
  kind: "zone" | "near" | "apart";
  role: string;
  other_role: string;
  side: Side | "";
  metres: number;
};
export type Brief = {
  id: string;
  text: string;
  status: "starting" | "generating" | "draft" | "failed" | "submission_unknown";
  /** "import" when the draft came from a workflow file. */
  source?: "import";
  message: string;
  draft: {
    roles: BriefRole[];
    steps: BriefStep[];
    assumptions: string[];
    preferences?: BriefPreference[];
  } | null;
  bindings: Record<string, string>;
};
export type TraceStep = {
  step: number;
  device_id: string;
  operation: Operation;
  sample?: string;
  site?: string | null;
  location: string | null;
  vessel: Vessel | null;
  volume_ul: number;
  temperature_c: number;
  mixed: boolean;
  elapsed_s: number;
  consumables: Record<string, Record<string, number>>;
  measurement: {
    kind: string;
    temperature_c: number;
    volume_ul: number;
    mixed: boolean;
  } | null;
  motion?: MotionSummary;
};
export type InstrumentRun = {
  id: string;
  created_at: string;
  evidence: "synthetic";
  connector: "in_process_mock" | "mock_sila2";
  steps: Step[];
  twins: { id: string; name: string; revision: number; spec?: TwinSpec }[];
  trace: TraceStep[];
  status: "completed";
};
export type InstrumentCatalog = {
  version: number;
  twins: Twin[];
  steps: Step[];
  runs: InstrumentRun[];
  layout: Layout | null;
  brief: Brief | null;
  constraints: Constraint[];
  /** Workflows kept for this bench besides the current one. */
  bench_workflows?: BenchWorkflow[];
  templates: Record<string, TwinSpec>;
  simready: Record<string, SimReadyAsset>;
  astra_available: boolean;
  /** Whether a described workflow can be drafted here, and by which model. */
  brief_available?: boolean;
  refine_available?: boolean;
  brief_model?: string;
  real_available: boolean;
  real_reason: string;
};
export type ConnectorPackage = {
  device_id: string;
  evidence: "synthetic";
  files: Record<string, string>;
};

export type BenchWorkflow = { id: string; name: string; steps: Step[] };
export type ToleranceAxis = "x" | "z" | "yaw" | "height";
/** One replanning of a misplaced layout. */
export type ToleranceCheck = {
  ok: boolean;
  cause: string | null;
  step: number | null;
  transfer: string | null;
  blocker: string | null;
  link: string | null;
  message?: string | null;
};
export type ToleranceTask = Record<string, unknown> & { task: number };
export type ToleranceSide = {
  band: number;
  saturated: boolean;
  limit: ToleranceCheck | null;
  workflow: number;
} | null;
export type ToleranceBinding = ToleranceCheck & {
  axis: ToleranceAxis;
  sign: -1 | 1;
  band: number;
};
export type ToleranceRow = {
  twin_id: string;
  name: string;
  role: "station" | "spare" | "arm";
  xz_m: number | null;
  yaw_deg: number | null;
  height_m: number | null;
  sides: Partial<
    Record<ToleranceAxis, { minus: ToleranceSide; plus: ToleranceSide }>
  >;
  binding: ToleranceBinding | null;
  complete: boolean;
  tool?: {
    longer_m: number | null;
    shorter_m: number | null;
    lateral_m: number | null;
  };
};
export type TolerancePoint = {
  level_m: number;
  level_deg: number;
  runs: number;
  passed: number;
  skipped: number;
  drawn: number;
  rate: number | null;
  lower: number | null;
  by_workflow: (number | null)[];
  causes: Record<string, number>;
};
export type ToleranceAdvice = {
  level_m: number;
  level_deg: number;
  rate: number;
  lower: number;
  runs: number;
  needed: number;
} | null;
/** Allowed error per axis, [toward minus, toward plus]; null until measured. */
export type ToleranceBands = Record<
  string,
  Partial<Record<ToleranceAxis, [number | null, number | null]>>
>;
export type ToleranceSummary = {
  evidence: "synthetic";
  workflows: string[];
  target: number;
  samples: number;
  requirements: ToleranceRow[];
  arms: ToleranceRow[];
  per_workflow: {
    name: string;
    xz_m: number | null;
    binding:
      (ToleranceCheck & { name: string; axis: string; sign: number }) | null;
  }[];
  curves: Record<
    "instruments" | "arm",
    { points: TolerancePoint[]; advice: ToleranceAdvice }
  >;
  overlay: ToleranceBands;
  capture_m: number;
};
export type ToleranceChunk = {
  total: number;
  next: number | null;
  trail: ToleranceCheck[];
  done: ToleranceTask[];
  checked: number;
  summary: ToleranceSummary;
};
