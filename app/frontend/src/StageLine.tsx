import { STAGES, STAGE_LABEL, type Stage } from "./skills";
import s from "./SkillTree.module.css";

export type LineStep = { stage: Stage; lit: boolean; title: string };

/** A workflow as a line through the three parts of an experiment. */
export default function StageLine({
  steps,
  loop,
  dotRef,
}: {
  steps: LineStep[];
  /** The result decides the next sample, so the line closes on itself. */
  loop?: boolean;
  dotRef?: (index: number, node: HTMLElement | null) => void;
}) {
  const label = STAGES.map((stage) => {
    const n = steps.filter((step) => step.stage === stage).length;
    return n ? `${STAGE_LABEL[stage]} ${n}` : "";
  })
    .filter(Boolean)
    .join(", ");
  return (
    <span
      className={s.line}
      role="img"
      aria-label={`${label}${loop ? ", then decide the next sample" : ""}`}
      data-loop={loop || undefined}
    >
      {STAGES.map((stage) => (
        <span key={stage} className={s.lane} data-stage={stage}>
          {steps.map(
            (step, index) =>
              step.stage === stage && (
                <i
                  key={index}
                  ref={(node) => dotRef?.(index, node)}
                  className={s.dot}
                  data-lit={step.lit || undefined}
                  title={step.title}
                />
              ),
          )}
        </span>
      ))}
    </span>
  );
}
