import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Play, RotateCcw, SkipForward, Square } from "lucide-react";
import { api, json } from "./api";
import {
  operationLabels,
  type InstrumentCatalog,
  type Layout,
  type Operation,
  type TwinSpec,
  type Vec,
} from "./instrumentTypes";
import studio from "./InstrumentStudio.module.css";
import s from "./MonitoredRun.module.css";

const TwinScene = lazy(() => import("./TwinScene"));

type Scalar = number | string | boolean | null;
type Difference = {
  field: string;
  expected: Scalar;
  observed: Scalar;
  delta?: number;
};
type Change = { field: string; before: Scalar; after: Scalar };
type TwinState = {
  samples: Record<string, { location: string | null; volume_ul: number }>;
  stock: Record<string, Record<string, number>>;
  placements: Record<string, { x: number; z: number; yaw: number }>;
};
type Pause = {
  kind: "predicted" | "motion" | "diverged" | "failed";
  layer: "lookahead" | "motion" | "divergence" | "executor";
  step: number;
  code: string;
  message: string;
  fields: Difference[];
};
type RunStep = {
  device_id: string;
  operation: Operation;
  source_id: string | null;
  target_id: string | null;
  value: number;
  sample?: string;
};
export type MonitoredRunRecord = {
  run_id: string;
  version: number;
  workspace_version: number;
  status: "ready" | "paused" | "blocked" | "failed" | "completed" | "stopped";
  evidence: "synthetic";
  physical_execution: false;
  executor: { kind: string; transport: string };
  twins: { id: string; spec: TwinSpec; confirmed: boolean }[];
  steps: RunStep[];
  layout: Layout | null;
  horizon: number;
  cursor: number;
  twin: TwinState;
  initial: { observed: TwinState };
  pause: Pause | null;
  pauses: Pause[];
  prediction: {
    checked: number[];
    failure: { step: number; code: string; message: string } | null;
  } | null;
  next: {
    step: number;
    operation: Operation;
    device_id: string;
    source_id: string | null;
    target_id: string | null;
    sample: string;
    changes: Change[];
    motion: {
      planner: string;
      length_m: number;
      seconds: number;
      replanned: boolean;
      joints: number[][];
      path: Vec[];
    } | null;
  } | null;
  trace: { step: number; status: string; divergence: Difference[] }[];
  faults: { kind: string }[];
};
type Replay = {
  original: { status: string; step: number | null; message: string };
  replay: { status: string; step: number | null; message: string };
  avoided: boolean | null;
  assumption: string;
};

type FaultKind =
  | ""
  | "tip_shortfall"
  | "volume_loss"
  | "door_open"
  | "gripper_stuck"
  | "layout_shift";
const FAULTS: Record<FaultKind, string> = {
  "": "No fault",
  tip_shortfall: "Rack holds fewer than declared",
  volume_loss: "Liquid lost after a step",
  door_open: "Door left open after a step",
  gripper_stuck: "Gripper keeps the sample",
  layout_shift: "Instrument shifted on the bench",
};
const LAYERS: Record<Pause["layer"], string> = {
  lookahead: "Twin lookahead",
  motion: "Arm path check",
  divergence: "Twin and executor differ",
  executor: "Executor refused the step",
};
const key = "academy-twin-run";

