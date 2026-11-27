import {
  ArrowLeft,
  Check,
  CircleAlert,
  Pause,
  Play,
  RotateCcw,
  ShieldOff,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, json } from "./api";
import s from "./SupervisorReview.module.css";

type Kind = "run" | "practice" | "agent";
type Outcome = "success" | "error" | "not_run" | "restricted";
type Entry = {
  index: number;
  step: number | null;
  label: string;
  outcome: Outcome;
  detail: string;
  hint: string;
  start_s: number;
  end_s: number;
  state: {
    wells: Record<string, number>;
    tip: boolean;
    tip_volume: number;
  } | null;
};
type Comment = {
  id: string;
  member_id: string;
  author: string;
  role: "reviewer" | "learner";
  text: string;
  index: number | null;
  t_s: number | null;
  parent: string | null;
  at: string;
  resolved_at: string | null;
  resolved_by: string | null;
};
type Summary = {
  id: string;
  group_id: string;
  group: string;
  version: number;
  member_id: string;
  learner: string;
  kind: Kind;
  title: string;
  summary: string;
  submitted_at: string;
  via: "shared" | "policy";
  comments: number;
  open_threads: number;
};
type Review = Omit<Summary, "comments" | "open_threads"> & {
  role: "reviewer" | "learner";
  you: { id: string; facilitator: boolean };
  evidence: "synthetic";
  agent?: string | null;
  timeline: Entry[];
  duration_s: number;
  comments: Comment[];
};
type GroupRow = {
  id: string;
  name: string;
  role: "facilitator" | "member";
  policy: "shared" | "supervised";
  policy_version: number;
  consent_version: number;
  allow: boolean | null;
  supervised: boolean;
};
type Overview = { groups: GroupRow[]; mine: Summary[]; to_review: Summary[] };
type Source = {
  kind: Kind;
  id: string;
  title: string;
  at: string;
  summary: string;
};
type MemberRow = {
  id: string;
  name: string;
  role: string;
  supervised: boolean;
};

const kindText: Record<Kind, string> = {
  run: "Workflow run",
  practice: "Find the fault",
  agent: "Agent episode",
};

/** The entry running at `clock`: the last one that has started (as in layoutTimeline). */
function entryAt(timeline: Entry[], clock: number) {
  let found = 0;
  timeline.forEach((entry, i) => {
    if (entry.start_s <= clock) found = i;
  });
  return found;
}

const seconds = (value: number) => `${value.toFixed(1)} s`;

