import { useEffect, useMemo, useState } from "react";
import { ArrowRight, Check, Play, RotateCcw, Undo2 } from "lucide-react";
import { EQUIPMENT } from "../learningContent";
import {
  COVERS,
  DECK_ITEMS,
  ROBOTS,
  pipetteReaches,
  placementIssue,
  type DeckItemId,
  type Robot,
} from "./labTwinContent";
import { reducedMotion, useDrag, useProgress } from "./useDrag";
import s from "./LabTwin.module.css";

type Placement = Partial<Record<DeckItemId, string>>;
type Saved = {
  robot: Robot;
  decks: Record<Robot, Placement>;
  done: string[];
};
const KEY = "lab.twin.deck";
const EMPTY: Saved = { robot: "flex", decks: { flex: {}, ot2: {} }, done: [] };
const ROUTE = ["tips", "stock", "plate", "waste"] as const;
const CAPTIONS = [
  "Pick up a tip",
  "Aspirate 100 µL",
  "Dispense into well A1",
  "Discard the tip",
];
const TASKS = [
  ["reach", "Place tips, source and plate where the pipette reaches"],
  ["run", "Run the transfer"],
  ["module", "Fit a Heater-Shaker on the deck"],
  ["short", "Arrange a near-shortest pipette path"],
] as const;
// Slots are wider than they are deep (128 × 86 mm footprint).
const DEPTH = 86 / 128;

function position(robot: Robot, slot: string): [number, number] {
  const rows = ROBOTS[robot].rows;
  const row = rows.findIndex((r) => r.includes(slot));
  return [rows[row].indexOf(slot), row];
}
function travel(robot: Robot, stops: string[]) {
  let total = 0;
  for (let i = 1; i < stops.length; i++) {
    const [ax, ay] = position(robot, stops[i - 1]);
    const [bx, by] = position(robot, stops[i]);
    total += Math.hypot(bx - ax, (by - ay) * DEPTH);
  }
  return total;
}

