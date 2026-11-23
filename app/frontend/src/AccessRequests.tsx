import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, json } from "./api";
import s from "./AccessRequests.module.css";

type AccessRequest = {
  id: string;
  version: number;
  email: string;
  name: string;
  note: string;
  status: "pending" | "invited" | "declined";
  created_at: string;
};

const day = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });

/** Lab operators admit learners whose email cannot register by itself. */
export default function AccessRequests({
  onError,
}: {
  onError: (message: string) => void;
}) {
  const [requests, setRequests] = useState<AccessRequest[] | null>(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState("");
  const failed = useCallback(
    (error: unknown) =>
      onError(
        error instanceof Error ? error.message : "The request did not finish.",
      ),
    [onError],
  );
  const load = useCallback(
    () =>
      api<AccessRequest[]>("/access-requests").then(setRequests).catch(failed),
    [failed],
  );
  useEffect(() => {
    void load();
  }, [load]);

  const act = async (id: string, path: string, body: unknown) => {
    setBusy(id);
    try {
      await api(path, json(body));
      return true;
    } catch (error) {
      failed(error);
      return false;
    } finally {
      await load();
      setBusy("");
    }
  };
  const decide = (request: AccessRequest, decision: "approve" | "decline") =>
    act(request.id, `/access-requests/${request.id}/${decision}`, {
      expected_version: request.version,
    });
  const invite = async (event: FormEvent) => {
    event.preventDefault();
    if (await act("invite", "/invitations", { email: email.trim() }))
      setEmail("");
  };

  const waiting = requests?.filter((r) => r.status === "pending") ?? [];
  const decided = requests?.filter((r) => r.status !== "pending") ?? [];
  return (
    <div className={s.page}>
      <h1>Access requests</h1>
      <form className={s.invite} onSubmit={invite}>
        <label htmlFor="invite-email">Invite by email</label>
        <div className={s.inline}>
          <input
            id="invite-email"
            type="email"
            required
            maxLength={254}
            autoComplete="off"
            placeholder="name@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <button className={s.primary} disabled={busy === "invite"}>
            Send invitation
          </button>
        </div>
      </form>

      <section aria-labelledby="access-waiting">
        <h2 id="access-waiting">Waiting</h2>
        {requests && !waiting.length ? (
          <p className={s.empty}>No one is waiting.</p>
        ) : (
          <ul className={s.list}>
            {waiting.map((request) => (
              <li key={request.id}>
                <div>
                  <strong>{request.name}</strong>
                  <span>{request.email}</span>
                  {request.note && <p>{request.note}</p>}
                </div>
                <time dateTime={request.created_at}>
                  {day(request.created_at)}
                </time>
                <div className={s.actions}>
                  <button
                    className={s.secondary}
                    disabled={busy === request.id}
                    aria-label={`Decline ${request.email}`}
                    onClick={() => decide(request, "decline")}
                  >
                    Decline
                  </button>
                  <button
                    className={s.primary}
                    disabled={busy === request.id}
                    aria-label={`Approve ${request.email}`}
                    onClick={() => decide(request, "approve")}
                  >
                    Approve
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {decided.length > 0 && (
        <section aria-labelledby="access-decided">
          <h2 id="access-decided">Decided</h2>
          <ul className={s.list}>
            {decided.map((request) => (
              <li key={request.id}>
                <div>
                  {request.name && <strong>{request.name}</strong>}
                  <span>{request.email}</span>
                </div>
                <span className={s[request.status]}>
                  {request.status === "invited" ? "Invited" : "Declined"}
                </span>
                {request.status === "invited" && (
                  <div className={s.actions}>
                    <button
                      className={s.secondary}
                      disabled={busy === request.id}
                      aria-label={`Resend invitation to ${request.email}`}
                      onClick={() => decide(request, "approve")}
                    >
                      Resend
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