export default function MonitoredRun({
  catalog,
  disabled,
}: {
  catalog: InstrumentCatalog;
  disabled: boolean;
}) {
  const [run, setRun] = useState<MonitoredRunRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [kind, setKind] = useState<FaultKind>("");
  const [device, setDevice] = useState("");
  const [consumable, setConsumable] = useState("");
  const [amount, setAmount] = useState(3);
  const [step, setStep] = useState(1);
  const [horizon, setHorizon] = useState(3);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [edits, setEdits] = useState<Record<string, number>>({});
  const lock = useRef(false);

  useEffect(() => {
    const id = sessionStorage.getItem(key);
    if (id)
      api<MonitoredRunRecord>(`/twin-runs/${id}`)
        .then(setRun)
        .catch(() => sessionStorage.removeItem(key));
  }, []);

  const twins = catalog.twins.filter((t) => t.confirmed && t.spec);
  const names = new Map((run?.twins ?? twins).map((t) => [t.id, t.spec!.name]));
  const name = (id: string | null | undefined) => (id && names.get(id)) ?? "—";
  const choices =
    kind === "tip_shortfall"
      ? twins.filter((t) => t.spec!.consumables.length)
      : kind === "door_open"
        ? twins.filter((t) => t.spec!.access === "front")
        : kind === "layout_shift"
          ? twins.filter((t) =>
              catalog.layout?.placements.some((p) => p.twin_id === t.id),
            )
          : [];
  const chosen = choices.find((t) => t.id === device) ?? choices[0];
  const items = chosen?.spec!.consumables ?? [];
  const item = items.find((c) => c.name === consumable) ?? items[0];
  const transfers = catalog.steps
    .map((st, i) => ({ st, n: i + 1 }))
    .filter(({ st }) => st.operation === "transfer");

  function fault() {
    if (!kind) return [];
    if (kind === "tip_shortfall")
      return [
        {
          kind,
          device_id: chosen?.id,
          consumable: item?.name,
          actual: amount,
        },
      ];
    if (kind === "volume_loss") return [{ kind, step, loss_ul: amount }];
    if (kind === "door_open") return [{ kind, step, device_id: chosen?.id }];
    if (kind === "gripper_stuck")
      return [
        {
          kind,
          step: transfers.some((t) => t.n === step) ? step : transfers[0]?.n,
        },
      ];
    return [{ kind, step: 0, twin_id: chosen?.id, dx: amount / 100, dz: 0 }];
  }

  async function act(action: "create" | "step" | "run" | "resume" | "stop") {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      if (action === "create") {
        const id = crypto.randomUUID();
        const next = await api<MonitoredRunRecord>(
          "/twin-runs",
          json({
            run_id: id,
            expected_version: catalog.version,
            horizon,
            faults: fault(),
          }),
        );
        sessionStorage.setItem(key, id);
        setReplay(null);
        setEdits({});
        setRun(next);
      } else if (run) {
        setRun(
          await api<MonitoredRunRecord>(
            `/twin-runs/${run.run_id}/commands`,
            json({ expected_version: run.version, command: action }),
          ),
        );
      }
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "The run request failed.",
      );
      if (run)
        api<MonitoredRunRecord>(`/twin-runs/${run.run_id}`)
          .then(setRun)
          .catch(() => undefined);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  async function counterfactual() {
    if (!run || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    const stock: Record<string, Record<string, number>> = {};
    for (const [field, value] of Object.entries(edits)) {
      const [dev, ...rest] = field.split(".");
      (stock[dev] ??= {})[rest.join(".")] = value;
    }
    try {
      setReplay(
        await api<Replay>(
          `/twin-runs/${run.run_id}/counterfactual`,
          json({ stock }),
        ),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The replay failed.");
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  const shown: Layout | null = run?.layout
    ? {
        ...run.layout,
        placements: run.layout.placements.map((p) => ({
          ...p,
          ...run.twin.placements[p.twin_id],
        })),
      }
    : null;
  const ghost = run?.next;
  const ahead =
    run?.prediction?.failure && run.prediction.failure.step !== run.pause?.step
      ? run.prediction.failure
      : null;
  const stopped = run && run.pauses.length > 0;
  const stock = Object.entries(run?.initial.observed.stock ?? {}).flatMap(
    ([dev, entries]) =>
      Object.entries(entries).map(([item, count]) => ({
        field: `${dev}.${item}`,
        label: `${name(dev)} · ${item}`,
        // What the rack turned out to hold: as observed at the start, plus every
        // difference found once it was used.
        count: (run?.trace ?? []).reduce(
          (total, entry) =>
            total +
            entry.divergence
              .filter((d) => d.field === `stock.${dev}.${item}`)
              .reduce((sum, d) => sum + (d.delta ?? 0), 0),
          count,
        ),
      })),
  );

  return (
    <section className={s.monitor} aria-labelledby="monitored-run-title">
      <h3 id="monitored-run-title">Run with the twin ahead</h3>
      <div className={s.setup}>
        <label className={studio.field}>
          Mock fault
          <select
            value={kind}
            disabled={busy}
            onChange={(e) => setKind(e.target.value as FaultKind)}
          >
            {(Object.keys(FAULTS) as FaultKind[]).map((k) => (
              <option key={k} value={k}>
                {FAULTS[k]}
              </option>
            ))}
          </select>
        </label>
        {choices.length > 0 && (
          <label className={studio.field}>
            Instrument
            <select
              value={chosen?.id ?? ""}
              onChange={(e) => setDevice(e.target.value)}
            >
              {choices.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.spec!.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {kind === "tip_shortfall" && items.length > 1 && (
          <label className={studio.field}>
            Consumable
            <select
              value={item?.name ?? ""}
              onChange={(e) => setConsumable(e.target.value)}
            >
              {items.map((c) => (
                <option key={c.name}>{c.name}</option>
              ))}
            </select>
          </label>
        )}
        {(kind === "volume_loss" ||
          kind === "door_open" ||
          kind === "gripper_stuck") && (
          <label className={studio.field}>
            After step
            <input
              type="number"
              min={1}
              max={catalog.steps.length}
              value={step}
              onChange={(e) => setStep(Number(e.target.value))}
            />
          </label>
        )}
        {(kind === "tip_shortfall" ||
          kind === "volume_loss" ||
          kind === "layout_shift") && (
          <label className={studio.field}>
            {kind === "tip_shortfall"
              ? `Actually in the rack (declared ${item?.stock ?? 0})`
              : kind === "volume_loss"
                ? "Lost (µL)"
                : "Shift (cm)"}
            <input
              type="number"
              min={kind === "layout_shift" ? -50 : 0}
              max={kind === "layout_shift" ? 50 : undefined}
              value={amount}
              onChange={(e) => setAmount(Number(e.target.value))}
            />
          </label>
        )}
        <label className={studio.field}>
          Lookahead (steps)
          <input
            type="number"
            min={1}
            max={12}
            value={horizon}
            onChange={(e) => setHorizon(Number(e.target.value))}
          />
        </label>
      </div>
      <div className={studio.actions}>
        <button
          className={studio.secondary}
          disabled={disabled || busy || !catalog.steps.length}
          onClick={() => act("create")}
        >
          <RotateCcw size={14} />{" "}
          {run ? "New monitored run" : "Prepare monitored run"}
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {run && (
        <div className={s.run} aria-label="Monitored run">
          <div className={s.status} data-status={run.status}>
            <strong>
              Step {run.cursor}/{run.steps.length} · {run.status}
            </strong>
            <span>Synthetic · {run.executor.transport}</span>
          </div>
          <div className={studio.actions}>
            <button
              className={studio.primary}
              disabled={busy || run.status !== "ready"}
              onClick={() => act("step")}
            >
              <SkipForward size={14} /> Next step
            </button>
            <button
              className={studio.primary}
              disabled={busy || run.status !== "ready"}
              onClick={() => act("run")}
            >
              <Play size={14} /> Run to the end
            </button>
            <button
              className={studio.secondary}
              disabled={busy || !["paused", "blocked"].includes(run.status)}
              onClick={() => act("resume")}
            >
              <Play size={14} /> Resume
            </button>
            <button
              className={studio.secondary}
              disabled={
                busy || !["ready", "paused", "blocked"].includes(run.status)
              }
              onClick={() => act("stop")}
            >
              <Square size={14} /> Stop
            </button>
          </div>
          {run.pause && (
            <div className={s.pause} role="status" aria-label="Run paused">
              <strong>{LAYERS[run.pause.layer]}</strong>
              <p>{run.pause.message}</p>
              {run.pause.fields.length > 0 && (
                <table>
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th>Twin</th>
                      <th>Observed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.pause.fields.map((d) => (
                      <tr key={d.field}>
                        <td>{label(d.field, name)}</td>
                        <td>{value(d.expected, name)}</td>
                        <td>{value(d.observed, name)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
          {ghost && run.status !== "completed" && (
            <figure className={s.ghost} aria-label="Next move">
              <Suspense fallback={<div className={s.scene} />}>
                <div className={s.scene}>
                  <TwinScene
                    twins={run.twins}
                    layout={shown}
                    active={ghost.device_id}
                    sample={run.twin.samples[ghost.sample]?.location ?? null}
                    armActor={ghost.motion ? ghost.device_id : null}
                    armJoints={ghost.motion?.joints[0] ?? null}
                    path={ghost.motion?.path ?? null}
                  />
                </div>
              </Suspense>
              <figcaption>
                <strong>
                  Next · Step {ghost.step} · {operationLabels[ghost.operation]}{" "}
                  ·{" "}
                  {ghost.operation === "transfer"
                    ? `${name(ghost.source_id)} → ${name(ghost.target_id)}`
                    : name(ghost.device_id)}
                </strong>
                {ghost.motion && (
                  <span>
                    {ghost.motion.length_m.toFixed(2)} m ·{" "}
                    {ghost.motion.seconds.toFixed(1)} s
                    {ghost.motion.replanned &&
                      " · re-planned for observed layout"}
                  </span>
                )}
                {ghost.changes.length > 0 && (
                  <ul>
                    {ghost.changes.map((c) => (
                      <li key={c.field}>
                        {label(c.field, name)}: {value(c.before, name)} →{" "}
                        {value(c.after, name)}
                      </li>
                    ))}
                  </ul>
                )}
              </figcaption>
            </figure>
          )}
          {ahead && (
            <p className={s.ahead}>
              Predicted stop at step {ahead.step}: {ahead.message}
            </p>
          )}
          <ol className={s.steps} aria-label="Monitored steps">
            {run.steps.map((st, i) => {
              const done = run.trace.find((t) => t.step === i + 1);
              const state =
                run.pause?.step === i + 1 && !done
                  ? "held"
                  : done?.divergence.length
                    ? "diverged"
                    : done
                      ? "done"
                      : ghost?.step === i + 1
                        ? "next"
                        : "pending";
              return (
                <li key={i} data-state={state}>
                  {i + 1}. {operationLabels[st.operation]} ·{" "}
                  {st.operation === "transfer"
                    ? `${name(st.source_id)} → ${name(st.target_id)}`
                    : name(st.device_id)}
                </li>
              );
            })}
          </ol>
          {stopped && (
            <details className={s.replay}>
              <summary>Replay with changes</summary>
              {stock.map((entry) => (
                <label key={entry.field} className={studio.field}>
                  {entry.label}
                  <input
                    type="number"
                    min={0}
                    value={edits[entry.field] ?? entry.count}
                    onChange={(e) =>
                      setEdits({
                        ...edits,
                        [entry.field]: Number(e.target.value),
                      })
                    }
                  />
                </label>
              ))}
              <button
                className={studio.secondary}
                disabled={busy}
                onClick={counterfactual}
              >
                Replay in the twin
              </button>
              {replay && (
                <p role="status">
                  {replay.avoided
                    ? replay.replay.status === "completed"
                      ? "With these changes the run completes."
                      : `Avoided the step ${replay.original.step} stop; stops at step ${replay.replay.step}: ${replay.replay.message}`
                    : `Still stops at step ${replay.replay.step}: ${replay.replay.message}`}
                  {replay.assumption && <small>{replay.assumption}</small>}
                </p>
              )}
            </details>
          )}
        </div>
      )}
    </section>
  );
}

function label(field: string, name: (id: string) => string) {
  const [group, id, ...rest] = field.split(".");
  if (group === "samples") return `${id} ${rest.join(" ").replace("_", " ")}`;
  if (group === "stock") return `${name(id)} ${rest.join(".")}`;
  return `${name(id)} ${group === "doors" ? "door" : group === "placements" ? rest.join(" ") : group}`;
}

function value(v: Scalar, name: (id: string) => string) {
  if (v === null || v === "") return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return name(v) === "—" ? v : name(v);
  return String(v);
}
