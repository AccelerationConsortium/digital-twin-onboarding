import { useEffect, useRef, useState } from "react";
import { Download, Upload } from "lucide-react";
import { api, apiText, json } from "./api";
import s from "./SimReal.module.css";

type Feature = {
  id: string;
  identifier: string;
  sha256: string;
  commands: {
    name: string;
    observable: boolean;
    parameters: { name: string; type: string }[];
  }[];
};
type Connector = {
  key: string;
  name: string;
  repository: string;
  simulator: string;
  imported: boolean;
  package_version?: string;
  source?: { commit: string | null; dirty: boolean | null };
  features?: Feature[];
};
type PlanStep = {
  id: string;
  device: string;
  feature: string;
  command: string;
  cycle: number;
  simulation_only?: boolean;
  world: { labware: Record<string, { device: string; site: string }> };
};
type Plan = {
  name: string;
  valid: boolean;
  digest?: string;
  cycles?: number;
  problems: { step: string | null; layer: string; message: string }[];
  steps: PlanStep[];
  motions: {
    step: string;
    clearance_m: number;
    seconds: number;
    planner: string;
  }[];
  limits?: string[];
};
type RunSummary = {
  run_id: string;
  name: string;
  outcome: string;
  reason: string | null;
  kept_at: number;
  device_s: number | null;
  steps: number;
};
type Run = RunSummary & {
  wall_s: number | null;
  plan_digest: string;
  connectors: Record<
    string,
    { connector: string; package_version: string; commit: string | null }
  >;
  steps: {
    id: string;
    device: string;
    command: string;
    status: string;
    wall_s: number | null;
    device_s: number | null;
    error: string | null;
  }[];
};

const seconds = (value: number | null | undefined) =>
  value == null ? "" : `${value.toFixed(value < 10 ? 2 : 1)} s`;

function where(step: PlanStep) {
  return Object.entries(step.world.labware)
    .map(
      ([plate, at]) =>
        `${plate}: ${at.site === "gripper" ? `${at.device} gripper` : at.device + (at.site ? ` ${at.site}` : "")}`,
    )
    .join(", ");
}

