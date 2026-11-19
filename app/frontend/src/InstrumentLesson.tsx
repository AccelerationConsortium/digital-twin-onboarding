import { ArrowLeft, ArrowRight, Box, ExternalLink } from "lucide-react";
import { Fragment, useEffect, useId, useState } from "react";
import { api } from "./api";
import {
  BASIS_NAMES,
  basisLabel,
  CAN,
  metres,
  part,
  sourceUrl,
  volume,
  type Instrument,
  type Overview,
} from "./cloudlabFacts";
import TwinExplorer, { useTwin } from "./TwinExplorer";
import s from "./InstrumentLesson.module.css";

type Tab = "use" | "parts" | "details";

/** How a sample goes in, in one sentence; where each figure comes from is under Details. */
const goesIn = (item: Instrument) =>
  `${item.access === "front" ? "Through the front" : "From above"}${part(item.opening)}` +
  (item.level_m !== null
    ? `, ${item.level_m.toFixed(2)} m above the bench`
    : "") +
  (item.drawer_m !== null
    ? `; its drawer comes out ${item.drawer_m.toFixed(2)} m`
    : "");

/** One cloud lab instrument as a lesson: what it does, its parts and how to use it. */
export default function InstrumentLesson({
  id,
  onOpen,
  onBack,
  onWorkflow,
}: {
  id: string;
  onOpen: (id: string) => void;
  onBack: () => void;
  onWorkflow: () => void;
}) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    setFailed(false);
    api<Overview>("/cloudlab/instruments")
      .then((found) => alive && setOverview(found))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [attempt]);

  if (failed)
    return (
      <p className={s.failed}>
        The instrument could not be loaded.{" "}
        <button onClick={() => setAttempt((n) => n + 1)}>Try again</button>
      </p>
    );
  if (!overview) return <section className={s.page} aria-busy="true" />;
  const at = overview.instruments.findIndex((i) => i.id === id);
  if (at < 0)
    return (
      <p className={s.failed}>
        There is no cloud lab instrument here.{" "}
        <button onClick={onBack}>Meet the instruments</button>
      </p>
    );
  const next = overview.instruments[(at + 1) % overview.instruments.length];
  return (
    <Lesson
      // A fresh lesson, at rest, for each instrument.
      key={id}
      item={overview.instruments[at]}
      overview={overview}
      next={next}
      onOpen={onOpen}
      onBack={onBack}
      onWorkflow={onWorkflow}
    />
  );
}

