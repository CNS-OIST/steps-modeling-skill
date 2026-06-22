---
name: steps-modeling
description: Write, run, and debug STEPS (STochastic Engine for Pathway Simulation) reaction-diffusion models in the modern Python API_2 (steps.interface). Use whenever creating or editing a STEPS simulation script — well-mixed or spatial (tetrahedral mesh), volume/surface reactions, diffusion, membrane potential (EField), multi-state complexes, or data recording with ResultSelector.
---

# STEPS modeling (API_2 / `steps.interface`)

STEPS simulates stochastic reaction-diffusion in 3D geometries. Since v3.6 the
idiomatic interface is **API_2** (`steps.interface`) — a pythonic, context-manager
style. Write all new models in it. This skill encodes the manual's conventions
(https://steps.sourceforge.net/manual) plus gotchas that bite AI agents.

**Read [reference.md](reference.md) for the full cheatsheet** (solver table, units,
EField/complexes/parallel, ResultSelector recipes, mesh-from-pipeline notes). Start
from a [template](templates/) and adapt. The rules below are the ones you must not
get wrong.

## Staying current (version check)

This skill is versioned in [VERSION](VERSION). **On first use in a session**, check
whether a newer version is published and, if so, tell the user how to update — then
continue either way. This is advisory: never block on it, and skip it under CI / when
there's no network.

1. Read the local `VERSION` (in this skill's directory).
2. Fetch the latest (one line; WebFetch the same URL if `curl` is unavailable):
   `curl -fsS https://raw.githubusercontent.com/CNS-OIST/steps-modeling-skill/main/VERSION`
3. If they differ, tell the user a newer `steps-modeling` skill is out (show both
   versions) and how to update: `git -C <skill dir> pull` for a git checkout, or
   re-install / update the plugin otherwise. **The skill cannot update itself** — the
   files are read from disk at session start, so the user updates, then the next session
   picks it up. (The maintainer can automate the pull with a `SessionStart` hook.)

## Cardinal rules

1. **Imports, in order.** `import steps.interface` FIRST, then star-import the
   submodules. Never mix API_1 and API_2 in one script.
   ```python
   import steps.interface
   from steps.model import *
   from steps.geom import *
   from steps.rng import *
   from steps.sim import *
   from steps.saving import *
   ```

2. **Objects name themselves from the assignment.** `cyt = Compartment.Create(...)`
   names the object `'cyt'` by reading the **source line**. You then address it in
   simulation paths as `sim.cyt.Ca.Count`. So the left-hand variable name *is* the
   simulation name — pick names you will use, and they must be valid Python
   identifiers.

3. **`.Create()` needs a real `name = X.Create(...)` source line.** It fails in a
   loop, comprehension, multi-line call, `python -c`, or any REPL without source
   ("does not match the expected format for automatic assignment"). To create
   objects programmatically (e.g. one ROI per region in a loop), call the
   **constructor with `name=`** instead: `ROI(triList, name=regionName)`.

4. **Reactions live in a `with` block and use a ReactionManager `r`.**
   ```python
   r = ReactionManager()
   with vsys:
       A + B <r['bind']> C          # reversible
       r['bind'].K = 1e6, 0.7       # (kf, kb); irreversible '>r[..]>' takes one K
   ```
   Surface reactions tag each species with its location: `.i` inner compartment,
   `.o` outer compartment, `.s` the patch surface. All *volume* reactants must be in
   the same compartment. A pump: `Ca.i + P.s >r['pump']> Ca.o + P.s`.

5. **Patch inner compartment comes first:** `Patch.Create(tris, inner, outer, ssys)`.
   A boundary membrane with nothing outside uses `outer=None`.

6. **Everything is SI, but `Conc` is molar.** Diffusion constants m²/s, lengths m,
   `Count` is integer molecules, **`Conc` is mol/L (molar)**. `TetMesh.LoadGmsh(path,
   scale=...)` multiplies mesh coords into metres — a nanometre mesh needs
   `scale=1e-9`.

7. **Record with ResultSelector, not ad-hoc reads.**
   ```python
   rs = ResultSelector(sim)
   caConc = rs.cyt.Ca.Conc            # build a selector
   sim.toSave(caConc, dt=0.01)        # register BEFORE running
   ...
   caConc.data[run, timeIdx, col]; caConc.time[run]; caConc.labels
   ```
   Group access: `.ALL()`, `.LIST(A, B)`, `.MATCH(regex)`, `.SUM(...)`, and for mesh
   elements `sim.TET(t)/TETS(list)`, `sim.TRI(t)/TRIS(list)`. `sim.MATCH('regex')`
   over the whole sim selects every compartment/patch/ROI whose name matches — the
   clean way to address many named regions at once.

8. **Run loop:** `sim.newRun()` resets state; set initial conditions *after* it;
   then `sim.run(endTime)`. Wrap multiple runs in a `for` loop for statistics.

9. **Reserved names.** Single capitals (`A`=Area, `V`=Volume, `D`, `I`, ...) and
   feature words (`Ves`, ...) are reserved — Species/object names must be
   descriptive multi-letter identifiers (`Ca`, `IP3`, `mitoMemb`).

## Canonical skeleton (spatial, Tetexact)

See [templates/spatial_tetexact.py](templates/spatial_tetexact.py) for a runnable
version; [templates/well_mixed.py](templates/well_mixed.py) for the well-mixed case.

```python
import steps.interface
from steps.model import *
from steps.geom import *
from steps.rng import *
from steps.sim import *
from steps.saving import *

mdl = Model()
r = ReactionManager()
with mdl:
    Ca, P = Species.Create()
    vsys = VolumeSystem.Create()
    with vsys:
        Diffusion(Ca, 1e-12)
    ssys = SurfaceSystem.Create()
    with ssys:
        Ca.i + P.s >r['pump']> Ca.o + P.s
        r['pump'].K = 2e8

mesh = TetMesh.LoadGmsh('model.msh', scale=1e-9)     # mesh coords nm -> m
with mesh:
    cyt = Compartment.Create(mesh.tetGroups[(0, 'cytosol')], vsys)
    er  = Compartment.Create(mesh.tetGroups[(0, 'ER')], vsys)
    memb = Patch.Create(mesh.triGroups[(0, 'ER_surface')], er, cyt, ssys)

rng = RNG('mt19937', 512, 1234)
sim = Simulation('Tetexact', mdl, mesh, rng)

rs = ResultSelector(sim)
caConc = rs.cyt.Ca.Conc
sim.toSave(caConc, dt=0.01)

sim.newRun()
sim.cyt.Ca.Conc = 1e-6        # molar
sim.memb.P.Count = 100
sim.run(1.0)
print(caConc.data[0, -1], 'at t =', caConc.time[0, -1])
```

## API_1 input → ask before converting

STEPS scripts come in two flavours. **API_1** (the legacy procedural interface) shows
markers the validator already flags: `import steps.model as smodel` (aliased imports),
`steps.solver` / `steps.mpi.solver`, and `sim.setCompConc(...)` / `getPatchCount(...)`
solver methods. If the input is API_1:

1. **Ask the modeler** whether to convert it to API_2 (`steps.interface`). Do not
   convert silently — it's a rewrite, and they may want the original validated as-is.
2. **If yes** — rewrite into a **new file** (`<name>_api2.py`, never overwrite the
   original). Put a source reference as the first comment so the provenance is recorded:
   ```python
   # Converted to STEPS API_2 from: <original filename>
   ```
   Use the conversion crib in [reference.md](reference.md) → "API_1 → API_2 conversion".
   Then validate the new file.
3. **If no** — validate the original as it is (the lint will still report the API_1
   markers as errors; that's expected and informative).

**Multi-file models.** Real projects split across files (e.g. a `camodel.py` defining
the model + geometry that a driver `import`s, plus the run script). Treat the whole set
as one unit:
- **Find the set** — follow local `import`s between project files; lint/convert every
  STEPS file, not just the one named. The validator runs per file, so run it on each.
- **Convert together, keep the split** — produce one `*_api2.py` per source file and fix
  the inter-file imports (`import camodel` → `import camodel_api2`). API_2 objects name
  themselves from their assignment, so a model built in one file is reached in another by
  passing the **model object** (`gen_geom(mdl, ...)`; fetch systems via `mdl.vsys`) and by
  sim-path/`MATCH` names — not by re-importing the Python objects.
- **Reorder when API_2 demands it** — anything that adds to the mesh (e.g. `ROI`s built in
  the driver) must run **before** `Simulation(...)`; the API_1 habit of creating ROIs and
  setting counts after the solver exists has to move ahead of solver creation.

## Validate a script

Before running a STEPS script, lint it for the pitfalls above — no execution, STEPS
not required:

```bash
python validate_steps_script.py model.py
```

It reports each issue with a concrete **fix**: import order / API_1↔API_2 mixing,
`.Create()` misuse (loops, no assignment), reserved Species names, **units &
biological scale** (Conc is molar, Diffusion in m²/s, mesh `scale=`),
newRun/toSave/run ordering, and reaction rates declared but never set. Exit code is
non-zero on ERRORs (so it fits a pre-run / CI gate); `--selftest` checks the checker.

## Semantic review (beyond static linting)

The validator catches mechanical errors; some bugs need a **read of the model's
meaning**. After the static pass, walk the model end to end against this checklist
(it's what found a "records only 1 of 7 mitochondria" bug a syntax check can't see),
and write up findings as **problem + fix + severity** — a short report, not just a
pass/fail.

- **Comprehension / loop-variable scoping** — a generator whose first iterable uses a
  variable bound by a *later* `for` silently reads a stale value (`(t for t in m.tets
  for m in mitos)` → only the last `m`). The validator now flags the clear case; still
  eyeball aggregations built over lists of compartments/patches.
- **Rate-constant magnitude vs intent** — does each `r[..].K` match its inline comment /
  cited source? A `v*factor` landing ~1000× off a commented "default" is a red flag.
  Sanity the order: 1/s (first-order), 1/(M·s) (second-order).
- **Units inside custom rate functions** — `VDepRate`/lambda rates receive V in *volts*;
  a formula written in mV must scale (`V*1e3`), and a 1/ms result needs `*1e3` → 1/s.
  Static checks can't see inside the lambda.
- **Clamped species with dynamics** — a `Clamped = True` species is pinned, so its
  channels/buffers/reactions can't move it. Intended (a clamp experiment) or a leftover
  that defeats the model?
- **Stoichiometry & cooperative factors** — multi-site binding needs statistical factors
  (2·kon / 2·koff for two equivalent sites); reversible `<r[..]>` takes `(kf, kb)`.
- **Initialised vs declared** — every Species/Complex meant to start non-zero needs a
  `Count`/`Conc`; species that are only ever products are fine at 0.
- **Geometry selection** — picking boundary tris/tets by comparing `.center`/`.bbox`
  with `==`/`in` silently misses (float equality); use a tolerance or a half-space
  (`<=`/`>=`). Watch for a stray `for x in seq:` that ignores `x` and rebuilds a
  comprehension over `seq` (O(n²), recomputed identically). The validator flags both.
- **Mesh side** — did every input body become a compartment? Tiny bodies below the
  element size (or collapsed by a resolver wall-shift) can silently drop.

When the semantic read turns up a *new* class of bug that's statically detectable, add
a check for it (next section) so the next script is caught automatically.

## Validate against the literature

A STEPS model is only as good as its kinetics, but a model is usually assembled from
**several publications**, and their parameters legitimately disagree — different
species, temperatures, prep, and lab protocols all move a rate constant. So this pass
is **mostly advisory: surface context and suggestions, not a pass/fail verdict.** Do
not treat "differs from paper X" as an error. After the static + semantic passes,
dump what the model actually encodes:

```bash
python validate_steps_script.py --params model.py
```

This prints the reaction schemes, every `r[..].K`, `Diffusion(...)` constant, and
initial `Conc`/`Count` — the list you line up against the source(s). Separate findings
into two tiers:

**Hard issues (flag as real problems with a fix).** These are wrong regardless of which
lab the number came from:
- **unit / scale errors** — the #1 trap. STEPS is SI-with-molar (M⁻¹·s⁻¹, s⁻¹, m²/s,
  volts); papers quote µM⁻¹·s⁻¹, mV, ms⁻¹, µm²/s. A value that's 1e3/1e6/1e9 off a
  cited number, or outside the physical envelope (kon ≫ ~1e10 M⁻¹·s⁻¹ diffusion limit,
  D outside ~1e-13–1e-9 m²/s), is almost certainly a conversion bug. See the crib in
  [reference.md](reference.md);
- **wrong stoichiometry** or missing cooperative factors (two equivalent sites →
  `2·kon` / `2·koff`); reaction order that doesn't match the scheme;
- missing / extra reactions versus the cited mechanism.

**Advisory (suggestions, not failures).** Present these for the modeler to judge:
- a rate / concentration / D that sits within plausible biological spread of the
  cited values — note the model's choice and the published range, don't "correct" it;
- values drawn from a different species/temperature/prep than the model targets — flag
  the mismatch in conditions, let the modeler decide;
- when sources disagree, report the **range and each value's conditions/citation**
  rather than forcing one number.

Write it up as a table (model value | published value(s) + conditions/source |
unit-normalised | **hard issue vs suggestion**). Only hard issues get a
problem + fix + severity like the semantic review; the rest are framed as "consider /
note", with the citation for every published value.

**No publication is provided** — do *not* silently search. First **ask the modeler
if they can provide the publication(s)** the model is based on (often more than one).
If they can, use them. If they can't, **ask permission to web-search** the literature
for the pathway's kinetics/parameters. Only on a yes: `WebSearch` the pathway + rate
constants, `WebFetch` a few authoritative sources (prefer the primary modelling papers
or a curated DB), extract the published values **with their experimental conditions**,
and run the same two-tier comparison — **citing the URL/DOI for every value**. If the
modeler declines both, note that the kinetics are unvalidated and stop.

### Generate a report

For a substantial validation (a literature comparison, or a semantic review with
several findings) — or whenever the modeler asks for a report — write it up as a file
and offer a PDF. Write the report as **Markdown** (it doubles as a readable `.md`) and
convert with the bundled helper, which renders to PDF in **pure Python via fpdf2** — no
browser or system binaries:

```bash
pip install fpdf2                                    # once
python report_to_pdf.py report.md report.pdf
```

The helper picks the best renderer available: a **browser** (Chrome/Chromium/Edge) +
the `markdown` module → styled HTML → PDF; else **fpdf2** → pure-Python PDF; else it
leaves the `.md` as the report. You write Markdown once; the environment decides the
output. It supports the usual subset (`#`/`##`/`###` headings, paragraphs, `-` bullets,
pipe tables, `**bold**`) and Unicode (µ, M⁻¹s⁻¹, Ca²⁺, →, ✓).

**Skip report generation under CI / non-interactive automation.** A report is for a
human; in CI there's no one to read it, hand fixes to, or grant permission. There, run
**only the static lint** as the exit-code gate (`validate_steps_script.py model.py`) and
skip the report, the literature web-search, and the permission prompts — they're all
interactive steps. (Detect automation the usual way, e.g. a `CI` env var or no TTY.)

Structure the report so the verdict is readable at a glance:

1. **Verdict** — one short paragraph + a tier-count table (HARD / ADVISORY / CONFIRMED).
2. **Comparison tables** — model value | published value(s) + conditions | source | match.
3. **Findings** — HARD issues as problem + fix + severity; ADVISORY as "consider / note".
   Keep the two-tier split from the literature pass (hard = wrong regardless of source;
   advisory = legitimate species/protocol differences).
4. **Static + semantic carry-over** — any lint/semantic findings, so the report is the
   single artefact.
5. **Sources** — every cited value's URL/DOI.

Be honest in the report itself: mark values you couldn't independently re-fetch as
"cited, not re-verified", and frame a suspected error as "verify" unless it's
unambiguous (a unit/scale slip).

**If fpdf2 isn't available and the modeler can't install it** (no permission, locked
environment), don't block — the **Markdown report is the deliverable**. Hand them the
`.md` (it's fully readable as-is) and note they can render it later with `pip install
fpdf2 && python report_to_pdf.py report.md`. Same for any other missing tool: degrade
to the artefact you can produce, never fail silently.

### Ask before changing the model

Validation **reports**; it does not edit. After presenting the findings (and the
report), **ask the modeler for permission before modifying the script** — list the
exact fixes you propose and wait for a yes. This applies to every tier (lint, semantic,
literature). **If the modeler declines, stop at the report** — leave the script
untouched. Only apply fixes you've been explicitly cleared to make.

## Maintaining this skill

When you hit a STEPS scripting error this skill didn't prevent, **extend it in the
same change**: add a check (with a self-test case) to `validate_steps_script.py`, and
record the trap in the cardinal rules above, the `reference.md` common-errors table,
and the debugging checklist below. Keep the validator and the docs in sync — the
validator should catch every documented gotcha. **Bump [VERSION](VERSION)** (the date,
`YYYY-MM-DD`) in the same change so other users' version check flags the update.

## Debugging checklist

- `Assertion Fail: i < 4` at solver setup → a surface triangle appears as **two
  elements for one tet face** (duplicate interface facets). Each facet needs exactly
  one triangle element; dedup the mesh. (See reference.md → "Meshes from a pipeline".)
- "does not match the expected format for automatic assignment" → a `.Create()` not on
  its own `name = ...Create(...)` line; use the constructor with `name=` (rule 3).
- "name is reserved" → rename the Species/object (rule 9).
- "Outer compartment not defined for this patch" → a surface reaction used `.o` on a
  boundary patch created with `outer=None`; that patch can only host `.i`/`.s` species.
- Counts all zero after a run → reaction `K` too small, or the volume reactant's
  density at the surface is ~0; raise `K` or `Count`, or check units (`Conc` is molar).
