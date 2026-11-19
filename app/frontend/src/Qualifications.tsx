import { useCallback, useEffect, useState } from "react";
import { Bot, CheckCircle2, Circle, Download, User } from "lucide-react";
import { api, ApiError, json } from "./api";
import { unwrap } from "./CloudLabTraining";
import s from "./Qualifications.module.css";

type Kind = "liquid-handler" | "incubator" | "plate-reader";
// Where a criterion is trained: a page the person opens, or the agent sandbox.
type Place = { label: string; route: string | null };
type Criterion = {
  id: string;
  title: string;
  passed: boolean;
  source: string | null;
  earn: Place[];
};
type Holder = {
  kind: "person" | "agent";
  agent: string | null;
  instruments: Record<
    Kind,
    { title: string; criteria: Criterion[]; complete: boolean }
  >;
};
type Overview = {
  version: number;
  kinds: Record<Kind, { title: string }>;
  holders: Holder[];
};
type Envelope = { payload?: string };
type Issued = {
  envelope: Envelope;
  record: {
    holder: { kind: string; label?: string };
    instrument: { kind: Kind; title: string };
    issued_at: string;
    expires_at: string;
    criteria: { id: string; title: string; passed_at: string }[];
    statement: string;
  };
};
type Verdict = {
  authentic: boolean;
  current: boolean;
  cleared: boolean;
  problems: string[];
  instrument: string | null;
  record: { expires_at?: string } | null;
};

const SOURCES: Record<string, string> = {
  cloudlab: "Cloud lab training",
  "fault-practice": "Find the fault",
  "fault-drills": "Fault drills checkride",
  sandbox: "Agent sandbox",
};
const sourceLabel = (source: string | null) =>
  source ? (SOURCES[source.split(/[:/]/)[0]] ?? source) : "";
const day = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
const holderName = (h: { agent: string | null }) =>
  h.agent ? `Agent · ${h.agent}` : "You";

