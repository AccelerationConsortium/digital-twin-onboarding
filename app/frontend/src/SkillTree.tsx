import { useCallback, useLayoutEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Atom,
  AudioWaveform,
  Check,
  Cog,
  Disc3,
  Flame,
  Heater,
  Pipette,
  Play,
  Plus,
  Rainbow,
  RefreshCw,
  Repeat,
  Scale,
  ScanLine,
  Shuffle,
  Sparkles,
  Sun,
  Thermometer,
  Wind,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { ApiError, api, json } from "./api";
import { workflows } from "./discoveryContent";
import StageLine from "./StageLine";
import StageRail from "./StageRail";
import {
  STAGES,
  STAGE_LABEL,
  useSkills,
  type SkillFunction,
  type SkillPaper,
  type Skills,
} from "./skills";
import s from "./SkillTree.module.css";

const ICONS: Record<string, LucideIcon> = {
  dispense: Pipette,
  stir: RefreshCw,
  incubate: Thermometer,
  sonicate: AudioWaveform,
  "dose-powder": Scale,
  grind: Cog,
  "spin-coat": Disc3,
  anneal: Heater,
  fire: Flame,
  illuminate: Sun,
  conductivity: Zap,
  absorbance: Rainbow,
  fluorescence: Sparkles,
  "sheet-resistance": ScanLine,
  "gas-analysis": Wind,
  diffraction: Atom,
};
const DID: Record<string, string> = {
  load: "Loaded",
  mix: "Mixed",
  heat: "Heated",
  wait: "Held",
  read: "Read",
};
type Trace = {
  step: number;
  operation: string;
  volume_ul: number;
  temperature_c: number;
  elapsed_s: number;
}[];
type Link = { d: string; stage: string; lit: boolean };

const paperOf = (id: string) => workflows.find((w) => w.id === id);
const ready = (paper: SkillPaper) => paper.steps.filter((x) => x.met).length;

/** The workflow to look at first: the nearest one not yet reproduced. */
function nearest(skills: Skills) {
  const open = skills.papers.filter((p) => !p.reproduced);
  return (
    [...open].sort(
      (a, b) => ready(b) / b.steps.length - ready(a) / a.steps.length,
    )[0] ?? skills.papers[0]
  ).id;
}

/** One function, and a twin to have do it. */
function FunctionPanel({
  item,
  skills,
  onMet,
  onPaper,
  onInstrument,
}: {
  item: SkillFunction;
  skills: Skills;
  onMet: (next: Skills) => void;
  onPaper: (id: string) => void;
  onInstrument: (id: string) => void;
}) {
  const [twin, setTwin] = useState(item.met ?? item.twins[0]?.id ?? "");
  const [trace, setTrace] = useState<Trace | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const used = skills.papers.filter((p) =>
    p.steps.some((step) => step.functions.includes(item.id)),
  );
  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const next = await api<Skills & { trace: Trace }>(
        "/skills/meet",
        json({
          expected_version: skills.version,
          function: item.id,
          instrument: twin,
        }),
      );
      setTrace(next.trace);
      onMet(next);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 409
          ? "Your tree changed in another tab. Reload to see it."
          : (e as Error).message,
      );
    } finally {
      setBusy(false);
    }
  };
  const chosen = item.twins.find((t) => t.id === twin);
  return (
    <div
      className={s.panel}
      role="region"
      aria-label={item.label}
      data-stage={item.group === "prepare" ? "prepare" : "characterize"}
    >
      <div className={s.panelHead}>
        <h3>{item.label}</h3>
        <span className={s.chips}>
          {item.group === "prepare" ? (
            <span data-stage="prepare">Prepare</span>
          ) : (
            <>
              <span data-stage="characterize">Characterize</span>
              <span data-stage="test">Test</span>
            </>
          )}
        </span>
      </div>
      <div className={s.twins} role="radiogroup" aria-label="Twin">
        {item.twins.map((t) => (
          <label key={t.id} data-picked={twin === t.id || undefined}>
            <input
              type="radio"
              name={`twin-${item.id}`}
              checked={twin === t.id}
              onChange={() => {
                setTwin(t.id);
                setTrace(null);
              }}
            />
            <strong>{t.name}</strong>
            <small>{t.source}</small>
          </label>
        ))}
      </div>
      <div className={s.panelRun}>
        <button className={s.primary} disabled={busy || !twin} onClick={run}>
          <Play size={15} /> {busy ? "Running…" : "Run it on the twin"}
        </button>
        {chosen?.source === "Cloud lab" && (
          <button className={s.quiet} onClick={() => onInstrument(chosen.id)}>
            Open its page <ArrowRight size={14} />
          </button>
        )}
        {trace && (
          <ol className={s.trace} aria-label="What the twin did">
            {trace.map((entry, index) => (
              <li
                key={entry.step}
                style={{ animationDelay: `${index * 320}ms` }}
              >
                <Check size={13} />
                {DID[entry.operation]}
                <small>
                  {entry.operation === "load"
                    ? `${entry.volume_ul} µL`
                    : entry.operation === "heat"
                      ? `${entry.temperature_c} °C`
                      : entry.operation === "read"
                        ? "synthetic readout"
                        : `${Math.round(entry.elapsed_s)} s`}
                </small>
              </li>
            ))}
          </ol>
        )}
        {error && <p role="alert">{error}</p>}
      </div>
      {!!used.length && (
        <div className={s.usedBy}>
          <small>Used in</small>
          {used.map((p) => (
            <button key={p.id} onClick={() => onPaper(p.id)}>
              {paperOf(p.id)?.title}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Published workflows as lines through the three stages. */
export function PublishedLines({
  skills,
  selected,
  onSelect,
  onOpen,
  dotRef,
}: {
  skills: Skills;
  selected?: string;
  onSelect?: (id: string) => void;
  onOpen: (id: string) => void;
  dotRef?: (index: number, node: HTMLElement | null) => void;
}) {
  return (
    <div className={s.published}>
      <div className={s.laneHead} aria-hidden="true">
        {STAGES.map((stage) => (
          <span key={stage} data-stage={stage}>
            {STAGE_LABEL[stage]}
          </span>
        ))}
      </div>
      <ul>
        {skills.papers.map((paper) => {
          const meta = paperOf(paper.id);
          const open = selected === paper.id;
          return (
            <li
              key={paper.id}
              data-selected={open || undefined}
              data-done={paper.reproduced || undefined}
            >
              <button
                className={s.paper}
                aria-expanded={onSelect ? open : undefined}
                onClick={() =>
                  onSelect ? onSelect(paper.id) : onOpen(paper.id)
                }
              >
                <span className={s.paperName}>
                  <strong>{meta?.title}</strong>
                  <small>{meta?.domain}</small>
                </span>
                <StageLine
                  steps={paper.steps.map((step) => ({
                    stage: step.stage,
                    lit: paper.reproduced || step.met,
                    title: step.text,
                  }))}
                  loop={meta?.kind === "Closed loop"}
                  dotRef={open ? dotRef : undefined}
                />
                <span className={s.paperState}>
                  {paper.reproduced ? (
                    <>
                      <Check size={14} /> Reproduced
                    </>
                  ) : (
                    `${ready(paper)} / ${paper.steps.length} ready`
                  )}
                </span>
              </button>
              {open && (
                <div className={s.paperOpen}>
                  <ol>
                    {paper.steps.map((step, index) => (
                      <li
                        key={index}
                        data-stage={step.stage}
                        data-lit={paper.reproduced || step.met || undefined}
                      >
                        {step.text}
                      </li>
                    ))}
                    {meta?.kind === "Closed loop" && (
                      <li className={s.decide}>
                        <Repeat size={13} /> {meta.question}
                      </li>
                    )}
                  </ol>
                  <button
                    className={s.primary}
                    onClick={() => onOpen(paper.id)}
                  >
                    {paper.reproduced
                      ? "Run it again"
                      : "Reproduce on the twins"}
                    <ArrowRight size={15} />
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function SkillTree({
  onNavigate,
  onChange,
}: {
  onNavigate: (target: string) => void;
  /** Open a published workflow where it can be changed. */
  onChange: (paper: string) => void;
}) {
  const [skills, setSkills] = useSkills();
  const [picked, setPicked] = useState<string>();
  const [open, setOpen] = useState<string | null>(null);
  const [links, setLinks] = useState<Link[]>([]);
  const tree = useRef<HTMLDivElement>(null);
  const nodes = useRef(new Map<string, HTMLElement>());
  const dots = useRef(new Map<number, HTMLElement>());
  const selected = skills ? (picked ?? nearest(skills)) : undefined;
  const paper = skills
    ? skills.papers.find((p) => p.id === selected)
    : undefined;

  // The branches from each function the selected workflow needs down to its step.
  const draw = useCallback(() => {
    const box = tree.current?.getBoundingClientRect();
    if (!box || !paper || !skills) return setLinks([]);
    const next: Link[] = [];
    paper.steps.forEach((step, index) => {
      const to = dots.current.get(index)?.getBoundingClientRect();
      if (!to) return;
      for (const id of step.functions) {
        const from = nodes.current.get(id)?.getBoundingClientRect();
        if (!from) continue;
        const x1 = from.left + from.width / 2 - box.left;
        const y1 = from.bottom - box.top;
        const x2 = to.left + to.width / 2 - box.left;
        const y2 = to.top - box.top;
        const mid = y1 + (y2 - y1) * 0.55;
        next.push({
          d: `M${x1} ${y1} C${x1} ${mid} ${x2} ${mid} ${x2} ${y2}`,
          stage: step.stage,
          lit: !!skills.functions.find((f) => f.id === id)?.met,
        });
      }
    });
    setLinks(next);
  }, [paper, skills]);
  useLayoutEffect(() => {
    draw();
    if (!tree.current) return;
    const watch = new ResizeObserver(draw);
    watch.observe(tree.current);
    return () => watch.disconnect();
  }, [draw, open]);

  if (skills === false)
    return (
      <div className={s.page}>
        <p role="alert">
          Your skill tree could not be loaded. Reload to try again.
        </p>
      </div>
    );
  if (!skills || !paper) return <div className={s.page} aria-busy="true" />;

  const needed = new Set(paper.steps.flatMap((step) => step.functions));
  const shown = skills.functions.find((f) => f.id === open);
  const group = (name: "prepare" | "measure") => (
    <div
      className={s.group}
      data-stage={name === "prepare" ? "prepare" : "measure"}
    >
      <h3>{name === "prepare" ? "Prepare" : "Characterize · Test"}</h3>
      <div className={s.nodes}>
        {skills.functions
          .filter((f) => f.group === name)
          .map((f) => {
            const Icon = ICONS[f.id];
            return (
              <button
                key={f.id}
                className={s.node}
                data-met={!!f.met || undefined}
                data-needed={needed.has(f.id) || undefined}
                aria-expanded={open === f.id}
                aria-label={`${f.label}${f.met ? ", met" : ""}`}
                onClick={() => setOpen(open === f.id ? null : f.id)}
              >
                <span
                  className={s.badge}
                  ref={(node) => {
                    if (node) nodes.current.set(f.id, node);
                    else nodes.current.delete(f.id);
                  }}
                >
                  <Icon size={22} />
                  {f.met && (
                    <em>
                      <Check size={11} />
                    </em>
                  )}
                </span>
                <span>{f.label}</span>
              </button>
            );
          })}
      </div>
    </div>
  );
  const recombined = skills.recombined.filter(
    (pair) => pair.prepare === paper.id || pair.measure === paper.id,
  );
  const title = paperOf(paper.id)?.title;
  const own: [LucideIcon, string, string | null][] = [
    [Shuffle, "Swap an instrument", paper.swapped ? "Done" : null],
    [
      Plus,
      "Add a measurement",
      paper.extended.length
        ? paper.extended
            .map((id) => skills.functions.find((f) => f.id === id)?.label)
            .join(", ")
        : null,
    ],
    [
      Repeat,
      "Recombine two papers",
      recombined.length
        ? recombined
            .map(
              (pair) =>
                `${paperOf(pair.prepare)?.title} → ${paperOf(pair.measure)?.title}`,
            )
            .join(" · ")
        : null,
    ],
  ];
  return (
    <div className={s.page}>
      <h1>Skill tree</h1>
      <StageRail skills={skills} onNavigate={onNavigate} />
      <div className={s.tree} ref={tree}>
        <svg className={s.links} aria-hidden="true">
          {links.map((link, index) => (
            <path
              key={index}
              d={link.d}
              data-stage={link.stage}
              data-lit={link.lit || undefined}
            />
          ))}
        </svg>
        <section className={s.tier} aria-labelledby="tier-instruments">
          <h2 id="tier-instruments">
            <span>1</span> Instruments
          </h2>
          <div className={s.groups}>
            {group("prepare")}
            {group("measure")}
          </div>
          {shown && (
            <FunctionPanel
              key={shown.id}
              item={shown}
              skills={skills}
              onMet={setSkills}
              onPaper={(id) => {
                setPicked(id);
                setOpen(null);
              }}
              onInstrument={(id) => onNavigate(`instruments/${id}`)}
            />
          )}
        </section>
        <p className={s.gate}>
          <span>
            {title} · {ready(paper)} of {paper.steps.length} steps met
          </span>
        </p>
        <section className={s.tier} aria-labelledby="tier-published">
          <h2 id="tier-published">
            <span>2</span> Published workflows
          </h2>
          <PublishedLines
            skills={skills}
            selected={paper.id}
            onSelect={setPicked}
            onOpen={(id) => onNavigate(`marketplace/${id}`)}
            dotRef={(index, node) => {
              if (node) dots.current.set(index, node);
              else dots.current.delete(index);
            }}
          />
        </section>
        <p className={s.gate}>
          <span>
            {paper.reproduced
              ? `${title} · reproduced`
              : `${title} · not reproduced yet`}
          </span>
        </p>
        <section className={s.tier} aria-labelledby="tier-own">
          <h2 id="tier-own">
            <span>3</span> Your own
          </h2>
          <div className={s.own}>
            {own.map(([Icon, name, done]) => (
              <div
                key={name}
                className={s.ownNode}
                data-met={!!done || undefined}
              >
                <span className={s.hex}>
                  <Icon size={22} />
                </span>
                <strong>{name}</strong>
                <small>{done ?? " "}</small>
              </div>
            ))}
            <button className={s.primary} onClick={() => onChange(paper.id)}>
              Change {title} <ArrowRight size={15} />
            </button>
          </div>
        </section>
      </div>
      <details className={s.about}>
        <summary>What the tree records</summary>
        <p>{skills.statement}</p>
      </details>
    </div>
  );
}
