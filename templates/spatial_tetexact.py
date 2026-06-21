#!/usr/bin/env python3
"""Spatial STEPS model in API_2 style: a tetrahedral-mesh simulation with a
compartment, a membrane patch, volume diffusion and a surface pump, recorded with a
ResultSelector. This is a TEMPLATE — point it at your own mesh:

    python spatial_tetexact.py mesh.msh   cytosol  ER  ER_surface

Args: mesh path, then the $PhysicalNames group names for the outer compartment, the
inner compartment, and the interface surface. Adapt the model to your kinetics.
"""
import sys

import steps.interface
from steps.model import *
from steps.geom import *
from steps.rng import *
from steps.sim import *
from steps.saving import *

meshPath, cytName, erName, membName = (
    sys.argv[1:5] if len(sys.argv) >= 5 else
    ('mesh.msh', 'cytosol', 'ER', 'ER_surface'))

# --- model ---------------------------------------------------------------
mdl = Model()
r = ReactionManager()
with mdl:
    Ca, Pump = Species.Create()
    vsys = VolumeSystem.Create()
    with vsys:
        Diffusion(Ca, 1e-12)                     # m^2/s
    ssys = SurfaceSystem.Create()
    with ssys:
        # pump Ca from the inner compartment to the outer one across the membrane
        Ca.i + Pump.s >r['pump']> Ca.o + Pump.s
        r['pump'].K = 2e8

# --- geometry ------------------------------------------------------------
mesh = TetMesh.LoadGmsh(meshPath, scale=1e-9)     # mesh coords nm -> metres
with mesh:
    cyt = Compartment.Create(mesh.tetGroups[(0, cytName)], vsys)
    er  = Compartment.Create(mesh.tetGroups[(0, erName)], vsys)
    memb = Patch.Create(mesh.triGroups[(0, membName)], er, cyt, ssys)  # inner=er

# --- simulation ----------------------------------------------------------
rng = RNG('mt19937', 512, 1234)
sim = Simulation('Tetexact', mdl, mesh, rng)

rs = ResultSelector(sim)
caCyt = rs.cyt.Ca.Count
caER  = rs.er.Ca.Count
sim.toSave(caCyt, caER, dt=0.01)

sim.newRun()
sim.er.Ca.Conc = 150e-6                # molar, inside the ER
sim.memb.Pump.Count = 1000             # pumps on the membrane
sim.run(0.1)

print(f'after {caCyt.time[0, -1]:.3g} s: Ca in {cytName}={caCyt.data[0, -1, 0]:.0f}, '
      f'Ca in {erName}={caER.data[0, -1, 0]:.0f}')
