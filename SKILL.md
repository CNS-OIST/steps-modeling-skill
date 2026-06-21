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
