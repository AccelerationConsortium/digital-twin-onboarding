import {
  CheckCircle2,
  CircleSlash,
  Clock,
  Upload,
  XCircle,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, json } from "./api";
import { RECORD_HANDOFF } from "./CloudLabTraining";
import s from "./CloudLabTraining.module.css";

type Verdict = {
  authentic: boolean;
  current: boolean;
  complete: boolean;
  problems: string[];
  record: TrainingRecord | null;
};
type Envelope = {
  format?: string;
  alg?: string;
  kid?: string;
  payload?: string;
  signature?: string;
};
type Issuer = {
  keys: (JsonWebKey & { kid: string })[];
  rules: Record<string, string>;
  format: string;
  now: string;
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
  type?: string;
  complete?: boolean;
  module?: { id?: string; instrument?: string; rules_version?: string };
  tasks?: RecordTask[];
  time_to_first_valid_workflow_s?: number | null;
  statement?: string;
};

const bytes = (text: string) =>
  Uint8Array.from(
    atob(
      text.replace(/-/g, "+").replace(/_/g, "/") +
        "=".repeat((4 - (text.length % 4)) % 4),
    ),
    (c) => c.charCodeAt(0),
  );

/**
 * Check a record the way an independent portal would: with the issuer's public key and
 * current rules only. Null when this browser cannot verify Ed25519 itself.
 */
async function verifyHere(
  envelope: Envelope,
  issuer: Issuer,
): Promise<Verdict | null> {
  const shaped =
    typeof envelope === "object" &&
    envelope !== null &&
    envelope.format === issuer.format &&
    envelope.alg === "EdDSA" &&
    typeof envelope.payload === "string" &&
    typeof envelope.signature === "string";
  const jwk = shaped && issuer.keys.find((k) => k.kid === envelope.kid);
  let record: TrainingRecord | null = null;
  if (jwk && envelope.payload && envelope.signature) {
    let key: CryptoKey;
    try {
      key = await crypto.subtle.importKey(
        "jwk",
        { kty: jwk.kty, crv: jwk.crv, x: jwk.x },
        { name: "Ed25519" },
        false,
        ["verify"],
      );
    } catch {
      return null;
    }
    try {
      const payload = bytes(envelope.payload);
      if (
        await crypto.subtle.verify(
          { name: "Ed25519" },
          key,
          bytes(envelope.signature),
          payload,
        )
      )
        record = JSON.parse(new TextDecoder().decode(payload));
    } catch {
      record = null;
    }
  }
  const authentic = record !== null;
  const found = record ?? {};
  const known = found.type === "academy.training-record/1";
  const sameRules =
    !!found.module?.id &&
    issuer.rules[found.module.id] === found.module.rules_version;
  // Judged by the issuer's clock, not this browser's, which the learner controls.
  const lapse =
    typeof found.expires_at === "string" ? Date.parse(found.expires_at) : NaN;
  const expired = !(lapse >= Date.parse(issuer.now));
  const complete = found.complete === true;
  const problems = (
    [
      [!authentic, "The signature does not match: edited, or not issued here"],
      [authentic && !known, "This is not an Academy training record"],
      [
        authentic && !sameRules,
        "Earned under rules that have since changed; retrain first",
      ],
      [authentic && expired, "The record has expired"],
      [authentic && !complete, "Not every training task has been passed"],
    ] as [boolean, string][]
  ).flatMap(([failed, message]) => (failed ? [message] : []));
  return {
    authentic,
    current: authentic && known && sameRules && !expired,
    complete: authentic && complete,
    problems,
    record,
  };
}

function minutes(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  return seconds < 60 ? `${seconds} s` : `${Math.round(seconds / 60)} min`;
}

/**
 * A stand-in for a cloud lab's run-request page. It sees only the record the learner
 * attaches and checks it itself with the Academy's published key, asking the Academy
 * only when this browser cannot verify Ed25519. Then it applies its own policy: passing
 * would send a real request to operator review; this mock sends nothing, and no portal
 * here ever approves a run.
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
  const [checkedHere, setCheckedHere] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attached, setAttached] = useState<Envelope | null>(null);
  // Only the latest attachment's check may set the verdict.
  const attempt = useRef(0);

  const check = async (envelope: Envelope) => {
    const mine = ++attempt.current;
    setAttached(envelope);
    setRecord(null);
    setVerdict(null);
    setSubmitted(false);
    setFailed(false);
    setBusy(true);
    try {
      const issuer = await api<Issuer>("/cloudlab/issuer");
      const here = await verifyHere(envelope, issuer);
      const found =
        here ??
        (await api<Verdict>(
          "/cloudlab/records/verify",
          json({ record: envelope }),
        ));
      if (mine !== attempt.current) return;
      setCheckedHere(here !== null);
      setVerdict(found);
      setRecord(found.record);
    } catch (e) {
      if (mine === attempt.current) {
        setFailed(true);
        onError((e as Error).message);
      }
    } finally {
      if (mine === attempt.current) setBusy(false);
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
              {verdict ? "Attach a different record" : "Attach your record"}
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
              <dd>
                {typeof record.expires_at === "string"
                  ? record.expires_at.slice(0, 10)
                  : "—"}
              </dd>
            </dl>
          )}
          {Array.isArray(record?.tasks) && (
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Status</th>
                  <th>Retries</th>
                </tr>
              </thead>
              <tbody>
                {record!.tasks!.map((t) => (
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
          {busy ? (
            <p className={s.note} aria-busy="true">
              Checking…
            </p>
          ) : failed && attached ? (
            <div className={s.problems} role="status">
              <p>
                <CircleSlash size={16} /> The record could not be checked
              </p>
              <button
                className={s.secondary}
                onClick={() => void check(attached)}
              >
                Check again
              </button>
            </div>
          ) : !verdict ? (
            <p className={s.note}>
              Attach the record from Academy cloud lab onboarding.{" "}
              <button className={s.textButton} onClick={onTraining}>
                Go to training
              </button>
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
              <p className={s.fine}>
                {checkedHere
                  ? "Checked in this browser with the Academy's public key."
                  : "This browser cannot check Ed25519, so the Academy checked it."}
              </p>
              {eligible ? (
                submitted ? (
                  <div className={s.ok} role="status">
                    <p>
                      <Clock size={16} /> Ready for operator safety review
                    </p>
                    <small>
                      In a real portal the request would now go to the lab's
                      operators, who still check access policy, the protocol and
                      the instrument before anything runs. This mock sends
                      nothing.
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
