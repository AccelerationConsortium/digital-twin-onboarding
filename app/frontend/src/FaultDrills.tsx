import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  Clock3,
  OctagonAlert,
  Play,
  XCircle,
} from "lucide-react";
import { api, json } from "./api";
import course from "./WorkflowCourse.module.css";
import fp from "./FaultPractice.module.css";
import s from "./FaultDrills.module.css";

type Choice = { id: string; text: string };
type Result = {
  response_s: number | null;
  total_s: number | null;
  unsafe_actions: number;
  recovery_correct: boolean;
  ending: string | null;
  timed_out: boolean;
  passed: boolean;
};
type Drill = {
  id: string;
  status: "open" | "done" | "timed_out";
  checkride_id: string | null;
  title: string | null;
  source: "catalog" | "lab";
  instrument_name: string;
  steps: string[];
  fault_step: number | null;
  symptom: string | null;
  running_s: number;
  fires_in_s: number;
  time_left_s: number;
  pool: Choice[];
  endings: Choice[];
  actions: { id: string; t: number }[];
  result?: Result;
  answer?: {
    recovery: Choice[];
    unsafe: string[];
    ending: string;
    why: string;
    contract: { layer: string; message: string } | null;
    layer: string | null;
  };
};
type Checkride = {
  id: string;
  status: "open" | "done";
  size: number;
  done: number;
  passed: boolean | null;
  finished_at: string | null;
  drills?: (Result & { title: string; instrument_name: string })[];
};
type Instrument = {
  key: string;
  name: string;
  steps: string[];
  families: { key: string; title: string }[];
};
type Drills = {
  version: number;
  limit_s: number;
  step_s: number;
  checkride_size: number;
  can_author: boolean;
  instruments: Instrument[];
  open: Drill | null;
  checkride: Checkride | null;
  drills: Drill[];
  checkrides: Checkride[];
  summary: {
    drills: number;
    passed: number;
    unsafe_actions: number;
    median_response_s: number | null;
    checkrides_passed: number;
  };
};
type Incident = {
  id: string;
  title: string;
  instrument: string;
  step: number;
  symptom: string;
};
type Lab = {
  lab: string;
  version: number;
  can_author: boolean;
  incidents: Incident[];
};
const LAB_KEY = "academy-drill-lab";

function savedLab() {
  try {
    return localStorage.getItem(LAB_KEY) || "my-lab";
  } catch {
    return "my-lab";
  }
}

