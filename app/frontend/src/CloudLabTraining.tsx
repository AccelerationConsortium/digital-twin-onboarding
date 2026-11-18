import {
  CheckCircle2,
  Circle,
  Download,
  Plus,
  Send,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api, json } from "./api";
import type { Action } from "./types";
import s from "./CloudLabTraining.module.css";

type ChoiceId =
  "orient" | "assume" | "escalate" | "accept" | "report" | "audit" | "need";
type TaskId = ChoiceId | "fault" | "own";
type Question = {
  id: string;
  prompt: string;
  options: string[];
  multiple: boolean;
};
type Answer = number | number[];
type Competency = {
  key: string;
  tracks: string[];
  seniority: string;
  step: string;
  proficiency: string;
  label: string;
};
type Problem = {
  source: "rules" | "goal";
  step: number | null;
  message: string;
};
type Task = {
  title: string;
  status: "open" | "passed";
  attempts: number;
  errors: string[];
  actions?: Action[];
  note?: string;
};
type Training = {
  version: number;
  started_at: string;
  tasks: Record<TaskId, Task>;
  outdated: boolean;
  choices: Record<
    ChoiceId,
    { context: string | null; note: boolean; questions: Question[] }
  >;
  goals: Record<"fault" | "own", string>;
  last_check:
    | { task: ChoiceId; valid: boolean; wrong: number; note_missing: boolean }
    | { task: "fault" | "own"; valid: boolean; problems: Problem[] }
    | null;
};
type Capabilities = {
  instrument: {
    name: string;
    pipette: string;
    volume_ul: [number, number];
    plate: { load_name: string; capacity_ul: number };
    stock: { load_name: string; capacity_ul: number };
    layout: Record<string, string>;
    simulator_rules: string;
  };
  modules: { title: string; rules_version: string }[];
};

/** Handed to the mock portal in this tab; the portal also accepts a downloaded file. */
export const RECORD_HANDOFF = "academy-training-record";
const ORDER: TaskId[] = [
  "orient",
  "fault",
  "own",
  "assume",
  "escalate",
  "accept",
  "report",
  "audit",
  "need",
];
const STEP_LABELS: Record<TaskId, string> = {
  orient: "Learn",
  fault: "Repair",
  own: "Write",
  assume: "Assumptions",
  escalate: "Escalate",
  accept: "Accept",
  report: "Report",
  audit: "Audit",
  need: "Decide",
};
/** What the button to each step says. */
const NEXT: Record<TaskId | "record", string> = {
  orient: "Next: learn the deck",
  fault: "Next: repair a workflow",
  own: "Next: write your own",
  assume: "Next: record your assumptions",
  escalate: "Next: know when to escalate",
  accept: "Next: judge the results",
  report: "Next: write up the deviation",
  audit: "Next: audit a run log",
  need: "Next: decide whether to automate",
  record: "Next: your record",
};
const CHOICE_TASKS = new Set<TaskId>([
  "orient",
  "assume",
  "escalate",
  "accept",
  "report",
  "audit",
  "need",
]);
const isChoice = (id: TaskId | "record"): id is ChoiceId =>
  CHOICE_TASKS.has(id as TaskId);
const after = (id: TaskId): TaskId | "record" =>
  ORDER[ORDER.indexOf(id) + 1] ?? "record";
/** The record inside a signed envelope; the portal is what checks the signature. */
const unwrap = (envelope: { payload?: string }) =>
  JSON.parse(
    new TextDecoder().decode(
      Uint8Array.from(
        atob(
          (envelope.payload ?? "").replace(/-/g, "+").replace(/_/g, "/") +
            "=".repeat((4 - ((envelope.payload ?? "").length % 4)) % 4),
        ),
        (c) => c.charCodeAt(0),
      ),
    ),
  );
const PLACES: Record<string, string> = {
  stock: "Stock reservoir",
  plate: "Deep-well plate",
  tips: "1000 µL tips",
  waste: "Waste chute",
};