export default function SimReal() {
  const [connectors, setConnectors] = useState<Connector[] | null>(null);
  const [text, setText] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);

  useEffect(() => {
    let active = true;
    Promise.all([
      api<{ connectors: Connector[] }>("/sim-real/v1/connectors"),
      api<object>("/sim-real/v1/example"),
      api<{ runs: RunSummary[] }>("/sim-real/v1/runs"),
    ])
      .then(([found, example, kept]) => {
        if (!active) return;
        setConnectors(found.connectors);
        setText(JSON.stringify(example, null, 2));
        setRuns(kept.runs);
      })
      .catch((reason: Error) => active && setError(reason.message));
    return () => {
      active = false;
    };
  }, []);

  async function act(work: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  const check = () =>
    act(async () => {
      let workflow: unknown;
      try {
        workflow = JSON.parse(text);
      } catch {
        throw new Error("The workflow is not valid JSON.");
      }
      setPlan(await api<Plan>("/sim-real/v1/compile", json(workflow)));
    });

  const download = () => {
    if (!plan) return;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(
      new Blob([JSON.stringify(plan, null, 2)], { type: "application/json" }),
    );
    link.download = "plan.json";
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const keep = (file: File | undefined) =>
    file &&
    act(async () => {
      if (!plan?.valid) throw new Error("Check the workflow first.");
      let report: unknown;
      try {
        report = JSON.parse(await file.text());
      } catch {
        throw new Error("The report is not valid JSON.");
      }
      const kept = await api<Run>("/sim-real/v1/runs", json({ plan, report }));
      setRun(kept);
      setRuns((await api<{ runs: RunSummary[] }>("/sim-real/v1/runs")).runs);
    });

  const show = (id: string) =>
    act(async () => setRun(await api<Run>(`/sim-real/v1/runs/${id}`)));

  const remove = (id: string) =>
    act(async () => {
      await apiText(`/sim-real/v1/runs/${id}`, { method: "DELETE" });
      setRun(null);
      setRuns((list) => list.filter((item) => item.run_id !== id));
    });

  return (
    <div className={s.page}>
      <header className={s.header}>
        <div>
          <h1>Sim–Real</h1>
          <p className={s.lede}>
            A workflow runs on the instruments&rsquo; own connectors, in their
            simulation mode, before it runs on the instruments.
          </p>
        </div>
        <span className={s.evidence}>Connector simulation · no hardware</span>
      </header>
      {error && (
        <p className={s.error} role="alert">
          {error}
        </p>
      )}

      <section className={s.card} aria-labelledby="simreal-connectors">
        <h2 id="simreal-connectors">Connectors</h2>
        <div className={s.connectors}>
          {(connectors ?? []).map((connector) => (
            <article key={connector.key} className={s.connector}>
              <h3>{connector.name}</h3>
              {connector.imported ? (
                <p>
                  {connector.repository} · {connector.package_version}
                  {connector.source?.commit &&
                    ` · ${connector.source.commit.slice(0, 7)}`}
                </p>
              ) : (
                <p>Not imported yet.</p>
              )}
              <p>{connector.simulator}</p>
              {connector.features && (
                <details>
                  <summary>
                    {connector.features.length} features,{" "}
                    {connector.features.reduce(
                      (count, feature) => count + feature.commands.length,
                      0,
                    )}{" "}
                    commands
                  </summary>
                  {connector.features
                    .filter((feature) => feature.commands.length)
                    .map((feature) => (
                      <div key={feature.id}>
                        <p title={`${feature.id} · sha256 ${feature.sha256}`}>
                          {feature.identifier}
                        </p>
                        <ul className={s.commands}>
                          {feature.commands.map((command) => (
                            <li key={command.name}>
                              {command.name}
                              <span>
                                (
                                {command.parameters
                                  .map((p) => `${p.name}: ${p.type}`)
                                  .join(", ")}
                                )
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                </details>
              )}
            </article>
          ))}
        </div>
      </section>

      <section className={s.card} aria-labelledby="simreal-workflow">
        <h2 id="simreal-workflow">Workflow</h2>
        <label className={s.field}>
          Workflow JSON
          <textarea
            className={s.editor}
            spellCheck={false}
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              setPlan(null);
            }}
          />
        </label>
        <div className={s.actions}>
          <button
            className={s.primary}
            disabled={busy || !text}
            onClick={check}
          >
            {busy ? "Checking…" : "Check workflow"}
          </button>
          {plan?.valid && (
            <button className={s.secondary} onClick={download}>
              <Download size={15} /> Download plan
            </button>
          )}
        </div>
      </section>

      {plan && !plan.valid && (
        <section className={s.card} aria-labelledby="simreal-problems">
          <h2 id="simreal-problems">Why it would not run</h2>
          <ul className={s.problems}>
            {plan.problems.map((problem, index) => (
              <li key={index}>
                {problem.message}
                <small>
                  {problem.step ? `Step ${problem.step} · ` : ""}
                  {problem.layer}
                </small>
              </li>
            ))}
          </ul>
        </section>
      )}

      {plan?.valid && (
        <section className={s.card} aria-labelledby="simreal-plan">
          <h2 id="simreal-plan">Plan</h2>
          <dl className={s.summary}>
            <div>
              <dt>Commands</dt>
              <dd>{plan.steps.length}</dd>
            </div>
            <div>
              <dt>Transfers</dt>
              <dd>{plan.motions.length}</dd>
            </div>
            {plan.motions.length > 0 && (
              <div>
                <dt>Least clearance</dt>
                <dd>
                  {Math.round(
                    Math.min(...plan.motions.map((m) => m.clearance_m)) * 1000,
                  )}{" "}
                  mm
                </dd>
              </div>
            )}
            <div>
              <dt>Plan digest</dt>
              <dd title={plan.digest}>{plan.digest?.slice(0, 12)}</dd>
            </div>
          </dl>
          <div className={s.scroll}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Step</th>
                  <th>Device</th>
                  <th>Command</th>
                  <th>Plates afterwards</th>
                </tr>
              </thead>
              <tbody>
                {plan.steps.map((step) => (
                  <tr key={step.id}>
                    <td>{step.id}</td>
                    <td>{step.device}</td>
                    <td>
                      {step.feature.split("/")[2]}.{step.command}
                      {step.simulation_only && " (simulation only)"}
                    </td>
                    <td>{where(step)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {plan.limits && (
            <details>
              <summary>What this plan does not establish</summary>
              <ul>
                {plan.limits.map((limit) => (
                  <li key={limit}>{limit}</li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}

      <section className={s.card} aria-labelledby="simreal-runs">
        <h2 id="simreal-runs">Runs</h2>
        <p className={s.meta}>
          Connectors run where they are installed. Run the plan there, then keep
          its report here.
        </p>
        <pre className={s.command}>
          academy-sim-real run plan.json --report report.json
        </pre>
        <div className={s.actions}>
          <label className={s.upload}>
            <Upload size={15} /> Keep a run report
            <input
              type="file"
              accept="application/json,.json"
              disabled={busy || !plan?.valid}
              onChange={(event) => {
                void keep(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
          </label>
          {!plan?.valid && (
            <span className={s.meta}>Check the workflow first.</span>
          )}
        </div>
        {runs.length > 0 && (
          <ul className={s.runs} aria-label="Kept runs">
            {runs.map((item) => (
              <li key={item.run_id}>
                <button
                  aria-pressed={run?.run_id === item.run_id}
                  onClick={() => show(item.run_id)}
                >
                  <span className={s.status} data-outcome={item.outcome}>
                    {item.outcome}
                  </span>
                  <span>{item.name}</span>
                  <span>
                    {item.steps} commands · {seconds(item.device_s)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {run && (
          <>
            {run.reason && (
              <p className={s.error} role="status">
                {run.reason}
              </p>
            )}
            <dl className={s.summary}>
              <div>
                <dt>Instrument time</dt>
                <dd>{seconds(run.device_s)}</dd>
              </div>
              <div>
                <dt>Simulated in</dt>
                <dd>{seconds(run.wall_s)}</dd>
              </div>
              {Object.entries(run.connectors).map(([device, connector]) => (
                <div key={device}>
                  <dt>{device}</dt>
                  <dd>
                    {connector.connector} {connector.package_version}
                    {connector.commit && ` · ${connector.commit.slice(0, 7)}`}
                  </dd>
                </div>
              ))}
            </dl>
            <div className={s.scroll}>
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>Step</th>
                    <th>Command</th>
                    <th>Result</th>
                    <th>Instrument time</th>
                  </tr>
                </thead>
                <tbody>
                  {run.steps.map((step) => (
                    <tr key={step.id}>
                      <td>{step.id}</td>
                      <td>
                        {step.device} · {step.command}
                      </td>
                      <td>
                        <span className={s.status} data-outcome={step.status}>
                          {step.status}
                        </span>
                        {step.error && ` ${step.error}`}
                      </td>
                      <td>{seconds(step.device_s ?? step.wall_s)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className={s.actions}>
              <button
                className={s.secondary}
                disabled={busy}
                onClick={() => remove(run.run_id)}
              >
                Delete this run
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
