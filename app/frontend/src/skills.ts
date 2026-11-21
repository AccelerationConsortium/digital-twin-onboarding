import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export type Stage = "prepare" | "characterize" | "test";
export const STAGES: Stage[] = ["prepare", "characterize", "test"];
export const STAGE_LABEL: Record<Stage, string> = {
  prepare: "Prepare",
  characterize: "Characterize",
  test: "Test",
};

export type SkillTwin = {
  id: string;
  name: string;
  source: string;
  notes: string[];
};
export type SkillFunction = {
  id: string;
  label: string;
  operation: string;
  group: "prepare" | "measure";
  twins: SkillTwin[];
  /** The twin the learner had do it. */
  met: string | null;
};
export type SkillStep = {
  text: string;
  stage: Stage;
  functions: string[];
  met: boolean;
};
export type SkillPaper = {
  id: string;
  steps: SkillStep[];
  reproduced: boolean;
  swapped: boolean;
  extended: string[];
};
export type Skills = {
  version: number;
  functions: SkillFunction[];
  papers: SkillPaper[];
  recombined: { prepare: string; measure: string }[];
  statement: string;
};
/** What a run added to the tree. */
export type Earned = {
  functions: string[];
  papers: string[];
  swapped: string[];
  extended: [string, string][];
  recombined: [string, string][];
};

/** How far along each of the three stages a learner is. */
export function progress(skills: Skills) {
  const changed = skills.papers.reduce(
    (n, p) => n + (p.swapped ? 1 : 0) + p.extended.length,
    skills.recombined.length,
  );
  return [
    {
      done: skills.functions.filter((f) => f.met).length,
      of: skills.functions.length,
    },
    {
      done: skills.papers.filter((p) => p.reproduced).length,
      of: skills.papers.length,
    },
    { done: changed, of: null },
  ] as const;
}

/** The learner's skill tree; null until it loads, false if it cannot. */
export function useSkills() {
  const [skills, setSkills] = useState<Skills | null | false>(null);
  const load = useCallback(() => {
    api<Skills>("/skills")
      .then(setSkills)
      .catch(() => setSkills(false));
  }, []);
  useEffect(load, [load]);
  return [skills, setSkills, load] as const;
}
