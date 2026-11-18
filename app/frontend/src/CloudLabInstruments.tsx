import { Box, ExternalLink, X } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { Mesh, Operation } from "./instrumentTypes";
import { Preview, Thumbnail } from "./ModelLibrary";
import s from "./CloudLabInstruments.module.css";

type Instrument = {
  id: string;
  name: string;
  section: string;
  experiment: string;
  published: string;
  narrowed: string | null;
  operations: Operation[];
  holds: { vessel: string; max_volume_ul: number };
  slots: number;
  limits: { min_temp_c: number; max_temp_c: number; max_duration_s: number };
  consumables: { name: string; stock: number }[];
  size_m: [number, number, number];
  stand_in: string | null;
  mesh: Mesh | null;
  attribution: string;
};
type Overview = {
  provider: string;
  source: string;
  retrieved: string;
  sections: string[];
  instruments: Instrument[];
};

const CAN: Record<Operation, string> = {
  load: "Load",
  transfer: "Transfer",
  mix: "Mix",
  heat: "Heat",
  read: "Read",
  wait: "Wait",
};
const volume = (ul: number) =>
  ul >= 1000 ? `${(ul / 1000).toLocaleString()} mL` : `${ul} µL`;

/** The instruments a cloud lab lists, as teaching twins a learner can look at. */
export default function CloudLabInstruments() {
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
      <section className={s.section} aria-labelledby="cloudlab-instruments">
        <h2 id="cloudlab-instruments" className={s.title}>
          In a cloud lab
        </h2>
        <p className={s.failed}>
          The cloud lab instruments could not be loaded.{" "}
          <button onClick={() => setAttempt((n) => n + 1)}>Try again</button>
        </p>
      </section>
    );
  if (!overview) return <section className={s.section} aria-busy="true" />;
  const shown = overview.instruments.filter(
    (i) => section === "All" || i.section === section,
  );

  return (
    <section className={s.section} aria-labelledby="cloudlab-instruments">
      <header className={s.header}>
        <h2 id="cloudlab-instruments">In a cloud lab</h2>
        <p>
          {overview.instruments.length} instruments {overview.provider} lists
          for remote experiments, as teaching twins.
        </p>
      </header>
      <div className={s.filters} role="group" aria-label="Instrument type">
        {["All", ...overview.sections].map((name) => (
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
          aria-labelledby="cloudlab-detail"
        >
          <header>
            <div>
              <h3 id="cloudlab-detail">{open.name}</h3>
              <small>
                {open.section} · <code>{open.experiment}</code>
              </small>
            </div>
            <button
              className={s.close}
              aria-label="Close"
              onClick={() => setOpen(null)}
            >
              <X size={18} />
            </button>
          </header>
          <div className={s.detailBody}>
            {open.mesh ? (
              <div className={s.view}>
                <Preview mesh={open.mesh} />
              </div>
            ) : (
              <div className={s.noModel}>
                <Box size={28} aria-hidden="true" />
                <span>No 3D model; the twin is one estimated box.</span>
              </div>
            )}
            <div className={s.facts}>
              <h4>What the cloud lab publishes</h4>
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
                  {open.size_m.map((v) => v.toFixed(2)).join(" × ")} m ·{" "}
                  {open.stand_in
                    ? `footprint of a comparable ${open.stand_in}`
                    : "Academy estimate"}
                </dd>
              </dl>
              {open.narrowed && <p className={s.narrowed}>{open.narrowed}</p>}
              <p className={s.fine}>
                Synthetic teaching twin, not this instrument's specification.{" "}
                {open.stand_in && `${open.attribution}. `}
                <a href={overview.source} target="_blank" rel="noreferrer">
                  {overview.provider} instrumentation{" "}
                  <ExternalLink size={12} aria-hidden="true" />
                </a>{" "}
                · read {overview.retrieved}
              </p>
            </div>
          </div>
        </article>
      )}
    </section>
  );
}
