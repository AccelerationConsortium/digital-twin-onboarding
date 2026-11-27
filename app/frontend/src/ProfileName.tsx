import { useCallback, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useDialog } from "./useDialog";
import type { Profile } from "./types";
import s from "./App.module.css";

/** The signed-in learner's avatar and name; choosing it lets them rename themselves. */
export default function ProfileName({
  profile,
  onSave,
}: {
  profile: Profile;
  onSave: (name: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(profile.name);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const close = useCallback(() => {
    if (!busy) setOpen(false);
  }, [busy]);
  useDialog(open, close);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const next = name.trim();
    if (!next) return setError("Enter a name.");
    if (next === profile.name) return setOpen(false);
    setBusy(true);
    try {
      await onSave(next);
      setOpen(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button
        className={s.userName}
        aria-label={`${profile.name}, change your name`}
        onClick={() => {
          setName(profile.name);
          setError("");
          setOpen(true);
        }}
      >
        <span aria-hidden="true">{profile.name.slice(0, 1).toUpperCase()}</span>
        <strong>{profile.name}</strong>
      </button>
      {open &&
        createPortal(
          <div className={s.modalBackdrop} onClick={close}>
            <section
              className={`${s.modal} ${s.nameDialog}`}
              role="dialog"
              aria-modal="true"
              aria-labelledby="name-title"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                className={s.closeButton}
                aria-label="Close"
                onClick={close}
              >
                <X size={20} />
              </button>
              <h2 id="name-title">Your name</h2>
              <form onSubmit={submit}>
                <label>
                  Name shown to your study groups
                  <input
                    value={name}
                    maxLength={60}
                    onChange={(e) => {
                      setName(e.target.value);
                      setError("");
                    }}
                  />
                </label>
                {error && <p role="alert">{error}</p>}
                <button className={s.primary} disabled={busy}>
                  Save name
                </button>
              </form>
            </section>
          </div>,
          document.body,
        )}
    </>
  );
}
