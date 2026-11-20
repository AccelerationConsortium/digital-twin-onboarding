import { useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Play,
  RotateCcw,
  X,
} from "lucide-react";
import {
  operationLabels,
  operations,
  type Operation,
} from "../instrumentTypes";
import {
  DEVICES,
  PLACE_NAMES,
  STARTER_CHAIN,
  devicesFor,
  type ChainStep,
  type Place,
} from "./labTwinContent";
import { Tasks } from "./DeckTwin";
import { reducedMotion, useDrag, useProgress } from "./useDrag";
import s from "./LabTwin.module.css";

type Saved = { steps: ChainStep[]; done: string[] };
const KEY = "lab.twin.chain";
let counter = 0;
const keyed = (step: Omit<ChainStep, "key">): ChainStep => ({
  ...step,
  key: `${Date.now().toString(36)}-${counter++}`,
});
const EMPTY: Saved = { steps: STARTER_CHAIN.map(keyed), done: [] };
const TASKS = [
  ["complete", "Run a chain to completion"],
  ["reject", "See a connector reject a command"],
  ["fault", "See a device fault stop the run"],
  ["custom", "Complete a chain that mixes on the Heater-Shaker"],
] as const;
const PHASES = ["Request", "Running", "Result"] as const;

/** What the connector would say about each step, given where the plate is. */
function check(steps: ChainStep[]) {
  let plate: Place = "flex";
  return steps.map((step, i) => {
    const device = DEVICES[step.device];
    let issue: string | null = null;
    let note: string | null = null;
    if (!device.commands[step.op])
      issue = `${device.name} has no ${operationLabels[step.op].toLowerCase()} command.`;
    else if (device.needs && device.needs !== plate)
      issue = `The plate is on the ${PLACE_NAMES[plate]}, not the ${PLACE_NAMES[device.needs]}.`;
    if (step.op === "load" && step.to) {
      if (step.to === plate)
        note = `The plate is already on the ${PLACE_NAMES[plate]}.`;
      plate = step.to;
    }
    const before = steps[i - 1];
    if (!issue && step.op === "read" && before?.op === "heat")
      note =
        "Reading straight after heating: a wait lets the temperature settle.";
    return { issue, note, plate };
  });
}

