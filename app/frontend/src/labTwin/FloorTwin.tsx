import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Eye,
  EyeOff,
  LayoutGrid,
  Play,
  RotateCcw,
  Undo2,
} from "lucide-react";
import { workflows } from "../discoveryContent";
import {
  FLOOR,
  FLOOR_LABS,
  type FloorLab,
  type Station,
} from "./labTwinContent";
import { Tasks } from "./DeckTwin";
import { reducedMotion, useDrag, useProgress } from "./useDrag";
import s from "./LabTwin.module.css";

type Cell = [number, number];
type Saved = {
  lab: string;
  layouts: Record<string, Record<string, Cell>>;
  routes: Record<string, string[]>;
  done: string[];
};
const KEY = "lab.twin.floor";
const EMPTY: Saved = { lab: "clio", layouts: {}, routes: {}, done: [] };
const TASKS = [
  ["place", "Place every station of one lab"],
  ["route", "Route a sample in the paper's order"],
  ["run", "Run a sample through your layout"],
  ["beat", "Match or beat the teaching layout's travel"],
  ["arm", "Keep an arm-centred cell within reach"],
] as const;
const KIND_NAMES: Record<Station["kind"], string> = {
  storage: "Storage",
  liquid: "Liquid handling",
  process: "Processing",
  measure: "Measurement",
  transport: "Transport",
  compute: "Decision (software)",
};

const physical = (lab: FloorLab, id: string) =>
  lab.stations.find((st) => st.id === id)?.kind !== "compute";
const reach = (a: Cell, b: Cell) =>
  Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]));

/** Distance a sample travels between physical stations, via the hub if there is one. */
function travel(lab: FloorLab, at: Record<string, Cell>) {
  const legs = lab.route.filter((id) => physical(lab, id));
  const hub = lab.hub && at[lab.hub.id];
  let total = 0;
  for (let i = 0; i < legs.length; i++) {
    const a = at[legs[i]];
    const b = at[legs[(i + 1) % legs.length]];
    if (!a || !b) return null;
    total += hub
      ? Math.hypot(a[0] - hub[0], a[1] - hub[1]) +
        Math.hypot(b[0] - hub[0], b[1] - hub[1])
      : Math.hypot(a[0] - b[0], a[1] - b[1]);
  }
  return total;
}

