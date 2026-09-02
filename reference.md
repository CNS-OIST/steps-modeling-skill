# STEPS API_2 reference cheatsheet

Companion to [SKILL.md](SKILL.md). Source: the STEPS user manual
(https://steps.sourceforge.net/manual) API_2 tutorials + API reference. Verified
against STEPS 5.1.0.

## Module map

| `from steps.X import *` | Provides |
|---|---|
| `model`  | `Model`, `Species`, `VolumeSystem`, `SurfaceSystem`, `Reaction`/`ReactionManager`, `Diffusion`, `Channel`, `OhmicCurr`, `GHKCurr`, `Current`, `Complex`, `Endocytosis`/`Exocytosis` |
| `geom`   | `Geometry` (well-mixed), `TetMesh`/`DistMesh`, `Compartment`, `Patch`, `Membrane`, `ROI`, `TetList`/`TriList`/`VertList`, `DiffBoundary` |
| `rng`    | `RNG` |
| `sim`    | `Simulation`, `SimPath` (the `sim.loc.obj.attr` access), `MPI` |
| `saving` | `ResultSelector`, `HDF5Handler`, `SQLiteDBHandler`, `XDMFHandler` |

## Solvers (`Simulation('NAME', mdl, geom, rng)`)

| Solver | Geometry | Kind | Use |
|---|---|---|---|
| `Wmdirect` | well-mixed | stochastic SSA | fast well-mixed kinetics |
| `Wmrssa`   | well-mixed | stochastic (rejection SSA) | many reactions |
| `Wmrk4`    | well-mixed | deterministic RK4 | ODE check |
| `Tetexact` | tet mesh | spatial stochastic | the workhorse spatial solver |
| `TetODE`   | tet mesh | spatial deterministic | fast, no noise |
| `TetOpSplit` | tet mesh | parallel (MPI) | large spatial, multi-core |
| `DistTetOpSplit` | `DistMesh` | distributed (MPI) | very large meshes |

`RNG('mt19937', bufferSize, seed)` — e.g. `RNG('mt19937', 512, 1234)`. Bigger buffer
= fewer refills.

## Model

```python
mdl = Model()
r = ReactionManager()
with mdl:
    Ca, IP3, R, RIP3, Ropen = Species.Create()     # multi-assign names from the line
    vsys = VolumeSystem.Create()
    ssys = SurfaceSystem.Create()

    with vsys:
        A + B <r['r1']> C            # reversible; r['r1'].K = kf, kb
        2*A >r['r2']> D              # stoichiometry with *; irreversible, one K
        Diffusion(A, 1e-12)          # m^2/s

    with ssys:
        # location tags: .i inner comp, .o outer comp, .s patch surface
        R.s + IP3.o <r['bind']> RIP3.s
        Ca.i + Ropen.s >r['pump']> Ca.o + Ropen.s
        Diffusion(R, 1e-14)          # surface diffusion (same call, surface species)
    r['r1'].K = 1000e6, 25800
    r['pump'].K = 2e8
```

Rules: a reaction's volume reactants must share one compartment; set `K` after
declaring (or inside the block). Reversible `<r[..]>` takes `K = (kf, kb)`,
irreversible `>r[..]>` takes a single `K`.

## Geometry

**Well-mixed** (volumes/areas only):
```python
geom = Geometry()
with geom:
    cyt, ER = Compartment.Create()
    cyt.Vol = 1.66e-19           # m^3
    memb = Patch.Create(ER, cyt, ssys)   # inner=ER, outer=cyt
    memb.Area = 0.41e-12         # m^2
```

**Tetrahedral mesh:**
```python
mesh = TetMesh.LoadGmsh('model.msh', scale=1e-9)   # also LoadAbaqus/LoadTetGen/LoadVTK
with mesh:
    # from named physical groups ($PhysicalNames -> tetGroups/triGroups by name):
    cyt  = Compartment.Create(mesh.tetGroups[(0, 'cytosol')], vsys)
    memb = Patch.Create(mesh.triGroups[(0, 'ER_surface')], er, cyt, ssys)

    # or geometrically, from TetList/TriList:
    topTets = TetList(t for t in mesh.tets if t.center.z > 0)
    top = Compartment.Create(topTets, vsys)
    capTris = TriList(tr for tr in mesh.surface if tr.center.z == mesh.bbox.max.z)
    cap = Patch.Create(capTris, top, None, ssys)     # outer=None: boundary membrane

    # ROI: a named element subset for injection/recording (constructor in a loop)
    roi = ROI(topTets, name='topROI')
```
`mesh.tets`, `mesh.tris`, `mesh.surface`, `mesh.bbox`, `t.center`, `t.vol`;
`TetList`/`TriList` support `|` (union), indexing, comprehension. Patch inner comp
first; `outer=None` for an outer boundary.

## Simulation, initial conditions, running

```python
rng = RNG('mt19937', 512, 1234)
sim = Simulation('Tetexact', mdl, mesh, rng)   # check=False to silence model checks

sim.newRun()                          # ALWAYS before a run; resets state
sim.cyt.Ca.Conc = 1e-6                # molar (mol/L)
sim.cyt.IP3.Count = 6                 # integer molecules
sim.ER.Ca.Clamped = True              # hold concentration fixed
sim.memb.R.Count = 160
sim.TET(centerTet).Ca.Count = 1000    # inject into one tetrahedron
sim.MATCH('AZ.*').Dock.Count = 200    # set on every region whose name matches
sim.cyt.MATCH('SB.*').Count = 1000    # LIST/MATCH take plain name strings too:
counts = sim.cyt.LIST(*names).Count   # how to reach loop-created objects
total  = sum(counts)                  # a read gives the list of values, not a sum
sim.run(1.0)                          # advance to t = 1 s (absolute)
```

`SimPath` attributes include `Count`, `Conc`, `Amount`, `Clamped`, `K`, `Active`,
`Vol`, `Area`, `Dcst`, `V` (potential), `I` (current). Selector/group helpers:
`ALL()`, `LIST(...)`, `MATCH(regex)`, `SUM(...)`, `TET/TETS`, `TRI/TRIS`, `VERT/VERTS`.

## Recording (ResultSelector)

```python
rs = ResultSelector(sim)
caConc   = rs.cyt.Ca.Conc                       # one value
allCounts= rs.cyt.ALL(Species).Count            # every species in cyt
twoSpec  = rs.cyt.LIST(Ca, IP3).Count           # selected species
patchCnt = rs.TRIS(capTris).Open.Count          # per-triangle
total    = rs.SUM(rs.MATCH('AZ.*').Prim.Count)  # summed over matching regions
sim.toSave(caConc, allCounts, dt=0.01)          # register BEFORE running (regular dt)
# ... run ...
caConc.data[runIdx, timeIdx, colIdx]            # numpy array
caConc.time[runIdx]                             # matching time points
caConc.labels                                   # column names
```

Save to file (auto-closed), with run metadata, then reload:
```python
with HDF5Handler('results') as hdf:
    sim.toDB(hdf, 'run_group', cond=value)
    for i in range(NRUNS):
        sim.newRun(); sim.run(ENDT)
# later:
with HDF5Handler('results') as hdf:
    sel, = hdf.get(cond=value).results
    plt.plot(sel.time[0], sel.data[0])
```

## Membrane potential (EField) — key classes

For voltage-clamp / channel models add to the model: `Channel` (a Species that is a
channel with conductance states), `OhmicCurr(channelState, g, erev)`,
`GHKCurr(...)`, and in geometry a `Membrane.Create([patches], capacitance=...)`.
Enable EField in the solver (`Simulation('Tetexact', ..., calcMembPot=True)` /
`'TetOpSplit'`). Set/read with `sim.memb.Pot`, `sim.patch.chan[state].Count`,
`sim.VERT(v).V`. See manual `API_2/STEPS_Tutorial_Efield.html`.

## Multi-state complexes — key classes

`Complex.Create(subunits, statesMatrix)` models proteins with internal states; declare
state-dependent reactions with complex selectors (`C[S1A, :, :] + Ca <r[1]> C[S1B, ...]`).
See `API_2/STEPS_Tutorial_Complexes.html`. Use when a species has combinatorial
internal states (phosphorylation, CaMKII subunits) instead of enumerating species.

## Parallel (MPI)

`from steps.sim import MPI`; solver `'TetOpSplit'` with a partitioned mesh
(`LinearMeshPartition`/`MetisPartition`). Guard rank-0-only output with
`if MPI.rank == 0:`. Launch with `mpirun -n N python script.py`. See
`API_2/STEPS_Tutorial_MPI.html` and `STEPS_Tutorial_Distributed.html`.

## Meshes from a meshing pipeline (Gmsh `$PhysicalNames`)

Meshes named via Gmsh `$PhysicalNames` expose groups under **both** an integer tag
and the name string: `sim`/`mesh.tetGroups[(0, 'cytosol')]`, `mesh.triGroups[(0,
'cytosol_surface')]`. Two gotchas:

- **Each compartment interface facet must be ONE triangle element.** Some mesh
  generators tag every compartment's full boundary, emitting a nested organelle's
  interface twice (container tag + organelle tag). STEPS loads both for one tet face,
  overflowing the tet's 4 face-slots → `Assertion Fail: i < 4` at solver setup.
  Group *loading* tolerates duplicates; the *solver* does not. Dedup so each facet has
  one element (keep the organelle copy; the container surface becomes the outer
  membrane only).
- **Sub-regions baked as separate named groups must not duplicate triangles.** If a
  region (e.g. an active zone) is carved out of a membrane as its own named group, the
  triangles must be **moved** (re-tagged), not copied. Reconstruct the full membrane
  patch as the union: `tris = mesh.triGroups[(0,'memb')]; for n in subNames: tris |=
  mesh.triGroups[(0, n)]`.

## Common errors → fixes

| Symptom | Cause | Fix |
|---|---|---|
| `does not match the expected format for automatic assignment` | `.Create()` not on its own `name = ...` line (loop/`-c`/multiline) | constructor with `name=`: `ROI(tris, name=n)` |
| `Cannot call an element 'X', this name is reserved` | reserved Species/object name | descriptive multi-letter name |
| `Assertion Fail: i < 4` (Tetexact setup) | duplicate triangle elements per facet | dedup interface tris (above) |
| `Outer compartment not defined for this patch` | `.o` species on a `outer=None` patch | only `.i`/`.s` on a boundary patch, or give it an outer comp |
| counts stay 0 | rate too low / wrong units (`Conc` is molar) / no reactant at surface | raise `K`/`Count`; check SI + molar |
| mixing APIs (validator warns — unsafe) | API_1 and API_2 in one script; `steps.interface` switches `steps.*` to API_2, so API_1 solver/methods then fail | update fully to API_2; a pure API_1 script is fine, just legacy |
| aggregation reads only the last element (silent) | comprehension's first iterable uses a name bound by a later `for` (`(t for t in m.tets for m in mitos)`) | reorder: `for m in mitos for t in m.tets` |
| boundary tris/tets selection comes out empty/wrong | exact float `==`/`in` on geometry (`tri.center.y in [bbox.max.y]`) never matches | tolerance `abs(a-b) < eps` or half-space `tri.center.y >= z0` |
| geometry setup is O(n²) / a list is recomputed | a `for x in seq:` whose body ignores `x` and rebuilds a comprehension over `seq` | drop the stray loop; compute the comprehension once |
| pulse train behaves as a constant input (no gaps) | pulse duration ≥ inter-pulse interval (1/freq) — fixed-width pulses reused at higher frequency overlap | ensure `duration < 1/freq` per frequency; narrow the pulse at high freq (e.g. 80 ms @ 10 Hz vs 200 ms) |
| a reaction silently never fires | no rate set — API_2 `r['k']` with no `.K`, or API_1 `smodel.Reac(...)` with no `.kcst` (incl. the `Reac1 = 8` clobber typo writing the var instead of `Reac1.kcst = 8`); rate defaults to 0 | set the rate (`.K` / `.kcst`), or a dynamic `set*ReacK('name', ...)`; the linter flags this for **both** APIs |
| concentration / diffusion off by 10³–10⁹ | wrong units — Conc is molar (`150e-6`, not `150`), Diff/dcst is m²/s (`2e-10`, not `2e2` µm²/s); applies to API_2 (`.Conc`, `Diffusion`) **and** API_1 (`set*Conc`, `smodel.Diff(... dcst)`) | the linter flags both dialects; reserved single-cap names, though, are an API_2-only collision (`sim.comp.A` vs `Area`) — fine in API_1's string keys |

## API_1 → API_2 conversion

When the modeler asks to convert a legacy API_1 script (see SKILL.md → "API_1 input"),
rewrite into a new `*_api2.py` file with a `# Converted to STEPS API_2 from: <orig>`
header. The structural map:

| API_1 | API_2 |
|---|---|
| `import steps.model as smodel` etc. (aliased) | `import steps.interface` then `from steps.<mod> import *` (interface first) |
| `mdl = smodel.Model()` | `mdl = Model()` + `with mdl:` for everything inside |
| `S = smodel.Spec('Ca', mdl)` | `Ca = Species.Create()` (var name *is* the name) |
| `vsys = smodel.Volsys('v', mdl)` | `vsys = VolumeSystem.Create()` |
| `smodel.Reac('r', vsys, lhs=[A], rhs=[B], kcst=k)` | inside `with vsys:` → `A >r['r']> B` then `r['r'].K = k` |
| `smodel.SReac(...)` (ilhs/olhs/slhs) | surface reaction with `.i`/`.o`/`.s` tags inside `with ssys:` |
| `smodel.Diff('d', vsys, S, dcst=D)` | inside `with vsys:` → `Diffusion(S, D)` |
| `sgeom.Comp('cyt', geom, vol=V)` / mesh `TmComp` | `Compartment.Create(tets, vsys)` inside `with mesh/geom:` |
| `sgeom.TmPatch('m', mesh, tris, icomp, ocomp)` | `Patch.Create(tris, inner, outer, ssys)` (inner first) |
| `steps.geom.Tetmesh` / `meshio` load | `TetMesh.LoadGmsh(path, scale=...)` |
| `solv = ssolver.Tetexact(mdl, mesh, rng)` | `sim = Simulation('Tetexact', mdl, mesh, rng)` |
| `solv.reset()` | `sim.newRun()` |
| `solv.setCompConc('cyt', 'Ca', c)` | `sim.cyt.Ca.Conc = c` |
| `solv.setPatchCount('m', 'P', n)` | `sim.m.P.Count = n` |
| `solv.getCompConc('cyt', 'Ca')` | `sim.cyt.Ca.Conc` |
| `solv.run(t)` | `sim.run(t)` |
| manual `numpy` result arrays + `getCompConc` in a loop | `rs = ResultSelector(sim)`; `sim.toSave(rs.cyt.Ca.Conc, dt=...)` before running |

Names in API_2 come from the **left-hand variable** (rule 2), so the API_1 string name
and the variable should match (`Ca = Species.Create()` → addressed as `sim.cyt.Ca`).
After converting, run the validator on the new file.

## Literature units → STEPS (SI + molar)

When comparing a model to a paper (`--params` dump + SKILL.md → "Validate against the
literature"), papers rarely use STEPS units. Convert before judging a mismatch:

| Quantity | Paper often uses | STEPS wants | Multiply by |
|---|---|---|---|
| 2nd-order rate (kon) | µM⁻¹·s⁻¹ | M⁻¹·s⁻¹ | ×1e6 |
| 2nd-order rate (kon) | nM⁻¹·s⁻¹ | M⁻¹·s⁻¹ | ×1e9 |
| 1st-order rate (koff, kcat) | ms⁻¹ | s⁻¹ | ×1e3 |
| 1st-order rate | min⁻¹ | s⁻¹ | ÷60 |
| concentration | µM / nM | M (`Conc`) | ×1e-6 / ×1e-9 |
| diffusion constant | µm²/s | m²/s | ×1e-12 |
| voltage (in custom rate fns) | mV | V | ×1e-3 |
| length | µm / nm | m | ×1e-6 / ×1e-9 |

Quick sanity: a diffusion-limited kon is ~1e8–1e9 M⁻¹·s⁻¹; cytosolic D ≈ 1e-13–1e-9 m²/s
(small ion ~2e-10, protein ~1e-11). Anything far outside is a unit error, not biology.

## Reusability smells (SKILL.md → "Reusability review")

Signals that a model is calibrated to one operating point, not mechanistic — so it
reproduces its figure but breaks on reuse. All are **intrinsic** (read from the script
alone, no reference model needed) and the validator flags the first three as advisories:

| Smell | What it means for reuse | Validator flag |
|---|---|---|
| `Clamped = True` species | infinite reservoir → results tied to this volume / copy-number | yes |
| `k_eff = kcat/Km` rate | valid only if [S] ≪ Km; compute [S]/Km from the script's own counts ÷ volume vs Km | yes |
| param comment tying it to an output ("reproduces the paper's ~56 %") | calibrated, not derived → bounds the reuse envelope | yes |
| init by `.Count` (not `.Conc`) | counts are geometry-specific → won't rescale to another mesh/volume | review only |
| zones-as-species + diffusion-as-first-order-reaction | well-mixed standing in for spatial → can't be spatialised as-is | review only |
| compensating errors (several approximations cancel only at the fit point) | model right for the wrong reasons | probe: run one off-calibration point |

Reuse axes to score: re-run published scenario · perturbation/knockout · rescale
(copy-number, volume) · spatialise (well-mixed→mesh) · couple upstream · per-component
quantitative claim. Advisory tier — report the calibration envelope, don't fail the run.
