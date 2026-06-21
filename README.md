# steps-modeling — an AI agent skill for STEPS

A portable **skill** that teaches an AI coding agent to write, run, and debug
[STEPS](https://steps.sourceforge.net) (STochastic Engine for Pathway Simulation)
reaction-diffusion models in the modern Python **API_2** (`steps.interface`) — the
idiomatic style from the [user manual](https://steps.sourceforge.net/manual),
plus the gotchas that trip agents up (the `.Create()` source-line magic, reserved
names, duplicate-interface-triangle solver crashes, units).

It's just markdown + runnable templates, so it works with **Claude Code** as a
first-class skill and with **any other AI agent** as reference context.

## Contents

- **[SKILL.md](SKILL.md)** — the skill: cardinal rules, the canonical script
  skeleton, and a debugging checklist. (Has the YAML frontmatter Claude Code needs.)
- **[reference.md](reference.md)** — full cheatsheet: solver table, model/geometry/
  simulation/recording recipes, EField/complexes/MPI pointers, units, and a
  common-errors table.
- **[templates/well_mixed.py](templates/well_mixed.py)** — runnable well-mixed model
  (`A + B <-> C`, recorded with a ResultSelector).
- **[templates/spatial_tetexact.py](templates/spatial_tetexact.py)** — spatial
  tetrahedral-mesh template (compartment + membrane patch + diffusion + surface pump).
- **[validate_steps_script.py](validate_steps_script.py)** — static validator: lints a
  STEPS script for the cardinal-rule pitfalls + unit/biological-scale sanity (Conc
  molar, Diffusion m²/s, mesh `scale=`) and prints a **fix** for each issue. No
  execution, STEPS not required. `python validate_steps_script.py model.py` (or
  `--selftest`).

Both templates are verified against STEPS 5.1.0.

## Use with Claude Code

Install as a personal skill (available in every project):

```bash
git clone https://github.com/CNS-OIST/steps-modeling-skill.git \
  ~/.claude/skills/steps-modeling
```

…or as a project skill (shared with a repo): clone it to
`.claude/skills/steps-modeling/` inside your project. Claude Code discovers it by the
`name`/`description` in `SKILL.md` and loads it when you ask anything about STEPS
modelling — e.g. *“write a STEPS model of calcium buffering in this mesh”* or
*“why does my Tetexact simulation crash with `i < 4`?”*

## Use with any other AI agent

`SKILL.md` and `reference.md` are plain markdown. Point your agent at them, add them
to its rules/context (Cursor `.cursorrules`, a system prompt, a RAG corpus), or paste
the relevant section. The cardinal rules and the common-errors table are written to be
dropped into any model's context.

## Scope

Covers the API_2 essentials: model definition (species, volume/surface reactions,
diffusion), geometry (well-mixed and tetrahedral meshes, compartments, patches,
ROIs), simulation and solvers, and data recording with `ResultSelector`. It points to
the manual for deeper topics (membrane potential / EField, multi-state complexes,
parallel/distributed MPI). It does **not** replace the manual — it makes an agent
fluent in the house style so its STEPS code runs the first time.

## Source & license

Distilled from the [STEPS user manual](https://steps.sourceforge.net/manual) (API_2
tutorials and reference). STEPS is developed by the
[CNS-OIST](https://github.com/CNS-OIST/STEPS) unit. Contributions welcome — keep
examples runnable and verified against a current STEPS release.