export default function SupervisorReview({
  onGroups,
  onError,
}: {
  onGroups: () => void;
  onError: (message: string) => void;
}) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [review, setReview] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(
    async <T,>(work: () => Promise<T>) => {
      setBusy(true);
      try {
        return await work();
      } catch (e) {
        onError((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [onError],
  );
  const reload = useCallback(
    () =>
      run(async () => {
        const [found, mine] = await Promise.all([
          api<Overview>("/reviews"),
          api<{ sessions: Source[] }>("/reviews/sessions"),
        ]);
        setOverview(found);
        setSources(mine.sessions);
      }),
    [run],
  );
  useEffect(() => {
    void reload();
  }, [reload]);

  const open = (item: { group_id: string; id: string }) =>
    run(async () =>
      setReview(
        await api<Review>(`/reviews/groups/${item.group_id}/items/${item.id}`),
      ),
    );

  if (review)
    return (
      <ReviewPage
        review={review}
        busy={busy}
        run={run}
        onChange={setReview}
        onBack={() => {
          setReview(null);
          void reload();
        }}
      />
    );
  if (!overview) return <div className={s.page} aria-busy="true" />;

  const facilitated = overview.groups.filter((g) => g.role === "facilitator");
  return (
    <div className={s.page}>
      <h1>Reviews</h1>
      {overview.groups.length === 0 ? (
        <div className={s.panel}>
          <p>
            Reviews happen in a study group. Join one, then ask for a review.
          </p>
          <button className={s.primary} onClick={onGroups}>
            Study groups
          </button>
        </div>
      ) : (
        <>
          <AskForm
            groups={overview.groups}
            sources={sources}
            busy={busy}
            onSubmit={(groupId, source) =>
              run(async () => {
                const created = await api<Review>(
                  `/reviews/groups/${groupId}`,
                  json({ kind: source.kind, source_id: source.id }),
                );
                setReview(created);
              })
            }
          />
          <Consents
            groups={overview.groups}
            busy={busy}
            run={run}
            onDone={reload}
          />
          {(facilitated.length > 0 || overview.to_review.length > 0) && (
            <section aria-labelledby="queue-title">
              <h2 id="queue-title">To review</h2>
              <ReviewList
                items={overview.to_review}
                empty="Nothing submitted yet."
                onOpen={open}
                showLearner
              />
              {facilitated.map((group) => (
                <Supervision
                  key={group.id}
                  group={group}
                  busy={busy}
                  run={run}
                  onOpened={setReview}
                  onChanged={reload}
                />
              ))}
            </section>
          )}
          <section aria-labelledby="mine-title">
            <h2 id="mine-title">Your reviews</h2>
            <ReviewList
              items={overview.mine}
              empty="Ask for a review of a run, an exercise or an agent episode."
              onOpen={open}
            />
          </section>
        </>
      )}
    </div>
  );
}

function AskForm({
  groups,
  sources,
  busy,
  onSubmit,
}: {
  groups: GroupRow[];
  sources: Source[];
  busy: boolean;
  onSubmit: (groupId: string, source: Source) => void;
}) {
  return (
    <form
      className={s.panel}
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        const source = sources.find(
          (item) => `${item.kind}:${item.id}` === data.get("session"),
        );
        if (source) onSubmit(String(data.get("group")), source);
      }}
    >
      <h2>Ask for a review</h2>
      <div className={s.fields}>
        <div>
          <label htmlFor="review-session">Session</label>
          <select id="review-session" name="session" required>
            {sources.map((item) => (
              <option
                key={`${item.kind}:${item.id}`}
                value={`${item.kind}:${item.id}`}
              >
                {kindText[item.kind]} · {item.title} · {item.summary}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="review-group">Group</label>
          <select id="review-group" name="group" required>
            {groups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
              </option>
            ))}
          </select>
        </div>
        <button className={s.primary} disabled={busy || sources.length === 0}>
          Ask for review
        </button>
      </div>
      {sources.length === 0 && (
        <p className={s.reason}>
          Run a workflow, start a find-the-fault exercise or let an agent work
          in the sandbox first.
        </p>
      )}
    </form>
  );
}

function Consents({
  groups,
  busy,
  run,
  onDone,
}: {
  groups: GroupRow[];
  busy: boolean;
  run: <T>(work: () => Promise<T>) => Promise<T | undefined>;
  onDone: () => void;
}) {
  const supervisedGroups = groups.filter(
    (g) => g.policy === "supervised" && g.role === "member",
  );
  if (supervisedGroups.length === 0) return null;
  const set = (group: GroupRow, allow: boolean) =>
    run(async () => {
      await api(
        `/reviews/groups/${group.id}/consent`,
        json({ expected_version: group.consent_version, allow }),
      );
      onDone();
    });
  return (
    <ul className={s.consents} aria-label="Supervised groups">
      {supervisedGroups.map((group) => (
        <li key={group.id}>
          <span>
            {group.supervised
              ? `Facilitators of ${group.name} can review any of your sessions.`
              : `${group.name} asks to review any of your sessions.`}
          </span>
          {group.supervised ? (
            <button
              className={s.secondary}
              disabled={busy}
              onClick={() => void set(group, false)}
            >
              <ShieldOff size={15} /> Stop
            </button>
          ) : (
            <button
              className={s.secondary}
              disabled={busy}
              onClick={() => void set(group, true)}
            >
              Allow
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

function Supervision({
  group,
  busy,
  run,
  onOpened,
  onChanged,
}: {
  group: GroupRow;
  busy: boolean;
  run: <T>(work: () => Promise<T>) => Promise<T | undefined>;
  onOpened: (review: Review) => void;
  onChanged: () => void;
}) {
  const [members, setMembers] = useState<MemberRow[] | null>(null);
  const [picked, setPicked] = useState<{
    member: MemberRow;
    sessions: Source[];
  } | null>(null);
  const supervised = group.policy === "supervised";
  return (
    <details
      className={s.supervision}
      onToggle={(event) => {
        if ((event.target as HTMLDetailsElement).open && !members)
          void run(async () =>
            setMembers(
              (
                await api<{ members: MemberRow[] }>(
                  `/reviews/groups/${group.id}/members`,
                )
              ).members,
            ),
          );
      }}
    >
      <summary>{group.name}</summary>
      <label className={s.check}>
        <input
          type="checkbox"
          checked={supervised}
          disabled={busy}
          onChange={(event) =>
            void run(async () => {
              await api(
                `/reviews/groups/${group.id}/policy`,
                json({
                  expected_version: group.policy_version,
                  policy: event.target.checked ? "supervised" : "shared",
                }),
              );
              setMembers(null);
              onChanged();
            })
          }
        />
        Review every session of members who join from now on or allow it
      </label>
      {supervised && members && (
        <ul className={s.memberList}>
          {members.map((member) => (
            <li key={member.id}>
              <span>{member.name}</span>
              {member.supervised ? (
                <button
                  className={s.secondary}
                  disabled={busy}
                  onClick={() =>
                    void run(async () =>
                      setPicked({
                        member,
                        sessions: (
                          await api<{ sessions: Source[] }>(
                            `/reviews/groups/${group.id}/members/${member.id}/sessions`,
                          )
                        ).sessions,
                      }),
                    )
                  }
                >
                  Sessions
                </button>
              ) : (
                <small>Shares on request</small>
              )}
            </li>
          ))}
        </ul>
      )}
      {picked && (
        <ul
          className={s.sources}
          aria-label={`Sessions of ${picked.member.name}`}
        >
          {picked.sessions.length === 0 && <li>No sessions yet.</li>}
          {picked.sessions.map((item) => (
            <li key={`${item.kind}:${item.id}`}>
              <button
                disabled={busy}
                onClick={() =>
                  void run(async () =>
                    onOpened(
                      await api<Review>(
                        `/reviews/groups/${group.id}/members/${picked.member.id}`,
                        json({ kind: item.kind, source_id: item.id }),
                      ),
                    ),
                  )
                }
              >
                <strong>{item.title}</strong>
                <span>
                  {kindText[item.kind]} · {item.summary}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

function ReviewList({
  items,
  empty,
  onOpen,
  showLearner = false,
}: {
  items: Summary[];
  empty: string;
  onOpen: (item: Summary) => void;
  showLearner?: boolean;
}) {
  if (items.length === 0) return <p className={s.empty}>{empty}</p>;
  return (
    <ul className={s.cards}>
      {items.map((item) => (
        <li key={`${item.group_id}:${item.id}`}>
          <button onClick={() => onOpen(item)}>
            <strong>{item.title}</strong>
            <span>
              {showLearner ? `${item.learner} · ` : ""}
              {kindText[item.kind]} · {item.group}
            </span>
            <span className={item.open_threads ? s.open : ""}>
              {item.open_threads
                ? `${item.open_threads} open ${item.open_threads === 1 ? "comment" : "comments"}`
                : item.comments
                  ? "All resolved"
                  : "No comments yet"}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function ReviewPage({
  review,
  busy,
  run,
  onChange,
  onBack,
}: {
  review: Review;
  busy: boolean;
  run: <T>(work: () => Promise<T>) => Promise<T | undefined>;
  onChange: (review: Review) => void;
  onBack: () => void;
}) {
  const { timeline } = review;
  const duration = timeline.length ? timeline[timeline.length - 1].end_s : 0;
  const [clock, setClock] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [draft, setDraft] = useState("");
  const [pinTime, setPinTime] = useState(true);
  const current = timeline.length ? entryAt(timeline, clock) : null;
  const entry = current === null ? null : timeline[current];
  const base = `/reviews/groups/${review.group_id}/items/${review.id}`;

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setClock((value) => {
        const next = Math.min(duration, value + 0.1);
        if (next >= duration) setPlaying(false);
        return next;
      });
    }, 100);
    return () => window.clearInterval(timer);
  }, [playing, duration]);

  const threads = review.comments.filter((c) => c.parent === null);
  const replies = (id: string) =>
    review.comments.filter((c) => c.parent === id);
  const pinned = useMemo(() => {
    const counts = new Map<number, number>();
    threads.forEach((c) => {
      if (c.index !== null) counts.set(c.index, (counts.get(c.index) ?? 0) + 1);
    });
    return counts;
  }, [threads]);
  const shown = threads.filter((c) => c.index === current || c.index === null);

  const post = (body: Record<string, unknown>) =>
    run(async () => {
      onChange(
        await api<Review>(
          `${base}/comments`,
          json({ version: review.version, ...body }),
        ),
      );
      return true;
    });
  const resolve = (comment: Comment, resolved: boolean) =>
    run(async () =>
      onChange(
        await api<Review>(
          `${base}/comments/${comment.id}/resolve`,
          json({ version: review.version, resolved }),
        ),
      ),
    );

  return (
    <div className={s.page}>
      <button className={s.back} onClick={onBack}>
        <ArrowLeft size={16} /> Reviews
      </button>
      <div className={s.heading}>
        <h1>{review.title}</h1>
        <p>
          {review.learner}
          {review.agent ? ` · agent ${review.agent}` : ""} ·{" "}
          {kindText[review.kind]} · {review.group} · {review.summary}
        </p>
        <span className={s.synthetic}>Synthetic replay</span>
      </div>

      <div className={s.replay}>
        <div className={s.player}>
          <div className={s.controls}>
            <button
              className={s.icon}
              aria-label={playing ? "Pause replay" : "Play replay"}
              disabled={!duration}
              onClick={() => {
                if (!playing && clock >= duration) setClock(0);
                setPlaying(!playing);
              }}
            >
              {playing ? <Pause size={16} /> : <Play size={16} />}
            </button>
            <div className={s.track}>
              <input
                type="range"
                min={0}
                max={duration}
                step={0.1}
                value={clock}
                aria-label="Replay time"
                aria-valuetext={`${seconds(clock)}, step ${(current ?? 0) + 1} of ${timeline.length}`}
                onChange={(event) => {
                  setPlaying(false);
                  setClock(Number(event.target.value));
                }}
              />
              <div className={s.pins} aria-hidden="true">
                {threads
                  .filter((c) => c.index !== null)
                  .map((c) => (
                    <span
                      key={c.id}
                      className={c.resolved_at ? s.pinDone : s.pin}
                      style={{
                        left: `${duration ? (((c.t_s ?? timeline[c.index!].start_s) / duration) * 100).toFixed(2) : 0}%`,
                      }}
                    />
                  ))}
              </div>
            </div>
            <output className={s.clock}>
              {seconds(clock)} / {seconds(duration)}
            </output>
          </div>
          <ol className={s.timeline} aria-label="Steps">
            {timeline.map((item) => (
              <li
                key={item.index}
                className={`${s[item.outcome]} ${item.index === current ? s.current : ""}`}
              >
                <button
                  aria-current={item.index === current ? "step" : undefined}
                  onClick={() => {
                    setPlaying(false);
                    setClock(item.start_s);
                  }}
                >
                  <span className={s.marker} aria-hidden="true">
                    {item.outcome === "success" ? (
                      <Check size={13} />
                    ) : item.outcome === "not_run" ? null : (
                      <CircleAlert size={13} />
                    )}
                  </span>
                  <span className={s.label}>
                    {item.step !== null && <small>{item.step}</small>}
                    {item.label}
                  </span>
                  <span className={s.detail}>{item.detail}</span>
                  {pinned.get(item.index) && (
                    <span className={s.count}>
                      {pinned.get(item.index)}
                      <span className={s.srOnly}> comments</span>
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ol>
        </div>

        <aside className={s.comments} aria-labelledby="comments-title">
          <h2 id="comments-title">
            {entry ? `Step ${entry.index + 1} · ${entry.label}` : "Comments"}
          </h2>
          {entry?.state && (
            <p className={s.state}>
              {Object.entries(entry.state.wells)
                .map(([well, volume]) => `${well} ${volume} µL`)
                .join(" · ")}
              {entry.state.tip
                ? ` · tip holds ${entry.state.tip_volume} µL`
                : ""}
            </p>
          )}
          {entry?.hint && (
            <p className={s.hint}>
              {review.kind === "agent"
                ? `Refused by the ${entry.hint} layer`
                : entry.hint}
            </p>
          )}
          {shown.length === 0 && review.role === "learner" && (
            <p className={s.empty}>No comments on this step.</p>
          )}
          <ul className={s.threads}>
            {shown.map((thread) => (
              <Thread
                key={thread.id}
                thread={thread}
                replies={replies(thread.id)}
                busy={busy}
                onReply={(text) => post({ text, parent: thread.id })}
                onResolve={
                  review.role === "learner" ||
                  review.you.facilitator ||
                  thread.member_id === review.you.id
                    ? (resolved) => resolve(thread, resolved)
                    : undefined
                }
              />
            ))}
          </ul>
          {review.role === "reviewer" && entry && (
            <form
              className={s.composer}
              onSubmit={(event) => {
                event.preventDefault();
                void post({
                  text: draft,
                  index: entry.index,
                  t_s: pinTime
                    ? Math.min(entry.end_s, Math.max(entry.start_s, clock))
                    : null,
                }).then((ok) => ok && setDraft(""));
              }}
            >
              <label htmlFor="review-comment">
                Comment on step {entry.index + 1}
              </label>
              <textarea
                id="review-comment"
                value={draft}
                maxLength={1000}
                required
                rows={3}
                onChange={(event) => setDraft(event.target.value)}
              />
              <div className={s.composerRow}>
                <label className={s.check}>
                  <input
                    type="checkbox"
                    checked={pinTime}
                    onChange={(event) => setPinTime(event.target.checked)}
                  />
                  At{" "}
                  {seconds(
                    Math.min(entry.end_s, Math.max(entry.start_s, clock)),
                  )}
                </label>
                <button className={s.primary} disabled={busy}>
                  Comment
                </button>
              </div>
            </form>
          )}
        </aside>
      </div>
    </div>
  );
}

function Thread({
  thread,
  replies,
  busy,
  onReply,
  onResolve,
}: {
  thread: Comment;
  replies: Comment[];
  busy: boolean;
  onReply: (text: string) => Promise<boolean | undefined>;
  onResolve?: (resolved: boolean) => void;
}) {
  const [draft, setDraft] = useState("");
  const resolved = thread.resolved_at !== null;
  return (
    <li className={resolved ? s.resolved : ""}>
      <p>
        <strong>{thread.author}</strong>
        {thread.t_s !== null && <small> at {seconds(thread.t_s)}</small>}
      </p>
      <p>{thread.text}</p>
      {replies.map((reply) => (
        <p key={reply.id} className={s.reply}>
          <strong>{reply.author}</strong> {reply.text}
        </p>
      ))}
      {resolved ? (
        <div className={s.threadRow}>
          <small>Resolved by {thread.resolved_by}</small>
          {onResolve && (
            <button
              className={s.link}
              disabled={busy}
              onClick={() => onResolve(false)}
            >
              <RotateCcw size={13} /> Reopen
            </button>
          )}
        </div>
      ) : (
        <form
          className={s.replyForm}
          onSubmit={(event) => {
            event.preventDefault();
            void onReply(draft).then((ok) => ok && setDraft(""));
          }}
        >
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            maxLength={1000}
            required
            aria-label={`Reply to ${thread.author}`}
          />
          <button className={s.secondary} disabled={busy}>
            Reply
          </button>
          {onResolve && (
            <button
              type="button"
              className={s.secondary}
              disabled={busy}
              onClick={() => onResolve(true)}
            >
              Resolve
            </button>
          )}
        </form>
      )}
    </li>
  );
}
