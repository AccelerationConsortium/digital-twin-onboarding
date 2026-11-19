import type { Session } from "./types";

/** The levers a learner can change between runs of the dilution lesson. */
export const LEVERS = {
  stock: "Starting stock",
  diluent: "Diluent volume",
  volumes: "Transfer volumes",
  steps: "Steps or order",
  tips: "Tip handling",
  repeat: "Repeat unchanged",
} as const;
export type Lever = keyof typeof LEVERS;

/** The rule, in the order it is checked. Shown to learners as written. */
export const RULE = [
  "A fault names its lever: an empty stock means more stock, a tip problem means tip handling, a volume problem means transfer volumes.",
  "A 1:2 step needs each transfer to equal the diluent already in the well.",
  "If volumes match but a concentration misses, the steps or their order are wrong.",
  "If only the final tip check fails, fix tip handling.",
  "If every check passes, repeat unchanged to show the result holds.",
];

const TIP_FAULTS = new Set([
  "no_tip",
  "tip_attached",
  "used_tip",
  "tips_empty",
]);

/** A fixed, explainable choice of the next lever from one finished run. */
export function ruleDecision(session: Session): {
  lever: Lever;
  reason: string;
} {
  const { experiment, assessment } = session;
  const fault = session.events.find((e) => e.level === "error");
  const transfers = experiment.actions.filter(
    (a) => a.kind === "dispense" && a.well !== "stock",
  );
  const largest = Math.max(0, ...transfers.map((a) => a.volume));
  if (fault) {
    const action = experiment.actions[fault.step - 1];
    if (TIP_FAULTS.has(fault.code))
      return { lever: "tips", reason: `Step ${fault.step} failed on the tip.` };
    if (fault.code === "source_empty" && action?.well === "stock")
      return {
        lever: "stock",
        reason: `The stock ran out at step ${fault.step}.`,
      };
    if (fault.code === "overflow" && experiment.diluent_volume > largest)
      return {
        lever: "diluent",
        reason: `${experiment.diluent_volume} µL of diluent leaves no room for a transfer.`,
      };
    if (
      ["source_empty", "capacity", "overflow", "insufficient_liquid"].includes(
        fault.code,
      )
    )
      return {
        lever: "volumes",
        reason: `Step ${fault.step} failed on a volume.`,
      };
    return {
      lever: "steps",
      reason: `Step ${fault.step} cannot run in this order.`,
    };
  }
  const missed = assessment?.checks.filter((c) => !c.passed) ?? [];
  if (!missed.length)
    return {
      lever: "repeat",
      reason: "Every check passed. A second identical run shows it holds.",
    };
  const unequal = transfers.find((a) => a.volume !== experiment.diluent_volume);
  if (unequal && missed.some((c) => c.label.includes("concentration")))
    return {
      lever: "volumes",
      reason: `A ${unequal.volume} µL transfer into ${experiment.diluent_volume} µL of diluent is not a 1:2 step.`,
    };
  if (missed.some((c) => c.label.includes("concentration")))
    return {
      lever: "steps",
      reason: "Volumes match, yet a concentration missed its target.",
    };
  return {
    lever: "tips",
    reason: "The pipette finished with a tip or liquid still attached.",
  };
}
