import type { Stage } from "./skills";
// What Meet the instruments and the teaching pages show of a cloud lab or AC twin.
import type { Mesh, Operation } from "./instrumentTypes";
import type { Anatomy, Mass } from "./TwinAnatomy";
import type { Motion } from "./twinMotion";

export type LabId = "ecl" | "ac";
export type Lab = {
  id: LabId;
  name: string;
  provider: string;
  source: string;
  retrieved: string;
  sections: string[];
};
export type Instrument = {
  id: string;
  lab: LabId;
  /** The provider's page for this instrument: the cloud lab's list, or its documentation. */
  url: string;
  name: string;
  section: string;
  experiment: string;
  published: string;
  narrowed: string | null;
  operations: Operation[];
  /** The parts of an experiment the instrument can take. */
  stages: Stage[];
  holds: { vessel: string; max_volume_ul: number };
  slots: number;
  limits: { min_temp_c: number; max_temp_c: number; max_duration_s: number };
  consumables: { name: string; stock: number }[];
  size_m: [number, number, number];
  access: "top" | "front";
  level_m: number | null;
  opening: {
    face: "front" | "left" | "right";
    start: number;
    end: number;
  } | null;
  drawer_m: number | null;
  model_size_m: [number, number, number] | null;
  /** The drawn stand-in's documented mass; `basis` says where it comes from. */
  mass_kg: (Mass & { basis: string }) | null;
  layout_model: string | null;
  geometry_basis: Record<string, string>;
  stand_in: string | null;
  mesh: Mesh | null;
  attribution: string;
  does: string;
  steps: {
    operation: Operation;
    verb: string;
    says: string;
    state: string | null;
  }[];
  motion: Motion | null;
  anatomy: Anatomy | null;
  in_workflow: boolean;
  /** Slot names, and a first workflow that uses every action once. */
  sites: string[];
  starter: {
    operation: Operation;
    sample: string;
    value: number;
    slot: string;
  }[];
};
export type Overview = {
  provider: string;
  source: string;
  retrieved: string;
  sections: string[];
  labs: Lab[];
  instruments: Instrument[];
};

export const BASIS_NAMES: Record<string, string> = {
  size: "Size",
  access: "Loading face",
  level_m: "Loading height",
  opening: "Opening",
  drawer_m: "Drawer",
  sites: "Slot",
};
export const CAN: Record<Operation, string> = {
  load: "Load",
  transfer: "Transfer",
  mix: "Mix",
  heat: "Heat",
  read: "Read",
  wait: "Wait",
};
export const volume = (ul: number) =>
  ul >= 1000 ? `${(ul / 1000).toLocaleString()} mL` : `${ul} µL`;

/** Where a geometry value comes from, in a few words; the full basis sits under Sources. */
export const basisLabel = (basis: string | undefined, item: Instrument) => {
  const kind = basis?.split(":")[0];
  if (kind === "datasheet") return `${item.layout_model} datasheet`;
  if (kind === "manufacturer")
    return `manufacturer figure for a comparable ${item.stand_in}`;
  if (kind === "engineering_assumption")
    return `ChemLab-Assets estimate for a comparable ${item.stand_in}`;
  if (kind === "footprint") return `footprint of a comparable ${item.stand_in}`;
  if (basis === "unset") return "not published";
  return "Academy estimate";
};
/** A figure's own source, where it differs from the one the row ends with. */
export const own = (key: string, item: Instrument) => {
  const label = basisLabel(item.geometry_basis[key], item);
  return label === basisLabel(item.geometry_basis.access, item)
    ? ""
    : ` (${label})`;
};
export const kilograms = (m: Mass) =>
  `${m.range ? `${m.range[0]}–${m.range[1]}` : m.value} kg`;
export const metres = (v: number[]) =>
  `${v.map((x) => x.toFixed(2)).join(" × ")} m`;
/** Where along the front a plate goes in, from the open part of that face. */
export const part = (opening: Instrument["opening"]) => {
  if (!opening || opening.face !== "front") return "";
  const middle = (opening.start + opening.end) / 2;
  return middle < 0.4 ? ", left" : middle > 0.6 ? ", right" : "";
};
export const sourceUrl = (basis: string) =>
  basis.match(/https?:\/\/[^\s,]+/)?.[0];
