import { useEffect, useRef, useState } from "react";
import { Crosshair, Download, Printer, Square, Trash2 } from "lucide-react";
import { api, apiText, json } from "./api";
import type {
  BenchWorkflow,
  Layout,
  ToleranceBands,
  ToleranceBinding,
  ToleranceChunk,
  ToleranceCheck,
  TolerancePoint,
  ToleranceRow,
  ToleranceSummary,
  ToleranceTask,
} from "./instrumentTypes";
import studio from "./InstrumentStudio.module.css";
import s from "./LayoutPanel.module.css";

const SAMPLES = [8, 12, 32];
const mm = (m: number | null | undefined) =>
  m == null ? "—" : `${Math.round(m * 1000)}`;
const pct = (v: number | null | undefined) =>
  v == null ? "—" : `${Math.round(v * 100)}%`;

/** What stopped the plan, in a few words. */
export function limitText(b: ToleranceCheck | null | undefined) {
  if (!b) return "";
  const where = b.step ? ` · step ${b.step}` : "";
  switch (b.cause) {
    case "collision":
      return `Hits ${b.blocker ?? "an instrument"}${where}`;
    case "unreachable":
      return `Out of reach${where}`;
    case "joint limit":
      return `Joint limit${where}`;
    case "overlap":
      return `Touches ${b.blocker ?? "a neighbour"}`;
    case "bench edge":
      return "Bench edge";
    case "torque":
      return `Joint torque${where}`;
    case "tracking":
      return `Path tracking${where}`;
    default:
      return `Plan fails${where}`;
  }
}

const AXIS = { x: "x", z: "z", yaw: "yaw", height: "height" } as const;
const sideText = (b: ToleranceBinding) =>
  `${AXIS[b.axis]}${b.sign < 0 ? "−" : "+"}`;

/** "±12 mm", or "≥120 mm" when no failure was found within the range checked. */
function within(row: ToleranceRow, axes: ("x" | "z" | "yaw" | "height")[]) {
  const sides = axes.flatMap((a) =>
    row.sides[a] ? [row.sides[a]!.minus, row.sides[a]!.plus] : [],
  );
  if (!sides.length || sides.some((v) => !v)) return null;
  const least = Math.min(...sides.map((v) => v!.band));
  return {
    value: least,
    open: sides.every((v) => v!.saturated),
  };
}

function Band({
  row,
  axes,
  unit,
}: {
  row: ToleranceRow;
  axes: ("x" | "z" | "yaw" | "height")[];
  unit: "mm" | "°";
}) {
  const w = within(row, axes);
  if (!w) return <td className={s.pending}>…</td>;
  const value = unit === "mm" ? mm(w.value) : w.value.toFixed(1);
  return (
    <td>
      {w.open ? "≥" : "±"}
      {value}
      {unit === "mm" ? " mm" : "°"}
    </td>
  );
}

/** Share of combined misplacements that still plan, against the ± tolerance. */
function Curve({
  series,
}: {
  series: { label: string; points: TolerancePoint[]; className: string }[];
}) {
  const W = 260;
  const H = 90;
  const n = series[0]?.points.length ?? 0;
  // Drawn once the combined samples have started.
  if (!n || !series.some((l) => l.points.some((p) => p.rate != null)))
    return null;
  const x = (i: number) => 24 + (i * (W - 34)) / Math.max(1, n - 1);
  const y = (r: number) => 8 + (1 - r) * (H - 26);
  return (
    <svg
      className={s.curve}
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Success rate against placement tolerance"
    >
      {[0, 0.5, 1].map((r) => (
        <g key={r}>
          <line className={s.grid} x1={24} x2={W - 10} y1={y(r)} y2={y(r)} />
          <text x={20} y={y(r) + 3} textAnchor="end">
            {r * 100}%
          </text>
        </g>
      ))}
      {series[0].points.map((p, i) => (
        <text key={i} x={x(i)} y={H - 4} textAnchor="middle">
          ±{mm(p.level_m)}
        </text>
      ))}
      {series.map((line) => {
        const shown = line.points
          .map((p, i) => [i, p.rate] as const)
          .filter(([, r]) => r != null);
        return (
          <g key={line.label} className={line.className}>
            <polyline
              points={shown.map(([i, r]) => `${x(i)},${y(r!)}`).join(" ")}
            />
            {shown.map(([i, r]) => (
              <circle key={i} cx={x(i)} cy={y(r!)} r={2.5}>
                <title>
                  {line.label}: {pct(r)} at ±{mm(line.points[i].level_m)} mm / ±
                  {line.points[i].level_deg}°
                </title>
              </circle>
            ))}
          </g>
        );
      })}
    </svg>
  );
}

