import type { WorkflowId } from "../discoveryContent";
import type { Operation } from "../instrumentTypes";

/* ---------- Beginner: a deck you set up yourself ---------- */

export type Robot = "flex" | "ot2";
export type DeckItemId =
  "tips" | "stock" | "plate" | "heater" | "temperature" | "thermocycler";

export const ROBOTS: Record<
  Robot,
  { name: string; rows: string[][]; waste: string; wasteName: string }
> = {
  // Drawn back to front, as you face the robot.
  flex: {
    name: "Opentrons Flex",
    rows: [
      ["A1", "A2", "A3", "A4"],
      ["B1", "B2", "B3", "B4"],
      ["C1", "C2", "C3", "C4"],
      ["D1", "D2", "D3", "D4"],
    ],
    waste: "D3",
    wasteName: "Waste chute",
  },
  ot2: {
    name: "Opentrons OT-2",
    rows: [
      ["10", "11", "12"],
      ["7", "8", "9"],
      ["4", "5", "6"],
      ["1", "2", "3"],
    ],
    waste: "12",
    wasteName: "Fixed trash",
  },
};

export const DECK_ITEMS: Record<
  DeckItemId,
  { name: string; short: string; kind: "labware" | "module"; purpose: string }
> = {
  tips: {
    name: "Tip rack",
    short: "Tips",
    kind: "labware",
    purpose:
      "Disposable tips. The pipette picks one up before it touches any liquid.",
  },
  stock: {
    name: "Source container",
    short: "Source",
    kind: "labware",
    purpose: "Holds the liquid you transfer from. The run starts here.",
  },
  plate: {
    name: "Target plate",
    short: "Plate",
    kind: "labware",
    purpose:
      "Receives the liquid. The plate takes one slot; each of its wells has its own address, such as A1.",
  },
  heater: {
    name: "Heater-Shaker",
    short: "Heater-Shaker",
    kind: "module",
    purpose:
      "Heats and shakes one plate. It needs clearance on its sides, so it only fits the outer columns.",
  },
  temperature: {
    name: "Temperature module",
    short: "Temp module",
    kind: "module",
    purpose: "Holds samples cold or warm while the pipette works on them.",
  },
  thermocycler: {
    name: "Thermocycler",
    short: "Thermocycler",
    kind: "module",
    purpose:
      "Cycles a plate through temperatures under a lid. It is large and always sits in the back-left corner.",
  },
};

/** Slots a multi-slot module covers, keyed by the one slot it may anchor in. */
export const COVERS: Record<Robot, Partial<Record<DeckItemId, string[]>>> = {
  flex: { thermocycler: ["A1", "B1"] },
  ot2: { thermocycler: ["7", "8", "10", "11"] },
};

/** Why an item may not sit in a slot, or null when it may. */
export function placementIssue(
  robot: Robot,
  item: DeckItemId,
  slot: string,
): string | null {
  const deck = ROBOTS[robot];
  if (slot === deck.waste)
    return `${slot} is the ${deck.wasteName.toLowerCase()}. It cannot be moved.`;
  const thermo = COVERS[robot].thermocycler!;
  if (item === "thermocycler")
    return slot === thermo[0]
      ? null
      : `The thermocycler only fits at ${thermo[0]}, where it covers ${thermo.join(" + ")}.`;
  if (robot === "flex") {
    const column = slot.slice(1);
    if (column === "4" && DECK_ITEMS[item].kind === "module")
      return "Column 4 is a staging area. Modules cannot go there.";
    if ((item === "heater" || item === "temperature") && column === "2")
      return `On Flex the ${DECK_ITEMS[item].name.toLowerCase()} goes in column 1 or 3.`;
  } else if (
    item === "heater" &&
    !["1", "3", "4", "6", "7", "10"].includes(slot)
  )
    return "On OT-2 the Heater-Shaker goes in slot 1, 3, 4, 6, 7 or 10.";
  return null;
}

/** Column 4 on Flex is reached by the gripper, not the pipette. */
export const pipetteReaches = (robot: Robot, slot: string) =>
  !(robot === "flex" && slot.endsWith("4"));

/* ---------- Intermediate: published self-driving lab layouts ---------- */

export type StationKind =
  "storage" | "liquid" | "process" | "measure" | "transport" | "compute";

export type Station = {
  id: string;
  name: string;
  kind: StationKind;
  /** Teaching position on the 8 × 5 floor grid. */
  reference: [number, number];
  /** What happens here, in the paper's words where possible. */
  does: string;
};

