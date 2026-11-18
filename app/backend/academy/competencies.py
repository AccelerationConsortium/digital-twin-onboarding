"""Where Academy practice sits in the GASE Guidelines' competency framework.

The Global Automated Science Education (GASE) Guidelines (SLAS, with the Acceleration
Consortium and EBRC; draft, to be announced at SLAS 2027) describe competencies by career
track, seniority, process-of-automation step and proficiency (Aware, Informed, Executes,
Leads). They are not yet published, so this map holds only positions in that framework
and Academy-written labels for what is practised here, never the guideline text. The
guideline gives its items no identifiers; the keys below are the Academy's own.

An activity is evidence toward a competency, not certification. Synthetic practice can
show a learner is Informed or Executes a step in a teaching model; Leads needs real
accountability for outcomes, so nothing here claims it.
"""

FRAMEWORK = {
    "name": "GASE Guidelines",
    "status": "draft",
    "levels": ["Aware", "Informed", "Executes", "Leads"],
    "note": "Positions in the framework only; labels are the Academy's, not guideline text.",
}
STEPS = [
    "Identify Need",
    "Critical Composition & Risks",
    "Identify Automation Options",
    "Tool Selection",
    "Suitability & Risk Assessment",
    "Trial of Automated Process",
    "Optimize",
    "Validate Equivalency",
    "Deploy to Production and Monitor",
]

# key: (tracks, seniority, step, proficiency, Academy label, activities that evidence it)
COMPETENCIES = {
    "liquid-handling-principles": (
        ["Science"],
        "Entry",
        "Critical Composition & Risks",
        "Informed",
        "Knows how liquid-handling limits and container rules shape a run",
        ["cloudlab:orient"],
    ),
    "handling-error-sources": (
        ["Science"],
        "Entry",
        "Critical Composition & Risks",
        "Informed",
        "Recognises common sources of error in automated sample handling",
        ["cloudlab:fault"],
    ),
    "run-to-procedure": (
        ["Science"],
        "Entry",
        "Trial of Automated Process",
        "Executes",
        "Builds and runs a method as the procedure asks",
        ["cloudlab:own"],
    ),
    "troubleshoot-to-procedure": (
        ["Science"],
        "Entry",
        "Trial of Automated Process",
        "Executes",
        "Troubleshoots a failing run within the procedure",
        ["cloudlab:fault"],
    ),
    "escalate-out-of-scope": (
        ["Science"],
        "Entry",
        "Trial of Automated Process",
        "Executes",
        "Escalates a problem the procedure does not cover instead of improvising",
        ["cloudlab:escalate", "sandbox:escalate"],
    ),
    "record-assumptions": (
        ["Hardware", "Software", "Science"],
        "Entry",
        "Identify Need",
        "Executes",
        "Records the assumptions a workflow's result depends on",
        ["cloudlab:assume"],
    ),
    "acceptance-criteria": (
        ["Science"],
        "Entry",
        "Validate Equivalency",
        "Executes",
        "Checks automated against manual results with predefined acceptance criteria",
        ["cloudlab:accept"],
    ),
    "document-deviations": (
        ["Science"],
        "Entry",
        "Deploy to Production and Monitor",
        "Executes",
        "Documents a deviation or failure so others can trace it",
        ["cloudlab:report"],
    ),
    "audit-findings": (
        ["Hardware", "Software", "Science"],
        "Mid",
        "Deploy to Production and Monitor",
        "Executes",
        "Finds and documents data-integrity gaps in a simulated audit",
        ["cloudlab:audit"],
    ),
    "automation-worth": (
        ["Hardware", "Software", "Science"],
        "Mid",
        "Identify Need",
        "Executes",
        "Weighs whether a workflow is worth automating, including the cost of not doing it",
        ["cloudlab:need"],
    ),
    "layout-and-paths": (
        ["Hardware"],
        "Mid",
        "Tool Selection",
        "Executes",
        "Plans instrument placement, deck layout and transfer paths",
        ["workcell:layout"],
    ),
    "compare-by-simulation": (
        ["Hardware"],
        "Mid",
        "Identify Automation Options",
        "Executes",
        "Compares candidate setups in simulation before committing to one",
        ["workcell:search"],
    ),
    "robust-to-variation": (
        ["Hardware"],
        "Mid",
        "Optimize",
        "Executes",
        "Tests whether a setup holds against expected variation such as positioning",
        ["workcell:robustness"],
    ),
}


def entry(key):
    tracks, seniority, step, proficiency, label, activities = COMPETENCIES[key]
    return {
        "key": key,
        "tracks": tracks,
        "seniority": seniority,
        "step": step,
        "proficiency": proficiency,
        "label": label,
        "activities": activities,
    }


def catalog():
    return {
        "framework": FRAMEWORK,
        "steps": STEPS,
        "competencies": [entry(k) for k in COMPETENCIES],
    }


def evidenced_by(activities):
    """The competencies a set of completed activities gives evidence toward."""
    done = set(activities)
    return [
        {**entry(key), "evidence": sorted(done & set(row[5]))}
        for key, row in COMPETENCIES.items()
        if done & set(row[5])
    ]
