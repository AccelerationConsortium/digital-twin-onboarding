import {
  CheckCircle2,
  CircleSlash,
  Clock,
  Upload,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api, json } from "./api";
import { RECORD_HANDOFF } from "./CloudLabTraining";
import s from "./CloudLabTraining.module.css";

type Verdict = {
  authentic: boolean;
  current: boolean;
  complete: boolean;
  problems: string[];
  rules_version: string;
};
type RecordTask = {
  id: string;
  title: string;
  status: string;
  attempts: number;
  retries: number;
};
type TrainingRecord = {
  subject?: string;
  issued_at?: string;
  expires_at?: string;
  module?: { instrument?: string; rules_version?: string };
  tasks?: RecordTask[];
  time_to_first_valid_workflow_s?: number | null;
  statement?: string;
};

function minutes(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  return seconds < 60 ? `${seconds} s` : `${Math.round(seconds / 60)} min`;
}

/**
 * A stand-in for a cloud lab's run-request page. It sees only the record the learner
 * attaches, asks the Academy whether that record is authentic and current, then applies
 * its own policy. Passing sends the request to operator review; it never approves a run.
 */
export default function CloudLabPortal({
  onTraining,
  onError,
}: {
  onTraining: () => void;
  onError: (message: string) => void;
}) {
  const [record, setRecord] = useState<TrainingRecord | null>(null);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);

  const check = async (next: TrainingRecord) => {
    setRecord(next);
    setVerdict(null);
    setSubmitted(false);
    setBusy(true);
    try {
      setVerdict(
        await api<Verdict>("/cloudlab/records/verify", json({ record: next })),
      );
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    try {
      const handed = sessionStorage.getItem(RECORD_HANDOFF);
      if (handed) {
        sessionStorage.removeItem(RECORD_HANDOFF);
        void check(JSON.parse(handed));
      }
    } catch {
      // Storage unavailable: the learner attaches the downloaded file instead.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const attach = async (file: File | undefined) => {
    if (!file) return;
    try {
      await check(JSON.parse(await file.text()));
    } catch {
      onError("That file is not a training record.");
    }
  };

  const eligible =
    !!verdict && verdict.authentic && verdict.current && verdict.complete;
  const rows: [string, boolean][] = verdict
    ? [
        ["Issued by the Academy and unedited", verdict.authentic],
        ["Earned under the current rules, not expired", verdict.current],
        ["Every training task passed", verdict.complete],
      ]
    : [];

  return (
    <main className={s.page}>
      <div className={s.portalBanner} role="note">
        Mock cloud lab portal · a demonstration of how a cloud lab could read an
        Academy record. No real cloud lab or instrument is involved.
      </div>
      <header className={s.header}>
        <div>
          <h1>Request a run</h1>
          <p className={s.lede}>Opentrons Flex · liquid transfer</p>
        </div>
      </header>

      <section className={s.grid}>
        <div className={s.card}>
          <h2>Training record</h2>
          <label className={s.upload}>
            <Upload size={16} />
            <span>
              {record ? "Attach a different record" : "Attach your record"}
            </span>
            <input
              type="file"
              accept="application/json,.json"
              onChange={(e) => void attach(e.target.files?.[0])}
            />
          </label>
          {record && (
            <dl className={s.facts}>
              <dt>Learner</dt>
              <dd>
                <code>{record.subject ?? "—"}</code>
              </dd>
              <dt>Instrument</dt>
              <dd>{record.module?.instrument ?? "—"}</dd>
              <dt>Rules</dt>
              <dd>
                <code>{record.module?.rules_version ?? "—"}</code>
              </dd>
              <dt>First valid workflow</dt>
              <dd>{minutes(record.time_to_first_valid_workflow_s)}</dd>
              <dt>Expires</dt>
              <dd>{record.expires_at?.slice(0, 10) ?? "—"}</dd>
            </dl>
          )}
          {record?.tasks && (
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Status</th>
                  <th>Retries</th>
                </tr>
              </thead>
              <tbody>
                {record.tasks.map((t) => (
                  <tr key={t.id}>
                    <td>{t.title}</td>
                    <td className={t.status === "passed" ? s.passed : s.bad}>
                      {t.status === "passed" ? "Passed" : "Not yet"}
                    </td>
                    <td>{t.retries}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className={s.card}>
          <h2>Portal checks</h2>
          {!record ? (
            <p className={s.note}>
              Attach the record from Academy cloud lab onboarding.{" "}
              <button className={s.textButton} onClick={onTraining}>
                Go to training
              </button>
            </p>
          ) : !verdict ? (
            <p className={s.note} aria-busy={busy}>
              Checking…
            </p>
          ) : (
            <>
              <ul className={s.checklist}>
                {rows.map(([label, ok]) => (
                  <li key={label}>
                    {ok ? (
                      <CheckCircle2 size={16} className={s.passed} />
                    ) : (
                      <XCircle size={16} className={s.bad} />
                    )}
                    {label}
                  </li>
                ))}
              </ul>
              {eligible ? (
                submitted ? (
                  <div className={s.ok} role="status">
                    <p>
                      <Clock size={16} /> Request sent to operator safety review
                    </p>
                    <small>
                      The record is one input. Operators still check access
                      policy, the protocol itself and the instrument's state
                      before anything runs.
                    </small>
                  </div>
                ) : (
                  <div className={s.actions}>
                    <button
                      className={s.primary}
                      onClick={() => setSubmitted(true)}
                    >
                      Submit for operator review
                    </button>
                  </div>
                )
              ) : (
                <div className={s.problems} role="status">
                  <p>
                    <CircleSlash size={16} /> This request cannot be submitted
                    yet
                  </p>
                  <ul>
                    {verdict.problems.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                  <button className={s.secondary} onClick={onTraining}>
                    Back to training
                  </button>
                </div>
              )}
            </>
          )}
          {record?.statement && <p className={s.fine}>{record.statement}</p>}
        </div>
      </section>
    </main>
  );
}