export default function ChainTwin({
  onNavigate,
}: {
  onNavigate: (target: string) => void;
}) {
  const { saved, update, finish } = useProgress(KEY, EMPTY);
  const steps = saved.steps;
  const [selected, setSelected] = useState(steps[0]?.key ?? "");
  const [fault, setFault] = useState(false);
  const [run, setRun] = useState<{
    index: number;
    phase: number;
    end?: "complete" | "reject" | "fault";
  } | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const logBox = useRef<HTMLDivElement>(null);
  useEffect(() => {
    logBox.current?.scrollTo({ top: logBox.current.scrollHeight });
  }, [log, run?.end]);
  const checks = check(steps);
  const running = !!run && !run.end;
  const setSteps = (next: ChainStep[]) => {
    update({ steps: next });
    setRun(null);
  };
  const add = (op: Operation, at = steps.length) => {
    const device = devicesFor(op)[0];
    const step = keyed({
      op,
      device,
      ...(op === "load" ? { to: "heater" as Place } : {}),
    });
    setSteps([...steps.slice(0, at), step, ...steps.slice(at)]);
    setSelected(step.key);
  };
  const { ghost, start, click } = useDrag((item, target) => {
    if (running) return;
    const at = target === "lane" ? steps.length : Number(target.split(":")[1]);
    if (item.startsWith("op:")) add(item.slice(3) as Operation, at);
    else {
      const from = steps.findIndex((st) => st.key === item);
      if (from < 0) return;
      const next = steps.filter((st) => st.key !== item);
      next.splice(at > from ? at - 1 : at, 0, steps[from]);
      setSteps(next);
    }
  });
  const edit = (key: string, patch: Partial<ChainStep>) =>
    setSteps(steps.map((st) => (st.key === key ? { ...st, ...patch } : st)));
  const move = (index: number, by: number) => {
    const next = [...steps];
    [next[index], next[index + by]] = [next[index + by], next[index]];
    setSteps(next);
  };

  useEffect(() => {
    if (!run || run.end) return;
    const step = steps[run.index];
    const verdict = checks[run.index];
    const timer = window.setTimeout(
      () => {
        const device = DEVICES[step.device];
        const command = device.commands[step.op] ?? step.op;
        const say = (line: string) => setLog((old) => [...old, line]);
        if (run.phase === 0) {
          say(
            `${run.index + 1}. Orchestrator → ${device.connector ?? "timer"}: ${command}`,
          );
          if (verdict.issue) {
            say(`   Rejected before motion: ${verdict.issue}`);
            setRun({ ...run, end: "reject" });
            finish("reject");
            return;
          }
          setRun({ ...run, phase: 1 });
        } else if (run.phase === 1) {
          if (fault && step.device === "reader") {
            say(
              "   Device error mid-command. The orchestrator stops; it does not guess the outcome.",
            );
            setRun({ ...run, end: "fault" });
            finish("fault");
            return;
          }
          say(`   ${device.name}: running · progress reported`);
          setRun({ ...run, phase: 2 });
        } else {
          say(`   Completed${verdict.note ? ` · ${verdict.note}` : ""}`);
          if (run.index + 1 >= steps.length) {
            setRun({ ...run, end: "complete" });
            finish("complete");
            if (steps.some((st) => st.op === "mix" && st.device === "heater"))
              finish("custom");
          } else setRun({ index: run.index + 1, phase: 0 });
        }
      },
      reducedMotion() ? 0 : 650,
    );
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run]);

  const chosen = steps.find((st) => st.key === selected) ?? steps[0];
  const chosenIndex = chosen ? steps.indexOf(chosen) : -1;
  const live = run ? steps[run.index] : null;
  const liveDevice = live ? DEVICES[live.device] : null;
  return (
    <section className={s.twin} aria-labelledby="chain-twin-title">
      <header className={s.twinHead}>
        <h3 id="chain-twin-title">Run unit operations through connectors</h3>
        <label className={s.toggle}>
          <input
            type="checkbox"
            checked={fault}
            disabled={running}
            onChange={(e) => setFault(e.target.checked)}
          />
          Plate reader faults mid-command
        </label>
      </header>
      <div className={s.twinBody}>
        <div className={s.stageCol}>
          <div className={s.tray} role="group" aria-label="Unit operations">
            {operations.map((op) => (
              <button
                key={op}
                className={s.chip}
                data-kind="op"
                disabled={running}
                onPointerDown={start(`op:${op}`, operationLabels[op])}
                onClick={click(() => add(op))}
              >
                + {operationLabels[op]}
              </button>
            ))}
          </div>
          <ol className={s.lane} data-drop="lane" aria-label="Workflow">
            {steps.map((step, i) => {
              const verdict = checks[i];
              const state = !run
                ? undefined
                : i < run.index || (i === run.index && run.end === "complete")
                  ? "done"
                  : i === run.index
                    ? (run.end ?? "live")
                    : undefined;
              return (
                <li
                  key={step.key}
                  className={s.opCard}
                  data-drop={`at:${i}`}
                  data-selected={step.key === chosen?.key || undefined}
                  data-state={state}
                  data-issue={!!verdict.issue || undefined}
                >
                  <span
                    className={s.grip}
                    onPointerDown={
                      running
                        ? undefined
                        : start(step.key, operationLabels[step.op])
                    }
                    aria-hidden="true"
                  >
                    {i + 1}
                  </span>
                  <button
                    className={s.opName}
                    onClick={() => setSelected(step.key)}
                  >
                    {operationLabels[step.op]}
                    {step.op === "load" && step.to && (
                      <small>→ {PLACE_NAMES[step.to]}</small>
                    )}
                  </button>
                  <select
                    aria-label={`Step ${i + 1} device`}
                    value={step.device}
                    disabled={running}
                    onChange={(e) =>
                      edit(step.key, {
                        device: e.target.value as ChainStep["device"],
                      })
                    }
                  >
                    {devicesFor(step.op).map((id) => (
                      <option key={id} value={id}>
                        {DEVICES[id].name}
                      </option>
                    ))}
                  </select>
                  {step.op === "load" && (
                    <select
                      aria-label={`Step ${i + 1} destination`}
                      value={step.to}
                      disabled={running}
                      onChange={(e) =>
                        edit(step.key, { to: e.target.value as Place })
                      }
                    >
                      {(Object.keys(PLACE_NAMES) as Place[]).map((place) => (
                        <option key={place} value={place}>
                          to {PLACE_NAMES[place]}
                        </option>
                      ))}
                    </select>
                  )}
                  <span className={s.opTools}>
                    <button
                      aria-label={`Move step ${i + 1} up`}
                      disabled={running || i === 0}
                      onClick={() => move(i, -1)}
                    >
                      <ArrowUp size={13} />
                    </button>
                    <button
                      aria-label={`Move step ${i + 1} down`}
                      disabled={running || i === steps.length - 1}
                      onClick={() => move(i, 1)}
                    >
                      <ArrowDown size={13} />
                    </button>
                    <button
                      aria-label={`Remove step ${i + 1}`}
                      disabled={running}
                      onClick={() =>
                        setSteps(steps.filter((st) => st.key !== step.key))
                      }
                    >
                      <X size={13} />
                    </button>
                  </span>
                  {(verdict.issue || verdict.note) && (
                    <small
                      className={s.opIssue}
                      data-warn={!verdict.issue || undefined}
                    >
                      {verdict.issue ?? verdict.note}
                    </small>
                  )}
                </li>
              );
            })}
            {!steps.length && (
              <li className={s.empty}>
                Add unit operations to build a workflow.
              </li>
            )}
          </ol>
          <div className={s.layers} aria-label="Command path">
            {(["Orchestrator", "Connector", "Device twin"] as const).map(
              (layer, i) => (
                <div
                  key={layer}
                  className={s.layer}
                  data-on={
                    (running &&
                      run!.phase >= i &&
                      (i < 2 || liveDevice?.connector)) ||
                    undefined
                  }
                >
                  <span>{layer}</span>
                  <strong>
                    {!live
                      ? "Idle"
                      : i === 0
                        ? operationLabels[live.op]
                        : i === 1
                          ? (liveDevice!.connector ?? "No connector · timer")
                          : liveDevice!.name}
                  </strong>
                  {i === 1 && live && (
                    <code>{liveDevice!.commands[live.op] ?? "—"}</code>
                  )}
                  {i === 2 && run && (
                    <small>
                      {run.end === "fault"
                        ? "Error"
                        : run.end === "reject"
                          ? "Not started"
                          : run.end === "complete"
                            ? "Done"
                            : PHASES[run.phase]}
                    </small>
                  )}
                </div>
              ),
            )}
          </div>
        </div>
        <aside className={s.side}>
          {chosen && (
            <div className={s.infoCard}>
              <strong>
                Step {chosenIndex + 1} · {operationLabels[chosen.op]}
              </strong>
              <p>
                {DEVICES[chosen.device].connector
                  ? `${DEVICES[chosen.device].name} through ${DEVICES[chosen.device].connector}.`
                  : "Handled by the orchestrator itself; no device is commanded."}
              </p>
              <code className={s.command}>
                {DEVICES[chosen.device].commands[chosen.op]}
              </code>
              <p className={s.compare}>
                <span>Plate after this step</span>
                <ArrowRight size={14} />
                <span>{PLACE_NAMES[checks[chosenIndex].plate]}</span>
              </p>
            </div>
          )}
          <div className={s.actions}>
            <button
              className={s.primary}
              disabled={running || !steps.length}
              onClick={() => {
                setLog([]);
                setRun({ index: 0, phase: 0 });
              }}
            >
              <Play size={15} /> Run the chain
            </button>
            <button
              className={s.ghostBtn}
              disabled={running}
              onClick={() => {
                setSteps(STARTER_CHAIN.map(keyed));
                setLog([]);
              }}
            >
              <RotateCcw size={14} /> Starter chain
            </button>
          </div>
          <div
            className={s.log}
            ref={logBox}
            role="log"
            aria-label="Command log"
          >
            {log.length ? (
              log.map((line, i) => <p key={i}>{line}</p>)
            ) : (
              <p>Commands appear here as the chain runs.</p>
            )}
            {run?.end && (
              <strong data-end={run.end}>
                {run.end === "complete"
                  ? "Chain complete"
                  : run.end === "reject"
                    ? `Stopped at step ${run.index + 1}: rejected`
                    : `Stopped at step ${run.index + 1}: device fault`}
              </strong>
            )}
          </div>
          <Tasks done={saved.done} tasks={TASKS} />
          <button className={s.next} onClick={() => onNavigate("connector")}>
            Read the real Flex connector code <ArrowRight size={15} />
          </button>
        </aside>
      </div>
      <p className={s.scope}>
        Teaching twin · synthetic. Flex commands follow the opentrons-flex
        connector; other command names are illustrative.
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
