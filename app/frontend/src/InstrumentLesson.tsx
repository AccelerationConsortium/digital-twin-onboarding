import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Box,
  Copy,
  ExternalLink,
  Layers3,
  Pause,
  Play,
  Plus,
  RotateCcw,
  SkipForward,
  Trash2,
  TriangleAlert,
  Workflow,
} from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import { api, json } from "./api";
import {
  BASIS_NAMES,
  basisLabel,
  metres,
  part,
  sourceUrl,
  volume,
  type Instrument,
  type Overview,
} from "./cloudlabFacts";
import type { Operation } from "./instrumentTypes";
import TwinAnatomy from "./TwinAnatomy";
import TwinExplorer, { useTwin } from "./TwinExplorer";
import s from "./WorkflowStudio.module.css";
import c from "./CloudLabWorkflow.module.css";
import l from "./InstrumentLesson.module.css";

type Action = Exclude<Operation, "transfer">;
type Step = { operation: Action; sample: string; value: number; slot: string };
type Entry = {
  step: number;
  operation: Action;
  elapsed_s: number;
  consumables: Record<string, Record<string, number>>;
  samples: Record<
    string,
    {
      location: string | null;
      site: string | null;
      volume_ul: number;
      temperature_c: number;
      mixed: boolean;
    }
  >;
  measurement: { kind: string } | null;
};
type Check = {
  ok: boolean;
  trace: Entry[];
  error: { step: number | null; message: string } | null;
  statement: string;
};

const MAX_STEPS = 24;
const PACE_MS = 1100;
const LABELS: Record<Action, string> = {
  load: "Load",
  mix: "Mix",
  heat: "Hold temperature",
  read: "Read",
  wait: "Wait",
};
const VALUES: Partial<Record<Action, [string, string]>> = {
  load: ["VOLUME", "µL"],
  heat: ["TEMPERATURE", "°C"],
  mix: ["FOR", "s"],
  wait: ["FOR", "s"],
};
const TONES: Record<Action, string> = {
  load: s.pickup,
  mix: s.aspirate,
  heat: s.dispense,
  read: s.read,
  wait: s.drop,
};
const format = (value: number) => Number(value.toFixed(1)).toLocaleString();
const remembered = (id: string): Step[] | null => {
  try {
    const kept = window.localStorage.getItem(`academy:instrument-steps:${id}`);
    return kept ? (JSON.parse(kept) as Step[]) : null;
  } catch {
    return null;
  }
};
const remember = (id: string, steps: Step[]) => {
  try {
    window.localStorage.setItem(
      `academy:instrument-steps:${id}`,
      JSON.stringify(steps),
    );
  } catch {
    // A private window keeps the steps for this visit only.
  }
};

/** How a sample goes in, in one sentence; where each figure comes from is under Sources. */
const goesIn = (item: Instrument) =>
  `${item.access === "front" ? "Through the front" : "From above"}${part(item.opening)}` +
  (item.level_m !== null
    ? `, ${item.level_m.toFixed(2)} m above the bench`
    : "") +
  (item.drawer_m !== null
    ? `; its drawer comes out ${item.drawer_m.toFixed(2)} m`
    : "");

/** One cloud lab instrument on its own: compose steps on its twin and watch them run. */
export default function InstrumentLesson({
  id,
  onOpen,
  onBack,
  onWorkflow,
}: {
  id: string;
  onOpen: (id: string) => void;
  onBack: () => void;
  onWorkflow: () => void;
}) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    setFailed(false);
    api<Overview>("/cloudlab/instruments")
      .then((found) => alive && setOverview(found))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [attempt]);

  if (failed)
    return (
      <p className={l.failed}>
        The instrument could not be loaded.{" "}
        <button onClick={() => setAttempt((n) => n + 1)}>Try again</button>
      </p>
    );
  if (!overview) return <div className={s.studio} aria-busy="true" />;
  const at = overview.instruments.findIndex((i) => i.id === id);
  if (at < 0)
    return (
      <p className={l.failed}>
        There is no cloud lab instrument here.{" "}
        <button onClick={onBack}>Meet the instruments</button>
      </p>
    );
  return (
    <Studio
      // A fresh studio, at rest, for each instrument.
      key={id}
      item={overview.instruments[at]}
      overview={overview}
      next={overview.instruments[(at + 1) % overview.instruments.length]}
      onOpen={onOpen}
      onBack={onBack}
      onWorkflow={onWorkflow}
    />
  );
}

