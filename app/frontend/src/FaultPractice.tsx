import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2, Plus } from "lucide-react";
import { api, json } from "./api";
import type { Session } from "./types";
import course from "./WorkflowCourse.module.css";
import s from "./FaultPractice.module.css";

type Exercise = {
  id: string;
  version: number;
  number: number;
  session_id: string;
  title: string;
  instrument: "flex" | "ot2";
  phase: "predict" | "diagnose" | "repair" | "done";
  prediction: {
    stops: boolean;
    step: number | null;
    after_run: boolean;
  } | null;
  choices: { cause: string; text: string }[];
  diagnosis: string | null;
  attempts: number;
  repaired: boolean;
  last_check: string | null;
  answer?: { cause: string; text: string; stops: boolean; step: number | null };
  prediction_correct?: boolean;
  diagnosis_correct?: boolean;
};
type Practice = {
  evidence: "synthetic";
  total: number;
  exercises: Exercise[];
  summary: {
    answered: number;
    predicted: number;
    /** Predictions made before running; later ones are not scored. */
    predicted_of: number;
    diagnosed: number;
    repaired: number;
    first_try: number;
  };
};
const INSTRUMENTS = { flex: "Opentrons Flex", ot2: "Opentrons OT-2" };

/** A working workflow with one mistake put in: predict, name the cause, repair. */
export default function FaultPractice({
  onBack,
  onOpen,
}: {
  onBack: () => void;
  onOpen: (session: Session) => void;
}) {
  const [practice, setPractice] = useState<Practice | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [stops, setStops] = useState<"" | "yes" | "no">("");
  const [step, setStep] = useState("");
  const [cause, setCause] = useState("");
  const alive = useRef(true);

  const load = async () => {
    try {
      const next = await api<Practice>("/practice");
      if (alive.current) setPractice(next);
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    }
  };
  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
    };
  }, []);

  // One request at a time; whatever happens, the saved record is read again.
  const send = async (path: string, init?: RequestInit) => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api<Exercise>(path, init);
      setStops("");
      setStep("");
      setCause("");
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    } finally {
      await load();
      if (alive.current) setBusy(false);
    }
  };
  const open = async (exercise: Exercise) => {
    try {
      onOpen(await api<Session>(`/sessions/${exercise.session_id}`));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const current = practice?.exercises.find((e) => e.phase !== "done");
  const finished = practice?.exercises.filter((e) => e.phase === "done") ?? [];
  const summary = practice?.summary;

  return (
    <div className={course.course}>
      <button className={course.back} onClick={onBack}>
        <ArrowLeft size={16} /> Back to learning lab
      </button>
      <header className={course.header}>
        <h1>Find the fault</h1>
        <p>
          Each workflow worked until one mistake was put in. Say what will
          happen before you run it, name the cause, then repair it.
        </p>
      </header>
      {error && (
        <p className={s.error} role="alert">
          {error}
        </p>
      )}
      {summary && summary.answered > 0 && (
        <dl className={s.score} aria-label="Your results">
          {summary.predicted_of > 0 && (
            <div>
              <dt>Predicted</dt>
              <dd>
                {summary.predicted} / {summary.predicted_of}
              </dd>
            </div>
          )}
          <div>
            <dt>Cause named</dt>
            <dd>
              {summary.diagnosed} / {summary.answered}
            </dd>
          </div>
          <div>
            <dt>Repaired</dt>
            <dd>
              {summary.repaired} / {summary.answered}
            </dd>
          </div>
          <div>
            <dt>Repaired first try</dt>
            <dd>{summary.first_try}</dd>
          </div>
        </dl>
      )}
      {practice && !current && (
        <button
          className={course.primary}
          disabled={busy}
          onClick={() => send("/practice", { method: "POST" })}
        >
          <Plus size={16} />{" "}
          {finished.length ? "Next workflow" : "Start with the first workflow"}
        </button>
      )}
      {current && (
        <section
          className={s.exercise}
          aria-label={`Workflow ${current.number}`}
        >
          <h2>
            {current.number} · {current.title}
          </h2>
          <p className={s.meta}>{INSTRUMENTS[current.instrument]}</p>
          <button className={course.secondary} onClick={() => open(current)}>
            Open the workflow <ArrowRight size={16} />
          </button>

          {current.phase === "predict" && (
            <form
              className={s.step}
              onSubmit={(e) => {
                e.preventDefault();
                void send(
                  `/practice/${current.id}/prediction`,
                  json(
                    {
                      version: current.version,
                      stops: stops === "no",
                      step: stops === "no" ? Number(step) : null,
                    },
                    "PUT",
                  ),
                );
              }}
            >
              <h3>1 · Before you run it</h3>
              <fieldset>
                <legend>Will this workflow run to the end?</legend>
                <label>
                  <input
                    type="radio"
                    name="stops"
                    checked={stops === "yes"}
                    onChange={() => setStops("yes")}
                  />
                  Yes, every step runs
                </label>
                <label>
                  <input
                    type="radio"
                    name="stops"
                    checked={stops === "no"}
                    onChange={() => setStops("no")}
                  />
                  No, it stops at step
                  <input
                    type="number"
                    aria-label="Step where it stops"
                    min={1}
                    max={64}
                    value={step}
                    disabled={stops !== "no"}
                    onChange={(e) => setStep(e.target.value)}
                  />
                </label>
              </fieldset>
              <button
                className={course.primary}
                disabled={busy || !stops || (stops === "no" && !Number(step))}
              >
                Record my prediction
              </button>
            </form>
          )}

          {current.phase === "diagnose" && (
            <form
              className={s.step}
              onSubmit={(e) => {
                e.preventDefault();
                void send(
                  `/practice/${current.id}/diagnosis`,
                  json({ version: current.version, cause }, "PUT"),
                );
              }}
            >
              <h3>2 · Run it, then name the cause</h3>
              <fieldset>
                <legend>What is wrong with this workflow?</legend>
                {current.choices.map((choice) => (
                  <label key={choice.cause}>
                    <input
                      type="radio"
                      name="cause"
                      checked={cause === choice.cause}
                      onChange={() => setCause(choice.cause)}
                    />
                    {choice.text}
                  </label>
                ))}
              </fieldset>
              <button className={course.primary} disabled={busy || !cause}>
                Record my answer
              </button>
            </form>
          )}

          {current.phase === "repair" && current.answer && (
            <div className={s.step}>
              <h3>3 · Repair it</h3>
              <Verdict exercise={current} />
              <p>
                Change the workflow so that it runs and still does what it was
                meant to, save it, then check it here.
              </p>
              {current.last_check && (
                <p role="status" className={s.check}>
                  {current.last_check}
                </p>
              )}
              <button
                className={course.primary}
                disabled={busy}
                onClick={() =>
                  send(
                    `/practice/${current.id}/repair`,
                    json({ version: current.version }),
                  )
                }
              >
                Check my repair
              </button>
            </div>
          )}
        </section>
      )}
      {finished.length > 0 && (
        <ol className={s.history} aria-label="Finished workflows">
          {[...finished].reverse().map((exercise) => (
            <li key={exercise.id}>
              <strong>
                {exercise.number} · {exercise.title}
              </strong>
              <Verdict exercise={exercise} />
              <span>
                <CheckCircle2 size={14} /> Repaired in {exercise.attempts}{" "}
                {exercise.attempts === 1 ? "try" : "tries"}
              </span>
            </li>
          ))}
        </ol>
      )}
      <p className={s.boundary}>
        Synthetic teaching model. These results are practice records, not a
        qualification to run an instrument.
      </p>
    </div>
  );
}

function Verdict({ exercise }: { exercise: Exercise }) {
  const answer = exercise.answer!;
  return (
    <ul className={s.verdict}>
      <li data-correct={exercise.prediction_correct}>
        {answer.stops
          ? `It stops at step ${answer.step}.`
          : "It runs to the end, and its end checks fail."}{" "}
        {exercise.prediction?.after_run
          ? "Your prediction came after a run, so it is not counted."
          : exercise.prediction_correct
            ? "You predicted that."
            : "You predicted otherwise."}
      </li>
      <li data-correct={exercise.diagnosis_correct}>
        {answer.text}{" "}
        {exercise.diagnosis_correct
          ? "You named it."
          : "You chose another cause."}
      </li>
    </ul>
  );
}
