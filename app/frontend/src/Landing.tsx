import { useRef, useState, type CSSProperties, type ReactNode } from "react";
import { api, json } from "./api";
import { ArrowRight, BookOpen, FlaskConical, GitBranch } from "lucide-react";
import type { Config } from "./types";
import SketchTwin from "./SketchTwin";
import s from "./Landing.module.css";

const steps = [
  {
    Icon: BookOpen,
    title: "Learn the basics",
    text: "Short lessons that start from what you already know.",
  },
  {
    Icon: GitBranch,
    title: "Design a workflow",
    text: "Combine steps into an experiment of your own.",
  },
  {
    Icon: FlaskConical,
    title: "Try it and compare",
    text: "Run it on a teaching model, change something, run again.",
  },
];

export default function Landing({
  brand,
  config,
  onEnter,
  busy,
}: {
  brand: ReactNode;
  config: Config;
  onEnter: (name: string) => void;
  busy: boolean;
}) {
  const [name, setName] = useState("");
  // Emails outside the sign-up domains ask a lab operator for an invitation.
  const [asking, setAsking] = useState(false);
  const [ask, setAsk] = useState({ email: "", name: "", note: "" });
  const [asked, setAsked] = useState<"" | "sending" | "sent">("");
  const [refused, setRefused] = useState("");
  const request = async () => {
    setAsked("sending");
    setRefused("");
    try {
      await api("/access-requests", json(ask));
      setAsked("sent");
    } catch (error) {
      setAsked("");
      setRefused(
        error instanceof Error ? error.message : "The request was not sent.",
      );
    }
  };
  const page = useRef<HTMLElement>(null);
  const entry = useRef<HTMLFormElement>(null);
  const signup = config.self_signup_email_domains ?? [];
  return (
    <main
      ref={page}
      className={s.landing}
      onPointerMove={(e) => {
        const box = page.current?.getBoundingClientRect();
        if (!box) return;
        const x = e.clientX - box.left;
        const y = e.clientY - box.top;
        page.current?.style.setProperty("--px", `${x}px`);
        page.current?.style.setProperty("--py", `${y}px`);
        page.current?.style.setProperty("--nx", `${x / box.width - 0.5}`);
        page.current?.style.setProperty("--ny", `${y / box.height - 0.5}`);
      }}
    >
      <div className={s.backdrop} aria-hidden="true">
        <span className={s.blobA} />
        <span className={s.blobB} />
        <span className={s.blobC} />
        <span className={s.rays}>
          <i />
          <i />
          <i />
          <i />
        </span>
        <div className={s.twin}>
          <SketchTwin />
        </div>
        <span className={s.spotlight} />
      </div>

      <header className={s.header}>
        {brand}
        <button
          className={s.signIn}
          onClick={() => {
            entry.current?.scrollIntoView({ block: "center" });
            entry.current
              ?.querySelector<HTMLInputElement | HTMLButtonElement>(
                "input, button",
              )
              ?.focus({ preventScroll: true });
          }}
        >
          Sign in <ArrowRight size={16} />
        </button>
      </header>

      <section className={s.hero}>
        <div className={s.copy}>
          <p className={s.kicker} style={{ "--i": 0 } as CSSProperties}>
            Virtual Laboratory Training &amp; Competency Platform
          </p>
          <h1 style={{ "--i": 1 } as CSSProperties}>
            How do we establish that a researcher is <em>ready to operate</em> a
            scientific instrument before granting them access to it?
          </h1>
          <p style={{ "--i": 3 } as CSSProperties}>
            Learn each instrument on a teaching model, practise its faults and
            build a record of what you can do — before any bench time.
          </p>
        </div>

        <form
          ref={entry}
          className={s.card}
          aria-labelledby="landing-entry"
          onSubmit={(e) => {
            e.preventDefault();
            if (asking) void request();
            else onEnter(name.trim() || "Learner");
          }}
        >
          <h2 id="landing-entry">
            {asking
              ? "Request access"
              : config.auth === "cognito" && signup.length
                ? "Join or sign in"
                : "Get started"}
          </h2>
          {asking && asked === "sent" && (
            <p className={s.sent} role="status">
              Request sent. An invitation will arrive by email once a lab
              operator approves it.
            </p>
          )}
          {asking && asked !== "sent" && (
            <>
              <label className={s.nameField}>
                Email
                <input
                  type="email"
                  required
                  maxLength={254}
                  autoComplete="email"
                  value={ask.email}
                  onChange={(e) => setAsk({ ...ask, email: e.target.value })}
                />
              </label>
              <label className={s.nameField}>
                Name
                <input
                  required
                  maxLength={80}
                  autoComplete="name"
                  value={ask.name}
                  onChange={(e) => setAsk({ ...ask, name: e.target.value })}
                />
              </label>
              <label className={s.nameField}>
                Lab or course (optional)
                <input
                  maxLength={300}
                  value={ask.note}
                  onChange={(e) => setAsk({ ...ask, note: e.target.value })}
                />
              </label>
              {refused && (
                <p className={s.refused} role="alert">
                  {refused}
                </p>
              )}
            </>
          )}
          {config.auth === "local" && (
            <label className={s.nameField}>
              What should we call you?
              <input
                autoComplete="given-name"
                maxLength={60}
                placeholder="Your first name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
          )}
          {!(asking && asked === "sent") && (
            <button
              className={s.primary}
              disabled={
                busy || asked === "sending" || config.auth === "disabled"
              }
            >
              {asking
                ? "Send request"
                : busy
                  ? "Opening your workspace…"
                  : config.auth === "cognito"
                    ? signup.length
                      ? "Sign in or create an account"
                      : "Sign in to Lab Onboarding"
                    : "Enter the learning lab"}
              <ArrowRight size={18} />
            </button>
          )}
          {!asking && (
            <span className={s.caption}>
              {config.auth === "local"
                ? "Local preview · your progress stays on this computer"
                : config.auth === "disabled"
                  ? "Sign-in has not been configured. Ask your administrator."
                  : signup.length
                    ? `New learners can sign up with ${signup.map((domain) => `@${domain}`).join(" or ")}. Verify your email to start learning.`
                    : "Use your training account to save your progress."}
            </span>
          )}
          {config.auth === "cognito" && (
            <button
              type="button"
              className={s.switch}
              onClick={() => setAsking(!asking)}
            >
              {asking ? "Back to sign in" : "Request access with another email"}
            </button>
          )}
        </form>
      </section>

      <ol className={s.steps}>
        {steps.map(({ Icon, title, text }, i) => (
          <li key={title} style={{ "--i": i } as CSSProperties}>
            <span className={s.stepIcon}>
              <Icon size={20} />
            </span>
            <span className={s.stepNumber}>0{i + 1}</span>
            <h3>{title}</h3>
            <p>{text}</p>
          </li>
        ))}
      </ol>

      <footer className={s.footer}>
        <span>TEACHING MODEL · SYNTHETIC</span>
        <span>Results here come from a teaching model, not a real lab.</span>
      </footer>
    </main>
  );
}
