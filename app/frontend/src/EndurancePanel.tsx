import { useEffect, useRef, useState } from "react";
import { Play, Repeat, Square } from "lucide-react";
import { api, json } from "./api";
import type { ArmFrame, Layout } from "./instrumentTypes";
import LikeliestFailure from "./LikeliestFailure";
import studio from "./InstrumentStudio.module.css";
import s from "./EndurancePanel.module.css";
import panel from "./LayoutPanel.module.css";

type Mode = "ik" | "limit" | "collision" | "tracking" | "drop" | "slip";
type Failure = {
  mode: Mode;
  step: number;
  segment: string | null;
  message: string;
};
type Cycle = {
  cycle: number;
  ok: boolean;
  seconds: number;
  clearance_m: number | null;
  margin: number | null;
  failures: Failure[];
};
type GraspReport = {
  margin: number | null;
  required_n: number;
  available_n: number;
  limit: string | null;
  worst_segment: string;
  slip: boolean;
  slip_mm: number;
  drop: { segment: string; at_s: number } | null;
  segments: { label: string; margin: number | null; at_s: number }[];
};
type Basis = { value: number; basis: "default" | "run" };
type Chunk = {
  cycles: number;
  seed: number;
  next: number | null;
  results: Cycle[];
  nominal?: (GraspReport & {
    step: number;
    seconds: number;
    clearance_m: number;
    labware_kg: number;
  })[];
  parameters?: {
    labware: {
      step: number;
      vessel: string;
      kg: number;
      kg_basis: "default" | "run";
    }[];
    gripper: Record<string, Basis>;
    defaults: string[];
  };
};
export type ReplayMotion = {
  step: number;
  actor_id: string;
  source_id: string;
  target_id: string;
  arm: string;
  frames: ArmFrame[];
  joints: number[][];
};
export type Replay = {
  seed: number;
  /** The cycle is null for one the likeliest-failure search found. */
  record: Omit<Cycle, "cycle"> & { cycle: number | null };
  transfers: {
    step: number;
    seconds: number;
    clearance_m: number;
    speed: number;
    labware_kg: number;
    grasp_offset_mm: number;
    grasp: GraspReport;
  }[];
  motions: ReplayMotion[];
  drift: { name: string; dx_mm: number; dz_mm: number; dyaw_deg: number }[];
  moves: {
    step: number;
    pick_error_mm: number[];
    place_error_mm: number[];
  }[];
};

const MODES: Record<Mode, string> = {
  slip: "Slip",
  drop: "Drop",
  collision: "Collision",
  limit: "Joint or torque limit",
  tracking: "Tracking error",
  ik: "No IK solution",
};
const NOISE = [
  ["pose_mm", "Pick and place error (mm)", 1, 0, 10, 0.5],
  ["drift_mm", "Instrument drift (mm)", 2, 0, 20, 0.5],
  ["drift_deg", "Instrument turn (°)", 0.3, 0, 5, 0.1],
  ["mass_pct", "Labware mass spread (%)", 10, 0, 50, 1],
  ["speed_pct", "Speed spread (%)", 10, 0, 50, 1],
] as const;
const GRIP = [
  ["grip_force_n", "Grip force (N)", 20, 1, 200, 1],
  ["friction", "Pad friction", 0.4, 0.05, 1.5, 0.05],
  ["labware_kg", "Labware mass (kg)", null, 0.001, 5, 0.01],
] as const;
const DEFAULT_NAMES: Record<
  string,
  (p: NonNullable<Chunk["parameters"]>) => string
> = {
  grip_force_n: (p) => `grip ${p.gripper.grip_force_n.value} N`,
  friction: (p) => `pad friction ${p.gripper.friction.value}`,
  pad_radius_m: (p) => `pad radius ${p.gripper.pad_radius_m.value * 1000} mm`,
  hold_depth_m: (p) =>
    `${p.gripper.hold_depth_m.value * 1000} mm of pad overlap`,
  labware_kg: (p) =>
    [
      ...new Set(
        p.labware.map((l) => `${l.vessel} ${Math.round(l.kg * 1000)} g`),
      ),
    ].join(", "),
};
const LANES = 3;

const quantile = (sorted: number[], q: number) =>
  sorted.length
    ? sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))]
    : NaN;
