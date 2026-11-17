export type Config = {
  auth: "local" | "cognito" | "disabled";
  issuer: string;
  client_id: string;
  cognito_domain: string;
  self_signup_email_domains?: string[];
  app_url: string;
  engines: { matterix: { available: boolean; reason: string } };
};
export type Profile = {
  name: string;
  experience: "new" | "some" | "experienced";
  onboarded: boolean;
};
export type Place =
  "deck" | "heater_shaker" | "temperature" | "reader" | "stacker";
export type DeckModule = Exclude<Place, "deck"> | "gripper";
export type Action = {
  kind:
    | "pickup"
    | "aspirate"
    | "dispense"
    | "drop"
    | "move"
    | "heat"
    | "shake"
    | "read";
  well: "stock" | "A1" | "A2" | "A3";
  volume: number;
  /** Where a move takes the sample plate. */
  to?: Place;
  /** °C for heat, rpm for shake. */
  value?: number;
  seconds?: number;
};
export type Experiment = {
  title: string;
  course_id: "flex-foundations" | "flex-first-transfer" | "workflow-sandbox";
  instrument?: "flex" | "ot2";
  transfer_volume?: number;
  layout: Record<string, string>;
  source_volume: number;
  diluent_volume: number;
  actions: Action[];
  /** Deck modules of a Workflow Studio design. */
  modules?: DeckModule[];
};
export type Assessment = {
  scope?: "lesson-goal" | "model-checks";
  passed: boolean;
  checks: { label: string; passed: boolean }[];
  concentrations: Record<string, number>;
};
export type RunEvent = {
  step: number;
  level: "error" | "success";
  code: string;
  message: string;
  hint: string;
  /** State after the step; absent on events saved before replay existed. */
  state?: TeachingState;
};
export type TeachingState = {
  wells: Record<string, { volume: number; solute: number }>;
  pipette: { volume: number; solute: number; tip: boolean; used: boolean };
  tips_used: number;
  tips_discarded: number;
  waste_volume: number;
  /** Present once a design has deck modules. */
  plate?: { at: Place; temperature: number | null; shaken: boolean };
  readings?: { step: number; wells: Record<string, number> }[];
};
export type Session = {
  remote_active_run?: string | null;
  id: string;
  version: number;
  created_at: string;
  experiment: Experiment;
  engine: "teaching";
  evidence: "synthetic";
  status: "draft" | "running" | "paused" | "faulted" | "completed";
  cursor: number;
  state: TeachingState;
  events: RunEvent[];
  assessment: Assessment | null;
  attempts: {
    status: string;
    steps: number;
    assessment: Assessment | null;
    last_event: RunEvent | null;
  }[];
  learning?: LearningProgress;
  readiness?: {
    ready: boolean;
    checks: { id: string; label: string; passed: boolean }[];
  };
  lesson_outcome?: {
    practice_completed: boolean;
    understanding_demonstrated: boolean;
    evidence: "synthetic";
  };
};
export type LearningProgress = {
  phase: "orient" | "prepare" | "predict" | "run" | "reflect";
  visited: string[];
  checks: string[];
  location_answer: "" | "slot" | "well";
  prediction: { source: number; tip: number; target: number } | null;
  reflection: "" | "source_to_tip" | "source_to_target" | "target_to_tip";
};
export type Course = {
  id: string;
  title: string;
  subtitle: string;
  duration: string;
  level: string;
  objectives: string[];
  model_note: string;
};
