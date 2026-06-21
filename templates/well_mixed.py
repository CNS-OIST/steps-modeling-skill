#!/usr/bin/env python3
"""Well-mixed STEPS model in API_2 style: a reversible A + B <-> C in one
compartment, recorded with a ResultSelector. Runnable as-is (no mesh needed):

    python well_mixed.py

Prints the final counts and a few time points. Adapt the model/geometry blocks.
"""
import steps.interface
from steps.model import *
from steps.geom import *
from steps.rng import *
from steps.sim import *
from steps.saving import *

# --- model ---------------------------------------------------------------
mdl = Model()
r = ReactionManager()
with mdl:
    molA, molB, molC = Species.Create()
    vsys = VolumeSystem.Create()
    with vsys:
        molA + molB <r['bind']> molC
        r['bind'].K = 0.3e6, 0.7        # (kf [1/M/s], kb [1/s])

# --- geometry (well-mixed: just a volume) --------------------------------
geom = Geometry()
with geom:
    comp = Compartment.Create(vsys, 1.6667e-21)   # m^3

# --- simulation ----------------------------------------------------------
rng = RNG('mt19937', 256, 1234)
sim = Simulation('Wmdirect', mdl, geom, rng)

rs = ResultSelector(sim)
counts = rs.comp.LIST(molA, molB, molC).Count
sim.toSave(counts, dt=0.01)

sim.newRun()
sim.comp.molA.Conc = 31.4e-6           # molar
sim.comp.molB.Conc = 22.3e-6
sim.run(2.0)

print('species:', counts.labels)
print('t=0   :', counts.data[0, 0])
print('t=end :', counts.data[0, -1], 'at', counts.time[0, -1], 's')