function Advice({
  label,
  curve,
}: {
  label: string;
  curve: ToleranceSummary["curves"]["instruments"];
}) {
  const a = curve.advice;
  if (!a)
    return curve.points[0]?.runs ? (
      <p className={s.problem}>
        {label}: fails even at ±{mm(curve.points[0].level_m)} mm / ±
        {curve.points[0].level_deg}°
      </p>
    ) : null;
  return (
    <p className={s.advice}>
      <span>{label}</span>
      <strong>
        ±{mm(a.level_m)} mm · ±{a.level_deg}°
      </strong>
      <small>
        {a.runs}/{a.runs} held · ≥{pct(a.lower)} at 95% confidence
      </small>
    </p>
  );
}

export default function LayoutTolerance({
  layout,
  kept,
  canKeep,
  busy,
  onKeep,
  onDrop,
  onBands,
}: {
  layout: Layout;
  kept: BenchWorkflow[];
  /** The current workflow has a transfer and is not kept yet. */
  canKeep: boolean;
  busy: boolean;
  onKeep: (name: string) => void;
  onDrop: (id: string) => void;
  /** The allowed bands of the layout analysed, for the bench and 3D overlays. */
  onBands: (bands: ToleranceBands | null) => void;
}) {
  const [scope, setScope] = useState<"current" | "bench">("current");
  const [samples, setSamples] = useState(12);
  const [done, setDone] = useState<ToleranceTask[]>([]);
  const [summary, setSummary] = useState<ToleranceSummary | null>(null);
  const [progress, setProgress] = useState<{ at: number; total: number }>();
  // Where a stopped analysis picks up again.
  const [cursor, setCursor] = useState<{
    start: number | null;
    trail: ToleranceCheck[];
  }>({ start: 0, trail: [] });
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const runId = useRef(0);
  const workflows = kept.length ? scope : "current";
  const body = { ...layout, workflows, samples };
  const inputs = JSON.stringify(body);

  // An answer belongs to one layout, one set of workflows and one sample count.
  useEffect(() => {
    runId.current += 1;
    setDone([]);
    setSummary(null);
    setProgress(undefined);
    setCursor({ start: 0, trail: [] });
    setRunning(false);
    onBands(null);
  }, [inputs]);

  const measure = async () => {
    const id = ++runId.current;
    setRunning(true);
    setError("");
    let { start, trail } = cursor;
    let all = done;
    try {
      while (start !== null && runId.current === id) {
        const chunk: ToleranceChunk = await api<ToleranceChunk>(
          "/twins/layout/tolerance",
          json({ ...body, start, trail, done: all }),
        );
        if (runId.current !== id) return;
        ({ next: start, trail, done: all } = chunk);
        setDone(all);
        setCursor({ start, trail });
        setSummary(chunk.summary);
        setProgress({ at: chunk.next ?? chunk.total, total: chunk.total });
        onBands(chunk.summary.overlay);
      }
    } catch (e) {
      if (runId.current === id) setError((e as Error).message);
    } finally {
      if (runId.current === id) setRunning(false);
    }
  };

  const template = async (pages: boolean) => {
    setError("");
    try {
      const text = await apiText(
        `/twins/layout/template${pages ? "?pages=true" : ""}`,
        json({ ...body, done }),
      );
      if (pages) {
        // Printed from a frame of its own, so the sheets are the only thing on paper.
        const frame = document.createElement("iframe");
        frame.className = s.printFrame;
        frame.title = "Placement template";
        frame.srcdoc = text;
        frame.onload = () => {
          frame.contentWindow?.print();
          window.setTimeout(() => frame.remove(), 60_000);
        };
        document.body.appendChild(frame);
        return;
      }
      const url = URL.createObjectURL(
        new Blob([text], { type: "image/svg+xml" }),
      );
      Object.assign(document.createElement("a"), {
        href: url,
        download: "placement-template.svg",
      }).click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const rows = summary?.requirements ?? [];
  const arms = summary?.arms ?? [];
  const several = (summary?.workflows.length ?? 0) > 1;

  return (
    <section className={s.tolerance} aria-label="Placement tolerance">
      <div className={s.optionBar}>
        <strong>Placement tolerance</strong>
        {kept.length > 0 && (
          <div className={s.scope} role="radiogroup" aria-label="Workflows">
            <label>
              <input
                type="radio"
                checked={workflows === "current"}
                onChange={() => setScope("current")}
              />
              This workflow
            </label>
            <label>
              <input
                type="radio"
                checked={workflows === "bench"}
                onChange={() => setScope("bench")}
              />
              All {kept.length + 1} on this bench
            </label>
          </div>
        )}
        <label className={s.inlineCheck}>
          Samples
          <select
            aria-label="Combined samples per tolerance"
            value={samples}
            onChange={(e) => setSamples(Number(e.target.value))}
          >
            {SAMPLES.map((n) => (
              <option key={n}>{n}</option>
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
          cursor.start !== null && (
            <button className={studio.secondary} onClick={measure}>
              <Crosshair size={14} />{" "}
              {done.length ? "Resume" : "Measure tolerance"}
            </button>
          )
        )}
      </div>
      {progress && (
        <progress
          className={s.meter}
          aria-label="Tolerance checks done"
          max={progress.total}
          value={progress.at}
        />
      )}
      {error && (
        <p className={s.problem} role="status">
          {error}
        </p>
      )}
      {summary && (
        <>
          <Advice
            label="Every instrument at once"
            curve={summary.curves.instruments}
          />
          <Advice label="Arm base" curve={summary.curves.arm} />
          <table className={s.requirements} aria-label="Placement requirements">
            <thead>
              <tr>
                <th>Instrument</th>
                <th>x/z</th>
                <th>Yaw</th>
                <th>Height</th>
                <th>Limited by</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.twin_id}>
                  <th scope="row">{r.name}</th>
                  <Band row={r} axes={["x", "z"]} unit="mm" />
                  <Band row={r} axes={["yaw"]} unit="°" />
                  {r.role === "spare" ? (
                    <td />
                  ) : (
                    <Band row={r} axes={["height"]} unit="mm" />
                  )}
                  <td title={r.binding?.message ?? undefined}>
                    {r.binding
                      ? `${sideText(r.binding)} ${limitText(r.binding)}`
                      : r.complete
                        ? ""
                        : "…"}
                  </td>
                </tr>
              ))}
            </tbody>
            {arms.length > 0 && (
              <tbody>
                <tr>
                  <th colSpan={5} className={s.groupRow}>
                    Arm calibration
                  </th>
                </tr>
                {arms.map((r) => (
                  <tr key={r.twin_id}>
                    <th scope="row">{r.name} base</th>
                    <Band row={r} axes={["x", "z"]} unit="mm" />
                    <Band row={r} axes={["yaw"]} unit="°" />
                    <Band row={r} axes={["height"]} unit="mm" />
                    <td title={r.binding?.message ?? undefined}>
                      {r.binding
                        ? `${sideText(r.binding)} ${limitText(r.binding)}`
                        : ""}
                    </td>
                  </tr>
                ))}
                {arms.map((r) =>
                  r.tool ? (
                    <tr key={`${r.twin_id}-tool`}>
                      <th scope="row">Tool offset</th>
                      <td>
                        {r.tool.lateral_m == null
                          ? "…"
                          : `±${mm(r.tool.lateral_m)} mm`}
                      </td>
                      <td />
                      <td>
                        {r.tool.longer_m == null || r.tool.shorter_m == null
                          ? "…"
                          : `+${mm(r.tool.longer_m)} / −${mm(r.tool.shorter_m)} mm`}
                      </td>
                      <td />
                    </tr>
                  ) : null,
                )}
              </tbody>
            )}
          </table>
          <Curve
            series={[
              {
                label: "Every instrument",
                points: summary.curves.instruments.points,
                className: s.curveInstruments,
              },
              {
                label: "Arm base",
                points: summary.curves.arm.points,
                className: s.curveArm,
              },
            ]}
          />
          {several && (
            <ul className={s.preferenceList} aria-label="Each workflow">
              {summary.per_workflow.map((w) => (
                <li key={w.name}>
                  <span>
                    {w.name}: ±{mm(w.xz_m)} mm
                  </span>
                  <small>
                    {w.binding
                      ? `${w.binding.name} · ${limitText(w.binding)}`
                      : ""}
                  </small>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <div className={s.optionControls}>
        <button className={studio.secondary} onClick={() => template(false)}>
          <Download size={14} /> Template SVG
        </button>
        <button className={studio.secondary} onClick={() => template(true)}>
          <Printer size={14} /> Print 1:1 on A4
        </button>
      </div>
      <details className={s.fewer}>
        <summary>Bench workflows</summary>
        <ul className={s.preferenceList}>
          {kept.map((w) => (
            <li key={w.id}>
              <span>{w.name}</span>
              <button
                className={studio.secondary}
                aria-label={`Remove ${w.name}`}
                disabled={busy}
                onClick={() => onDrop(w.id)}
              >
                <Trash2 size={13} />
              </button>
            </li>
          ))}
        </ul>
        <form
          className={s.preferenceForm}
          onSubmit={(e) => {
            e.preventDefault();
            onKeep(name.trim());
            setName("");
          }}
        >
          <input
            aria-label="Kept workflow name"
            placeholder="Name"
            maxLength={60}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button
            className={studio.secondary}
            disabled={busy || !canKeep || !name.trim()}
            title={canKeep ? undefined : "Already kept, or no transfer step"}
          >
            Keep current workflow
          </button>
        </form>
      </details>
      <details className={studio.notice}>
        <summary>Synthetic geometry, not a calibrated placement</summary>
        Each band replans the workflow with one instrument moved along one bench
        axis, turned, or raised, outward in coarse steps and then by bisection,
        as if the arm were taught the positions the instruments actually have.
        Combined rows move every instrument at once within the ± tolerance, half
        the samples at the corners. A tool longer than modelled counts as the
        arm base standing lower; a sideways tool offset as the base moved. Run
        untaught, the gripper also has to meet labware within ±
        {mm(summary?.capture_m ?? 0.02)} mm. No Isaac/GPU, physical robot or
        chemical validation.
      </details>
    </section>
  );
}
