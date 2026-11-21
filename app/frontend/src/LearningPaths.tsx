import {
  ArrowRight,
  Cable,
  ClipboardCheck,
  FlaskConical,
  LayoutGrid,
  Search,
  ShieldCheck,
  Siren,
  SquareTerminal,
  type LucideIcon,
} from "lucide-react";
import { FirstLessonCard } from "./FirstLessonCard";
import { firstTransfer } from "./learningContent";
import {
  LEARNING_LEVELS,
  latestCourseSession,
  learningStatus,
  type LearningLevel,
} from "./learningLevels";
import type { Course, Session } from "./types";
import DeckTwin from "./labTwin/DeckTwin";
import FloorTwin from "./labTwin/FloorTwin";
import ChainTwin from "./labTwin/ChainTwin";
import { useState } from "react";
import { workflows } from "./discoveryContent";
import PaperCell from "./PaperCell";
import StageRail from "./StageRail";
import { PublishedLines } from "./SkillTree";
import { useSkills } from "./skills";
import s from "./LearningPaths.module.css";

const FOCUS = {
  beginner: "Instruments",
  intermediate: "Published labs",
  advanced: "Connectors",
} as const;

type Props = {
  level: LearningLevel;
  courses: Course[];
  sessions: Session[];
  busy: boolean;
  onNavigate: (target: string) => void;
  onFirstLesson: () => void;
  onPractice: () => void;
  onDesign: () => void;
};

function Resource({
  number,
  icon: Icon,
  title,
  description,
  action,
  onOpen,
  disabled,
  status,
}: {
  number: string;
  icon?: LucideIcon;
  title: string;
  description: string;
  action: string;
  onOpen: () => void;
  disabled?: boolean;
  status?: string;
}) {
  return (
    <article className={s.resource}>
      <span className={s.number} aria-hidden="true">
        {Icon ? <Icon size={20} /> : number}
      </span>
      <div>
        <h3>{title}</h3>
        <p>{description}</p>
        {status && <span className={s.status}>{status}</span>}
      </div>
      <button onClick={onOpen} disabled={disabled}>
        {action} <ArrowRight size={17} />
      </button>
    </article>
  );
}

