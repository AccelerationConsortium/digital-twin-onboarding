import type { Action, DeckModule, Experiment, Place } from "./types";

export type Instrument = "flex" | "ot2";
export type Starter =
  | "transfer"
  | "distribute"
  | "dilution"
  | "mix"
  | "incubate"
  | "move"
  | "read"
  | "blank";

export const INSTRUMENT_NAMES: Record<Instrument, string> = {
  flex: "Opentrons Flex",
  ot2: "Opentrons OT-2",
};

export const STUDIO_LAYOUTS: Record<
  Instrument,
  Record<"stock" | "plate" | "tips" | "waste", string>
> = {
  flex: { stock: "D1", plate: "D2", tips: "B1", waste: "D3" },
  ot2: { stock: "1", plate: "2", tips: "4", waste: "12" },
};

export const STARTERS: Record<
  Starter,
  {
    title: string;
    description: string;
    /** Instruments that have the modules the starter uses; all when left out. */
    instruments?: Instrument[];
  }
> = {
  transfer: {
    title: "Transfer",
    description: "Move 100 µL from a stock solution into one well.",
  },
  distribute: {
    title: "Distribute",
    description: "Aspirate once, then share 240 µL across three wells.",
  },
  dilution: {
    title: "Serial dilution",
    description:
      "Transfer through three wells with fresh tips and ideal mixing.",
  },
  mix: {
    title: "Shake to mix",
    description:
      "Transfer into a well, then shake the plate on the Heater-Shaker.",
  },
  incubate: {
    title: "Incubate",
    description: "Transfer into a well, then hold the plate at 37 °C.",
  },
  move: {
    title: "Move a plate",
    description: "Carry the plate onto a module and back to the deck.",
  },
  read: {
    title: "Read a plate",
    description: "Transfer into a well, then measure the plate in the reader.",
    instruments: ["flex"],
  },
  blank: {
    title: "Blank workflow",
    description: "Choose your own steps, volumes and destinations.",
  },
};

const action = (
  kind: Action["kind"],
  well: Action["well"] = "stock",
  volume = 100,
): Action => ({ kind, well, volume });
const plateTo = (to: Place): Action => ({ ...action("move"), to });

/** Module steps after one transfer, and the modules they need on the deck. */
const MODULE_STARTERS: Partial<
  Record<Starter, { modules: DeckModule[]; then: Action[] }>
> = {
  mix: {
    modules: ["heater_shaker"],
    then: [
      plateTo("heater_shaker"),
      { ...action("shake"), value: 1000, seconds: 30 },
      plateTo("deck"),
    ],
  },
  incubate: {
    modules: ["temperature"],
    then: [
      plateTo("temperature"),
      { ...action("heat"), value: 37 },
      plateTo("deck"),
    ],
  },
  move: {
    modules: ["temperature"],
    then: [plateTo("temperature"), plateTo("deck")],
  },
  read: {
    modules: ["reader"],
    then: [plateTo("reader"), action("read"), plateTo("deck")],
  },
};

export function makeStudioExperiment(
  instrument: Instrument,
  starter: Starter,
): Experiment {
  const transfer = [
    action("pickup"),
    action("aspirate"),
    action("dispense", "A1"),
    action("drop"),
  ];
  const withModules = MODULE_STARTERS[starter];
  const actions: Action[] = withModules
    ? [...transfer, ...withModules.then]
    : starter === "blank"
      ? []
      : starter === "distribute"
        ? [
            action("pickup"),
            action("aspirate", "stock", 240),
            ...(["A1", "A2", "A3"] as const).map((well) =>
              action("dispense", well, 80),
            ),
            action("drop"),
          ]
        : starter === "dilution"
          ? (["stock", "A1", "A2"] as const).flatMap((source, index) => [
              action("pickup"),
              action("aspirate", source),
              action("dispense", (["A1", "A2", "A3"] as const)[index]),
              action("drop"),
            ])
          : transfer;
  return {
    title: `${INSTRUMENT_NAMES[instrument]} · ${STARTERS[starter].title}`,
    course_id: "workflow-sandbox",
    instrument,
    layout: { ...STUDIO_LAYOUTS[instrument] },
    source_volume: 1000,
    diluent_volume: starter === "dilution" ? 100 : 0,
    actions,
    // The Flex moves the plate with its gripper; on the OT-2 it is moved by hand.
    ...(withModules && {
      modules: [
        ...(instrument === "flex" ? (["gripper"] as DeckModule[]) : []),
        ...withModules.modules,
      ],
    }),
  };
}

export const ACTION_LABELS: Record<Action["kind"], string> = {
  pickup: "Pick up tip",
  aspirate: "Aspirate",
  dispense: "Dispense",
  drop: "Discard tip",
  move: "Move plate",
  heat: "Set temperature",
  shake: "Shake",
  read: "Read plate",
};
export const PIPETTING: Action["kind"][] = [
  "pickup",
  "aspirate",
  "dispense",
  "drop",
];
export const MODULE_STEPS: Action["kind"][] = ["move", "heat", "shake", "read"];

/** Deck modules a design can add, and the slot each takes (as the backend places them). */
export const MODULES: Record<
  DeckModule,
  { name: string; slots: Partial<Record<Instrument, string>> }
> = {
  gripper: { name: "Gripper", slots: { flex: "" } },
  heater_shaker: { name: "Heater-Shaker", slots: { flex: "C1", ot2: "7" } },
  temperature: { name: "Temperature Module", slots: { flex: "A1", ot2: "6" } },
  reader: { name: "Plate reader", slots: { flex: "B3" } },
  stacker: { name: "Stacker", slots: { flex: "C3" } },
};
export const PLACE_NAMES: Record<Place, string> = {
  deck: "Deck",
  heater_shaker: "Heater-Shaker",
  temperature: "Temperature Module",
  reader: "Plate reader",
  stacker: "Stacker",
};

export const ACTION_HINTS: Record<Action["kind"], string> = {
  pickup: "Attach a fresh tip before drawing liquid.",
  aspirate: "Draw liquid from the selected container into the tip.",
  dispense: "Release liquid from the tip into the selected container.",
  drop: "Discard the tip and any liquid left inside it.",
  move: "Carry the sample plate to the deck or onto a module.",
  heat: "Set the module the plate is on to a temperature.",
  shake: "Shake the plate on the Heater-Shaker.",
  read: "Measure the plate inside the plate reader.",
};