export type FloorLab = {
  workflow: WorkflowId;
  name: string;
  /** How samples move between physical stations. */
  mover: string;
  /** Stations that must sit within reach of this one (an arm-centred cell). */
  hub?: { id: string; reach: number };
  stations: Station[];
  /** The sample's route, in the paper's order; the last stop feeds back to the first. */
  route: string[];
};

export const FLOOR = { cols: 8, rows: 5 };

export const FLOOR_LABS: FloorLab[] = [
  {
    workflow: "clio",
    name: "Clio + Dragonfly",
    mover: "Pumps and fluid lines carry each mixture",
    stations: [
      {
        id: "stocks",
        name: "Salt and solvent stocks",
        kind: "storage",
        reference: [1, 1],
        does: "Holds the salt and three solvents the recipes draw from.",
      },
      {
        id: "clio",
        name: "Clio dispensing",
        kind: "liquid",
        reference: [3, 1],
        does: "Blends a salt and solvents to the requested composition.",
      },
      {
        id: "conductivity",
        name: "Conductivity cell",
        kind: "measure",
        reference: [5, 1],
        does: "Measures ionic conductivity of the new electrolyte.",
      },
      {
        id: "dragonfly",
        name: "Dragonfly optimizer",
        kind: "compute",
        reference: [5, 3],
        does: "Bayesian optimization picks the next composition.",
      },
    ],
    route: ["stocks", "clio", "conductivity", "dragonfly"],
  },
  {
    workflow: "ada",
    name: "Ada",
    mover: "A robot arm at the centre of the cell",
    hub: { id: "arm", reach: 2 },
    stations: [
      {
        id: "arm",
        name: "Robot arm",
        kind: "transport",
        reference: [3, 2],
        does: "Moves vials and substrates between every station in the cell.",
      },
      {
        id: "precursors",
        name: "Precursor formulation",
        kind: "liquid",
        reference: [1, 1],
        does: "Combines precursor formulations for the next film.",
      },
      {
        id: "spin",
        name: "Spin coater",
        kind: "process",
        reference: [2, 4],
        does: "Spreads the solution into a thin film.",
      },
      {
        id: "anneal",
        name: "Thermal processing",
        kind: "process",
        reference: [4, 4],
        does: "Heats the film to process it.",
      },
      {
        id: "optical",
        name: "Optical characterization",
        kind: "measure",
        reference: [5, 1],
        does: "Images the film and measures its optical response.",
      },
      {
        id: "electrical",
        name: "Electrical characterization",
        kind: "measure",
        reference: [5, 3],
        does: "Measures the film's electrical performance.",
      },
      {
        id: "chemos",
        name: "ChemOS + Phoenics",
        kind: "compute",
        reference: [7, 2],
        does: "Proposes the next formulation and processing conditions.",
      },
    ],
    route: ["precursors", "spin", "anneal", "optical", "electrical", "chemos"],
  },
  {
    workflow: "sonication",
    name: "OT-2 + Jubilee",
    mover: "Sample plates handed between two platforms",
    stations: [
      {
        id: "ot2",
        name: "OT-2 liquid handler",
        kind: "liquid",
        reference: [1, 2],
        does: "Prepares the precursor library for nanocrystal synthesis.",
      },
      {
        id: "jubilee",
        name: "Jubilee with ultrasound tool",
        kind: "process",
        reference: [3, 2],
        does: "A tool-changing gantry brings the ultrasound probe to each sample.",
      },
      {
        id: "spectra",
        name: "Optical spectroscopy",
        kind: "measure",
        reference: [5, 2],
        does: "Characterizes optical spectra across the sample library.",
      },
      {
        id: "analysis",
        name: "Screening analysis",
        kind: "compute",
        reference: [5, 4],
        does: "Compares formulation conditions and their effects.",
      },
    ],
    route: ["ot2", "jubilee", "spectra", "analysis"],
  },
  {
    workflow: "rainbow",
    name: "Rainbow",
    mover: "A robot arm moves plates between robots",
    hub: { id: "arm", reach: 2 },
    stations: [
      {
        id: "arm",
        name: "Robot arm",
        kind: "transport",
        reference: [3, 2],
        does: "Carries plates between the liquid handler and the reader.",
      },
      {
        id: "ot2",
        name: "OT-2 liquid handler",
        kind: "liquid",
        reference: [1, 2],
        does: "Prepares nanocrystal formulations in solution.",
      },
      {
        id: "reader",
        name: "Plate reader",
        kind: "measure",
        reference: [5, 2],
        does: "Measures emission linewidth and a quantum-yield proxy.",
      },
      {
        id: "mobo",
        name: "Multi-objective optimizer",
        kind: "compute",
        reference: [5, 4],
        does: "Trades off brightness and linewidth at a target emission energy.",
      },
    ],
    route: ["ot2", "reader", "mobo"],
  },
  {
    workflow: "mobile",
    name: "Mobile robotic chemist",
    mover: "A mobile robot drives samples between stations",
    stations: [
      {
        id: "rack",
        name: "Sample rack",
        kind: "storage",
        reference: [0, 2],
        does: "Holds empty and finished sample vials.",
      },
      {
        id: "solids",
        name: "Solid dispensing",
        kind: "process",
        reference: [2, 0],
        does: "Weighs the candidate photocatalyst components into a vial.",
      },
      {
        id: "liquids",
        name: "Liquid dispensing",
        kind: "liquid",
        reference: [4, 0],
        does: "Adds the liquid components and seals the vial.",
      },
      {
        id: "light",
        name: "Illumination",
        kind: "process",
        reference: [6, 2],
        does: "Illuminates the mixture to drive hydrogen evolution.",
      },
      {
        id: "gc",
        name: "Gas analysis",
        kind: "measure",
        reference: [4, 4],
        does: "Measures the hydrogen produced.",
      },
      {
        id: "search",
        name: "Bayesian search",
        kind: "compute",
        reference: [2, 4],
        does: "Selects the next mixture to try.",
      },
    ],
    route: ["rack", "solids", "liquids", "light", "gc", "search"],
  },
  {
    workflow: "alab",
    name: "A-Lab",
    mover: "Robot arms move crucibles between stations",
    stations: [
      {
        id: "dosing",
        name: "Powder dosing and mixing",
        kind: "process",
        reference: [1, 1],
        does: "Doses and mixes precursor powders into a crucible.",
      },
      {
        id: "furnace",
        name: "Box furnaces",
        kind: "process",
        reference: [4, 1],
        does: "Heats the samples.",
      },
      {
        id: "xrd",
        name: "X-ray diffraction",
        kind: "measure",
        reference: [4, 3],
        does: "Prepares the product and measures its diffraction pattern.",
      },
      {
        id: "planner",
        name: "Recipe planner",
        kind: "compute",
        reference: [1, 3],
        does: "Literature-informed recipes and active learning revise the conditions.",
      },
    ],
    route: ["dosing", "furnace", "xrd", "planner"],
  },
];