export default function FloorTwin({
  onNavigate,
  selected,
  onSelect,
}: {
  onNavigate: (target: string) => void;
  /** A published workflow chosen elsewhere on the page, to lay out here too. */
  selected?: string;
  /** Told whenever the lab on the floor changes, so the page can follow it. */
  onSelect?: (workflow: string) => void;
}) {
  const { saved, update, change, finish } = useProgress(KEY, EMPTY);
  const lab = FLOOR_LABS.find((item) => item.workflow === saved.lab)!;
  const paper = workflows.find((item) => item.id === lab.workflow)!;
  const at = saved.layouts[lab.workflow] ?? {};
  const route = saved.routes[lab.workflow] ?? [];
  const [picked, setPicked] = useState<string | null>(null);
  const [focus, setFocus] = useState<string>(lab.stations[0].id);
  const [reference, setReference] = useState(false);
  const [message, setMessage] = useState("");
  const [step, setStep] = useState<number | null>(null);
  const [result, setResult] = useState<number | null>(null);
  const station = (id: string) => lab.stations.find((st) => st.id === id)!;
  const focused = lab.stations.find((st) => st.id === focus) ?? lab.stations[0];
  const setLayout = (next: Record<string, Cell>) =>
    change((old) => ({ layouts: { ...old.layouts, [old.lab]: next } }));
  const setRoute = (next: string[]) =>
    change((old) => ({ routes: { ...old.routes, [old.lab]: next } }));

  const place = (id: string, target: string) => {
    if (step !== null) return;
    setPicked(null);
    setFocus(id);
    setResult(null);
    const next = { ...at };
    if (target === "floor-tray") {
      delete next[id];
      setLayout(next);
      return;
    }
    const cell = target.split(",").map(Number) as Cell;
    const other = Object.keys(next).find(
      (key) => next[key][0] === cell[0] && next[key][1] === cell[1],
    );
    if (other && other !== id) {
      if (next[id]) next[other] = next[id];
      else delete next[other];
    }
    next[id] = cell;
    setLayout(next);
    const hub = lab.hub && next[lab.hub.id];
    setMessage(
      hub &&
        id !== lab.hub!.id &&
        physical(lab, id) &&
        reach(cell, hub) > lab.hub!.reach
        ? `${station(id).name} is out of the arm's reach. Keep it within ${lab.hub!.reach} cells.`
        : `${station(id).name} placed.`,
    );
  };
  const { ghost, start, click } = useDrag(place);

  const allPlaced = lab.stations.every((st) => at[st.id]);
  const hubCell = lab.hub ? at[lab.hub.id] : undefined;
  const outOfReach = lab.hub
    ? lab.stations.filter(
        (st) =>
          st.id !== lab.hub!.id &&
          st.kind !== "compute" &&
          at[st.id] &&
          hubCell &&
          reach(at[st.id], hubCell) > lab.hub!.reach,
      )
    : [];
  const routeCorrect =
    route.length === lab.route.length &&
    route.every((id, i) => id === lab.route[i]);
  const mismatch = route.findIndex((id, i) => id !== lab.route[i]);
  const mine = travel(lab, at);
  const ideal = travel(
    lab,
    Object.fromEntries(lab.stations.map((st) => [st.id, st.reference])),
  )!;
  useEffect(() => {
    if (allPlaced) finish("place");
    if (routeCorrect) finish("route");
    if (allPlaced && lab.hub && !outOfReach.length) finish("arm");
    // Challenges are only ever added.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allPlaced, routeCorrect, outOfReach.length, lab.workflow]);

  const choose = (item: FloorLab) => {
    update({ lab: item.workflow });
    setFocus(item.stations[0].id);
    setPicked(null);
    setResult(null);
    setMessage("");
    setStep(null);
  };
  // The page shows one published workflow at a time: report the lab on the
  // floor, and take up a workflow picked elsewhere (the 3D workcell's list).
  useEffect(() => {
    onSelect?.(lab.workflow);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lab.workflow]);
  const asked = useRef(selected);
  useEffect(() => {
    if (selected === asked.current) return;
    asked.current = selected;
    const next = FLOOR_LABS.find((item) => item.workflow === selected);
    if (next && next.workflow !== lab.workflow) choose(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const stops = lab.route;
  useEffect(() => {
    if (step === null) return;
    if (step >= stops.length) {
      setStep(null);
      setResult(mine);
      finish("run");
      const beat = mine !== null && mine <= ideal + 1e-6;
      if (beat) finish("beat");
      setMessage(
        beat
          ? "Loop complete. Your layout moves the sample no further than the teaching layout."
          : "Loop complete. Shorten the longest hop and run again.",
      );
      return;
    }
    const timer = window.setTimeout(
      () => setStep(step + 1),
      reducedMotion() ? 0 : 1000,
    );
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);
  const runnable =
    allPlaced && routeCorrect && !outOfReach.length && step === null;
  const current = step !== null && step < stops.length ? stops[step] : null;
  const token = current ? at[current] : null;

  return (
    <section className={s.twin} aria-labelledby="floor-twin-title">
      <header className={s.twinHead}>
        <h3 id="floor-twin-title">Lay out a published lab</h3>
        <div className={s.labPicker} role="group" aria-label="Published lab">
          {FLOOR_LABS.map((item) => (
            <button
              key={item.workflow}
              aria-pressed={item.workflow === lab.workflow}
              disabled={step !== null}
              onClick={() => choose(item)}
            >
              {item.name}
            </button>
          ))}
        </div>
      </header>
      <div className={s.paper}>
        <strong>{paper.title}</strong>
        <a href={paper.url} target="_blank" rel="noreferrer">
          {paper.authors}, {paper.journal} {paper.year} ↗
        </a>
        <span>{lab.mover}</span>
      </div>
      <div className={s.twinBody}>
        <div className={s.stageCol}>
          <div
            className={s.tray}
            data-drop="floor-tray"
            role="group"
            aria-label="Stations"
          >
            {lab.stations.map((st) => (
              <button
                key={st.id}
                className={s.chip}
                data-kind={st.kind}
                data-placed={!!at[st.id] || undefined}
                aria-pressed={picked === st.id}
                disabled={step !== null}
                onPointerDown={start(st.id, st.name)}
                onClick={click(() => {
                  setPicked(picked === st.id ? null : st.id);
                  setFocus(st.id);
                  setMessage(
                    picked === st.id ? "" : `Choose a cell for ${st.name}.`,
                  );
                })}
              >
                <i className={s.swatch} />
                {st.name}
              </button>
            ))}
          </div>
          <div
            className={s.floor}
            style={{ gridTemplateColumns: `repeat(${FLOOR.cols}, 1fr)` }}
            aria-label={`${lab.name} floor`}
          >
            {Array.from({ length: FLOOR.rows }, (_, r) =>
              Array.from({ length: FLOOR.cols }, (_, c) => {
                const here = lab.stations.find(
                  (st) => at[st.id]?.[0] === c && at[st.id]?.[1] === r,
                );
                const ghostRef =
                  reference &&
                  lab.stations.find(
                    (st) => st.reference[0] === c && st.reference[1] === r,
                  );
                const inReach =
                  hubCell && reach([c, r], hubCell) <= lab.hub!.reach;
                const order = here ? lab.route.indexOf(here.id) : -1;
                return (
                  <button
                    key={`${c},${r}`}
                    className={s.cell}
                    data-drop={`${c},${r}`}
                    data-reach={inReach || undefined}
                    data-active={(here && here.id === current) || undefined}
                    data-far={(here && outOfReach.includes(here)) || undefined}
                    disabled={step !== null}
                    aria-label={`Cell ${c + 1}, ${r + 1}${here ? `, ${here.name}` : ""}`}
                    onClick={() => {
                      if (picked) place(picked, `${c},${r}`);
                      else if (here) setFocus(here.id);
                    }}
                  >
                    {ghostRef && !here && (
                      <span className={s.refMark}>{ghostRef.name}</span>
                    )}
                    {here && (
                      <span
                        className={s.station}
                        data-kind={here.kind}
                        onPointerDown={start(here.id, here.name)}
                      >
                        {order >= 0 && <b>{order + 1}</b>}
                        {here.name}
                      </span>
                    )}
                  </button>
                );
              }),
            )}
            {token && (
              <span
                className={s.token}
                aria-hidden="true"
                style={{
                  left: `${((token[0] + 0.5) / FLOOR.cols) * 100}%`,
                  top: `${((token[1] + 0.5) / FLOOR.rows) * 100}%`,
                }}
              />
            )}
          </div>
          <p className={s.message} role="status">
            {current
              ? `${step! + 1} / ${stops.length} · ${station(current).name}: ${station(current).does}`
              : message ||
                "Drag each station onto the floor, then route the sample."}
          </p>
        </div>
        <aside className={s.side}>
          <div className={s.infoCard}>
            <strong>{focused.name}</strong>
            <span className={s.kindTag} data-kind={focused.kind}>
              {KIND_NAMES[focused.kind]}
            </span>
            <p>{focused.does}</p>
            {at[focused.id] && (
              <button
                className={s.textBtn}
                disabled={step !== null}
                onClick={() => place(focused.id, "floor-tray")}
              >
                <Undo2 size={14} /> Back to the tray
              </button>
            )}
          </div>
          <div className={s.routeBox}>
            <div className={s.tasksHead}>
              <strong>Sample route</strong>
              <button
                className={s.textBtn}
                disabled={!route.length || step !== null}
                onClick={() => setRoute([])}
              >
                Clear
              </button>
            </div>
            <ol className={s.route}>
              {route.map((id, i) => (
                <li key={`${id}-${i}`} data-wrong={i === mismatch || undefined}>
                  {station(id).name}
                </li>
              ))}
            </ol>
            <div
              className={s.routeAdd}
              role="group"
              aria-label="Add the next stop"
            >
              {lab.stations
                .filter(
                  (st) => st.kind !== "transport" && !route.includes(st.id),
                )
                .map((st) => (
                  <button
                    key={st.id}
                    disabled={step !== null}
                    onClick={() => setRoute([...route, st.id])}
                  >
                    + {st.name}
                  </button>
                ))}
            </div>
            {mismatch >= 0 && (
              <p className={s.hint}>
                {mismatch === 0
                  ? "The paper's sample starts at "
                  : `After ${station(route[mismatch - 1]).name.toLowerCase()}, the paper's sample goes to `}
                <strong>{station(lab.route[mismatch]).name}</strong>.
              </p>
            )}
          </div>
          <div className={s.metrics}>
            <div>
              <span>Your travel</span>
              <strong>
                {(result ?? mine) !== null ? (result ?? mine)!.toFixed(1) : "—"}
              </strong>
              <small>cells per loop</small>
            </div>
            <div>
              <span>Teaching layout</span>
              <strong>{ideal.toFixed(1)}</strong>
              <small>cells per loop</small>
            </div>
          </div>
          <div className={s.actions}>
            <button
              className={s.primary}
              disabled={!runnable}
              onClick={() => {
                setPicked(null);
                setStep(0);
              }}
            >
              <Play size={15} /> Run a sample
            </button>
            <button
              className={s.ghostBtn}
              aria-pressed={reference}
              onClick={() => setReference(!reference)}
            >
              {reference ? <EyeOff size={14} /> : <Eye size={14} />}
              Teaching layout
            </button>
          </div>
          {!runnable && step === null && (
            <small className={s.reason}>
              {!allPlaced
                ? "Place every station first."
                : outOfReach.length
                  ? `${outOfReach[0].name} is out of the arm's reach.`
                  : "Route the sample in the paper's order."}
            </small>
          )}
          <div className={s.actions}>
            <button
              className={s.textBtn}
              disabled={step !== null}
              onClick={() =>
                setLayout(
                  Object.fromEntries(
                    lab.stations.map((st) => [st.id, st.reference]),
                  ),
                )
              }
            >
              <LayoutGrid size={14} /> Use the teaching layout
            </button>
            <button
              className={s.textBtn}
              disabled={step !== null}
              onClick={() => {
                setLayout({});
                setResult(null);
              }}
            >
              <RotateCcw size={14} /> Clear floor
            </button>
          </div>
          <Tasks done={saved.done} tasks={TASKS} />
          <button className={s.next} onClick={() => onNavigate("marketplace")}>
            Read the workflow in the marketplace <ArrowRight size={15} />
          </button>
        </aside>
      </div>
      <p className={s.scope}>
        Teaching layout drawn from the paper's description, not its published
        floor plan. Synthetic travel in grid cells; decision software is linked
        by data, not transport.
      </p>
      {ghost && (
        <span
          className={s.dragGhost}
          style={{ left: ghost.x, top: ghost.y }}
          aria-hidden="true"
        >
          {ghost.label}
        </span>
      )}
    </section>
  );
}