const lower = (label: string) => label.charAt(0).toLowerCase() + label.slice(1);
const cm = (m: number) => `${(m * 100).toFixed(1)} cm`;
const times = (m: number | null) => (m === null ? "—" : `${m.toFixed(1)}×`);

function Histogram({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) return null;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const bins = new Array(16).fill(0);
  for (const v of values)
    bins[hi > lo ? Math.min(15, Math.floor(((v - lo) / (hi - lo)) * 16)) : 0]++;
  const top = Math.max(...bins);
  return (
    <svg
      className={s.histogram}
      viewBox="0 0 64 16"
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
    >
      {bins.map((n, i) => (
        <rect
          key={i}
          x={i * 4 + 0.4}
          width={3.2}
          y={16 - (n / top) * 16}
          height={(n / top) * 16}
        />
      ))}
    </svg>
  );
}

/**
 * Repeats the workflow's transfers many times with small perturbations in the MuJoCo
 * bench, and says how often, where and how they fail.
 */
export default function EndurancePanel({
  layout,
  ready,
  simulated,
  onReplay,
}: {
  layout: Layout;
  /** The layout plans cleanly; a stress run starts from a working plan. */
  ready: boolean;
  /** The server simulates arm paths in MuJoCo. */
  simulated: boolean;
  onReplay: (motion: ReplayMotion | null) => void;
}) {
  const [cycles, setCycles] = useState(500);
  const [seed, setSeed] = useState(1);
  const [speed, setSpeed] = useState(20);
  const [noise, setNoise] = useState<Record<string, number>>(
    Object.fromEntries(NOISE.map(([k, , v]) => [k, v])),
  );
  const [grip, setGrip] = useState<Record<string, number | null>>({
    grip_force_n: null,
    friction: null,
    labware_kg: null,
  });
  const [records, setRecords] = useState<Cycle[]>([]);
  const [first, setFirst] = useState<Chunk | null>(null);
  const [ran, setRan] = useState<{ cycles: number; seed: number } | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [replay, setReplay] = useState<Replay | null>(null);
  const runId = useRef(0);
  const placements = JSON.stringify(layout);

  // A changed bench is a different run.
  useEffect(() => {
    runId.current += 1;
    setRunning(false);
    setRecords([]);
    setFirst(null);
    setRan(null);
    setReplay(null);
    onReplay(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placements]);

  const settings = () => ({
    ...layout,
    seed,
    speed,
    noise,
    grip: Object.fromEntries(
      Object.entries(grip).filter(([, v]) => v !== null),
    ),
  });

  const run = async () => {
    const id = ++runId.current;
    setRunning(true);
    setError("");
    setRecords([]);
    setFirst(null);
    setReplay(null);
    onReplay(null);
    setRan({ cycles, seed });
    const body = settings();
    const size = Math.ceil(cycles / LANES);
    const lane = async (from: number, to: number) => {
      let start: number | null = from;
      while (start !== null) {
        const chunk: Chunk = await api<Chunk>(
          "/twins/layout/endurance",
          json({ ...body, cycles, start, stop: to }),
        );
        if (runId.current !== id) return;
        if (chunk.nominal) setFirst(chunk);
        setRecords((now) => [...now, ...chunk.results]);
        start = chunk.next;
      }
    };
    try {
      await Promise.all(
        Array.from({ length: LANES }, (_, i) => [
          i * size,
          Math.min(cycles, (i + 1) * size),
        ])
          .filter(([a, b]) => a < b)
          .map(([a, b]) => lane(a, b)),
      );
    } catch (e) {
      if (runId.current === id) setError((e as Error).message);
    } finally {
      if (runId.current === id) setRunning(false);
    }
  };

  const display = (result: Replay) => {
    setReplay(result);
    const failing = result.record.failures[0]?.step;
    onReplay(
      result.motions.find((m) => m.step === failing) ??
        result.motions[0] ??
        null,
    );
  };

  const show = async (cycle: number) => {
    setError("");
    try {
      display(
        await api<Replay>(
          "/twins/layout/endurance/replay",
          json({ ...settings(), seed: ran?.seed ?? seed, cycle }),
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const sorted = [...records].sort((a, b) => a.cycle - b.cycle);
  const failed = sorted.filter((r) => !r.ok);
  const counts = new Map<Mode, number>();
  for (const r of failed)
    for (const f of r.failures)
      counts.set(f.mode, (counts.get(f.mode) ?? 0) + 1);
  const clearances = sorted
    .map((r) => r.clearance_m)
    .filter((v): v is number => v !== null)
    .sort((a, b) => a - b);
  const seconds = sorted.map((r) => r.seconds).sort((a, b) => a - b);
  const margins = sorted
    .map((r) => r.margin)
    .filter((v): v is number => v !== null)
    .sort((a, b) => a - b);
  const tightest = sorted.reduce<Cycle | null>(
    (best, r) =>
      r.clearance_m !== null &&
      (best === null || r.clearance_m < (best.clearance_m ?? Infinity))
        ? r
        : best,
    null,
  );
  const worst = failed[0] ?? tightest;
  const params = first?.parameters;

  if (!simulated)
    return (
      <div className={s.panel}>
        <strong>Stress test</strong>
        <div className={s.bar}>
          <button className={studio.secondary} disabled>
            <Repeat size={14} /> Run stress test
          </button>
          <small className={panel.hint}>
            Needs the MuJoCo simulation, which this server does not have.
          </small>
        </div>
      </div>
    );

  return (
    <div className={s.panel} aria-live="polite">
      <strong>Stress test</strong>
      <div className={s.bar}>
        <label>
          Cycles
          <select
            value={cycles}
            disabled={running}
            onChange={(e) => setCycles(Number(e.target.value))}
          >
            {[50, 200, 500, 1000, 2000, 5000].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label>
          Seed
          <input
            type="number"
            min={0}
            step={1}
            value={seed}
            disabled={running}
            onChange={(e) =>
              setSeed(Math.max(0, Math.floor(Number(e.target.value))))
            }
          />
        </label>
        <label>
          Speed (°/s)
          <input
            type="number"
            min={5}
            max={90}
            step={5}
            value={speed}
            disabled={running}
            onChange={(e) => setSpeed(Number(e.target.value))}
          />
        </label>
        {running ? (
          <button
            className={studio.secondary}
            onClick={() => {
              runId.current += 1;
              setRunning(false);
            }}
          >
            <Square size={12} /> Stop
          </button>
        ) : (
          <button className={studio.secondary} disabled={!ready} onClick={run}>
            <Repeat size={14} /> Run stress test
          </button>
        )}
        {!ready && !running && (
          <small className={panel.hint}>Plan every transfer first.</small>
        )}
      </div>
      <details className={s.more}>
        <summary>Perturbations and grip</summary>
        <div className={s.fields}>
          {NOISE.map(([key, label, , min, max, step]) => (
            <label key={key}>
              {label}
              <input
                type="number"
                min={min}
                max={max}
                step={step}
                value={noise[key]}
                disabled={running}
                onChange={(e) =>
                  setNoise((n) => ({ ...n, [key]: Number(e.target.value) }))
                }
              />
            </label>
          ))}
          {GRIP.map(([key, label, fallback, min, max, step]) => (
            <label key={key}>
              {label}
              <input
                type="number"
                min={min}
                max={max}
                step={step}
                placeholder={
                  fallback === null ? "from the workflow" : String(fallback)
                }
                value={grip[key] ?? ""}
                disabled={running}
                onChange={(e) =>
                  setGrip((g) => ({
                    ...g,
                    [key]:
                      e.target.value === "" ? null : Number(e.target.value),
                  }))
                }
              />
            </label>
          ))}
        </div>
      </details>
      {error && (
        <p className={panel.problem} role="status">
          {error}
        </p>
      )}
      {ran && (
        <progress
          className={s.progress}
          value={records.length}
          max={ran.cycles}
          aria-label={`${records.length} of ${ran.cycles} cycles`}
        />
      )}
      {first?.nominal && (
        <ul className={s.grasps} aria-label="Grasp on the planned path">
          {first.nominal.map((g) => (
            <li key={g.step} className={g.slip || g.drop ? panel.problem : ""}>
              <span>
                Step {g.step} grasp ·{" "}
                {g.drop
                  ? `drops during ${lower(g.drop.segment)}`
                  : g.slip
                    ? `slips ${g.slip_mm} mm`
                    : `${times(g.margin)} margin`}
              </span>
              <small>
                {g.required_n.toFixed(2)} of {g.available_n.toFixed(1)} N
                friction · least during {lower(g.worst_segment)}
              </small>
            </li>
          ))}
        </ul>
      )}
      {sorted.length > 0 && ran && (
        <dl className={s.stats}>
          <div>
            <dt>Failures</dt>
            <dd>
              {failed.length} of {sorted.length}
              {failed.length > 0 &&
                ` (${((failed.length / sorted.length) * 100).toFixed(1)}%)`}
              {counts.size > 0 && (
                <small>
                  {[...counts]
                    .map(([mode, n]) => `${MODES[mode]} ${n}`)
                    .join(" · ")}
                </small>
              )}
            </dd>
          </div>
          <div>
            <dt>Clearance</dt>
            <dd>
              {cm(clearances[0])} min · {cm(quantile(clearances, 0.5))} median
              <Histogram values={clearances} label="Clearance per cycle" />
            </dd>
          </div>
          <div>
            <dt>Arm time</dt>
            <dd>
              {quantile(seconds, 0.5).toFixed(1)} s median ·{" "}
              {quantile(seconds, 0.95).toFixed(1)} s p95
              <Histogram values={seconds} label="Arm time per cycle" />
            </dd>
          </div>
          <div>
            <dt>Grip margin</dt>
            <dd>
              {times(margins[0] ?? null)} min · {times(quantile(margins, 0.05))}{" "}
              p5
            </dd>
          </div>
        </dl>
      )}
      {worst && ran && !running && (
        <div className={s.worst}>
          <span>
            {failed.length ? "First failure" : "Tightest cycle"} · cycle{" "}
            {worst.cycle}, seed {ran.seed}
            <small>
              {worst.failures[0]?.message ??
                `${cm(worst.clearance_m ?? 0)} clearance`}
            </small>
          </span>
          <button
            className={studio.secondary}
            onClick={() => show(worst.cycle)}
          >
            <Play size={14} /> Replay
          </button>
        </div>
      )}
      <LikeliestFailure
        settings={settings}
        bench={JSON.stringify([placements, seed, speed, noise, grip])}
        ready={ready && !running}
        onShow={display}
      />
      {replay && (
        <details className={s.more} open>
          <summary>
            {replay.record.cycle === null
              ? "Found cycle"
              : `Cycle ${replay.record.cycle}`}{" "}
            {replay.record.ok
              ? "held"
              : `· ${replay.record.failures.length} failed`}
          </summary>
          <ul className={s.grasps}>
            {replay.transfers.map((t) => {
              const move = replay.moves.find((m) => m.step === t.step);
              return (
                <li key={t.step}>
                  <span>
                    Step {t.step} · {t.speed}°/s ·{" "}
                    {Math.round(t.labware_kg * 1000)} g ·{" "}
                    {times(t.grasp.margin)} grip margin · {cm(t.clearance_m)}
                  </span>
                  <small>
                    Picked {move?.pick_error_mm.join(", ")} mm off, placed{" "}
                    {move?.place_error_mm.join(", ")} mm off, held{" "}
                    {t.grasp_offset_mm} mm across the pads
                  </small>
                </li>
              );
            })}
            {replay.record.failures.map((f, i) => (
              <li key={i} className={panel.problem}>
                {f.message}
              </li>
            ))}
          </ul>
          {replay.drift.length > 0 && (
            <small className={panel.hint}>
              Drift:{" "}
              {replay.drift
                .map(
                  (d) => `${d.name} ${d.dx_mm}, ${d.dz_mm} mm, ${d.dyaw_deg}°`,
                )
                .join(" · ")}
            </small>
          )}
          <button
            className={studio.secondary}
            onClick={() => {
              setReplay(null);
              onReplay(null);
            }}
          >
            Back to the planned path
          </button>
        </details>
      )}
      {params && params.defaults.length > 0 && (
        <small className={panel.hint}>
          Defaults used:{" "}
          {params.defaults
            .map((k) => DEFAULT_NAMES[k]?.(params) ?? k)
            .join(", ")}
          .
        </small>
      )}
      <details className={s.more}>
        <summary>How cycles are simulated</summary>
        Each cycle repeats every transfer in MuJoCo with instruments drifted off
        their spots, the pick and place points located with some error (the arm
        corrects its pose by inverse kinematics), and the labware mass and arm
        speed varied. The labware is a body in the gripper: MuJoCo gives the
        force and torque the fingers must hold it with, and two friction pads
        squeezing with the grip force either supply that or let it slide. A seed
        and cycle number repeat a cycle exactly. Synthetic teaching result: no
        robot, gripper or labware has been run.
      </details>
    </div>
  );
}
