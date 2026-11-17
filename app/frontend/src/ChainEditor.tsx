import { useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Copy,
  Download,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { api, json } from "./api";
import type { ArmFrame, Layout } from "./instrumentTypes";
import studio from "./InstrumentStudio.module.css";
import data from "./LayoutData.module.css";
import s from "./ChainEditor.module.css";

type Waypoint = { name: string; degrees: number[]; hold: number };
type Chain = {
  schema: string;
  reference: number[];
  speed: number;
  waypoints: Waypoint[];
  provenance: Record<string, unknown>;
};
/** What the server found for an edited chain; `problem` is null when it can run. */
export type ChainResult = {
  step: number;
  actor_id: string;
  arm: string;
  seconds: number;
  clearance_m: number;
  nearest: string | null;
  source_m: number;
  target_m: number;
  simulation: {
    engine: string;
    tracking_deg: number;
    torque_ratio: number;
    clearance_m: number;
    nearest: string | null;
  } | null;
  frames: ArmFrame[];
  joints: number[][];
  problem: string | null;
};

const JOINTS = [
  "J1 Base",
  "J2 Shoulder",
  "J3 Elbow",
  "J4 Wrist 1",
  "J5 Wrist 2",
  "J6 Wrist 3",
];
const rad = (degrees: number[]) => degrees.map((v) => (v * Math.PI) / 180);

/**
 * The waypoints of one planned transfer, to change by hand: every joint of every
 * waypoint, their order and their holds. The server checks the edited chain like the
 * connector would run it; nothing is saved here.
 */
export default function ChainEditor({
  layout,
  step,
  onPose,
  onResult,
  onClose,
}: {
  layout: Layout;
  step: number;
  /** The arm pose to draw: the selected waypoint's joints, in radians. */
  onPose: (joints: number[] | null) => void;
  /** A checked path to play in the 3D view, or null once it is out of date. */
  onResult: (result: ChainResult | null) => void;
  onClose: () => void;
}) {
  const [planned, setPlanned] = useState<Chain | null>(null);
  const [points, setPoints] = useState<Waypoint[]>([]);
  const [speed, setSpeed] = useState(20);
  const [chosen, setChosen] = useState(0);
  const [result, setResult] = useState<ChainResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const key = JSON.stringify(layout);
  const edited = useRef(false);
  // Counts every change, so a check that comes back late is recognised as stale.
  const revision = useRef(0);

  useEffect(() => {
    let live = true;
    setPlanned(null);
    setError("");
    // A check belongs to the layout it was made for.
    revision.current += 1;
    setResult(null);
    onResult(null);
    api<Chain>("/twins/layout/chain", json({ ...layout, step, speed: 20 }))
      .then((chain) => {
        if (!live) return;
        setPlanned(chain);
        // Waypoints already changed by hand stay; only the plan behind them is new.
        if (!edited.current) {
          setPoints(chain.waypoints);
          setChosen(0);
        }
      })
      .catch((e) => live && setError((e as Error).message));
    return () => {
      live = false;
    };
    // The chain belongs to one layout and one step.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, step]);

  const current = points[chosen];
  const pose = current ? JSON.stringify(current.degrees) : "";
  useEffect(() => {
    onPose(pose ? rad(JSON.parse(pose)) : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pose]);
  useEffect(() => () => onPose(null), []); // eslint-disable-line react-hooks/exhaustive-deps

  // Any edit makes the last check out of date.
  const edit = (next: Waypoint[], select = chosen) => {
    edited.current = next !== planned?.waypoints;
    revision.current += 1;
    setPoints(next);
    setChosen(Math.max(0, Math.min(select, next.length - 1)));
    setResult(null);
    onResult(null);
  };
  const change = (patch: Partial<Waypoint>) =>
    edit(points.map((p, i) => (i === chosen ? { ...p, ...patch } : p)));
  const swap = (i: number, j: number) => {
    const next = [...points];
    [next[i], next[j]] = [next[j], next[i]];
    edit(next, j);
  };

  if (error && !planned)
    return (
      <section className={s.editor} aria-label="Arm path editor">
        <p role="alert">{error}</p>
        <button className={studio.secondary} onClick={onClose}>
          Close
        </button>
      </section>
    );
  if (!planned || !current)
    return <p className={data.time}>Reading the planned waypoints…</p>;

  return (
    <section className={s.editor} aria-label="Arm path editor">
      <header>
        <h3>
          Arm path · step {step} · {points.length}/24 waypoints
        </h3>
        <button
          className={s.icon}
          aria-label="Close the arm path editor"
          onClick={onClose}
        >
          <X size={16} />
        </button>
      </header>

      <ol className={s.points} aria-label="Waypoints">
        {points.map((p, i) => (
          <li key={i} data-chosen={i === chosen}>
            <button className={s.point} onClick={() => setChosen(i)}>
              <strong>
                {String(i + 1).padStart(2, "0")} {p.name || "Waypoint"}
              </strong>
              <small>
                {p.degrees.map((v) => `${v.toFixed(1)}°`).join(" / ")}
              </small>
            </button>
            <button
              className={s.icon}
              aria-label={`Move waypoint ${i + 1} up`}
              disabled={i === 0}
              onClick={() => swap(i, i - 1)}
            >
              <ArrowUp size={14} />
            </button>
            <button
              className={s.icon}
              aria-label={`Move waypoint ${i + 1} down`}
              disabled={i === points.length - 1}
              onClick={() => swap(i, i + 1)}
            >
              <ArrowDown size={14} />
            </button>
            <button
              className={s.icon}
              aria-label={`Duplicate waypoint ${i + 1}`}
              disabled={points.length >= 24}
              onClick={() =>
                edit(
                  [...points.slice(0, i + 1), { ...p }, ...points.slice(i + 1)],
                  i + 1,
                )
              }
            >
              <Copy size={14} />
            </button>
            <button
              className={s.icon}
              aria-label={`Delete waypoint ${i + 1}`}
              disabled={points.length <= 1}
              onClick={() =>
                edit(
                  points.filter((_, k) => k !== i),
                  i,
                )
              }
            >
              <Trash2 size={14} />
            </button>
          </li>
        ))}
      </ol>

      <fieldset className={s.selected}>
        <legend>Waypoint {chosen + 1}</legend>
        <label>
          Name
          <input
            value={current.name}
            maxLength={60}
            onChange={(e) => change({ name: e.target.value })}
          />
        </label>
        <label>
          Hold (s)
          <input
            type="number"
            min={0}
            max={60}
            step={0.5}
            value={current.hold}
            onChange={(e) => change({ hold: Number(e.target.value) })}
          />
        </label>
        <div className={s.joints}>
          {JOINTS.map((name, j) => {
            const set = (value: number) =>
              change({
                degrees: current.degrees.map((v, k) =>
                  k === j ? Math.max(-360, Math.min(360, value)) : v,
                ),
              });
            return (
              <label key={name}>
                <span>{name}</span>
                <input
                  type="range"
                  aria-label={`${name} slider`}
                  min={-360}
                  max={360}
                  step={0.5}
                  value={current.degrees[j]}
                  onChange={(e) => set(Number(e.target.value))}
                />
                <input
                  type="number"
                  aria-label={`${name} degrees`}
                  min={-360}
                  max={360}
                  step={0.5}
                  value={current.degrees[j]}
                  onChange={(e) => set(Number(e.target.value))}
                />
              </label>
            );
          })}
        </div>
      </fieldset>

      <div className={s.actions}>
        <label>
          Speed (°/s)
          <input
            type="number"
            min={1}
            max={40}
            value={speed}
            onChange={(e) => {
              revision.current += 1;
              setSpeed(Number(e.target.value));
              setResult(null);
              onResult(null);
            }}
          />
        </label>
        <button
          className={studio.primary}
          disabled={checking}
          onClick={async () => {
            setChecking(true);
            setError("");
            const asked = revision.current;
            try {
              const next = await api<ChainResult>(
                "/twins/layout/chain/check",
                json({
                  ...layout,
                  step,
                  speed,
                  reference: planned.reference,
                  waypoints: points,
                }),
              );
              if (revision.current !== asked) return;
              setResult(next);
              onResult(next);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setChecking(false);
            }
          }}
        >
          {checking ? "Checking…" : "Check path"}
        </button>
        <button
          className={studio.secondary}
          disabled={points.length >= 24}
          onClick={() =>
            edit(
              [
                ...points.slice(0, chosen + 1),
                { ...current, name: "Waypoint", hold: 0.01 },
                ...points.slice(chosen + 1),
              ],
              chosen + 1,
            )
          }
        >
          <Plus size={14} /> Add after
        </button>
        <button
          className={studio.secondary}
          onClick={() => edit(planned.waypoints, 0)}
        >
          Back to planned
        </button>
        {result && !result.problem && (
          <button
            className={studio.secondary}
            onClick={() => {
              const doc = {
                ...planned,
                speed,
                waypoints: points,
                provenance: {
                  ...planned.provenance,
                  generator:
                    "Lab Onboarding bench layout, waypoints edited by hand",
                  estimated_seconds: result.seconds,
                  clearance_m: result.clearance_m,
                },
              };
              const url = URL.createObjectURL(
                new Blob([JSON.stringify(doc, null, 2)], {
                  type: "application/json",
                }),
              );
              const link = document.createElement("a");
              link.href = url;
              link.download = `ur5e-action-chain-step-${step}-edited.json`;
              link.click();
              URL.revokeObjectURL(url);
            }}
          >
            <Download size={14} /> Edited chain
          </button>
        )}
      </div>

      {error && <p role="alert">{error}</p>}
      {result && (
        <div className={s.result} role="status" data-ok={!result.problem}>
          <strong>
            {result.problem ??
              "This path is clear and reaches both instruments."}
          </strong>
          <dl className={data.facts}>
            <dt>Arm time</dt>
            <dd>{result.seconds.toFixed(1)} s</dd>
            <dt>Least clearance</dt>
            <dd>
              {(result.clearance_m * 100).toFixed(1)} cm
              {result.nearest ? ` to ${result.nearest}` : ""}
            </dd>
            <dt>Tool to grasp points</dt>
            <dd>
              {(result.source_m * 100).toFixed(1)} cm ·{" "}
              {(result.target_m * 100).toFixed(1)} cm
            </dd>
            {result.simulation && (
              <>
                <dt>Simulated</dt>
                <dd>
                  {Math.round(result.simulation.torque_ratio * 100)}% joint
                  torque · {result.simulation.tracking_deg.toFixed(2)}° tracking
                </dd>
              </>
            )}
          </dl>
        </div>
      )}
    </section>
  );
}
