import { useState } from "react";
import { Cpu, User } from "lucide-react";
import type { Session } from "./types";
import { LEVERS, RULE, ruleDecision, type Lever } from "./decide";
import c from "./DecideCard.module.css";

/** After a run, the learner commits to a next change, then sees what a fixed rule picks. */
export default function DecideCard({ session }: { session: Session }) {
  // Attempts grow on every reset, so a new run asks again.
  const run = `${session.id}:${session.attempts.length}`;
  const [pick, setPick] = useState<{ run: string; lever: Lever } | null>(null);
  const chosen = pick?.run === run ? pick.lever : null;
  const rule = ruleDecision(session);
  return (
    <section className={c.card} aria-labelledby="decide-title">
      <h3 id="decide-title">What changes in the next run?</h3>
      <div className={c.levers} role="group" aria-label="Your next change">
        {(Object.keys(LEVERS) as Lever[]).map((lever) => (
          <button
            key={lever}
            aria-pressed={chosen === lever}
            disabled={chosen !== null}
            onClick={() => setPick({ run, lever })}
          >
            {LEVERS[lever]}
          </button>
        ))}
      </div>
      {chosen && (
        <>
          <div className={c.compare}>
            <div role="group" aria-label="Your call">
              <span>
                <User size={14} /> You
              </span>
              <strong>{LEVERS[chosen]}</strong>
            </div>
            <div role="group" aria-label="The rule's call">
              <span>
                <Cpu size={14} /> Rule
              </span>
              <strong>{LEVERS[rule.lever]}</strong>
              <p>{rule.reason}</p>
            </div>
          </div>
          <p className={c.verdict}>
            {chosen === rule.lever
              ? "Same call."
              : "Different calls. Weigh the observations below."}
          </p>
          <details className={c.details}>
            <summary>How the rule decides</summary>
            <ol>
              {RULE.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ol>
            <p>
              Written down as rules, this decision can run without you. A
              self-driving lab goes further: a model picks the next experiment
              from every run so far, and people set the goal and the limits.
            </p>
          </details>
        </>
      )}
    </section>
  );
}