function Lesson({
  item,
  overview,
  next,
  onOpen,
  onBack,
  onWorkflow,
}: {
  item: Instrument;
  overview: Overview;
  next: Instrument;
  onOpen: (id: string) => void;
  onBack: () => void;
  onWorkflow: () => void;
}) {
  const twin = useTwin(item.motion);
  const [tab, setTab] = useState<Tab>("use");
  const tabs: [Tab, string][] = [
    ["use", "Use it"],
    ...(item.motion ? [["parts", "Parts"] as [Tab, string]] : []),
    ["details", "Details"],
  ];
  const ids = useId();

  return (
    <section className={s.page} aria-labelledby={`${ids}-title`}>
      <button className={s.back} onClick={onBack}>
        <ArrowLeft size={16} aria-hidden="true" /> Meet the instruments
      </button>
      <header className={s.header}>
        <div>
          <h1 id={`${ids}-title`}>{item.name}</h1>
          <p>{item.does}</p>
          <small>
            {item.section} · <code>{item.experiment}</code>
          </small>
        </div>
        {item.in_workflow && (
          <button className={s.primary} onClick={onWorkflow}>
            Use it in a cloud lab workflow{" "}
            <ArrowRight size={15} aria-hidden="true" />
          </button>
        )}
      </header>

      <div className={s.layout}>
        {item.mesh ? (
          <TwinExplorer mesh={item.mesh} twin={twin} tall />
        ) : (
          <div className={s.noModel}>
            <Box size={30} aria-hidden="true" />
            <span>No 3D model; the twin is one estimated box.</span>
          </div>
        )}

        <div className={s.panel}>
          <div className={s.tabs} role="tablist" aria-label={item.name}>
            {tabs.map(([key, label]) => (
              <button
                key={key}
                id={`${ids}-${key}`}
                role="tab"
                aria-selected={tab === key}
                aria-controls={`${ids}-${key}-panel`}
                onClick={() => setTab(key)}
              >
                {label}
              </button>
            ))}
          </div>

          <div
            id={`${ids}-${tab}-panel`}
            role="tabpanel"
            aria-labelledby={`${ids}-${tab}`}
            className={s.tabPanel}
          >
            {tab === "use" && (
              <>
                <ol className={s.steps}>
                  {item.steps.map((step, n) => {
                    const body = (
                      <>
                        <span className={s.number}>
                          {String(n + 1).padStart(2, "0")}
                        </span>
                        <span>
                          <strong>{step.verb}</strong>
                          <span>{step.says}</span>
                          {step.operation === "load" && (
                            <small>{goesIn(item)}.</small>
                          )}
                        </span>
                      </>
                    );
                    return (
                      <li key={step.operation}>
                        {step.state && item.mesh ? (
                          <button
                            className={s.step}
                            aria-pressed={twin.state === step.state}
                            onClick={() => twin.press(step.state!)}
                          >
                            {body}
                          </button>
                        ) : (
                          <div className={s.step}>{body}</div>
                        )}
                      </li>
                    );
                  })}
                </ol>
                {!item.in_workflow && (
                  <p className={s.note}>
                    This instrument is not yet a step in the{" "}
                    <button className={s.link} onClick={onWorkflow}>
                      cloud lab workflow
                    </button>
                    .
                  </p>
                )}
              </>
            )}

            {tab === "parts" && item.motion && (
              <ul className={s.parts}>
                {item.motion.parts.map((p) => (
                  <li key={p.id}>
                    <button
                      aria-pressed={twin.part === p.id}
                      onClick={() => twin.pick(p.id)}
                    >
                      <strong>{p.label}</strong>
                      <span>{p.about}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {tab === "details" && (
              <div className={s.details}>
                <h2>What the cloud lab publishes</h2>
                <p>{item.published}.</p>
                <h2>What the teaching twin models</h2>
                <ul className={s.can}>
                  {item.operations.map((op) => (
                    <li key={op}>{CAN[op]}</li>
                  ))}
                </ul>
                <dl>
                  {item.holds.vessel !== "none" && (
                    <>
                      <dt>Holds</dt>
                      <dd>
                        {item.slots} × {item.holds.vessel}, up to{" "}
                        {volume(item.holds.max_volume_ul)}
                      </dd>
                    </>
                  )}
                  {item.operations.includes("heat") && (
                    <>
                      <dt>Temperature</dt>
                      <dd>
                        {item.limits.min_temp_c}–{item.limits.max_temp_c} °C
                      </dd>
                    </>
                  )}
                  <dt>Longest step</dt>
                  <dd>{Math.round(item.limits.max_duration_s / 60)} min</dd>
                  {item.consumables.map((c) => (
                    <Fragment key={c.name}>
                      <dt>Consumable</dt>
                      <dd>
                        {c.name}, {c.stock} in stock
                      </dd>
                    </Fragment>
                  ))}
                  <dt>Size</dt>
                  <dd>
                    {metres(item.size_m)} ·{" "}
                    {basisLabel(item.geometry_basis.size, item)}
                  </dd>
                </dl>
                {item.narrowed && <p className={s.narrowed}>{item.narrowed}</p>}
                <details className={s.sources}>
                  <summary>Sources</summary>
                  <ul>
                    {Object.entries(item.geometry_basis).map(([key, basis]) => {
                      const url = sourceUrl(basis);
                      return (
                        <li key={key}>
                          <b>{BASIS_NAMES[key] ?? key}</b>{" "}
                          {url ? (
                            <a href={url} target="_blank" rel="noreferrer">
                              {basis.replace(`, ${url}`, "")}
                            </a>
                          ) : (
                            basis
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </details>
              </div>
            )}
          </div>
        </div>
      </div>

      <footer className={s.footer}>
        <p className={s.fine}>
          Synthetic teaching twin, not this instrument's specification.{" "}
          {item.stand_in && `${item.attribution}. `}
          <a href={overview.source} target="_blank" rel="noreferrer">
            {overview.provider} instrumentation{" "}
            <ExternalLink size={12} aria-hidden="true" />
          </a>{" "}
          · read {overview.retrieved}
        </p>
        <button className={s.next} onClick={() => onOpen(next.id)}>
          <span>
            <small>Next</small>
            <strong>{next.name}</strong>
          </span>
          <ArrowRight size={16} aria-hidden="true" />
        </button>
      </footer>
    </section>
  );
}