/** A run on the twin, a fault in the middle of it, and a response against the clock. */
export default function FaultDrills({ onBack }: { onBack: () => void }) {
  const [drills, setDrills] = useState<Drills | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [instrument, setInstrument] = useState("");
  const [family, setFamily] = useState("");
  const [fetchedAt, setFetchedAt] = useState(0);
  const [clock, setClock] = useState(0);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const next = await api<Drills>("/fault-drills");
      if (!alive.current) return;
      setDrills(next);
      setFetchedAt(performance.now());
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
    };
  }, [load]);

  const open = drills?.open ?? null;
  // The run advances, the fault fires and the time runs out on the server's clock;
  // the page asks again at each of those moments.
  useEffect(() => {
    if (!open) return;
    const timer = window.setInterval(() => setClock(performance.now()), 250);
    const wake = [open.fires_in_s, open.fires_in_s + open.time_left_s + 0.2]
      .filter((seconds) => seconds > 0)
      .map((seconds) =>
        window.setTimeout(() => void load(), seconds * 1000 + 150),
      );
    return () => {
      window.clearInterval(timer);
      wake.forEach(window.clearTimeout);
    };
  }, [open, load]);

  const send = async (path: string, body: object) => {
    if (busy || !drills) return;
    setBusy(true);
    setError("");
    try {
      const next = await api<Drills>(
        path,
        json({ expected_version: drills.version, ...body }),
      );
      if (alive.current) {
        setDrills(next);
        setFetchedAt(performance.now());
      }
    } catch (e) {
      if (alive.current) setError((e as Error).message);
      await load();
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const chosen = drills?.instruments.find((i) => i.key === instrument);
  const elapsed = Math.max(0, (clock - fetchedAt) / 1000);
  const last = drills?.drills.find((d) => d.status !== "open");
  const ride = drills?.checkride ?? null;
  const summary = drills?.summary;
  const lastRide = drills?.checkrides.find((c) => c.status === "done");

  return (
    <div className={course.course}>
      <button className={course.back} onClick={onBack}>
        <ArrowLeft size={16} /> Back to learning lab
      </button>
      <header className={course.header}>
        <h1>Fault drills</h1>
        <p>
          A run is going on the twin when an instrument fault fires. Choose what
          to do, in order, before the time runs out.
        </p>
      </header>
      {error && (
        <p className={fp.error} role="alert">
          {error}
        </p>
      )}
      {summary && summary.drills > 0 && (
        <dl className={fp.score} aria-label="Your results">
          <div>
            <dt>Passed</dt>
            <dd>
              {summary.passed} / {summary.drills}
            </dd>
          </div>
          <div>
            <dt>Unsafe actions</dt>
            <dd>{summary.unsafe_actions}</dd>
          </div>
          {summary.median_response_s !== null && (
            <div>
              <dt>Median response</dt>
              <dd>{summary.median_response_s.toFixed(1)} s</dd>
            </div>
          )}
          <div>
            <dt>Checkrides passed</dt>
            <dd>{summary.checkrides_passed}</dd>
          </div>
        </dl>
      )}

      {open && (
        <Run
          drill={open}
          elapsed={elapsed}
          stepSeconds={drills!.step_s}
          ride={ride}
          busy={busy}
          onAct={(action) =>
            send(`/fault-drills/drills/${open.id}/actions`, { action })
          }
        />
      )}

      {drills && !open && ride && (
        <section className={fp.exercise} aria-label="Checkride">
          <h2>
            Checkride · drill {ride.done + 1} of {ride.size}
          </h2>
          <button
            className={course.primary}
            disabled={busy}
            onClick={() => send(`/fault-drills/checkrides/${ride.id}/next`, {})}
          >
            <Play size={16} /> Start the next drill
          </button>
        </section>
      )}

      {drills && !open && last && <Outcome drill={last} />}

      {drills && !open && !ride && (
        <div className={s.starts}>
          <form
            className={fp.exercise}
            aria-label="Practise a drill"
            onSubmit={(e) => {
              e.preventDefault();
              void send("/fault-drills/drills", { instrument, family });
            }}
          >
            <h2>Practise</h2>
            <div className={s.field}>
              <label htmlFor="drill-instrument">Instrument</label>
              <select
                id="drill-instrument"
                value={instrument}
                onChange={(e) => {
                  setInstrument(e.target.value);
                  setFamily("");
                }}
              >
                <option value="">Choose an instrument</option>
                {drills.instruments.map((i) => (
                  <option key={i.key} value={i.key}>
                    {i.name}
                  </option>
                ))}
              </select>
            </div>
            <div className={s.field}>
              <label htmlFor="drill-fault">Fault</label>
              <select
                id="drill-fault"
                value={family}
                disabled={!chosen}
                onChange={(e) => setFamily(e.target.value)}
              >
                <option value="">Choose a fault</option>
                {chosen?.families.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.title}
                  </option>
                ))}
              </select>
            </div>
            <button
              className={course.primary}
              disabled={busy || !instrument || !family}
            >
              <Play size={16} /> Start the drill
            </button>
          </form>
          <section className={fp.exercise} aria-label="Checkride">
            <h2>Checkride</h2>
            <p>
              {drills.checkride_size} drills chosen at random, with no answers
              until the end. Passing all of them adds the checkride to your
              cloud lab training record.
            </p>
            <button
              className={course.secondary}
              disabled={busy}
              onClick={() => send("/fault-drills/checkrides", {})}
            >
              Take the checkride
            </button>
          </section>
        </div>
      )}

      {lastRide && <RideResult ride={lastRide} />}

      {drills && (
        <LabDrills
          instruments={drills.instruments}
          canStart={!open && !ride && !busy}
          onStart={(lab, incident_id) =>
            send("/fault-drills/drills", { lab, incident_id })
          }
        />
      )}

      <p className={fp.boundary}>
        Synthetic teaching model. Drill results are practice records, not
        permission to run an instrument.
      </p>
    </div>
  );
}