/** Every holder's progress toward each instrument qualification, and the signed record. */
export default function Qualifications({
  onOpen,
}: {
  onOpen: (route: string) => void;
}) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState<Issued | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api<Overview>("/qualifications"));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const issue = async (instrument: Kind, agent: string | null) => {
    if (!data || busy) return;
    setBusy(true);
    setError("");
    try {
      const found = await api<{ version: number; record: Envelope }>(
        "/qualifications/records",
        json({
          expected_version: data.version,
          instrument,
          ...(agent ? { agent } : {}),
        }),
      );
      setIssued({ envelope: found.record, record: unwrap(found.record) });
      setData({ ...data, version: found.version });
    } catch (e) {
      setError((e as Error).message);
      if (e instanceof ApiError && e.status === 409) await load();
    } finally {
      setBusy(false);
    }
  };

  if (!data)
    return (
      <main className={s.page} aria-busy={!error}>
        {error && (
          <p className={s.error} role="alert">
            {error}
          </p>
        )}
      </main>
    );

  return (
    <main className={s.page}>
      <header className={s.header}>
        <h1>Qualifications</h1>
        <span className={s.synthetic}>Synthetic evidence</span>
      </header>
      {error && (
        <p className={s.error} role="alert">
          {error}
        </p>
      )}

      {data.holders.map((holder) => (
        <section
          key={holder.agent ?? "person"}
          className={`${s.card} ${s.holder}`}
          aria-label={holderName(holder)}
        >
          <h2>
            {holder.agent ? (
              <Bot size={18} aria-hidden="true" />
            ) : (
              <User size={18} aria-hidden="true" />
            )}
            {holderName(holder)}
          </h2>
          <div className={s.kinds}>
            {(Object.keys(data.kinds) as Kind[]).map((kind) => {
              const status = holder.instruments[kind];
              return (
                <article
                  key={kind}
                  className={s.kind}
                  data-complete={status.complete}
                  aria-label={status.title}
                >
                  <h3>{status.title}</h3>
                  <ul className={s.criteria}>
                    {status.criteria.map((c) => (
                      <li key={c.id} data-passed={c.passed}>
                        {c.passed ? (
                          <CheckCircle2
                            size={15}
                            className={s.passed}
                            aria-label="Passed"
                          />
                        ) : (
                          <Circle size={15} aria-label="Not yet" />
                        )}
                        <div>
                          <span>{c.title}</span>
                          {c.passed ? (
                            <small>{sourceLabel(c.source)}</small>
                          ) : (
                            <small className={s.earn}>
                              {c.earn
                                .filter((p) => !holder.agent || !p.route)
                                .map((p, i) => (
                                  <span key={p.label}>
                                    {i > 0 && " · "}
                                    {p.route ? (
                                      <a
                                        href={`#/${p.route}`}
                                        onClick={(e) => {
                                          e.preventDefault();
                                          onOpen(p.route!);
                                        }}
                                      >
                                        {p.label}
                                      </a>
                                    ) : (
                                      p.label
                                    )}
                                  </span>
                                ))}
                            </small>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                  {status.complete && (
                    <button
                      className={s.primary}
                      disabled={busy}
                      onClick={() => void issue(kind, holder.agent)}
                    >
                      Issue signed record
                    </button>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      ))}

      {issued && <Record issued={issued} />}
      <Verify
        key={issued?.envelope.payload ?? "none"}
        kinds={data.kinds}
        initial={issued ? JSON.stringify(issued.envelope, null, 2) : ""}
      />
    </main>
  );
}

function Record({ issued }: { issued: Issued }) {
  const { record, envelope } = issued;
  const holder =
    record.holder.kind === "agent" ? `Agent · ${record.holder.label}` : "You";
  const download = () => {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(envelope, null, 2)], {
        type: "application/json",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `academy-qualification-${record.instrument.kind}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <section
      className={`${s.card} ${s.record}`}
      aria-label="Issued qualification"
    >
      <h2>
        {record.instrument.title} · {holder}
      </h2>
      <dl className={s.facts}>
        <dt>Issued</dt>
        <dd>{day(record.issued_at)}</dd>
        <dt>Expires</dt>
        <dd>{day(record.expires_at)}</dd>
        {record.criteria.map((c) => (
          <div key={c.id} style={{ display: "contents" }}>
            <dt>{c.title}</dt>
            <dd>{day(c.passed_at)}</dd>
          </div>
        ))}
      </dl>
      <p className={s.statement}>{record.statement}</p>
      <div className={s.actions}>
        <button className={s.secondary} onClick={download}>
          <Download size={15} /> Download JSON
        </button>
      </div>
    </section>
  );
}

function Verify({
  kinds,
  initial,
}: {
  kinds: Overview["kinds"];
  initial: string;
}) {
  const [text, setText] = useState(initial);
  const [instrument, setInstrument] = useState("");
  const [holder, setHolder] = useState("");
  const [verdict, setVerdict] = useState<(Verdict & { asked: string }) | null>(
    null,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const check = async () => {
    setError("");
    setVerdict(null);
    let record: unknown;
    try {
      record = JSON.parse(text);
    } catch {
      setError("Paste the record's JSON exactly as it was downloaded.");
      return;
    }
    if (!record || typeof record !== "object" || Array.isArray(record)) {
      setError("Paste the record's JSON exactly as it was downloaded.");
      return;
    }
    setBusy(true);
    try {
      const found = await api<Verdict>(
        "/qualifications/verify",
        json({
          record,
          ...(instrument ? { instrument } : {}),
          ...(holder ? { holder } : {}),
        }),
      );
      const asked = [
        instrument && kinds[instrument as Kind].title.toLowerCase(),
        holder && (holder === "agent" ? "an agent" : "a person"),
      ]
        .filter(Boolean)
        .join(", ");
      setVerdict({ ...found, asked });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const expires = verdict?.record?.expires_at;
  const expired = verdict?.problems.includes("The record has expired");
  return (
    <form
      className={`${s.card} ${s.verify}`}
      aria-label="Verify a qualification"
      onSubmit={(e) => {
        e.preventDefault();
        void check();
      }}
    >
      <h2>Verify a qualification</h2>
      <label className={s.field}>
        Signed record
        <textarea
          value={text}
          spellCheck={false}
          onChange={(e) => {
            setText(e.target.value);
            setVerdict(null);
          }}
        />
      </label>
      <div className={s.checks}>
        <label className={s.field}>
          Cleared for
          <select
            value={instrument}
            onChange={(e) => setInstrument(e.target.value)}
          >
            <option value="">Any instrument kind</option>
            {(Object.keys(kinds) as Kind[]).map((k) => (
              <option key={k} value={k}>
                {kinds[k].title}
              </option>
            ))}
          </select>
        </label>
        <label className={s.field}>
          Held by
          <select value={holder} onChange={(e) => setHolder(e.target.value)}>
            <option value="">A person or an agent</option>
            <option value="person">A person</option>
            <option value="agent">An agent</option>
          </select>
        </label>
      </div>
      <div className={s.actions}>
        <button className={s.primary} disabled={busy || !text.trim()}>
          Verify
        </button>
      </div>
      {error && (
        <p className={s.error} role="alert">
          {error}
        </p>
      )}
      {verdict && (
        <ul className={s.verdict} aria-label="Verification" role="status">
          <li data-ok={verdict.authentic}>
            {verdict.authentic
              ? "Authentic: signed here and unedited"
              : "Not authentic: edited, or not issued here"}
          </li>
          {verdict.authentic && (
            <li data-ok={!expired}>
              {expired
                ? "Expired"
                : expires
                  ? `Valid until ${day(expires)}`
                  : "No expiry"}
            </li>
          )}
          <li data-ok={verdict.cleared}>
            {verdict.cleared ? "Cleared" : "Not cleared"}
            {verdict.asked && ` for ${verdict.asked}`}
          </li>
          {verdict.problems
            .filter((p) => verdict.authentic && p !== "The record has expired")
            .map((p) => (
              <li key={p} data-ok={false}>
                {p}
              </li>
            ))}
        </ul>
      )}
    </form>
  );
}