export default function DeckTwin({
  onLesson,
  busy,
}: {
  onLesson: () => void;
  busy?: boolean;
}) {
  const { saved, update, change, finish } = useProgress(KEY, EMPTY);
  const [picked, setPicked] = useState<DeckItemId | null>(null);
  const [focus, setFocus] = useState<DeckItemId | "waste">("tips");
  const [message, setMessage] = useState("");
  const [step, setStep] = useState<number | null>(null);
  const [lastRun, setLastRun] = useState<number | null>(null);
  const { robot } = saved;
  const deck = ROBOTS[robot];
  const placed = saved.decks[robot];
  const thermo = COVERS[robot].thermocycler!;
  const covered = placed.thermocycler ? thermo.slice(1) : [];
  const occupant = (slot: string) =>
    (Object.keys(placed) as DeckItemId[]).find((id) => placed[id] === slot);
  const setDeck = (next: Placement) =>
    change((old) => ({ decks: { ...old.decks, [old.robot]: next } }));

  const place = (item: DeckItemId, slot: string) => {
    if (step !== null) return;
    setPicked(null);
    setFocus(item);
    if (slot === "tray") {
      const next = { ...placed };
      delete next[item];
      setDeck(next);
      setMessage(`${DECK_ITEMS[item].name} returned to the tray.`);
      return;
    }
    const issue =
      covered.includes(slot) && item !== "thermocycler"
        ? `${slot} is under the thermocycler.`
        : placementIssue(robot, item, slot);
    if (issue) {
      setMessage(issue);
      return;
    }
    const next = { ...placed };
    const from = next[item];
    const other = occupant(slot);
    if (other && other !== item) {
      if (from && !placementIssue(robot, other, from)) next[other] = from;
      else delete next[other];
    }
    if (item === "thermocycler")
      for (const id of Object.keys(next) as DeckItemId[])
        if (id !== item && thermo.includes(next[id]!)) delete next[id];
    next[item] = slot;
    setDeck(next);
    setLastRun(null);
    setMessage(
      !pipetteReaches(robot, slot) && DECK_ITEMS[item].kind === "labware"
        ? `${DECK_ITEMS[item].name} is on ${slot}. Only the gripper reaches column 4; the pipette cannot use it there.`
        : `${DECK_ITEMS[item].name} placed on ${slot}.`,
    );
  };
  const { ghost, start, click } = useDrag((item, target) =>
    place(item as DeckItemId, target),
  );

  const ready = (["tips", "stock", "plate"] as const).every(
    (id) => placed[id] && pipetteReaches(robot, placed[id]!),
  );
  useEffect(() => {
    if (ready) finish("reach");
    if (placed.heater) finish("module");
    // Tasks only ever get added.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, placed.heater]);

  const stops = ready
    ? [placed.tips!, placed.stock!, placed.plate!, deck.waste]
    : [];
  const path = ready ? travel(robot, stops) : 0;
  // The shortest path the same three labware could take on this deck.
  const shortest = useMemo(() => {
    if (!ready) return 0;
    const used = new Set(
      (Object.keys(placed) as DeckItemId[])
        .filter((id) => DECK_ITEMS[id].kind === "module")
        .map((id) => placed[id]!),
    );
    const free = deck.rows
      .flat()
      .filter(
        (slot) =>
          slot !== deck.waste &&
          pipetteReaches(robot, slot) &&
          !used.has(slot) &&
          !covered.includes(slot),
      );
    let best = Infinity;
    for (const a of free)
      for (const b of free)
        for (const c of free)
          if (a !== b && b !== c && a !== c)
            best = Math.min(best, travel(robot, [a, b, c, deck.waste]));
    return best;
  }, [ready, placed, robot, deck, covered]);

  useEffect(() => {
    if (step === null) return;
    if (step >= ROUTE.length) {
      setStep(null);
      setLastRun(path);
      finish("run");
      const near = path <= shortest * 1.15 + 1e-6;
      if (near) finish("short");
      setMessage(
        near
          ? "Transfer complete. That path is close to the shortest this deck allows."
          : "Transfer complete. Move the labware closer together and run again.",
      );
      return;
    }
    const timer = window.setTimeout(
      () => setStep(step + 1),
      reducedMotion() ? 0 : 900,
    );
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  const head = step !== null && step < ROUTE.length ? stops[step] : null;
  const [hx, hy] = head ? position(robot, head) : [0, 0];
  const cols = deck.rows[0].length;
  const info =
    focus === "waste"
      ? {
          name: deck.wasteName,
          purpose: EQUIPMENT.waste.purpose,
          manual: EQUIPMENT.waste.manual,
          robot: EQUIPMENT.waste.robot,
        }
      : {
          ...DECK_ITEMS[focus],
          ...(focus in EQUIPMENT
            ? {
                manual: EQUIPMENT[focus as keyof typeof EQUIPMENT].manual,
                robot: EQUIPMENT[focus as keyof typeof EQUIPMENT].robot,
              }
            : {}),
        };
  return (
    <section className={s.twin} aria-labelledby="deck-twin-title">
      <header className={s.twinHead}>
        <h3 id="deck-twin-title">Set up the deck</h3>
        <div className={s.segmented} role="group" aria-label="Robot">
          {(Object.keys(ROBOTS) as Robot[]).map((id) => (
            <button
              key={id}
              aria-pressed={robot === id}
              disabled={step !== null}
              onClick={() => {
                update({ robot: id });
                setPicked(null);
                setLastRun(null);
                setMessage("");
              }}
            >
              {ROBOTS[id].name.replace("Opentrons ", "")}
            </button>
          ))}
        </div>
      </header>
      <div className={s.twinBody}>
        <div className={s.stageCol}>
          <div
            className={s.tray}
            data-drop="tray"
            aria-label="Labware and modules"
            role="group"
          >
            {(Object.keys(DECK_ITEMS) as DeckItemId[]).map((id) => (
              <button
                key={id}
                className={s.chip}
                data-kind={DECK_ITEMS[id].kind}
                data-placed={!!placed[id] || undefined}
                aria-pressed={picked === id}
                disabled={step !== null}
                onPointerDown={start(id, DECK_ITEMS[id].short)}
                onClick={click(() => {
                  setPicked(picked === id ? null : id);
                  setFocus(id);
                  setMessage(
                    picked === id
                      ? ""
                      : `Choose a slot for the ${DECK_ITEMS[id].name.toLowerCase()}.`,
                  );
                })}
              >
                {placed[id] ? <Check size={13} /> : <i className={s.swatch} />}
                {DECK_ITEMS[id].short}
                {placed[id] && <small>{placed[id]}</small>}
              </button>
            ))}
          </div>
          <div
            className={s.deck}
            data-robot={robot}
            style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}
            aria-label={`${deck.name} deck`}
          >
            {deck.rows.flat().map((slot) => {
              const item = occupant(slot);
              const waste = slot === deck.waste;
              const under = covered.includes(slot);
              const verdict =
                picked && !waste
                  ? placementIssue(robot, picked, slot) ||
                    (under && picked !== "thermocycler")
                    ? "no"
                    : "ok"
                  : undefined;
              return (
                <button
                  key={slot}
                  className={s.slot}
                  data-drop={slot}
                  data-verdict={verdict}
                  data-staging={!pipetteReaches(robot, slot) || undefined}
                  data-module={item && DECK_ITEMS[item].kind === "module"}
                  data-span={item === "thermocycler" ? robot : undefined}
                  data-active={head === slot || undefined}
                  disabled={step !== null}
                  aria-label={`Slot ${slot}, ${
                    waste
                      ? deck.wasteName
                      : item
                        ? DECK_ITEMS[item].name
                        : under
                          ? "under the thermocycler"
                          : "empty"
                  }`}
                  onClick={() => {
                    if (picked) place(picked, slot);
                    else if (item) setFocus(item);
                    else if (waste) setFocus("waste");
                  }}
                >
                  <span className={s.slotName}>{slot}</span>
                  {waste ? (
                    <span className={s.fixed}>{deck.wasteName}</span>
                  ) : item ? (
                    <span
                      className={s.placed}
                      data-kind={DECK_ITEMS[item].kind}
                      onPointerDown={start(item, DECK_ITEMS[item].short)}
                    >
                      {DECK_ITEMS[item].short}
                    </span>
                  ) : under ? (
                    <span className={s.fixed}>Thermocycler</span>
                  ) : null}
                </button>
              );
            })}
            {head && (
              <span
                className={s.head}
                aria-hidden="true"
                style={{
                  left: `${((hx + 0.5) / cols) * 100}%`,
                  top: `${((hy + 0.5) / deck.rows.length) * 100}%`,
                }}
              />
            )}
          </div>
          <p className={s.message} role="status">
            {step !== null && step < ROUTE.length
              ? `${step + 1} / 4 · ${CAPTIONS[step]} at ${stops[step]}`
              : message ||
                "Drag labware onto the deck, or pick it and then a slot."}
          </p>
        </div>
        <aside className={s.side}>
          <div className={s.infoCard}>
            <strong>{info.name}</strong>
            <p>{info.purpose}</p>
            {"manual" in info && info.manual && (
              <p className={s.compare}>
                <span>{info.manual}</span>
                <ArrowRight size={14} />
                <span>{info.robot}</span>
              </p>
            )}
            {focus !== "waste" && placed[focus] && (
              <button
                className={s.textBtn}
                disabled={step !== null}
                onClick={() => place(focus, "tray")}
              >
                <Undo2 size={14} /> Back to the tray
              </button>
            )}
          </div>
          <div className={s.metrics}>
            <div>
              <span>Pipette path</span>
              <strong>
                {lastRun !== null
                  ? `${lastRun.toFixed(1)}`
                  : ready
                    ? path.toFixed(1)
                    : "—"}
              </strong>
              <small>slot widths</small>
            </div>
            <div>
              <span>Shortest here</span>
              <strong>{ready ? shortest.toFixed(1) : "—"}</strong>
              <small>same deck</small>
            </div>
          </div>
          <div className={s.actions}>
            <button
              className={s.primary}
              disabled={!ready || step !== null}
              onClick={() => {
                setPicked(null);
                setStep(0);
              }}
            >
              <Play size={15} /> Run the transfer
            </button>
            <button
              className={s.ghostBtn}
              disabled={step !== null}
              onClick={() => {
                setDeck({});
                setLastRun(null);
                setMessage("Deck cleared.");
              }}
            >
              <RotateCcw size={14} /> Clear deck
            </button>
          </div>
          {!ready && (
            <small className={s.reason}>
              Needs tips, a source and a plate in pipette reach.
            </small>
          )}
          <Tasks done={saved.done} tasks={TASKS} />
          <button className={s.next} onClick={onLesson} disabled={busy}>
            Take it into the guided Flex lesson <ArrowRight size={15} />
          </button>
        </aside>
      </div>
      <p className={s.scope}>
        Teaching twin · synthetic. Placement rules follow the robot's deck; it
        does not check collisions, liquid height or pipetting accuracy.
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

export function Tasks({
  done,
  tasks,
}: {
  done: string[];
  tasks: readonly (readonly [string, string])[];
}) {
  const count = tasks.filter(([id]) => done.includes(id)).length;
  return (
    <div className={s.tasks}>
      <div className={s.tasksHead}>
        <strong>Challenges</strong>
        <span>
          {count} / {tasks.length}
        </span>
      </div>
      <ul>
        {tasks.map(([id, label]) => (
          <li key={id} data-done={done.includes(id) || undefined}>
            <span aria-hidden="true">
              {done.includes(id) ? <Check size={12} /> : null}
            </span>
            {label}
            <span className={s.srOnly}>
              {done.includes(id) ? " · done" : " · to do"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