function Run({
  drill,
  elapsed,
  stepSeconds,
  ride,
  busy,
  onAct,
}: {
  drill: Drill;
  elapsed: number;
  stepSeconds: number;
  ride: Checkride | null;
  busy: boolean;
  onAct: (action: string) => void;
}) {
  const fired = drill.symptom !== null;
  const left = Math.max(0, Math.ceil(drill.time_left_s - elapsed));
  // Before the fault the run moves on one step per stepSeconds; then it holds.
  const running = fired
    ? (drill.fault_step ?? 1)
    : Math.min(
        drill.steps.length,
        Math.floor((drill.running_s + elapsed) / stepSeconds) + 1,
      );
  const done = new Set(drill.actions.map((a) => a.id));
  const text = new Map(
    [...drill.pool, ...drill.endings].map((a) => [a.id, a.text]),
  );
  return (
    <section
      className={fp.exercise}
      aria-label={ride ? `Checkride drill ${ride.done + 1}` : "Drill"}
    >
      <h2>{drill.title ?? drill.instrument_name}</h2>
      {drill.title && <p className={fp.meta}>{drill.instrument_name}</p>}
      <ol className={s.run} aria-label="Run">
        {drill.steps.map((step, index) => {
          const n = index + 1;
          const state =
            n < running
              ? "done"
              : n === running
                ? fired
                  ? "fault"
                  : "running"
                : "next";
          return (
            <li
              key={n}
              data-state={state}
              aria-current={n === running ? "step" : undefined}
            >
              <span>{n}</span> {step}
            </li>
          );
        })}
      </ol>
      {fired ? (
        <>
          <div className={s.alarm} role="alert">
            <OctagonAlert size={18} />
            <p>{drill.symptom}</p>
            <span className={s.timer} aria-label="Time left">
              <Clock3 size={14} /> {left} s
            </span>
          </div>
          {drill.actions.length > 0 && (
            <ol className={s.chosen} aria-label="Your response">
              {drill.actions.map((a) => (
                <li key={a.id}>{text.get(a.id)}</li>
              ))}
            </ol>
          )}
          <fieldset className={s.actions} disabled={busy}>
            <legend>What do you do next?</legend>
            {drill.pool
              .filter((a) => !done.has(a.id))
              .map((a) => (
                <button
                  key={a.id}
                  type="button"
                  className={course.secondary}
                  onClick={() => onAct(a.id)}
                >
                  {a.text}
                </button>
              ))}
          </fieldset>
          <fieldset className={s.endings} disabled={busy}>
            <legend>Then</legend>
            {drill.endings.map((a) => (
              <button
                key={a.id}
                type="button"
                className={course.primary}
                onClick={() => onAct(a.id)}
              >
                {a.text}
              </button>
            ))}
          </fieldset>
        </>
      ) : (
        <p className={fp.meta} role="status">
          Running on the twin
        </p>
      )}
    </section>
  );
}

