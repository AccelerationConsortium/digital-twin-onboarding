import { useEffect, useRef, useState } from "react";
import { Crosshair, Play, Square } from "lucide-react";
import { api, json } from "./api";
import type { Replay } from "./EndurancePanel";
import studio from "./InstrumentStudio.module.css";
import s from "./EndurancePanel.module.css";
import panel from "./LayoutPanel.module.css";

type Driver = {
  label: string;
  sigma: number;
  value: number;
  unit: string;
  share: number;
};
type Found = {
  mode: string;
  family: string;
  step: number;
  message: string;
  distance_sigma: number;
  probability: number;
  monte_carlo_cycles: number | null;
  sigma: number[];
  drivers: Driver[];
  first_found_at: number;
};
type Closest = {
  family: string;
  margin_left: number;
  distance_sigma: number;
  sigma: number[];
  drivers: Driver[];
};
type Chunk = {
  simulated: number;
  budget: number;
  failures: Found[];
  closest: Closest[];
  next: unknown | null;
};

const FAMILIES: Record<string, string> = {
  collision: "Collision",
  grip: "Grip",
  tracking: "Tracking",
  limit: "Joint or torque limit",
};
const MODES: Record<string, string> = {
  collision: "Collision",
  slip: "Slip",
  drop: "Drop",
  tracking: "Tracking error",
  limit: "Joint or torque limit",
  ik: "No IK solution",
};

const signed = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}`;
const drivers = (list: Driver[]) =>
  list
    .filter((d) => d.share >= 0.05)
    .map(
      (d) =>
        `${d.label} ${signed(d.value)} ${d.unit} (${signed(d.sigma)}σ, ${Math.round(d.share * 100)}%)`,
    )
    .join(" · ");
const odds = (n: number | null) =>
  n === null
    ? "beyond reach"
    : n >= 1e6
      ? `1 in ${n.toExponential(1)} cycles`
      : `1 in ${n.toLocaleString("en")} cycles`;

/**
 * Searches the endurance test's perturbations for the most probable way the transfers
 * fail (adaptive stress testing with the cross-entropy method), and replays it.
 */
export default function LikeliestFailure({
  settings,
  bench,
  ready,
  onShow,
}: {
  /** The endurance test's request body: layout, seed, speed, perturbations and grip. */
  settings: () => Record<string, unknown>;
  /** Changes when the bench or the stress settings change. */
  bench: string;
  ready: boolean;
  onShow: (replay: Replay) => void;
}) {
  const [budget, setBudget] = useState(400);
  const [chunk, setChunk] = useState<Chunk | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const runId = useRef(0);

  useEffect(() => {
    runId.current += 1;
    setRunning(false);
    setChunk(null);
  }, [bench]);

  const search = async () => {
    const id = ++runId.current;
    setRunning(true);
    setError("");
    setChunk(null);
    const body = { ...settings(), budget };
    let state: unknown = null;
    try {
      do {
        const next: Chunk = await api<Chunk>(
          "/twins/layout/endurance/adversary",
          json({ ...body, state }),
        );
        if (runId.current !== id) return;
        setChunk(next);
        state = next.next;
      } while (state);
    } catch (e) {
      if (runId.current === id) setError((e as Error).message);
    } finally {
      if (runId.current === id) setRunning(false);
    }
  };

  const show = async (sigma: number[]) => {
    setError("");
    try {
      onShow(
        await api<Replay>(
          "/twins/layout/endurance/adversary/replay",
          json({ ...settings(), sigma }),
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className={s.panel}>
      <strong>Likeliest failure</strong>
      <div className={s.bar}>
        <label>
          Search budget
          <select
            value={budget}
            disabled={running}
            onChange={(e) => setBudget(Number(e.target.value))}
          >
            {[100, 200, 400, 1000, 2000].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
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
          <button
            className={studio.secondary}
            disabled={!ready}
            onClick={search}
          >
            <Crosshair size={14} /> Find the likeliest failure
          </button>
        )}
      </div>
      {error && (
        <p className={panel.problem} role="status">
          {error}
        </p>
      )}
      {chunk && (
        <progress
          className={s.progress}
          value={Math.min(chunk.simulated, chunk.budget)}
          max={chunk.budget}
          aria-label={`${chunk.simulated} of ${chunk.budget} search cycles`}
        />
      )}
      {chunk && (
        <ul
          className={s.found}
          aria-label="Likeliest failures"
          aria-live="polite"
        >
          {chunk.failures.map((f) => (
            <li key={f.mode} className={s.worst}>
              <span>
                {MODES[f.mode] ?? f.mode} · {f.distance_sigma.toFixed(1)}σ ·
                about {odds(f.monte_carlo_cycles)}
                <small>{f.message}</small>
                <small>{drivers(f.drivers)}</small>
                <small>
                  Found after {f.first_found_at} of {chunk.simulated} simulated
                  cycles
                </small>
              </span>
              <button
                className={studio.secondary}
                disabled={running}
                onClick={() => show(f.sigma)}
              >
                <Play size={14} /> Replay
              </button>
            </li>
          ))}
          {!running && chunk.failures.length === 0 && (
            <li>No failure within ±3σ in {chunk.simulated} cycles.</li>
          )}
          {!running &&
            chunk.closest
              // A family the search barely moved says nothing new.
              .filter((c) => c.margin_left < 0.95)
              .map((c) => (
                <li key={c.family} className={s.worst}>
                  <span>
                    Closest {FAMILIES[c.family]?.toLowerCase() ?? c.family} ·{" "}
                    {Math.round(c.margin_left * 100)}% margin left at{" "}
                    {c.distance_sigma.toFixed(1)}σ
                    <small>{drivers(c.drivers)}</small>
                  </span>
                  <button
                    className={studio.secondary}
                    onClick={() => show(c.sigma)}
                  >
                    <Play size={14} /> Replay
                  </button>
                </li>
              ))}
        </ul>
      )}
      <details className={s.more}>
        <summary>How the search works</summary>
        Each perturbation of the endurance test is one dimension, measured in
        its σ. A cross-entropy search samples them, simulates each cycle in
        MuJoCo, and moves toward cycles that fail or come close to failing,
        preferring the more probable ones. A failure&apos;s distance from the
        planned cycle in σ gives a first-order estimate of how often a random
        cycle would hit it. Synthetic teaching result: no robot, gripper or
        labware has been run.
      </details>
    </div>
  );
}
