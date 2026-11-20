import { useState } from "react";
import { ArrowRight, Check, X } from "lucide-react";
import s from "./SimGuide.module.css";

type Stage = "predict" | "run" | "check";
type Prediction = { a1: string; tips: string };
const KEY = "lab.sim.prediction";
const read = (): Prediction => {
  try {
    return {
      a1: "",
      tips: "",
      ...JSON.parse(sessionStorage.getItem(KEY) ?? "{}"),
    };
  } catch {
    return { a1: "", tips: "" };
  }
};

/** Where the learner is in a simulation, and a prediction to test against it. */
export function SimGuide({
  steps,
  running,
  observed,
}: {
  steps: number;
  running: boolean;
  /** What the run reported, once it has finished. */
  observed: { a1: number | undefined; tips: number | undefined } | null;
}) {
  const [guess, setGuess] = useState(read);
  const set = (patch: Partial<Prediction>) => {
    const next = { ...guess, ...patch };
    setGuess(next);
    try {
      sessionStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      // The prediction then lasts until the page reloads.
    }
  };
  const predicted = guess.a1 !== "" && guess.tips !== "";
  const stage: Stage = observed
    ? "check"
    : running || predicted
      ? "run"
      : "predict";
  const order: Stage[] = ["predict", "run", "check"];
  const reached = (item: Stage) => order.indexOf(item) <= order.indexOf(stage);
  const match = (want: string, got: number | undefined) =>
    got !== undefined && Math.abs(Number(want) - got) < 0.01;
  return (
    <section className={s.guide} aria-label="Simulation steps">
      <ol className={s.rail}>
        <li data-done>
          <span>
            <Check size={13} />
          </span>
          <strong>Plan</strong>
          <small>{steps} steps · 4 vials into A1</small>
        </li>
        {(
          [
            ["predict", "Predict", "What will the twin report?"],
            ["run", "Run", "Watch each step on the twin"],
            ["check", "Check", "Compare with your prediction"],
          ] as const
        ).map(([id, title, detail], i) => (
          <li
            key={id}
            data-current={stage === id || undefined}
            data-done={(reached(id) && stage !== id) || undefined}
            aria-current={stage === id ? "step" : undefined}
          >
            <span>
              {reached(id) && stage !== id ? <Check size={13} /> : i + 2}
            </span>
            <strong>{title}</strong>
            <small>{detail}</small>
          </li>
        ))}
      </ol>
      <form className={s.predict} onSubmit={(e) => e.preventDefault()}>
        <label>
          Mixture in A1
          <span>
            <input
              type="number"
              min="0"
              step="any"
              inputMode="decimal"
              value={guess.a1}
              onChange={(e) => set({ a1: e.target.value })}
            />
            µL
          </span>
        </label>
        <label>
          Tips used
          <span>
            <input
              type="number"
              min="0"
              step="1"
              inputMode="numeric"
              value={guess.tips}
              onChange={(e) => set({ tips: e.target.value })}
            />
          </span>
        </label>
        {observed && predicted ? (
          <p className={s.verdict} role="status">
            {[
              ["A1", match(guess.a1, observed.a1), `${observed.a1 ?? "—"} µL`],
              [
                "Tips",
                match(guess.tips, observed.tips),
                `${observed.tips ?? "—"}`,
              ],
            ].map(([name, ok, got]) => (
              <span key={name as string} data-ok={ok || undefined}>
                {ok ? <Check size={13} /> : <X size={13} />}
                {name} · twin reported {got}
              </span>
            ))}
          </p>
        ) : (
          <p className={s.hint}>
            {predicted
              ? "Saved. Run the experiment to test it."
              : "Each transfer moves 10 µL with a fresh tip."}
          </p>
        )}
      </form>
    </section>
  );
}

/** Other runs on a teaching twin, for after this one. */
export function MoreTwins({
  onNavigate,
}: {
  onNavigate: (target: string) => void;
}) {
  return (
    <section className={s.more} aria-labelledby="more-twins">
      <h2 id="more-twins">More to run on a twin</h2>
      <div>
        {(
          [
            ["learn/beginner", "Set up a deck and run a transfer"],
            ["learn/intermediate", "Route a sample through a published lab"],
            ["drills", "Respond to a fault mid-run"],
            ["learn/advanced", "Send unit operations through connectors"],
          ] as const
        ).map(([target, title]) => (
          <button key={target} onClick={() => onNavigate(target)}>
            {title}
            <ArrowRight size={16} />
          </button>
        ))}
      </div>
    </section>
  );
}