function ActionEditor({
  actions,
  onChange,
  problemSteps,
  disabled,
}: {
  actions: Action[];
  onChange: (next: Action[]) => void;
  problemSteps: Set<number>;
  disabled: boolean;
}) {
  const set = (index: number, patch: Partial<Action>) =>
    onChange(actions.map((a, i) => (i === index ? { ...a, ...patch } : a)));
  const add = (kind: Action["kind"]) =>
    onChange([
      ...actions,
      {
        kind,
        well: kind === "dispense" ? "A1" : "stock",
        volume: 100,
      },
    ]);
  return (
    // Locked while a check runs, so no edit is lost when its result arrives.
    <fieldset
      className={s.editor}
      disabled={disabled}
      aria-label="Workflow steps"
    >
      <ol className={s.steps}>
        {actions.map((action, index) => (
          <li
            key={index}
            className={problemSteps.has(index + 1) ? s.flagged : undefined}
          >
            <span className={s.stepNo}>{index + 1}</span>
            <select
              aria-label={`Step ${index + 1} action`}
              value={action.kind}
              onChange={(e) =>
                set(index, { kind: e.target.value as Action["kind"] })
              }
            >
              <option value="pickup">Pick up tip</option>
              <option value="aspirate">Aspirate</option>
              <option value="dispense">Dispense</option>
              <option value="drop">Drop tip</option>
            </select>
            {(action.kind === "aspirate" || action.kind === "dispense") && (
              <>
                <input
                  aria-label={`Step ${index + 1} volume in µL`}
                  type="number"
                  min={1}
                  max={1000}
                  value={action.volume}
                  onChange={(e) =>
                    set(index, {
                      volume: Math.min(
                        1000,
                        Math.max(1, Number(e.target.value) || 1),
                      ),
                    })
                  }
                />
                <span className={s.unit}>µL</span>
                <span className={s.unit}>
                  {action.kind === "aspirate" ? "from" : "into"}
                </span>
                <select
                  aria-label={`Step ${index + 1} well`}
                  value={action.well}
                  onChange={(e) =>
                    set(index, { well: e.target.value as Action["well"] })
                  }
                >
                  <option value="stock">stock</option>
                  <option value="A1">A1</option>
                  <option value="A2">A2</option>
                  <option value="A3">A3</option>
                </select>
              </>
            )}
            <button
              className={s.iconButton}
              aria-label={`Remove step ${index + 1}`}
              onClick={() => onChange(actions.filter((_, i) => i !== index))}
            >
              <Trash2 size={15} />
            </button>
          </li>
        ))}
      </ol>
      <div className={s.adders}>
        {(
          [
            ["pickup", "Pick up tip"],
            ["aspirate", "Aspirate"],
            ["dispense", "Dispense"],
            ["drop", "Drop tip"],
          ] as const
        ).map(([kind, label]) => (
          <button key={kind} className={s.secondary} onClick={() => add(kind)}>
            <Plus size={14} /> {label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

const same = (a: Action[] = [], b: Action[] = []) =>
  JSON.stringify(a) === JSON.stringify(b);

export default function CloudLabTraining({
  onPortal,
  onError,
  registerLeaveGuard,
}: {
  onPortal: () => void;
  onError: (message: string) => void;
  registerLeaveGuard: (guard: (() => boolean) | null) => void;
}) {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [training, setTraining] = useState<Training | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [step, setStep] = useState<TaskId | "record">("orient");
  const [answers, setAnswers] = useState<
    Partial<Record<ChoiceId, Record<string, Answer>>>
  >({});
  const [notes, setNotes] = useState<Partial<Record<ChoiceId, string>>>({});
  const [evidence, setEvidence] = useState<Competency[] | null>(null);
  const [drafts, setDrafts] = useState<Partial<Record<TaskId, Action[]>>>({});
  const [busy, setBusy] = useState(false);

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    try {
      await work();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const adopt = (next: Training) => {
    setTraining(next);
    setDrafts({
      fault: next.tasks.fault.actions ?? [],
      own: next.tasks.own.actions ?? [],
    });
  };

  const load = () =>
    run(async () => {
      setFailed(true);
      const [c, t] = await Promise.all([
        api<Capabilities>("/cloudlab/capabilities"),
        api<{ training: Training | null }>(
          "/cloudlab/training-sessions/current",
        ),
      ]);
      setCaps(c);
      if (t.training) {
        adopt(t.training);
        // A training from earlier rules lacks the newer tasks; the page asks to start over.
        setStep(
          t.training.outdated
            ? "orient"
            : (ORDER.find((id) => t.training!.tasks[id]?.status !== "passed") ??
                "record"),
        );
      }
      setLoaded(true);
      setFailed(false);
    });
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty =
    !!training &&
    (["fault", "own"] as const).some(
      (id) => !same(drafts[id], training.tasks[id].actions),
    );
  useEffect(() => {
    registerLeaveGuard(
      () =>
        !dirty ||
        window.confirm(
          "Your workflow edits are not checked yet. Leave anyway?",
        ),
    );
    // Refreshing or closing the tab skips the app's own guard, so warn there too.
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      registerLeaveGuard(null);
      window.removeEventListener("beforeunload", warn);
    };
  }, [dirty, registerLeaveGuard]);

  const start = () =>
    run(async () => {
      const next = await api<Training>(
        "/cloudlab/training-sessions",
        json({ expected_version: training?.version ?? 0 }),
      );
      adopt(next);
      setAnswers({});
      setNotes({});
      setStep("orient");
    });

  const submitAnswers = (task: ChoiceId) =>
    run(async () => {
      if (!training) return;
      adopt(
        await api<Training>(
          "/cloudlab/training-sessions/answers",
          json({
            expected_version: training.version,
            task,
            answers: answers[task] ?? {},
            note: notes[task] ?? "",
          }),
        ),
      );
    });

  useEffect(() => {
    if (step !== "record" || !training || training.outdated) return;
    let alive = true;
    setEvidence(null);
    api<{ payload?: string }>("/cloudlab/qualifications/me")
      .then((envelope) => {
        if (alive)
          setEvidence(unwrap(envelope).competencies?.evidence_toward ?? []);
      })
      .catch(() => alive && setEvidence([]));
    return () => {
      alive = false;
    };
  }, [step, training]);

  const validate = (task: "fault" | "own") =>
    run(async () => {
      if (!training) return;
      adopt(
        await api<Training>(
          "/cloudlab/workflow-validations",
          json({
            expected_version: training.version,
            task,
            actions: drafts[task] ?? [],
          }),
        ),
      );
    });

  const fetchRecord = () =>
    api<Record<string, unknown>>("/cloudlab/qualifications/me");
  const download = () =>
    run(async () => {
      const record = await fetchRecord();
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(record, null, 2)], {
          type: "application/json",
        }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = "academy-training-record.json";
      link.click();
      URL.revokeObjectURL(url);
    });
  const sendToPortal = () =>
    run(async () => {
      const record = await fetchRecord();
      try {
        sessionStorage.setItem(RECORD_HANDOFF, JSON.stringify(record));
      } catch {
        // Without storage the portal asks for the downloaded file instead.
      }
      onPortal();
    });

  if (!loaded || !caps)
    return (
      <main className={s.page} aria-busy={busy}>
        {failed && !busy && (
          <section className={s.card}>
            <p className={s.note}>Cloud lab onboarding could not be loaded.</p>
            <button className={s.primary} onClick={load}>
              Try again
            </button>
          </section>
        )}
      </main>
    );
  const inst = caps.instrument;
  const check = training?.last_check;
  const done = (id: TaskId) => training?.tasks[id]?.status === "passed";

  const choiceTask = (task: ChoiceId) => {
    if (!training) return null;
    const spec = training.choices[task];
    const given = answers[task] ?? {};
    const set = (id: string, value: Answer) =>
      setAnswers((a) => ({ ...a, [task]: { ...a[task], [id]: value } }));
    const answered =
      spec.questions.every((q) =>
        q.multiple
          ? Array.isArray(given[q.id]) && (given[q.id] as number[]).length > 0
          : typeof given[q.id] === "number",
      ) &&
      (!spec.note || (notes[task] ?? "").trim().length > 0);
    const mine =
      check && check.task === task && "wrong" in check ? check : null;
    return (
      <>
        {spec.questions.map((q) => (
          <fieldset key={q.id} className={s.question}>
            <legend>{q.prompt}</legend>
            {q.options.map((option, index) => {
              const picked = given[q.id];
              const checked = q.multiple
                ? Array.isArray(picked) && picked.includes(index)
                : picked === index;
              return (
                <label key={option}>
                  <input
                    type={q.multiple ? "checkbox" : "radio"}
                    name={`${task}-${q.id}`}
                    checked={checked}
                    onChange={() => {
                      if (!q.multiple) return set(q.id, index);
                      const now = Array.isArray(picked) ? picked : [];
                      set(
                        q.id,
                        checked
                          ? now.filter((i) => i !== index)
                          : [...now, index],
                      );
                    }}
                  />
                  {option}
                </label>
              );
            })}
          </fieldset>
        ))}
        {spec.note && (
          <label className={s.noteField}>
            <span>Note for a colleague</span>
            <textarea
              rows={3}
              maxLength={500}
              value={notes[task] ?? ""}
              onChange={(e) =>
                setNotes((n) => ({ ...n, [task]: e.target.value }))
              }
            />
          </label>
        )}
        <div className={s.actions}>
          <button
            className={s.primary}
            disabled={busy || !answered}
            onClick={() => submitAnswers(task)}
          >
            Check answers
          </button>
          {done(task) ? (
            <button
              className={s.secondary}
              onClick={() => setStep(after(task))}
            >
              {NEXT[after(task)]}
            </button>
          ) : (
            mine &&
            !mine.valid && (
              <span className={s.bad}>
                {mine.wrong > 0 && `${mine.wrong} not right yet`}
                {mine.wrong > 0 && mine.note_missing && " · "}
                {mine.note_missing && "add a fuller note"}
              </span>
            )
          )}
        </div>
      </>
    );
  };

  return (
    <main className={s.page}>
      <header className={s.header}>
        <div>
          <h1>Cloud lab onboarding</h1>
          <p className={s.lede}>{caps.modules[0].title}</p>
        </div>
        <span className={s.synthetic}>
          Synthetic training · grants no instrument access
        </span>
      </header>

      {!training ? (
        <section className={s.card}>
          <h2>Before your first cloud lab run on the {inst.name}</h2>
          <ol className={s.intro}>
            <li>Learn the deck and the container rules.</li>
            <li>Repair a workflow that the simulator rules stop.</li>
            <li>Write your own workflow and pass the same check.</li>
            <li>
              Record its assumptions, know when to escalate, judge results and
              write up the deviation.
            </li>
            <li>Decide whether a workflow is worth automating.</li>
          </ol>
          <p className={s.note}>
            You get a signed training record to attach to a cloud lab run
            request. The lab's operators still review every request.
          </p>
          <button className={s.primary} disabled={busy} onClick={start}>
            Start training
          </button>
        </section>
      ) : training.outdated ? (
        <section className={s.card}>
          <h2>The training has changed</h2>
          <p className={s.note}>
            Your progress was made under earlier rules, so a portal would not
            accept its record. Start over to train under{" "}
            <code>{caps.modules[0].rules_version}</code>.
          </p>
          <button className={s.primary} disabled={busy} onClick={start}>
            Start over
          </button>
        </section>
      ) : (
        <>
          <nav className={s.stepper} aria-label="Training steps">
            {[...ORDER, "record" as const].map((id, index) => {
              const passed = id !== "record" && done(id);
              return (
                <button
                  key={id}
                  className={step === id ? s.currentStep : undefined}
                  aria-current={step === id ? "step" : undefined}
                  onClick={() => setStep(id)}
                >
                  {passed ? (
                    <CheckCircle2 size={16} className={s.passed} />
                  ) : (
                    <Circle size={16} />
                  )}
                  <span>
                    {index + 1} · {id === "record" ? "Record" : STEP_LABELS[id]}
                  </span>
                </button>
              );
            })}
          </nav>

          {step === "orient" && (
            <section className={s.grid}>
              <div className={s.card}>
                <h2>The {inst.name} deck</h2>
                <div
                  className={s.deck}
                  role="group"
                  aria-label="Flex deck layout"
                >
                  {["A", "B", "C", "D"].map((row) =>
                    [1, 2, 3].map((col) => {
                      const slot = `${row}${col}`;
                      const item = Object.entries(inst.layout).find(
                        ([, at]) => at === slot,
                      )?.[0];
                      return (
                        <div
                          key={slot}
                          className={item ? s.filled : s.slot}
                          data-item={item}
                        >
                          <small>{slot}</small>
                          {item && <strong>{PLACES[item]}</strong>}
                        </div>
                      );
                    }),
                  )}
                </div>
                <dl className={s.facts}>
                  <dt>Pipette</dt>
                  <dd>
                    {inst.pipette}, {inst.volume_ul[0]}–
                    {inst.volume_ul[1].toLocaleString()} µL per aspiration
                  </dd>
                  <dt>Plate well</dt>
                  <dd>{inst.plate.capacity_ul.toLocaleString()} µL</dd>
                  <dt>Stock reservoir</dt>
                  <dd>{inst.stock.capacity_ul.toLocaleString()} µL</dd>
                  <dt>Tips</dt>
                  <dd>One tip at a time; used tips go to the waste chute.</dd>
                </dl>
              </div>
              <div className={s.card}>
                <h2>Check what you know</h2>
                {choiceTask("orient")}
              </div>
            </section>
          )}

          {isChoice(step) && step !== "orient" && (
            <section className={s.card}>
              <div className={s.taskHead}>
                <h2>{training.tasks[step].title}</h2>
                <span>{done(step) ? "passed" : "open"}</span>
              </div>
              {training.choices[step].context && (
                <p className={s.context}>{training.choices[step].context}</p>
              )}
              {choiceTask(step)}
            </section>
          )}

          {(step === "fault" || step === "own") && (
            <section className={s.card}>
              <div className={s.taskHead}>
                <h2>{training.tasks[step].title}</h2>
                <span>
                  {training.tasks[step].attempts}{" "}
                  {training.tasks[step].attempts === 1 ? "check" : "checks"} ·{" "}
                  {done(step) ? "passed" : "open"}
                </span>
              </div>
              <p className={s.goal}>{training.goals[step]}</p>
              {step === "fault" && (
                <p className={s.note}>
                  Find the cause and fix it. The plate has to end up as the goal
                  asks.
                </p>
              )}
              <ActionEditor
                disabled={busy}
                actions={drafts[step] ?? []}
                onChange={(next) => setDrafts((d) => ({ ...d, [step]: next }))}
                problemSteps={
                  new Set(
                    check && check.task === step
                      ? check.problems.flatMap((p) => (p.step ? [p.step] : []))
                      : [],
                  )
                }
              />
              <div className={s.actions}>
                <button
                  className={s.primary}
                  disabled={busy}
                  onClick={() => validate(step)}
                >
                  Run dry check
                </button>
                {done(step) && (
                  <button
                    className={s.secondary}
                    onClick={() => setStep(after(step))}
                  >
                    {NEXT[after(step)]}
                  </button>
                )}
              </div>
              {check && check.task === step && (
                <div className={check.valid ? s.ok : s.problems} role="status">
                  {check.valid ? (
                    <p>
                      <CheckCircle2 size={16} /> Passes the {inst.name}{" "}
                      simulator rules and reaches the goal.
                    </p>
                  ) : (
                    <ul>
                      {check.problems.map((p, i) => (
                        <li key={i}>
                          <TriangleAlert size={15} />
                          <span>
                            {p.step ? `Step ${p.step} · ` : ""}
                            {p.message}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                  <small>{inst.simulator_rules} · synthetic dry run</small>
                </div>
              )}
            </section>
          )}

          {step === "record" && (
            <section className={s.card}>
              <h2>Your training record</h2>
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>Task</th>
                    <th>Status</th>
                    <th>Checks</th>
                    <th>Mistakes found on the way</th>
                  </tr>
                </thead>
                <tbody>
                  {ORDER.map((id) => {
                    const task = training.tasks[id];
                    return (
                      <tr key={id}>
                        <td>{task.title}</td>
                        <td className={done(id) ? s.passed : s.bad}>
                          {done(id) ? "Passed" : "Not yet"}
                        </td>
                        <td>{task.attempts}</td>
                        <td>
                          {task.errors.length
                            ? task.errors.slice(0, 3).join(" · ")
                            : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <h3 className={s.subhead}>Evidence toward GASE competencies</h3>
              {evidence === null ? (
                <p className={s.note} aria-busy="true">
                  Reading the record…
                </p>
              ) : evidence.length === 0 ? (
                <p className={s.note}>Pass a task to add evidence.</p>
              ) : (
                <ul className={s.competencies}>
                  {evidence.map((c) => (
                    <li key={c.key}>
                      <strong>{c.label}</strong>
                      <small>
                        {c.tracks.join(" · ")} · {c.seniority} · {c.step} ·{" "}
                        {c.proficiency}
                      </small>
                    </li>
                  ))}
                </ul>
              )}
              <p className={s.fine}>
                Positions in the draft GASE Guidelines (SLAS). Labels are the
                Academy's. Evidence from synthetic practice, not certification.
              </p>
              <p className={s.note}>
                Signed by the Academy and bound to rules version{" "}
                <code>{caps.modules[0].rules_version}</code>. It is evidence for
                the cloud lab's operators, not permission to run.
              </p>
              <div className={s.actions}>
                <button
                  className={s.primary}
                  disabled={busy}
                  onClick={sendToPortal}
                >
                  <Send size={15} /> Attach to a run request
                </button>
                <button
                  className={s.secondary}
                  disabled={busy}
                  onClick={download}
                >
                  <Download size={15} /> Download record
                </button>
                <button
                  className={s.textButton}
                  disabled={busy}
                  onClick={start}
                >
                  Start over
                </button>
              </div>
            </section>
          )}
        </>
      )}
    </main>
  );
}
