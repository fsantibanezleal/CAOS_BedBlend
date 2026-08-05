# bedblend

[![CI](https://img.shields.io/github/actions/workflow/status/fsantibanezleal/CAOS_BedBlend/ci.yml?branch=main&label=CI)](https://github.com/fsantibanezleal/CAOS_BedBlend/actions)
[![License](https://img.shields.io/github/license/fsantibanezleal/CAOS_BedBlend)](LICENSE)
[![Version](https://img.shields.io/github/v/tag/fsantibanezleal/CAOS_BedBlend?label=version&sort=semver)](https://github.com/fsantibanezleal/CAOS_BedBlend/tags)

An engine for TRUCK-BUILT run-of-mine stockpiles: haul trucks, a dozer, a pile that constrains its own
construction, Gray-Thornton kinetic size segregation down the dumped face, a per-cell lot ledger with
provenance, and reclaim by a loader working a face.

```bash
pip install bedblend
```

## What it models, and what it deliberately does not

A heaped-fill, truck-dumped, pre-crusher stockpile: the kind built on a prepared pad by haul trucks
and a dozer, lift by lift, and reclaimed by a loader. **It is the inverse of an open pit.** A pit cuts
benches downward; a stockpile adds lifts upward, with the same primitives, a working level, a face at
the angle of repose, a berm, and a ramp to the next level. Reclaim inverts it again.

**It does not model chevron, windrow or cone-shell beds.** Those are built by CONVEYOR STACKERS. Of
the five pre-crusher stockpile types only blended-in-blended-out is a chevron, and the software that
builds those beds is written for conveyor systems (Young and Rogers, *Minerals* 2021, 11, 636,
figure 1). Trucks do not build a chevron bed, and offering those geometries alongside trucks is a
category error that an earlier version of this library made.

```python
import bedblend as bb

terrain = bb.Terrain.flat(60, 60, 2.5)
plan = bb.rectangular_yard(n_areas=1, area_width_m=90.0, area_length_m=90.0,
                           bench_height_m=6.0, n_benches=2, margin_m=30.0)
fleet = bb.Fleet.of(4, bb.TruckSpec(), (15.0, 75.0), repose_deg=37.0)
loads = bb.payloads_from(bb.dig_sequence(n_loads=600, seed=7), seed=7)

built = bb.build(terrain, plan, fleet, loads, repose_deg=37.0, seed=20260801)
print(f"{len(built.placed)} placed, {built.refusal_rate:.1%} refused")

face = bb.ReclaimFace(method=bb.ReclaimMethod.FULL_HEIGHT, position_m=30.0,
                      depth_m=10.0, width_m=90.0, loader=bb.LoaderSpec())
cuts = bb.campaign(built.terrain, built.model, face,
                   cut_tonnes=3000.0, n_cuts=24, repose_deg=37.0)

var_in = bb.tonnage_weighted_variance([l.grade for l in loads], [l.tonnes for l in loads])
var_out = bb.tonnage_weighted_variance([c.grade for c in cuts], [c.tonnes for c in cuts])
print(f"{len(cuts)} cuts, VRR {bb.vrr(var_in, var_out):.3f}")
```


The ratio is variance OUT over variance IN, on a tonnage base, so **lower is better** and `1.0` means
the pile did nothing. Report it against the `1/N` bound: the gap between them is what the pile fails
to recover, and it is driven by the autocorrelation of the incoming stream. Layers only average if
they are independent.

## What is in it

| Module | What it computes |
|---|---|
| `terrain` | The ground, plus the two fields that constrain every machine: the crest of the working level, and trafficability. |
| `design` | The dump plan: named areas, a bench schedule, a reserved access ramp, and the tip positions that follow. |
| `stream` | The incoming loads, generated from a DIG SEQUENCE. Grade autocorrelation is an output of the shovel's dwell, not an input parameter. |
| `truck` | Machines with A\* routes over drivable ground, spotting, and retained approach and departure paths. |
| `dump` | The two placement regimes: a paddock heap sized by the truck, and an edge dump cascading down the face in one of four profiles measured across 28 UAV-surveyed dumps. |
| `relax` | Mass-conserving relaxation that HOLDS the angle of repose, in two stages, because a fresh heap stands near 2:1 and slumps afterwards. |
| `dozer` | Levels the floor, pushes material over the face, raises berms, and reports how far it displaced everything. |
| `segregation` | Gray-Thornton kinetic sieving, `dphi/dx + d/dz[-Sr phi(1-phi)] = 0`, with a Godunov flux so the concentration shocks survive, plus Gray-Chugunov diffusive remixing. `Sr = 0` degenerates to a passive tracer exactly, which is the negative control. |
| `facesegregation` | The coupling: what one cascading load does to the size split down a real face taken from the terrain. |
| `material` | The density chain, moisture-dependent repose, and the two-species size split. |
| `blocks` | The raw ledger at truckload support, carrying grade uncertainty and displacement. |
| `reclaim` | Sequenced extraction by a machine with a reach, in LIFO, FIFO or full-height order, with the haul cycle that carries each cut off site. |
| `build` | The loop that makes the above a system. |
| `blending` | Tonnage-weighted variance, VRR, the `1/N` bound, mixing effect, experimental variograms with a spherical fit. |
| `sectors`, `rtd`, `topography` | Working-region rollups, residence time, and the ground the pad is cut into. |

## What it does NOT claim

* **The angle of repose is imposed, not emergent.** A continuum height-field model, not DEM. It
  reproduces the geometry a given repose angle produces; it does not predict that angle from particle
  properties.
* **Two segregation coefficients are anchored, not measured.** `PERCOLATION_COEFFICIENT` and
  `PECLET_DEFAULT` are taken from the literature rather than fitted to a material. The size
  distribution down the face is SOLVED from the conservation law; where the mass lands and how much
  overruns the toe remain published operational observations, and neither touches the size split.
* **Trajectory segregation is not modelled.** Only kinetic sieving is. What rolls beyond the toe is
  reported as an overrun magnitude with a solver-derived composition.
* **No fleet scheduling.** One truck is routed per load and per cut; there is no queue, no cycle time
  and no spot time.
* **It is not a blending optimizer.** It evaluates a pile; it does not choose one.
* **It is not plant metal accounting.** It stops at the reclaimed stream.

## Determinism

A run is a pure function of `(parameters, seed)`. Everything stochastic comes from one 32-bit xorshift
written out explicitly rather than using `random` or numpy, so the same stream can be reproduced bit
for bit by an implementation in another language. That is what makes an in-browser mirror of this
engine checkable against it. The core is dependency-free for the same reason.

## References

* Gray, J.M.N.T. and Thornton, A.R. (2005), *A theory for particle size segregation in shallow granular
  free-surface flows*, Proc. R. Soc. A 461, 1447-1473. [doi:10.1098/rspa.2004.1420](https://doi.org/10.1098/rspa.2004.1420)
* Gray, J.M.N.T. and Chugunov, V.A. (2006), *Particle-size segregation and diffusive remixing in
  shallow granular avalanches*, J. Fluid Mech. 569, 365-398. [doi:10.1017/S0022112006002977](https://doi.org/10.1017/S0022112006002977)
* Young, A. and Rogers, W.P. (2021), *Modelling of pre-crusher stockpiles*, Minerals 11(6), 636.
  [doi:10.3390/min11060636](https://doi.org/10.3390/min11060636)
* Young, A. and Rogers, W.P. (2022), *Dump geometry from 28 UAV-surveyed dumps*, Mining 2(1), 92-114.
  [doi:10.3390/mining2010006](https://doi.org/10.3390/mining2010006)
* Bak, P., Tang, C. and Wiesenfeld, K. (1987), *Self-organized criticality: an explanation of 1/f noise*,
  Phys. Rev. Lett. 59, 381. [doi:10.1103/PhysRevLett.59.381](https://doi.org/10.1103/PhysRevLett.59.381)

## Licence

MIT. See [LICENSE](LICENSE).