function Studio({
  item,
  overview,
  next,
  onOpen,
  onBack,
  onWorkflow,
}: {
  item: Instrument;
  overview: Overview;
  next: Instrument;
  onOpen: (id: string) => void;
  onBack: () => void;
  onWorkflow: () => void;
}) {
  const twin = useTwin(item.motion);
  const actions = item.operations.filter(
    (op): op is Action => op !== "transfer",
  );
  const starter = item.starter as Step[];
  const [steps, setSteps] = useState<Step[]>(
    () => remembered(item.id) ?? starter,
  );
  const [check, setCheck] = useState<Check | null>(null);
  // Steps of the latest run shown so far, and whether the run plays on its own.
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const checked = useRef(0);

  // Every edit is checked against the twin's rules; only the latest answer counts.
  useEffect(() => {
    remember(item.id, steps);
    setCursor(0);
    setPlaying(false);
    const ticket = ++checked.current;
    const timer = window.setTimeout(() => {
      api<Check>(`/cloudlab/instruments/${item.id}/check`, json({ steps }))
        .then((found) => ticket === checked.current && setCheck(found))
        .catch(() => undefined);
    }, 200);
    return () => window.clearTimeout(timer);
  }, [steps, item.id]);

  const trace = check?.ok ? check.trace : [];
  useEffect(() => {
    if (!playing) return;
    if (cursor >= trace.length) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(() => setCursor((n) => n + 1), PACE_MS);
    return () => window.clearTimeout(timer);
  }, [playing, cursor, trace.length]);
  // The model shows the step that just ran, where one of its states shows that action.
  const { press, motion } = twin;
  useEffect(() => {
    const ran = trace[cursor - 1];
    const shows = motion?.states.find((x) => x.shows === ran?.operation);
    if (shows) press(shows.id);
    // Only a new step moves the model; a learner's own clicks stay put meanwhile.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursor]);

  const errorAt = check?.error?.step ?? null;
  const samples = [...new Set(["plate", ...steps.map((st) => st.sample)])];
  const edit = (index: number, change: Partial<Step>) =>
    setSteps(steps.map((st, i) => (i === index ? { ...st, ...change } : st)));
  const move = (index: number, offset: number) => {
    const moved = [...steps];
    [moved[index], moved[index + offset]] = [
      moved[index + offset],
      moved[index],
    ];
    setSteps(moved);
  };
  const add = (operation: Action) =>
    setSteps([
      ...steps,
      {
        operation,
        sample: steps.at(-1)?.sample ?? "plate",
        value:
          starter.find((st) => st.operation === operation)?.value ??
          (operation === "load" ? 100 : 60),
        slot: "",
      },
    ]);
  const shown = trace[cursor - 1];
  const here = Object.entries(shown?.samples ?? {}).filter(
    ([, state]) => state.location === item.id,
  );
  const stock = shown?.consumables[item.id];
  const blocked = !steps.length
    ? "Add a step to run it."
    : check?.error
      ? `Change step ${check.error.step ?? ""} first.`
      : "";
  const done = trace.length > 0 && cursor >= trace.length;

  return (
    <div className={s.studio} data-testid="instrument-studio">
      <div className={s.topline}>
        <button className={s.textButton} onClick={onBack}>
          <ArrowLeft size={16} /> Meet the instruments
        </button>
        <span className={s.evidence}>
          <i /> Synthetic teaching model
        </span>
      </div>
      <p className={s.eyebrow}>Cloud lab · {item.section}</p>
      <header className={s.heading}>
        <div>
          <h1>
            {item.name}
            <span>.</span>
          </h1>
          <p className={l.does}>{item.does}</p>
        </div>
      </header>

      <div className={s.columns}>
        <section className={s.plan} aria-label="Steps">
          <div className={s.sectionHeading}>
            <h2>Use it</h2>
            <span>
              {steps.length} / {MAX_STEPS} steps
            </span>
          </div>
          <div className={s.starterRow}>
            <span
              className={`${s.status} ${check?.error ? s.faultStatus : ""}`}
            >
              {!steps.length
                ? "Empty"
                : check?.error
                  ? `Step ${check.error.step ?? "?"} breaks a rule`
                  : "Every step fits"}
            </span>
            <button
              className={s.textButton}
              onClick={() => {
                if (
                  steps.length &&
                  !window.confirm("Replace your steps with every action once?")
                )
                  return;
                setSteps(starter);
              }}
            >
              Start again
            </button>
          </div>
          <div className={s.palette} role="group" aria-label="Add a step">
            {actions.map((op) => (
              <button
                key={op}
                className={TONES[op]}
                disabled={steps.length >= MAX_STEPS}
                onClick={() => add(op)}
              >
                <Plus size={14} /> {LABELS[op]}
              </button>
            ))}
          </div>
          <ol className={s.blockList}>
            {steps.map((step, index) => {
              const value = VALUES[step.operation];
              const wrong = errorAt === index + 1;
              const says = item.steps.find(
                (st) => st.operation === step.operation,
              )?.says;
              return (
                <li
                  key={index}
                  className={`${s.block} ${TONES[step.operation]} ${wrong ? c.wrongBlock : ""} ${cursor > 0 && index === cursor - 1 ? s.currentBlock : ""} ${index < cursor - 1 ? s.doneBlock : ""}`}
                  data-testid={`instrument-step-${index + 1}`}
                  aria-invalid={wrong || undefined}
                  aria-current={
                    cursor > 0 && index === cursor - 1 ? "step" : undefined
                  }
                >
                  <div className={s.blockTop}>
                    <span className={s.blockNumber}>
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <strong>{LABELS[step.operation]}</strong>
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
                  {step.operation === "read" ? (
                    <p className={s.blockHint}>{says}</p>
                  ) : (
                    <div className={`${s.blockParameters} ${c.parameters}`}>
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
                          {step.operation === "load" && (
                            <option value="+">New sample</option>
                          )}
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
                      {step.operation === "load" && item.sites.length > 1 && (
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
                            {item.sites.map((slot) => (
                              <option key={slot} value={slot}>
                                {slot}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}
                    </div>
                  )}
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
              <h3>Start with a load.</h3>
              <p>
                Put a {item.holds.vessel} in, then add what the instrument does
                to it.
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
              <strong>
                {cursor} / {trace.length || steps.length}
              </strong>
            </div>
            <div className={s.progress}>
              <i
                style={{
                  width: `${trace.length ? (cursor / trace.length) * 100 : 0}%`,
                }}
              />
            </div>
            <p className={s.runMessage} aria-live="polite">
              {blocked ||
                (shown
                  ? `Step ${cursor}: ${LABELS[shown.operation]} ${
                      shown.measurement ? "gives a synthetic readout" : "done"
                    }${done ? ". Run finished." : "."}`
                  : "Ready to run.")}
            </p>
            <button
              className={s.primary}
              disabled={!!blocked}
              onClick={() => {
                if (playing) return setPlaying(false);
                if (done) setCursor(0);
                setPlaying(true);
              }}
            >
              {playing ? <Pause size={18} /> : <Play size={18} />}{" "}
              {playing ? "Pause" : "Run teaching simulation"}
            </button>
            <div className={s.runSecondary}>
              <button
                className={s.textButton}
                disabled={!!blocked || playing || done}
                onClick={() => setCursor((n) => n + 1)}
              >
                <SkipForward size={15} /> Advance one step
              </button>
              <button
                className={s.textButton}
                disabled={cursor === 0}
                onClick={() => {
                  setPlaying(false);
                  setCursor(0);
                }}
              >
                <RotateCcw size={14} /> Reset run
              </button>
            </div>
            <div className={s.pipetteState} aria-label="Sample">
              {shown?.samples.plate ? (
                <>
                  <span>{format(shown.samples.plate.volume_ul)} µL</span>
                  <span>{format(shown.samples.plate.temperature_c)} °C</span>
                  <span>{format(shown.elapsed_s)} s</span>
                </>
              ) : (
                <span>No sample in yet</span>
              )}
              {stock &&
                Object.entries(stock).map(([name, left]) => (
                  <span key={name}>
                    {left} {name.toLowerCase()} left
                  </span>
                ))}
            </div>
          </section>

          <section className={s.deckPanel} aria-label="Instrument">
            <div className={s.sectionHeading}>
              <h2>Instrument</h2>
              <span>{item.mesh ? "3D" : "ESTIMATED BOX"}</span>
            </div>
            {item.mesh ? (
              <TwinExplorer mesh={item.mesh} twin={twin} />
            ) : (
              <div className={l.noModel}>
                <Box size={26} aria-hidden="true" />
                <span>No 3D model; the twin is one estimated box.</span>
              </div>
            )}
            <div
              className={l.slots}
              role="img"
              aria-label={`${here.length} of ${item.sites.length} slots in use`}
            >
              {item.sites.slice(0, 96).map((slot) => {
                const held = here.find(([, state]) => state.site === slot);
                return (
                  <i
                    key={slot}
                    className={held ? l.held : ""}
                    title={held ? `${slot}: ${held[0]}` : slot}
                  />
                );
              })}
            </div>
            <p className={l.caption}>
              {item.slots} × {item.holds.vessel}, up to{" "}
              {volume(item.holds.max_volume_ul)} · {goesIn(item)}
            </p>
          </section>

          <details className={c.about}>
            <summary>About this instrument</summary>
            <p>{item.published}.</p>
            {item.narrowed && <p>{item.narrowed}</p>}
            <dl className={l.facts}>
              {item.operations.includes("heat") && (
                <>
                  <dt>Temperature</dt>
                  <dd>
                    {item.limits.min_temp_c}–{item.limits.max_temp_c} °C
                  </dd>
                </>
              )}
              <dt>Longest step</dt>
              <dd>{Math.round(item.limits.max_duration_s / 60)} min</dd>
              {item.consumables.map((x) => (
                <Fragment key={x.name}>
                  <dt>Consumable</dt>
                  <dd>
                    {x.name}, {x.stock} in stock
                  </dd>
                </Fragment>
              ))}
              <dt>Size</dt>
              <dd>
                {metres(item.size_m)} ·{" "}
                {basisLabel(item.geometry_basis.size, item)}
              </dd>
            </dl>
            <ul>
              {Object.entries(item.geometry_basis).map(([key, basis]) => {
                const url = sourceUrl(basis);
                return (
                  <li key={key}>
                    <strong>{BASIS_NAMES[key] ?? key}</strong>{" "}
                    {url ? (
                      <a href={url} target="_blank" rel="noreferrer">
                        {basis.replace(`, ${url}`, "")}
                      </a>
                    ) : (
                      basis
                    )}
                  </li>
                );
              })}
            </ul>
            <p>{check?.statement}</p>
          </details>
        </aside>
      </div>

      {item.mesh && item.anatomy && (
        <section className={l.anatomy} aria-label="Anatomy">
          <div className={s.sectionHeading}>
            <h2>Inside</h2>
          </div>
          <TwinAnatomy mesh={item.mesh} anatomy={item.anatomy} />
        </section>
      )}

      <footer className={l.footer}>
        <p className={l.fine}>
          Synthetic teaching twin, not this instrument's specification.{" "}
          {item.stand_in && `${item.attribution}. `}
          <a href={overview.source} target="_blank" rel="noreferrer">
            {overview.provider} instrumentation{" "}
            <ExternalLink size={12} aria-hidden="true" />
          </a>{" "}
          · read {overview.retrieved}
        </p>
        <div className={l.onward}>
          {item.in_workflow && (
            <button className={l.next} onClick={onWorkflow}>
              <span>
                <small>Then</small>
                <strong>Chain it with other instruments</strong>
              </span>
              <ArrowRight size={16} aria-hidden="true" />
            </button>
          )}
          <button className={l.next} onClick={() => onOpen(next.id)}>
            <span>
              <small>Next instrument</small>
              <strong>{next.name}</strong>
            </span>
            <ArrowRight size={16} aria-hidden="true" />
          </button>
        </div>
      </footer>
    </div>
  );
}