export default function LearningPaths({
  level,
  courses,
  sessions,
  busy,
  onNavigate,
  onFirstLesson,
  onPractice,
  onDesign,
}: Props) {
  const selected = LEARNING_LEVELS.find((item) => item.id === level)!;
  const [skills] = useSkills();
  // The published workflow drawn as a workcell on the intermediate level.
  const [paper, setPaper] = useState<string>(workflows[0].id);
  const shown = workflows.find((w) => w.id === paper)!;
  const first = latestCourseSession(sessions, "flex-first-transfer");
  const practice = latestCourseSession(sessions, "flex-foundations");
  const design = latestCourseSession(sessions, "workflow-sandbox");
  const complete =
    !!first?.lesson_outcome?.practice_completed &&
    !!first?.lesson_outcome?.understanding_demonstrated;
  return (
    <div className={s.page}>
      <header className={s.header}>
        <h1>Learning lab</h1>
        <p>Choose the level that fits your work. You can start at any level.</p>
      </header>
      <StageRail current={2} onNavigate={onNavigate} />
      <nav className={s.levels} aria-label="Learning levels">
        {LEARNING_LEVELS.map((item, index) => (
          <a
            key={item.id}
            href={`/#/learn/${item.id}`}
            aria-current={level === item.id ? "page" : undefined}
            onClick={(event) => {
              if (
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
              )
                return;
              event.preventDefault();
              onNavigate(`learn/${item.id}`);
            }}
          >
            <span className={s.levelStep} aria-hidden="true">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span>
              {item.title}
              <small aria-hidden="true">{FOCUS[item.id]}</small>
            </span>
          </a>
        ))}
      </nav>
      <section aria-labelledby="learning-level-title">
        <div className={s.levelHeading}>
          <h2 id="learning-level-title">{selected.heading}</h2>
          <p>{selected.goal}</p>
        </div>
        {level === "beginner" ? (
          <DeckTwin onLesson={onFirstLesson} busy={busy} />
        ) : level === "intermediate" ? (
          <FloorTwin onNavigate={onNavigate} />
        ) : (
          <ChainTwin onNavigate={onNavigate} />
        )}
        {level === "intermediate" && skills && (
          <section className={s.lines} aria-labelledby="published-lines">
            <h3 id="published-lines">Published workflows as workcells</h3>
            <PaperCell item={shown} />
            <PublishedLines
              skills={skills}
              selected={shown.id}
              onSelect={setPaper}
              onOpen={(id) => onNavigate(`marketplace/${id}`)}
            />
          </section>
        )}
        <h3 className={s.lessonsTitle}>Guided lessons</h3>
        {level === "beginner" ? (
          <>
            <p className={s.scope}>
              Complete this path without connectors, orchestration or a GPU.
            </p>
            <Resource
              number="01"
              title="Meet the instruments"
              description="Explore Flex and OT-2, read the deck and recognize each pipetting operation."
              action="Explore the instruments"
              onOpen={() => onNavigate("instruments")}
            />
            <div className={s.lesson}>
              <span className={s.number} aria-hidden="true">
                02
              </span>
              <div>
                <FirstLessonCard
                  onStart={onFirstLesson}
                  resume={!!first}
                  disabled={busy}
                />
                <p className={s.status}>{learningStatus(first)}</p>
              </div>
            </div>
            <Resource
              number="03"
              title="Change a simple workflow"
              description="Arrange the deck and change transfer volumes in the existing Flex Foundations exercise."
              action={practice ? "Continue experiment" : "Start an experiment"}
              onOpen={onPractice}
              disabled={busy}
              status={learningStatus(practice)}
            />
            <Resource
              number="04"
              title="Make your own transfer"
              description="Continue your saved workflow or start with a four-step Flex transfer. Edit its slots, volume and destination, then inspect the teaching observations."
              action={design ? "Continue my workflow" : "Open transfer starter"}
              onOpen={onDesign}
              disabled={busy}
              status={learningStatus(design)}
            />
            <details className={s.code}>
              <summary>Read the code behind a 100 µL teaching transfer</summary>
              <p>
                This is the Academy teaching runner’s /sessions request, not an
                Opentrons hardware protocol. The layout names deck slots; each
                action names a well and volume.
              </p>
              <ol>
                <li>
                  <code>pickup</code>: attach a fresh tip.
                </li>
                <li>
                  <code>aspirate</code>: draw 100 µL from stock into the tip.
                </li>
                <li>
                  <code>dispense</code>: release 100 µL into well A1.
                </li>
                <li>
                  <code>drop</code>: discard the used tip.
                </li>
              </ol>
              <pre>
                <code>{JSON.stringify(firstTransfer(), null, 2)}</code>
              </pre>
            </details>
            <aside className={s.finish}>
              <h3>
                {complete
                  ? "Your first transfer is understood."
                  : "Finish by explaining the result."}
              </h3>
              <p>
                Use the lesson’s observations and reflection to explain where
                the liquid went. A saved teaching result records practice; it
                does not qualify you to operate a physical instrument.
              </p>
              <button onClick={onFirstLesson} disabled={busy}>
                {complete
                  ? "Review lesson outcome"
                  : first
                    ? "Return to my lesson"
                    : "Open the first lesson"}
                <ArrowRight size={17} />
              </button>
            </aside>
          </>
        ) : level === "intermediate" ? (
          <div className={s.cards}>
            <Resource
              number="01"
              icon={ClipboardCheck}
              title={
                courses.find((course) => course.id === "workflow-readiness")
                  ?.title ?? "Can this workflow run?"
              }
              description="Review and repair a teaching plan, reconcile an uncertain outcome and explain your decision. Existing course answers are kept."
              action="Open workflow judgment course"
              onOpen={() => onNavigate("workflow-course")}
            />
            <Resource
              number="02"
              icon={Search}
              title="Find the fault"
              description="Fourteen workflows, each with one mistake put in. Predict what happens, name the cause and repair it."
              action="Open fault practice"
              onOpen={() => onNavigate("practice")}
            />
            <Resource
              number="03"
              icon={Siren}
              title="Fault drills"
              description="An instrument fault fires mid-run on the twin. Respond against the clock, then take a checkride."
              action="Open fault drills"
              onOpen={() => onNavigate("drills")}
            />
            <Resource
              number="04"
              icon={FlaskConical}
              title="Discovery studio"
              description="Define what changes, what stays fixed and how measurements inform the next experiment."
              action="Open discovery studio"
              onOpen={() => onNavigate("discovery")}
            />
            <Resource
              number="05"
              icon={LayoutGrid}
              title="Plan a multi-device workcell"
              description="Assign operations to selected instruments, arrange a bench layout and inspect its arm path checks."
              action="Open workcell planner"
              onOpen={() => onNavigate("instruments/layout")}
            />
          </div>
        ) : (
          <div className={s.cards}>
            <Resource
              number="01"
              icon={Cable}
              title="Inside a connector"
              description="Explore the existing connector modules, command mapping and referenced implementation."
              action="Open connector explorer"
              onOpen={() => onNavigate("connector")}
            />
            <Resource
              number="02"
              icon={SquareTerminal}
              title="Mock command contracts"
              description="Inspect the selected instruments’ mock interfaces and SiLA bundle exports in the workcell planner."
              action="Explore mock connectors"
              onOpen={() => onNavigate("instruments/connectors")}
            />
            <Resource
              number="03"
              icon={ShieldCheck}
              title="Device readiness"
              description="Understand the checks required before a real connector can be used. Choosing this level does not grant execution permission."
              action="Review readiness"
              onOpen={() => onNavigate("readiness")}
            />
            <article className={s.planned}>
              <h3>Orchestration</h3>
              <p>
                Planned course. No orchestration lesson or completion assessment
                is available yet.
              </p>
            </article>
          </div>
        )}
      </section>
      <section className={s.shared} aria-label="Shared learning resources">
        <h2>Explore alongside any level</h2>
        <button onClick={() => onNavigate("marketplace")}>
          Workflow marketplace <ArrowRight size={17} />
        </button>
        <button onClick={() => onNavigate("sim")}>
          Simulation lab <ArrowRight size={17} />
        </button>
        <button onClick={() => onNavigate("history")}>
          My experiments <ArrowRight size={17} />
        </button>
        <p>
          Native simulation availability depends on the runtime’s readiness, not
          your learning level.
        </p>
      </section>
    </div>
  );
}
