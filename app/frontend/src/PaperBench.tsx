import { useEffect, useState } from "react";
import { ArrowRight, TriangleAlert, X } from "lucide-react";
import { api, json } from "./api";
import type { WorkflowTemplate } from "./CloudLabWorkflow";
import { workflows, type Workflow } from "./discoveryContent";
import StageLine from "./StageLine";
import { STAGES, STAGE_LABEL, type Stage } from "./skills";
import d from "./Discovery.module.css";
import s from "./SkillTree.module.css";

type Candidate = { id: string; name: string; source: string; notes: string[] };
type TemplateRow = {
  index: number;
  text: string;
  stage: Stage;
  /** The paper the step is read from; null for a measurement the learner added. */
  paper: string | null;
  chosen: string;
  candidates: Candidate[];
  rejected: { id: string; name: string; reason: string }[];
  gap: string | null;
};
type PaperTemplate = {
  rows: TemplateRow[];
  steps: WorkflowTemplate["steps"];
  check: {
    ok: boolean;
    error: { step: number | null; message: string } | null;
  } | null;
  instruments: WorkflowTemplate["instruments"];
  measures: { id: string; label: string }[];
};

/** A paper read into steps on the twins; with `change`, measured another way too. */
export default function PaperBench({
  item,
  change,
  onOpen,
}: {
  item: Workflow;
  /** Let the learner take another paper's measurements, or add one. */
  change?: boolean;
  onOpen: (template: WorkflowTemplate) => void;
}) {
  const [picks, setPicks] = useState<Record<number, string>>({});
  const [measure, setMeasure] = useState("");
  const [add, setAdd] = useState<string[]>([]);
  const [template, setTemplate] = useState<PaperTemplate | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let current = true;
    api<PaperTemplate>(
      `/marketplace/${item.id}/template`,
      json({ picks, measure: measure || null, add }),
    )
      .then((next) => {
        if (!current) return;
        setTemplate(next);
        setFailed(false);
      })
      .catch(() => current && setFailed(true));
    return () => {
      current = false;
    };
  }, [item.id, picks, measure, add]);

  if (failed && !template)
    return (
      <p className={d.note} role="alert">
        Instrument suggestions could not be loaded. Reload to try again.
      </p>
    );
  if (!template) return null;
  const used = template.rows.filter((row) => row.chosen).length;
  const error = template.check?.error;
  const other = workflows.find((w) => w.id === measure);
  // A step on a different twin, or left out, no longer has the same place in the list.
  const recompose = (next: () => void) => {
    setPicks({});
    next();
  };
  const offered = template.measures.filter((m) => !add.includes(m.id));
  const name = change ? "Change it on the twins" : "Reproduce on the twins";
  return (
    <section className={d.section} aria-label={name}>
      <div className={d.sectionHeading}>
        <h2>{name}</h2>
        <span>
          {used} of {template.rows.length} steps on a twin
        </span>
      </div>
      <div className={s.bench}>
        <div className={s.benchLine}>
          <div className={s.laneHead} aria-hidden="true">
            {STAGES.map((stage) => (
              <span key={stage} data-stage={stage}>
                {STAGE_LABEL[stage]}
              </span>
            ))}
          </div>
          <StageLine
            steps={template.rows.map((row) => ({
              stage: row.stage,
              lit: !!row.chosen,
              title: row.text,
            }))}
            loop={item.kind === "Closed loop"}
          />
        </div>
        {change && (
          <div className={s.change}>
            <label>
              Measure it like
              <select
                value={measure}
                onChange={(event) =>
                  recompose(() => setMeasure(event.target.value))
                }
              >
                <option value="">{item.title} (as published)</option>
                {workflows
                  .filter((w) => w.id !== item.id)
                  .map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.title}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Add a measurement
              <select
                value=""
                disabled={add.length >= 3}
                onChange={(event) =>
                  recompose(() => setAdd([...add, event.target.value]))
                }
              >
                <option value="">Choose…</option>
                {offered.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            <span className={s.added}>
              {add.map((id) => (
                <button
                  key={id}
                  aria-label={`Remove ${template.measures.find((m) => m.id === id)?.label}`}
                  onClick={() =>
                    recompose(() => setAdd(add.filter((x) => x !== id)))
                  }
                >
                  {template.measures.find((m) => m.id === id)?.label}
                  <X size={12} />
                </button>
              ))}
            </span>
          </div>
        )}
      </div>
      <ol className={d.reproduce}>
        {template.rows.map((row) => {
          const chosen = row.candidates.find((c) => c.id === row.chosen);
          const from =
            row.paper && row.paper !== item.id
              ? workflows.find((w) => w.id === row.paper)?.title
              : null;
          return (
            <li key={row.index} data-testid={`paper-step-${row.index + 1}`}>
              <span>{String(row.index + 1).padStart(2, "0")}</span>
              <div>
                <span className={s.stageChip} data-stage={row.stage}>
                  {STAGE_LABEL[row.stage]}
                </span>
                <h3>{row.text}</h3>
                {from && <small className={s.from}>From {from}</small>}
              </div>
              <div>
                {row.gap ? (
                  <p>{row.gap}</p>
                ) : (
                  <select
                    aria-label={`Instrument for step ${row.index + 1}`}
                    value={row.chosen}
                    onChange={(event) =>
                      setPicks({ ...picks, [row.index]: event.target.value })
                    }
                  >
                    {row.candidates.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name} · {c.source}
                      </option>
                    ))}
                    <option value="">Leave this step out</option>
                  </select>
                )}
                {chosen?.notes.map((note) => (
                  <small key={note} className={d.fitNote}>
                    {note}
                  </small>
                ))}
                {!!row.rejected.length && (
                  <details>
                    <summary>Not suggested</summary>
                    <ul>
                      {row.rejected.map((r) => (
                        <li key={r.id}>
                          {r.name}: {r.reason.toLowerCase()}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      <div className={d.reproduceActions}>
        {error && (
          <p role="alert">
            <TriangleAlert size={14} /> {error.message}
          </p>
        )}
        <button
          className={d.primary}
          disabled={!template.steps.length}
          onClick={() =>
            onOpen({
              title: other ? `${item.title} → ${other.title}` : item.title,
              steps: template.steps,
              instruments: template.instruments,
            })
          }
        >
          Open as a cloud lab workflow <ArrowRight size={16} />
        </button>
        <small>
          Values stay within each twin's teaching limits, not the paper's
          conditions. Runs are synthetic.
        </small>
      </div>
    </section>
  );
}

/** Stage three: pick a published workflow and make it your own. */
export function ChangeBench({
  initial,
  onOpen,
}: {
  initial?: string;
  onOpen: (template: WorkflowTemplate) => void;
}) {
  const papers = workflows.filter((w) => w.paper);
  const [id, setId] = useState(
    papers.some((w) => w.id === initial) ? initial! : papers[0].id,
  );
  const item = papers.find((w) => w.id === id)!;
  return (
    <div className={d.page} style={{ padding: 0, maxWidth: "none" }}>
      <div className={s.papers} role="group" aria-label="Published workflow">
        {papers.map((w) => (
          <button
            key={w.id}
            aria-pressed={w.id === id}
            onClick={() => setId(w.id)}
          >
            {w.title}
          </button>
        ))}
      </div>
      <PaperBench key={id} item={item} change onOpen={onOpen} />
    </div>
  );
}
