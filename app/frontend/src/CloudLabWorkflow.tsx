import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Check,
  Copy,
  Layers3,
  Play,
  Plus,
  Save,
  Trash2,
  TriangleAlert,
  Workflow,
} from "lucide-react";
import { api, ApiError, json } from "./api";
import { workflows } from "./discoveryContent";
import type { Earned } from "./skills";
import s from "./WorkflowStudio.module.css";
import c from "./CloudLabWorkflow.module.css";
import k from "./SkillTree.module.css";

type Operation = "load" | "transfer" | "mix" | "heat" | "read" | "wait";
type Step = {
  instrument: string;
  operation: Operation;
  sample: string;
  value: number;
  slot: string;
};
type Instrument = {
  id: string;
  name: string;
  section: string;
  experiment: string;
  published: string;
  narrowed: string | null;
  operations: Operation[];
  holds: { vessel: string; max_volume_ul: number };
  slots: string[];
  limits: { min_temp_c: number; max_temp_c: number; max_duration_s: number };
  consumables: {
    name: string;
    used_by: Operation;
    per_use: number;
    stock: number;
  }[];
  stand_in: string | null;
};
type SampleState = {
  location: string | null;
  site: string | null;
  volume_ul: number;
  temperature_c: number;
  mixed: boolean;
};
type TraceEntry = {
  step: number;
  device_id: string;
  operation: Operation;
  sample: string;
  volume_ul: number;
  temperature_c: number;
  mixed: boolean;
  elapsed_s: number;
  consumables: Record<string, Record<string, number>>;
  samples: Record<string, SampleState>;
  measurement: { kind: string } | null;
};
type Check = {
  ok: boolean;
  trace: TraceEntry[];
  error: { step: number | null; message: string; layer: string } | null;
};
type Run = { id: string; at: string; title: string; trace: TraceEntry[] };
/** A marketplace paper's steps on the twins, opened here as a starter. */
export type WorkflowTemplate = {
  title: string;
  steps: Step[];
  instruments: Instrument[];
};
type Workspace = {
  version: number;
  title: string;
  steps: Step[];
  runs: Run[];
  check: Check;
  instruments: Instrument[];
  starters: Record<string, { title: string; steps: Step[] }>;
  statement: string;
};

const MAX_STEPS = 32;
const LABELS: Record<Operation, string> = {
  load: "Load",
  transfer: "Move here",
  mix: "Mix",
  heat: "Hold temperature",
  read: "Read",
  wait: "Wait",
};
const VALUES: Partial<Record<Operation, [string, string]>> = {
  load: ["VOLUME", "µL"],
  heat: ["TEMPERATURE", "°C"],
  mix: ["FOR", "s"],
  wait: ["FOR", "s"],
};
// Each cloud lab section keeps one block colour, so the flow reads by kind of work.
const TONES: Record<string, string> = {
  Transfers: s.pickup,
  "Cell Culture": s.dispense,
  Spectroscopy: s.aspirate,
  Bioassays: s.aspirate,
  "Organic Synthesis": s.drop,
  Separations: s.read,
  "ChemLab-Assets": s.drop,
};
const PAPER = "paper";
const format = (value: number) => Number(value.toFixed(1)).toLocaleString();

/** Where each sample is before every step and after the last, as the twins' contract moves it. */
function locations(steps: Step[]) {
  const where: Record<string, string> = {};
  const before = steps.map((step) => {
    const now = { ...where };
    if (step.operation === "load") where[step.sample] ??= step.instrument;
    if (step.operation === "transfer") where[step.sample] = step.instrument;
    return now;
  });
  return [...before, where];
}

function operationsFor(instrument: Instrument) {
  // Anything that holds a sample can also receive one.
  return instrument.operations.includes("load")
    ? ([...instrument.operations, "transfer"] as Operation[])
    : instrument.operations;
}

function defaultValue(instrument: Instrument, operation: Operation) {
  if (operation === "load")
    return Math.min(100, instrument.holds.max_volume_ul);
  if (operation === "heat")
    return Math.round(
      (instrument.limits.min_temp_c + instrument.limits.max_temp_c) / 2,
    );
  if (operation === "mix") return 30;
  if (operation === "wait") return 60;
  return 1;
}