/* ---------- Advanced: unit operations through connectors ---------- */

export type DeviceId =
  "flex" | "gripper" | "heater" | "reader" | "orchestrator";
export type Place = "flex" | "heater" | "reader";

export const DEVICES: Record<
  DeviceId,
  {
    name: string;
    connector: string | null;
    commands: Partial<Record<Operation, string>>;
    /** Where the plate must be for this device to act on it. */
    needs?: Place;
  }
> = {
  flex: {
    name: "Flex pipette",
    connector: "opentrons-flex · MotionControl",
    commands: {
      transfer: "aspirate(mount, volume, rate) → dispense(…)",
      mix: "aspirate(…) ⇄ dispense(…) × n",
    },
    needs: "flex",
  },
  gripper: {
    name: "Flex gripper",
    connector: "opentrons-flex · labware movement",
    commands: { load: "move_labware(plate, to)" },
  },
  heater: {
    name: "Heater-Shaker",
    connector: "heater-shaker connector",
    commands: {
      heat: "set_temperature(°C) · wait until reached",
      mix: "set_shake_speed(rpm, duration)",
    },
    needs: "heater",
  },
  reader: {
    name: "Plate reader",
    connector: "plate-reader connector",
    commands: { read: "read_absorbance(wavelength)" },
    needs: "reader",
  },
  orchestrator: {
    name: "Orchestrator",
    connector: null,
    commands: { wait: "timer(duration) · no device command" },
  },
};

export const PLACE_NAMES: Record<Place, string> = {
  flex: "Flex deck",
  heater: "Heater-Shaker",
  reader: "Plate reader",
};

export type ChainStep = {
  key: string;
  op: Operation;
  device: DeviceId;
  /** Where a load moves the plate. */
  to?: Place;
};

export const STARTER_CHAIN: Omit<ChainStep, "key">[] = [
  { op: "transfer", device: "flex" },
  { op: "load", device: "gripper", to: "heater" },
  { op: "heat", device: "heater" },
  { op: "wait", device: "orchestrator" },
  { op: "load", device: "gripper", to: "reader" },
  { op: "read", device: "reader" },
];

/** The devices that offer an operation, for its binding menu. */
export const devicesFor = (op: Operation) =>
  (Object.keys(DEVICES) as DeviceId[]).filter((id) => DEVICES[id].commands[op]);
