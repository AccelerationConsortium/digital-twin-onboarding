import { Waypoints } from "lucide-react";
import { progress, useSkills, type Skills } from "./skills";
import s from "./SkillTree.module.css";

const STOPS = [
  ["instruments", "Meet the instruments", "functions run on a twin"],
  [
    "learn/intermediate",
    "Reproduce published workflows",
    "workflows reproduced",
  ],
  ["sim", "Make them your own", "changes made"],
] as const;

/** The three stages of the path, how far along each is, and the way between them. */
export default function StageRail({
  current,
  skills: given,
  onNavigate,
}: {
  current?: 1 | 2 | 3;
  /** The skill tree page's own tree; elsewhere the rail loads one and links to the page. */
  skills?: Skills | null | false;
  onNavigate: (target: string) => void;
}) {
  const [own] = useSkills();
  const skills = given === undefined ? own : given;
  const counts = skills ? progress(skills) : null;
  return (
    <nav className={s.rail} aria-label="Learning stages">
      <ol>
        {STOPS.map(([target, title, unit], index) => {
          const count = counts?.[index];
          return (
            <li key={target}>
              <button
                aria-current={current === index + 1 ? "step" : undefined}
                onClick={() => onNavigate(target)}
              >
                <span className={s.railStep} aria-hidden="true">
                  {index + 1}
                </span>
                <span>
                  <strong>{title}</strong>
                  <small>
                    {count
                      ? `${count.done}${count.of ? ` / ${count.of}` : ""} ${unit}`
                      : " "}
                  </small>
                </span>
                {count?.of && (
                  <span
                    className={s.railBar}
                    style={{ ["--done" as string]: count.done / count.of }}
                    aria-hidden="true"
                  />
                )}
              </button>
            </li>
          );
        })}
      </ol>
      {given === undefined && (
        <button className={s.railTree} onClick={() => onNavigate("skills")}>
          <Waypoints size={16} />{" "}
          {current === 1 ? "Run functions in the skill tree" : "Skill tree"}
        </button>
      )}
    </nav>
  );
}