export default function CloudLabWorkflow({
  onBack,
  onError,
  registerLeaveGuard,
  template,
  onSkills,
  onTemplateTaken,
}: {
  onBack: () => void;
  onError: (message: string) => void;
  registerLeaveGuard: (guard: (() => boolean) | null) => void;
  template?: WorkflowTemplate;
  onSkills?: () => void;
  onTemplateTaken?: () => void;
}) {
  // The paper template stays a starter for this visit.
  const [paper] = useState(template);
  const offered = useRef(false);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [title, setTitle] = useState("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [check, setCheck] = useState<Check | null>(null);
  const [starter, setStarter] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  // What the last run here added to the learner's skill tree.
  const [earned, setEarned] = useState<Earned | null>(null);
  const checked = useRef(0);

  const adopt = (next: Workspace) => {
    setWorkspace(next);
    setTitle(next.title);
    setSteps(next.steps);
    setCheck(next.check);
  };
  useEffect(() => {
    api<Workspace>("/cloudlab/workflow")
      .then((next) => {
        adopt(next);
        setStarter(paper ? PAPER : (Object.keys(next.starters)[0] ?? ""));
        if (!paper || offered.current) return;
        offered.current = true;
        onTemplateTaken?.();
        // The template is a draft: the saved workflow stays until the learner saves.
        if (
          !next.steps.length ||
          window.confirm(
            `Replace your workflow steps with the "${paper.title}" template? Your saved workflow stays until you save.`,
          )
        ) {
          setSteps(paper.steps);
          setTitle(paper.title);
        }
      })
      .catch(() => setFailed(true));
    // Opened once; a template is taken on arrival only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty =
    !!workspace &&
    (title !== workspace.title ||
      JSON.stringify(steps) !== JSON.stringify(workspace.steps));
  useEffect(() => {
    registerLeaveGuard(
      () =>
        !dirty ||
        window.confirm("Your workflow changes are not saved. Leave anyway?"),
    );
    return () => registerLeaveGuard(null);
  }, [dirty, registerLeaveGuard]);

  // Every edit is checked against the twins' rules; only the latest answer counts.
  useEffect(() => {
    if (!workspace || !dirty) return;
    const ticket = ++checked.current;
    const timer = window.setTimeout(() => {
      api<Check>("/cloudlab/workflow/check", json({ steps }))
        .then((next) => ticket === checked.current && setCheck(next))
        .catch(() => undefined);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [steps, dirty, workspace]);
  useEffect(() => {
    if (workspace && !dirty) setCheck(workspace.check);
  }, [dirty, workspace]);

  // The designer's instruments, then ChemLab-Assets twins the paper template uses.
  const instruments = useMemo(() => {
    const shown = workspace?.instruments ?? [];
    const known = new Set(shown.map((i) => i.id));
    return [
      ...shown,
      ...(paper?.instruments ?? []).filter((i) => !known.has(i.id)),
    ];
  }, [workspace, paper]);
  const byId = useMemo(
    () =>
      Object.fromEntries(instruments.map((i) => [i.id, i])) as Record<
        string,
        Instrument
      >,
    [instruments],
  );
  const starters = useMemo<Workspace["starters"]>(
    () => ({
      ...(paper ? { [PAPER]: { title: paper.title, steps: paper.steps } } : {}),
      ...workspace?.starters,
    }),
    [paper, workspace],
  );
  const before = useMemo(() => locations(steps), [steps]);

  if (failed)
    return (
      <p className={c.notice} role="alert">
        The cloud lab workflow could not be opened. Reload to try again.
      </p>
    );
  if (!workspace) return null;

  const samples = [...new Set(["plate", ...steps.map((st) => st.sample)])];
  const errorAt = check?.error?.step ?? null;
  const edit = (index: number, change: Partial<Step>) =>
    setSteps(
      steps.map((step, i) => {
        if (i !== index) return step;
        const next = { ...step, ...change };
        const instrument = byId[next.instrument];
        // A changed instrument or action starts from values that instrument accepts.
        if (
          change.instrument &&
          !operationsFor(instrument).includes(next.operation)
        )
          next.operation = operationsFor(instrument)[0];
        if (change.instrument || change.operation) {
          next.value = defaultValue(instrument, next.operation);
          next.slot = "";
        }
        return next;
      }),
    );
  const add = (instrument: Instrument) => {
    const sample = steps.at(-1)?.sample ?? "plate";
    const at = before[steps.length][sample];
    const operation: Operation = !at
      ? "load"
      : at !== instrument.id && instrument.operations.includes("load")
        ? "transfer"
        : (instrument.operations.find((op) => op !== "load") ?? "wait");
    setSteps([
      ...steps,
      {
        instrument: instrument.id,
        operation,
        sample,
        value: defaultValue(instrument, operation),
        slot: "",
      },
    ]);
  };
  const move = (index: number, offset: number) => {
    const next = [...steps];
    [next[index], next[index + offset]] = [next[index + offset], next[index]];
    setSteps(next);
  };
  const perform = async (task: () => Promise<Workspace>) => {
    setBusy(true);
    try {
      adopt(await task());
    } catch (error) {
      onError(
        error instanceof ApiError && error.status === 409
          ? "This workflow changed in another tab. Reload to see its latest version."
          : (error as Error).message,
      );
    } finally {
      setBusy(false);
    }
  };
  const save = () =>
    api<Workspace>(
      "/cloudlab/workflow",
      json(
        { expected_version: workspace.version, title: title.trim(), steps },
        "PUT",
      ),
    );
  const run = () =>
    perform(async () => {
      const saved = dirty ? await save() : workspace;
      const next = await api<Workspace & { earned: Earned | null }>(
        "/cloudlab/workflow/run",
        json({ expected_version: saved.version }),
      );
      setEarned(next.earned);
      return next;
    });
  const titleOf = (id: string) => workflows.find((w) => w.id === id)?.title;
  const gains = earned
    ? [
        ...earned.papers.map((id) => `Reproduced ${titleOf(id)}`),
        ...earned.swapped.map(
          (id) => `Swapped an instrument in ${titleOf(id)}`,
        ),
        ...earned.extended.map(
          ([id, f]) => `Added ${f.replace("-", " ")} to ${titleOf(id)}`,
        ),
        ...earned.recombined.map(
          ([a, b]) => `Recombined ${titleOf(a)} → ${titleOf(b)}`,
        ),
        ...earned.functions.map((f) => `Met ${f.replace("-", " ")}`),
      ]
    : [];

  // The flow: instruments in the order the workflow first uses them.
  const used = [...new Set(steps.map((st) => st.instrument))].filter(
    (id) => byId[id],
  );
  const shown = check?.ok ? check.trace : [];
  const final = shown.at(-1);
  const latest = workspace.runs[0];
  const ran = latest && !dirty && check?.ok ? latest : null;
  const blocked = !steps.length
    ? "Add a step to run the workflow."
    : check?.error
      ? `Change step ${check.error.step ?? ""} first.`
      : "";

  return (
    <div className={s.studio} data-testid="cloudlab-workflow">
      <div className={s.topline}>
        <button className={s.textButton} onClick={onBack}>
          <ArrowLeft size={16} /> Meet the instruments
        </button>
        <span className={s.evidence}>
          <i /> Synthetic teaching model
        </span>
      </div>
      <header className={s.heading}>
        <h1>
          Cloud lab workflow<span>.</span>
        </h1>
        <div className={s.headerActions}>
          <span className={s.saved} role="status">
            {busy ? (
              "Updating…"
            ) : dirty ? (
              "Unsaved changes"
            ) : (
              <>
                <Check size={14} /> Saved
              </>
            )}
          </span>
          <button
            className={s.secondary}
            disabled={busy || !dirty || !title.trim()}
            onClick={() => perform(save)}
          >
            <Save size={16} /> Save workflow
          </button>
        </div>
      </header>
      <div className={s.nameRow}>
        <label>
          WORKFLOW NAME
          <input
            aria-label="Workflow name"
            maxLength={80}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <span className={`${s.status} ${check?.error ? s.faultStatus : ""}`}>
          {!steps.length
            ? "Empty"
            : check?.error
              ? `Step ${check.error.step ?? "?"} breaks a rule`
              : "Every step fits"}
        </span>
      </div>
      <div className={s.columns}>
        <section className={s.plan} aria-label="Workflow steps">
          <div className={s.sectionHeading}>
            <h2>Workflow</h2>
            <span>
              {steps.length} / {MAX_STEPS} steps
            </span>
          </div>
          <div className={s.starterRow}>
            <label>
              Start from
              <select
                aria-label="Workflow starter"
                value={starter}
                onChange={(event) => setStarter(event.target.value)}
              >
                {Object.entries(starters).map(([key, value]) => (
                  <option key={key} value={key}>
                    {value.title}
                  </option>
                ))}
              </select>
            </label>
            <button
              className={s.textButton}
              disabled={!starter}
              onClick={() => {
                const chosen = starters[starter];
                if (
                  steps.length &&
                  !window.confirm("Replace your steps with this starter?")
                )
                  return;
                setSteps(chosen.steps);
                setTitle(chosen.title);
              }}
            >
              Load starter
            </button>
          </div>
          <div
            className={`${s.palette} ${c.palette}`}
            role="group"
            aria-label="Add a step"
          >
            {instruments.map((instrument) => (
              <button
                key={instrument.id}
                className={TONES[instrument.section]}
                disabled={steps.length >= MAX_STEPS}
                onClick={() => add(instrument)}
                aria-label={`Add a ${instrument.name} step`}
              >
                <Plus size={14} /> {instrument.name}
              </button>
            ))}
          </div>
          <ol className={s.blockList}>
            {steps.map((step, index) => {
              const instrument = byId[step.instrument];
              const value = VALUES[step.operation];
              const wrong = errorAt === index + 1;
              return (
                <li
                  key={index}
                  className={`${s.block} ${TONES[instrument.section]} ${wrong ? c.wrongBlock : ""}`}
                  data-testid={`cloudlab-step-${index + 1}`}
                  aria-invalid={wrong || undefined}
                >
                  <div className={s.blockTop}>
                    <span className={s.blockNumber}>
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <select
                      aria-label={`Step ${index + 1} instrument`}
                      value={step.instrument}
                      onChange={(event) =>
                        edit(index, { instrument: event.target.value })
                      }
                    >
                      {instruments.map((option) => (
                        <option key={option.id} value={option.id}>
                          {option.name}
                        </option>
                      ))}
                    </select>
                    <div className={s.blockTools}>
                      <button
                        aria-label={`Move step ${index + 1} up`}
                        disabled={index === 0}
                        onClick={() => move(index, -1)}
                      >
                        <ArrowUp size={14} />
                      </button>
                      <button
                        aria-label={`Move step ${index + 1} down`}
                        disabled={index === steps.length - 1}
                        onClick={() => move(index, 1)}
                      >
                        <ArrowDown size={14} />
                      </button>
                      <button
                        aria-label={`Duplicate step ${index + 1}`}
                        disabled={steps.length >= MAX_STEPS}
                        onClick={() =>
                          setSteps([
                            ...steps.slice(0, index + 1),
                            { ...step },
                            ...steps.slice(index + 1),
                          ])
                        }
                      >
                        <Copy size={14} />
                      </button>
                      <button
                        aria-label={`Delete step ${index + 1}`}
                        onClick={() =>
                          setSteps(steps.filter((_, i) => i !== index))
                        }
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                  <div className={`${s.blockParameters} ${c.parameters}`}>
                    <label>
                      ACTION
                      <select
                        aria-label={`Step ${index + 1} action`}
                        value={step.operation}
                        onChange={(event) =>
                          edit(index, {
                            operation: event.target.value as Operation,
                          })
                        }
                      >
                        {operationsFor(instrument).map((op) => (
                          <option key={op} value={op}>
                            {LABELS[op]}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      SAMPLE
                      <select
                        aria-label={`Step ${index + 1} sample`}
                        value={step.sample}
                        onChange={(event) =>
                          edit(index, {
                            sample:
                              event.target.value === "+"
                                ? `plate-${samples.length + 1}`
                                : event.target.value,
                          })
                        }
                      >
                        {samples.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                        <option value="+">New sample</option>
                      </select>
                    </label>
                    {value && (
                      <label>
                        {value[0]}
                        <span className={s.volumeInput}>
                          <input
                            type="number"
                            aria-label={`Step ${index + 1} ${value[0].toLowerCase()}`}
                            min={step.operation === "heat" ? 4 : 1}
                            max={step.operation === "heat" ? 120 : 1000000}
                            value={step.value}
                            onChange={(event) =>
                              edit(index, {
                                value: Math.max(
                                  0.001,
                                  Number(event.target.value) || 0,
                                ),
                              })
                            }
                          />
                          <span>{value[1]}</span>
                        </span>
                      </label>
                    )}
                    {(step.operation === "load" ||
                      step.operation === "transfer") &&
                      instrument.slots.length > 1 && (
                        <label>
                          SLOT
                          <select
                            aria-label={`Step ${index + 1} slot`}
                            value={step.slot}
                            onChange={(event) =>
                              edit(index, { slot: event.target.value })
                            }
                          >
                            <option value="">First free</option>
                            {instrument.slots.map((slot) => (
                              <option key={slot} value={slot}>
                                {slot}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}
                  </div>
                  {wrong && (
                    <p className={c.reason} role="alert">
                      <TriangleAlert size={13} />{" "}
                      {check?.error?.message.replace(/^Step \d+: /, "")}
                    </p>
                  )}
                </li>
              );
            })}
          </ol>
          {!steps.length && (
            <div className={s.empty}>
              <Layers3 size={30} />
              <h3>Chain instruments by what they do.</h3>
              <p>
                Load a plate where it starts, then add steps on the instruments
                it visits. Or load a starter above.
              </p>
            </div>
          )}
        </section>
        <aside className={s.preview}>
          <section
            className={s.runPanel}
            aria-label="Teaching simulation controls"
          >
            <div className={s.runTop}>
              <span>
                <Workflow size={17} /> TEACHING SIMULATION
              </span>
              <strong>{final ? `${format(final.elapsed_s)} s` : "—"}</strong>
            </div>
            <p className={s.runMessage}>
              {blocked ||
                (ran
                  ? `Run ${new Date(ran.at).toLocaleTimeString()} finished.`
                  : dirty
                    ? "Changes save when you run."
                    : "Ready to run.")}
            </p>
            <button
              className={s.primary}
              disabled={busy || !!blocked || !title.trim()}
              onClick={run}
            >
              <Play size={18} /> Run teaching simulation
            </button>
          </section>
          <section className={s.deckPanel} aria-label="Flow">
            <div className={s.sectionHeading}>
              <h2>Flow</h2>
            </div>
            {used.length ? (
              <ol className={c.flow}>
                {used.map((id, position) => {
                  const instrument = byId[id];
                  const here = Object.entries(final?.samples ?? {}).filter(
                    ([, state]) => state.location === id,
                  );
                  const stock = final?.consumables[id];
                  return (
                    <li
                      key={id}
                      className={`${c.station} ${TONES[instrument.section]}`}
                      aria-label={instrument.name}
                    >
                      {position > 0 && (
                        <ArrowRight className={c.arrow} size={14} />
                      )}
                      <strong>{instrument.name}</strong>
                      <span className={c.ops}>
                        {steps
                          .map((st, i) => ({ st, i }))
                          .filter(({ st }) => st.instrument === id)
                          .map(({ st, i }) => (
                            <i
                              key={i}
                              className={errorAt === i + 1 ? c.wrongOp : ""}
                            >
                              {i + 1} {LABELS[st.operation]}
                            </i>
                          ))}
                      </span>
                      <span
                        className={c.slots}
                        role="img"
                        aria-label={`${here.length} of ${instrument.slots.length} slots in use`}
                      >
                        {instrument.slots.map((slot) => {
                          const held = here.find(
                            ([, state]) => state.site === slot,
                          );
                          return (
                            <i
                              key={slot}
                              className={held ? c.held : ""}
                              title={held ? `${slot}: ${held[0]}` : slot}
                            />
                          );
                        })}
                      </span>
                      <small>
                        {instrument.holds.vessel} ·{" "}
                        {format(instrument.holds.max_volume_ul)} µL
                        {instrument.operations.includes("heat") &&
                          ` · ${instrument.limits.min_temp_c}–${instrument.limits.max_temp_c} °C`}
                        {stock &&
                          Object.entries(stock).map(
                            ([name, left]) =>
                              ` · ${left} ${name.toLowerCase()} left`,
                          )}
                      </small>
                    </li>
                  );
                })}
              </ol>
            ) : (
              <p className={c.quiet}>
                Instruments appear here as the workflow uses them.
              </p>
            )}
          </section>
          {ran && (
            <section className={s.deckPanel} aria-label="Run result">
              <div className={s.sectionHeading}>
                <h2>Run result</h2>
                <span>{ran.trace.length} steps</span>
              </div>
              {!!gains.length && (
                <div className={k.earned} aria-live="polite">
                  <strong>New on your skill tree</strong>
                  {gains.map((gain) => (
                    <span key={gain}>{gain}</span>
                  ))}
                  {onSkills && (
                    <button onClick={onSkills}>
                      See the tree <ArrowRight size={14} />
                    </button>
                  )}
                </div>
              )}
              <ol className={c.trace}>
                {ran.trace.map((entry) => (
                  <li key={entry.step}>
                    <span className={s.blockNumber}>
                      {String(entry.step).padStart(2, "0")}
                    </span>
                    <span>
                      {byId[entry.device_id]?.name} · {LABELS[entry.operation]}{" "}
                      {entry.sample}
                    </span>
                    <strong>
                      {entry.measurement
                        ? `Synthetic readout: ${format(entry.volume_ul)} µL · ${format(entry.temperature_c)} °C${entry.mixed ? " · mixed" : ""}`
                        : `${format(entry.elapsed_s)} s`}
                    </strong>
                  </li>
                ))}
              </ol>
            </section>
          )}
          <details className={c.about}>
            <summary>Where the rules come from</summary>
            <p>{workspace.statement}</p>
            <ul>
              {used.map((id) => (
                <li key={id}>
                  <strong>{byId[id].name}</strong> ({byId[id].experiment}):{" "}
                  {byId[id].published}. {byId[id].narrowed}
                  {byId[id].stand_in &&
                    ` Comparable instrument: ${byId[id].stand_in}.`}
                </li>
              ))}
            </ul>
          </details>
        </aside>
      </div>
    </div>
  );
}
