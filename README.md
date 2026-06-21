# steps-modeling — an AI agent skill for STEPS

A portable **skill** that teaches an AI coding agent to write, run, validate, and
debug [STEPS](https://steps.sourceforge.net) (STochastic Engine for Pathway
Simulation) reaction-diffusion models in the modern Python **API_2**
(`steps.interface`) — the idiomatic style from the
[user manual](https://steps.sourceforge.net/manual), plus the gotchas that trip
agents up (the `.Create()` source-line magic, reserved names,
duplicate-interface-triangle solver crashes, units).

It's **markdown guidance + runnable Python**: cardinal rules and a cheatsheet the
agent reads, working templates it adapts, and a validator script it runs to lint a
model and to extract its kinetics for checking against the literature. Works with
**Claude Code** as a first-class skill and with **any other AI agent** as reference
context.

## Contents

**Docs (read by the agent):**
- **[SKILL.md](SKILL.md)** — the skill: cardinal rules, the canonical script
  skeleton, a semantic-review checklist, the *Validate against the literature*
  procedure, and a debugging checklist. (Has the YAML frontmatter Claude Code needs.)
- **[reference.md](reference.md)** — full cheatsheet: solver table, model/geometry/
  simulation/recording recipes, EField/complexes/MPI pointers, units, a literature
  units → STEPS conversion crib, and a common-errors table.

**Templates (adapted into new models), verified against STEPS 5.1.0:**
- **[templates/well_mixed.py](templates/well_mixed.py)** — well-mixed model
  (`A + B <-> C`, recorded with a ResultSelector).
- **[templates/spatial_tetexact.py](templates/spatial_tetexact.py)** — spatial
  tetrahedral-mesh template (compartment + membrane patch + diffusion + surface pump).

**Scripts (run by the agent or in CI):**
- **[validate_steps_script.py](validate_steps_script.py)** — lint + `--params`, see below.
- **[report_to_pdf.py](report_to_pdf.py)** — turn a validation report (self-contained
  HTML, or Markdown) into a PDF using whatever's installed (headless Chrome/Chromium →
  wkhtmltopdf; pandoc for Markdown). `python report_to_pdf.py report.html report.pdf`
  (or `--selftest`). The agent writes the report; this only handles the conversion.

## Validation hierarchy

The skill validates a model in three tiers, cheap-and-mechanical first, each gating
the next. Earlier tiers are certain and automatable; later ones need a read of the
model's meaning and, finally, the outside world.

```
   model.py
      │
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 1. STATIC LINT          validate_steps_script.py model.py            │
│    mechanical · AST+regex · no execution · CI-gateable               │
│    import order, API_1↔2 mixing, .Create() misuse, reserved names,   │
│    units/scale (Conc molar, D in m²/s, mesh scale=), run ordering,   │
│    unset rates, + statically-detectable semantic traps               │
│    → ERROR / WARNING, each with a concrete fix                       │
└─────────────────────────────────────────────────────────────────────┘
      │  passes
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 2. SEMANTIC REVIEW      agent walks SKILL.md checklist               │
│    needs the model's *meaning* · not mechanical                      │
│    loop-variable scoping, rate magnitude vs intent, units inside     │
│    custom rate fns, clamped species, stoichiometry/cooperativity,    │
│    geometry selection, mesh-side coverage                            │
│    → problem + fix + severity report                                 │
└─────────────────────────────────────────────────────────────────────┘
      │  passes
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 3. LITERATURE VALIDATION   validate_steps_script.py --params + paper │
│    is the science right? · judgment, not pass/fail                   │
│                                                                       │
│      paper provided ──► compare reactions/rates/D/initial-conc       │
│      none ──► ask modeler for paper(s) ──► else ask to web-search    │
│                                                                       │
│    two tiers of finding:                                             │
│      HARD  unit/scale error, wrong stoichiometry, missing reaction   │
│      SOFT  values that legitimately differ (species/temp/prep/lab)   │
│            → advisory suggestion + citation, not a failure           │
└─────────────────────────────────────────────────────────────────────┘
      │
      ▼  report_to_pdf.py report.html report.pdf
   PDF report  (verdict · comparison tables · HARD/ADVISORY findings · sources)
```

## The validator script

Pure-Python, no execution of the model and **STEPS not required** (AST + regex only),
so it's safe to run in CI or a pre-run gate. Two modes:

```bash
python validate_steps_script.py model.py        # lint: cardinal-rule + unit/scale checks
python validate_steps_script.py --params model.py   # extract kinetics as a table
python validate_steps_script.py --selftest       # check the checker
```

- **Lint** flags import order / API_1↔API_2 mixing, `.Create()` source-line misuse
  (loops, comprehensions, no assignment), reserved Species names, unit & biological
  scale (Conc is molar, Diffusion in m²/s, mesh `scale=`), newRun/toSave/run ordering,
  unset reaction rates, plus semantic traps (stale comprehension loop-variable,
  stray O(n²) loop, exact float equality on mesh geometry). Each issue prints a
  concrete **fix**; exit code is non-zero on ERRORs.
- **`--params`** dumps the model's reaction schemes, rate constants (`r[..].K`),
  diffusion constants, and initial `Conc`/`Count` as a table — the starting point for
  comparing the model against its publication or the literature
  (SKILL.md → *Validate against the literature*).

## Use with Claude Code

Install as a personal skill (available in every project):

```bash
git clone https://github.com/CNS-OIST/steps-modeling-skill.git \
  ~/.claude/skills/steps-modeling
```

…or as a project skill (shared with a repo): clone it to
`.claude/skills/steps-modeling/` inside your project. Claude Code discovers it by the
`name`/`description` in `SKILL.md` and loads it when you ask anything about STEPS
modelling — e.g. *“write a STEPS model of calcium buffering in this mesh”*,
*“check my model's rate constants against the Bhalla & Iyengar paper”*, or
*“why does my Tetexact simulation crash with `i < 4`?”* The agent runs
`validate_steps_script.py` itself; you can also run it by hand.

## Use with any other AI agent

`SKILL.md` and `reference.md` are plain markdown — point your agent at them, add them
to its rules/context (Cursor `.cursorrules`, a system prompt, a RAG corpus), or paste
the relevant section. The validator is a standalone script (Python 3, stdlib only):
the agent can invoke it through whatever shell/tool access it has, or you can wire it
into CI independently of any agent.

## Scope

Covers the API_2 essentials: model definition (species, volume/surface reactions,
diffusion), geometry (well-mixed and tetrahedral meshes, compartments, patches,
ROIs), simulation and solvers, data recording with `ResultSelector`, and validating a
model's kinetics against its source publication or the literature. It points to the
manual for deeper topics (membrane potential / EField, multi-state complexes,
parallel/distributed MPI). It does **not** replace the manual — it makes an agent
fluent in the house style so its STEPS code runs the first time.

## Source & license

Distilled from the [STEPS user manual](https://steps.sourceforge.net/manual) (API_2
tutorials and reference). STEPS is developed by the
[CNS-OIST](https://github.com/CNS-OIST/STEPS) unit. Contributions welcome — keep
examples runnable and verified against a current STEPS release, and keep the validator
and the docs in sync (every documented gotcha should have a check).