function Outcome({ drill }: { drill: Drill }) {
  if (!drill.result || !drill.answer)
    return (
      <p className={fp.check} role="status">
        Drill recorded. Results come at the end of the checkride.
      </p>
    );
  const { result, answer } = drill;
  const ending = drill.endings.find((e) => e.id === answer.ending)?.text;
  return (
    <section className={fp.exercise} aria-label="Last drill">
      <h2>
        {result.passed ? (
          <CheckCircle2 size={18} className={s.ok} />
        ) : (
          <XCircle size={18} className={s.bad} />
        )}{" "}
        {result.passed ? "Passed" : "Not passed"} · {drill.title}
      </h2>
      <p className={fp.meta}>{drill.instrument_name}</p>
      <ul className={fp.verdict}>
        <li data-correct={!result.timed_out}>
          {result.timed_out
            ? "Time ran out before the response ended."
            : `First action after ${result.response_s?.toFixed(1)} s.`}
        </li>
        <li data-correct={result.unsafe_actions === 0}>
          {result.unsafe_actions === 0
            ? "No unsafe action."
            : `${result.unsafe_actions} unsafe ${
                result.unsafe_actions === 1 ? "action" : "actions"
              }.`}
        </li>
        <li data-correct={result.recovery_correct}>
          {result.recovery_correct
            ? "The recovery was in the right order."
            : "The recovery differs from the one below."}
        </li>
      </ul>
      <h3 className={s.subhead}>Recovery</h3>
      <ol className={s.chosen}>
        {answer.recovery.map((a) => (
          <li key={a.id}>{a.text}</li>
        ))}
        <li>
          <strong>{ending}</strong>
        </li>
      </ol>
      <p>{answer.why}</p>
      {drill.actions.some((a) => answer.unsafe.includes(a.id)) && (
        <p>
          Unsafe:{" "}
          {drill.pool
            .filter(
              (a) =>
                answer.unsafe.includes(a.id) &&
                drill.actions.some((x) => x.id === a.id),
            )
            .map((a) => a.text)
            .join("; ")}
        </p>
      )}
      {answer.contract && (
        <details className={s.details}>
          <summary>What an agent sees for this fault</summary>
          <p>
            The mock connector refuses the command at its{" "}
            <code>{answer.contract.layer}</code> layer:{" "}
            <q>{answer.contract.message}</q>
          </p>
        </details>
      )}
    </section>
  );
}

function RideResult({ ride }: { ride: Checkride }) {
  return (
    <section className={s.ride} aria-label="Last checkride">
      <h2>Checkride {ride.passed ? "passed" : "not passed"}</h2>
      <ol className={fp.history}>
        {ride.drills?.map((d, i) => (
          <li key={i}>
            <strong>
              {d.title} · {d.instrument_name}
            </strong>
            <span>
              {d.passed ? <CheckCircle2 size={14} /> : <XCircle size={14} />}{" "}
              {d.timed_out
                ? "Timed out"
                : `${d.response_s?.toFixed(1)} s · ${d.unsafe_actions} unsafe · ${
                    d.recovery_correct ? "right order" : "wrong order"
                  }`}
            </span>
          </li>
        ))}
      </ol>
      {ride.passed && (
        <p className={fp.meta}>Included in your cloud lab training record.</p>
      )}
    </section>
  );
}

const EMPTY = {
  title: "",
  instrument: "",
  step: "1",
  symptom: "",
  recovery: "",
  unsafe: "",
  ending: "operator",
  why: "",
};

