import { useRef, useState, type CSSProperties, type ReactNode } from "react";
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
          <h1>
            <span style={{ "--i": 0 } as CSSProperties}>Welcome to</span>{" "}
            <em style={{ "--i": 1 } as CSSProperties}>Lab</em>{" "}
            <em style={{ "--i": 2 } as CSSProperties}>Onboarding.</em>
          </h1>
          <p style={{ "--i": 3 } as CSSProperties}>
            A place to learn lab automation by trying it. Build a workflow, run
            it on a teaching model and see what changes — no bench time needed.
          </p>
        </div>

        <form
          ref={entry}
          className={s.card}
          aria-labelledby="landing-entry"
          onSubmit={(e) => {
            e.preventDefault();
            onEnter(name.trim() || "Learner");
          }}
        >
          <h2 id="landing-entry">
            {config.auth === "cognito" && signup.length
              ? "Join or sign in"
              : "Get started"}
          </h2>
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
          <button
            className={s.primary}
            disabled={busy || config.auth === "disabled"}
          >
            {busy
              ? "Opening your workspace…"
              : config.auth === "cognito"
                ? signup.length
                  ? "Sign in or create an account"
                  : "Sign in to Lab Onboarding"
                : "Enter the learning lab"}
            <ArrowRight size={18} />
          </button>
          <span className={s.caption}>
            {config.auth === "local"
              ? "Local preview · your progress stays on this computer"
              : config.auth === "disabled"
                ? "Sign-in has not been configured. Ask your administrator."
                : signup.length
                  ? `New learners can sign up with ${signup.map((domain) => `@${domain}`).join(" or ")}. Verify your email to start learning.`
                  : "Use your training account to save your progress."}
          </span>
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
