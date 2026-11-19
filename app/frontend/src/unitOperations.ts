// Unit operations a workflow is composed from, independent of any one instrument.
// Each one compiles to a connector command where the contract has one; the workcell's
// own twins decide whether it can run here, and on a mock or a lab connector.
import type { Operation, Twin } from "./instrumentTypes";

export type Family =
  "Move" | "Combine" | "Temperature" | "Measure" | "Separate" | "Time";
export const families: Family[] = [
  "Move",
  "Combine",
  "Temperature",
  "Measure",
  "Separate",
  "Time",
];

export type UnitOperation = {
  id: string;
  symbol: string;
  name: string;
  family: Family;
  /** The connector command it becomes; null while the contract has none. */
  command: Operation | null;
  value?: number;
};

export const unitOperations: UnitOperation[] = [
  {
    id: "load",
    symbol: "Ld",
    name: "Load",
    family: "Move",
    command: "load",
    value: 100,
  },
  {
    id: "transfer",
    symbol: "Tr",
    name: "Transfer",
    family: "Move",
    command: "transfer",
  },
  {
    id: "aliquot",
    symbol: "Al",
    name: "Aliquot",
    family: "Move",
    command: null,
  },
  {
    id: "mix",
    symbol: "Mx",
    name: "Mix",
    family: "Combine",
    command: "mix",
    value: 10,
  },
  {
    id: "shake",
    symbol: "Sh",
    name: "Shake",
    family: "Combine",
    command: "mix",
    value: 60,
  },
  {
    id: "vortex",
    symbol: "Vx",
    name: "Vortex",
    family: "Combine",
    command: "mix",
    value: 5,
  },
  {
    id: "heat",
    symbol: "Ht",
    name: "Heat",
    family: "Temperature",
    command: "heat",
    value: 65,
  },
  {
    id: "incubate",
    symbol: "In",
    name: "Incubate",
    family: "Temperature",
    command: "heat",
    value: 37,
  },
  {
    id: "cool",
    symbol: "Cl",
    name: "Cool",
    family: "Temperature",
    command: "heat",
    value: 4,
  },
  {
    id: "cycle",
    symbol: "Tc",
    name: "Thermal cycle",
    family: "Temperature",
    command: null,
  },
  {
    id: "read",
    symbol: "Rd",
    name: "Read",
    family: "Measure",
    command: "read",
  },
  {
    id: "absorbance",
    symbol: "Ab",
    name: "Absorbance",
    family: "Measure",
    command: "read",
  },
  {
    id: "fluorescence",
    symbol: "Fl",
    name: "Fluorescence",
    family: "Measure",
    command: "read",
  },
  {
    id: "weigh",
    symbol: "Wg",
    name: "Weigh",
    family: "Measure",
    command: null,
  },
  {
    id: "centrifuge",
    symbol: "Cf",
    name: "Centrifuge",
    family: "Separate",
    command: null,
  },
  {
    id: "filter",
    symbol: "Fi",
    name: "Filter",
    family: "Separate",
    command: null,
  },
  {
    id: "magnet",
    symbol: "Mg",
    name: "Magnetic separation",
    family: "Separate",
    command: null,
  },
  {
    id: "wait",
    symbol: "Wt",
    name: "Wait",
    family: "Time",
    command: "wait",
    value: 60,
  },
];

/**
 * How far a unit operation runs in this workcell: on a lab connector, on a mock
 * connector, nowhere here yet, or not at all until the contract has a command.
 */
export type Reach =
  | { kind: "lab" | "mock"; device: Twin }
  | { kind: "absent" | "stub"; reason: string };

const fits = (twin: Twin, op: UnitOperation) => {
  const { limits } = twin.spec!;
  if (op.command === "heat" && op.value !== undefined)
    return limits.min_temp_c <= op.value && op.value <= limits.max_temp_c;
  if ((op.command === "mix" || op.command === "wait") && op.value !== undefined)
    return op.value <= limits.max_duration_s;
  return true;
};

export function reach(op: UnitOperation, twins: Twin[]): Reach {
  if (!op.command) return { kind: "stub", reason: "No connector command yet" };
  const able = twins.filter((t) => t.spec!.operations.includes(op.command!));
  if (!able.length) return { kind: "absent", reason: "No instrument here" };
  const within = able.filter((t) => fits(t, op));
  if (!within.length)
    return {
      kind: "absent",
      reason:
        op.command === "heat" ? `None reaches ${op.value} °C` : "Too long here",
    };
  // A lab connector, where the learner has one, before the mock.
  const lab = within.find((t) => t.mode === "real");
  return lab
    ? { kind: "lab", device: lab }
    : { kind: "mock", device: within[0] };
}