function LabDrills({
  instruments,
  canStart,
  onStart,
}: {
  instruments: Instrument[];
  canStart: boolean;
  onStart: (lab: string, incident: string) => void;
}) {
  const [code, setCode] = useState(savedLab);
  const [lab, setLab] = useState<Lab | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const valid = /^[a-z0-9][a-z0-9-]{1,39}$/.test(code);

  useEffect(() => {
    if (!valid) return;
    let live = true;
    const timer = window.setTimeout(() => {
      api<Lab>(`/fault-drills/labs/${code}/incidents`)
        .then((next) => {
          if (!live) return;
          setLab(next);
          setError("");
          try {
            localStorage.setItem(LAB_KEY, code);
          } catch {
            /* a remembered lab code is a convenience only */
          }
        })
        .catch((e) => live && setError((e as Error).message));
    }, 250);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [code, valid]);

  const steps = instruments.find((i) => i.key === form.instrument)?.steps ?? [];
  const lines = (text: string) =>
    text
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  const submit = async () => {
    if (!lab) return;
    setBusy(true);
    setError("");
    try {
      const next = await api<Lab>(
        `/fault-drills/labs/${lab.lab}/incidents`,
        json({
          expected_version: lab.version,
          title: form.title,
          instrument: form.instrument,
          step: Number(form.step),
          symptom: form.symptom,
          recovery: lines(form.recovery),
          unsafe: lines(form.unsafe),
          ending: form.ending,
          why: form.why,
        }),
      );
      setLab(next);
      setForm(EMPTY);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const set =
    (key: keyof typeof EMPTY) =>
    (
      e: React.ChangeEvent<
        HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
      >,
    ) =>
      setForm((current) => ({ ...current, [key]: e.target.value }));

  return (
    <section className={s.lab} aria-label="Lab drills">
      <h2>From your lab's incidents</h2>
      <label className={s.field}>
        Lab code
        <input
          value={code}
          maxLength={40}
          onChange={(e) => setCode(e.target.value.toLowerCase())}
        />
      </label>
      {error && (
        <p className={fp.error} role="alert">
          {error}
        </p>
      )}
      {lab && lab.lab === code && (
        <>
          {lab.incidents.length ? (
            <ul className={s.incidents}>
              {lab.incidents.map((incident) => (
                <li key={incident.id}>
                  <strong>{incident.title}</strong>
                  <span>{incident.symptom}</span>
                  <button
                    className={course.secondary}
                    disabled={!canStart}
                    onClick={() => onStart(lab.lab, incident.id)}
                  >
                    Practise this drill
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className={fp.meta}>This lab has no drills yet.</p>
          )}
          {lab.can_author ? (
            <details className={s.details}>
              <summary>Turn an incident into a drill</summary>
              <form
                className={s.author}
                onSubmit={(e) => {
                  e.preventDefault();
                  void submit();
                }}
              >
                <label className={s.field}>
                  Title
                  <input
                    value={form.title}
                    maxLength={80}
                    onChange={set("title")}
                  />
                </label>
                <label className={s.field}>
                  Instrument
                  <select value={form.instrument} onChange={set("instrument")}>
                    <option value="">Choose an instrument</option>
                    {instruments.map((i) => (
                      <option key={i.key} value={i.key}>
                        {i.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={s.field}>
                  Step it happened at
                  <select
                    value={form.step}
                    disabled={!steps.length}
                    onChange={set("step")}
                  >
                    {steps.map((step, i) => (
                      <option key={i} value={i + 1}>
                        {i + 1} · {step}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={s.field}>
                  What the learner sees
                  <textarea
                    rows={2}
                    maxLength={300}
                    value={form.symptom}
                    onChange={set("symptom")}
                  />
                </label>
                <label className={s.field}>
                  Correct response, one step per line
                  <textarea
                    rows={4}
                    value={form.recovery}
                    onChange={set("recovery")}
                  />
                </label>
                <label className={s.field}>
                  Unsafe responses, one per line
                  <textarea
                    rows={2}
                    value={form.unsafe}
                    onChange={set("unsafe")}
                  />
                </label>
                <label className={s.field}>
                  Then
                  <select value={form.ending} onChange={set("ending")}>
                    <option value="operator">
                      Stop the run and call the operator
                    </option>
                    <option value="resume">Resume the run</option>
                  </select>
                </label>
                <label className={s.field}>
                  Why
                  <textarea
                    rows={2}
                    maxLength={300}
                    value={form.why}
                    onChange={set("why")}
                  />
                </label>
                <p className={fp.meta}>
                  Leave out names and anything that identifies a person.
                </p>
                <button
                  className={course.primary}
                  disabled={
                    busy ||
                    !form.title ||
                    !form.instrument ||
                    !form.symptom ||
                    !lines(form.recovery).length ||
                    !lines(form.unsafe).length
                  }
                >
                  Add the drill
                </button>
              </form>
            </details>
          ) : (
            <p className={fp.meta}>
              Adding a drill from an incident needs the lab operator role.
            </p>
          )}
        </>
      )}
    </section>
  );
}
