import { ArrowRight, Box, X } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import {
  BASIS_NAMES,
  basisLabel,
  CAN,
  metres,
  part,
  sketchCredit,
  sourceUrl,
  volume,
  type Instrument,
  type LabId,
  type Overview,
} from "./cloudlabFacts";
import LabProvenance from "./LabProvenance";
import { Thumbnail } from "./ModelLibrary";
import TwinExplorer, { useTwin } from "./TwinExplorer";
import { STAGE_LABEL } from "./skills";
import s from "./CloudLabInstruments.module.css";

const COPY: Record<
  LabId,
  {
    title: string;
    intro: (n: number, provider: string) => string;
    facts: string;
  }
> = {
  ecl: {
    title: "In a cloud lab",
    intro: (n, provider) =>
      `${n} instruments ${provider} lists for remote experiments, as teaching twins.`,
    facts: "What the cloud lab publishes",
  },
  ac: {
    title: "At the Acceleration Consortium",
    intro: (n) =>
      `${n} instruments the Acceleration Consortium's self-driving labs run, as teaching twins.`,
    facts: "What the equipment reference lists",
  },
};

/** The instruments a lab lists, as teaching twins a learner can look at. */
export default function CloudLabInstruments({
  lab: labId = "ecl",
  onTeach,
}: {
  lab?: LabId;
  onTeach: (id: string) => void;
}) {
  const copy = COPY[labId];
  const heading = `${labId}-instruments`;
  const [overview, setOverview] = useState<Overview | null>(null);
  const [hidden, setHidden] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [section, setSection] = useState("All");
  const [open, setOpen] = useState<Instrument | null>(null);
  const detail = useRef<HTMLElement>(null);
  // The details sit below the grid, so bring them into view when they open.
  useEffect(() => {
    if (open)
      detail.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [open]);

  useEffect(() => {
    let alive = true;
    setFailed(false);
    api<Overview>("/cloudlab/instruments")
      .then((found) => alive && setOverview(found))
      .catch((e) => {
        if (!alive) return;
        // Visitors who have not signed in see the rest of the page without this section.
        if (e instanceof ApiError && e.status === 401) setHidden(true);
        else setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [attempt]);

  if (hidden) return null;
  if (failed)
    return (
      <section className={s.section} aria-labelledby={heading}>
        <h2 id={heading} className={s.title}>
          {copy.title}
        </h2>
        <p className={s.failed}>
          These instruments could not be loaded.{" "}
          <button onClick={() => setAttempt((n) => n + 1)}>Try again</button>
        </p>
      </section>
    );
  if (!overview) return <section className={s.section} aria-busy="true" />;
  const lab = overview.labs.find((l) => l.id === labId)!;
  const listed = overview.instruments.filter((i) => i.lab === labId);
  const shown = listed.filter(
    (i) => section === "All" || i.section === section,
  );

  return (
    <section className={s.section} aria-labelledby={heading}>
      <header className={s.header}>
        <h2 id={heading}>{copy.title}</h2>
        <p>{copy.intro(listed.length, lab.provider)}</p>
      </header>
      <div className={s.filters} role="group" aria-label="Instrument type">
        {["All", ...lab.sections].map((name) => (
          <button
            key={name}
            aria-pressed={section === name}
            onClick={() => {
              setSection(name);
              // The open detail goes with the cards it belongs to.
              if (open && name !== "All" && open.section !== name)
                setOpen(null);
            }}
          >
            {name}
          </button>
        ))}
      </div>
      <ul className={s.grid}>
        {shown.map((item) => (
          <li key={item.id}>
            <button
              className={open?.id === item.id ? s.cardOpen : s.card}
              aria-expanded={open?.id === item.id}
              onClick={() => setOpen(open?.id === item.id ? null : item)}
            >
              {item.mesh ? (
                <Thumbnail mesh={item.mesh} />
              ) : (
                <span className={s.box} aria-hidden="true">
                  <Box size={22} />
                </span>
              )}
              <strong>{item.name}</strong>
              <small>{item.experiment}</small>
            </button>
          </li>
        ))}
      </ul>

      {open && (
        <article
          ref={detail}
          className={s.detail}
          aria-labelledby={`${labId}-detail`}
        >
          <header>
            <div>
              <h3 id={`${labId}-detail`}>{open.name}</h3>
              <small>
                {open.section} · <code>{open.experiment}</code>
              </small>
              <span className={s.stages}>
                {open.stages.map((stage) => (
                  <span key={stage} data-stage={stage}>
                    {STAGE_LABEL[stage]}
                  </span>
                ))}
              </span>
            </div>
            <div className={s.actions}>
              <button className={s.teach} onClick={() => onTeach(open.id)}>
                Use it <ArrowRight size={14} aria-hidden="true" />
              </button>
              <button
                className={s.close}
                aria-label="Close"
                onClick={() => setOpen(null)}
              >
                <X size={18} />
              </button>
            </div>
          </header>
          <div className={s.detailBody}>
            {open.mesh ? (
              <DetailTwin key={open.id} item={open} />
            ) : (
              <div className={s.noModel}>
                <Box size={28} aria-hidden="true" />
                <span>No 3D model; the twin is one estimated box.</span>
              </div>
            )}
            <div className={s.facts}>
              <h4>{copy.facts}</h4>
              <p>{open.published}.</p>
              <h4>What the teaching twin models</h4>
              <ul className={s.can}>
                {open.operations.map((op) => (
                  <li key={op}>{CAN[op]}</li>
                ))}
              </ul>
              <dl>
                {open.holds.vessel !== "none" && (
                  <>
                    <dt>Holds</dt>
                    <dd>
                      {open.slots} × {open.holds.vessel}, up to{" "}
                      {volume(open.holds.max_volume_ul)}
                    </dd>
                  </>
                )}
                {open.operations.includes("heat") && (
                  <>
                    <dt>Temperature</dt>
                    <dd>
                      {open.limits.min_temp_c}–{open.limits.max_temp_c} °C
                    </dd>
                  </>
                )}
                {open.consumables.map((c) => (
                  <Fragment key={c.name}>
                    <dt>Consumable</dt>
                    <dd>
                      {c.name}, {c.stock} in stock
                    </dd>
                  </Fragment>
                ))}
                <dt>Size</dt>
                <dd>
                  {metres(open.size_m)} ·{" "}
                  {basisLabel(open.geometry_basis.size, open)}
                  {open.model_size_m &&
                    metres(open.model_size_m) !== metres(open.size_m) &&
                    ` (3D model ${metres(open.model_size_m)})`}
                </dd>
                <dt>Plate goes in</dt>
                <dd>
                  {open.access === "front" ? "At the front" : "From above"}
                  {part(open.opening)} ·{" "}
                  {basisLabel(open.geometry_basis.access, open)}
                </dd>
                {open.level_m !== null && (
                  <>
                    <dt>Loading height</dt>
                    <dd>
                      {open.level_m.toFixed(2)} m above the bench ·{" "}
                      {basisLabel(open.geometry_basis.level_m, open)}
                    </dd>
                  </>
                )}
                {open.drawer_m !== null && (
                  <>
                    <dt>Drawer</dt>
                    <dd>
                      Comes out {open.drawer_m.toFixed(2)} m ·{" "}
                      {basisLabel(open.geometry_basis.drawer_m, open)}
                    </dd>
                  </>
                )}
              </dl>
              <details className={s.sources}>
                <summary>Sources</summary>
                <ul>
                  {Object.entries(open.geometry_basis).map(([key, basis]) => {
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
              {open.narrowed && <p className={s.narrowed}>{open.narrowed}</p>}
              <p className={s.fine}>
                Synthetic teaching twin, not this instrument's specification.{" "}
                {open.stand_in && `${open.attribution}. `}
                {sketchCredit(open)}
                <LabProvenance lab={lab} item={open} />
              </p>
            </div>
          </div>
        </article>
      )}
    </section>
  );
}

/** The stand-in model, moving where its contract has joints. */
function DetailTwin({ item }: { item: Instrument }) {
  const twin = useTwin(item.motion);
  return <TwinExplorer mesh={item.mesh!} twin={twin} />;
}
