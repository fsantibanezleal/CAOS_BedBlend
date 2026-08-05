# Methods

This theme is one document per computation the engine performs: what it is, the equations behind it,
the published source it came from, what it explicitly does not claim, and which of its constants are
anchored to the literature rather than fitted to a material. These are the pages to read before
quoting a number out of this engine to anyone.

Two claims recur across the theme and are worth having in mind while reading it. The first is that
the angle of repose here is IMPOSED, not emergent: this is a continuum height-field model, not a DEM,
so it reproduces the geometry that a given repose angle produces and does not predict that angle from
particle properties. The second is that the size distribution down a dumped face is genuinely SOLVED
from a conservation law, while two neighbouring quantities are not. Where the mass lands down the
face, and how much of it overruns the toe, remain published operational observations, both labelled
as such in the source, and neither touches the size split.

## The two equations the theme is built around

Kinetic size segregation in the flowing layer, from Gray and Thornton (2005), reduced by plug flow
and a march in the downslope coordinate to a one-dimensional scalar conservation law in depth:

```
    dphi/dx + dF/dz = 0,        F(phi) = -Sr * phi * (1 - phi)

    phi  volume fraction of the SMALL species, 0 to 1
    x    downslope coordinate along the face, the marching direction
    z    depth through the flowing layer, no flux at the free surface or the base
    F    the segregation flux, convex, so a Godunov flux is exact at every interface
    Sr   the segregation number, the ratio of the mean segregation velocity to the
         typical normal bulk velocity. Sr = 0 degenerates to pure tracer advection,
         which is the engine's negative control and comes from this same solver
         rather than from a separate code path
```

And the verdict the whole engine exists to produce, from Loubser and de Korte (2015) following
Kumral (2006):

```
    VRR = var_out / var_in            LOWER IS BETTER

    var_in   tonnage-weighted variance of the grade of the incoming loads
    var_out  tonnage-weighted variance of the grade of the reclaimed cuts
    VRR = 1  the pile did nothing

    VRR_ideal = 1 / N      the independent-layer bound, DERIVED not cited,
                           where N is the number of layers ONE CUT CROSSES,
                           not the number of cuts
```

Both variances must be computed on the same base, that is over equal tonnages rather than equal
counts, which is why `tonnage_weighted_variance` is the only variance function in `blending.py`. The
reciprocal convention for VRR also circulates in secondary sources; building against it would invert
every number the engine produces, which is why `VRR_FORMULA_LABEL` exists and reads exactly
`VRR = var_out / var_in (lower is better)`.

## Documents

All ten are written. Each is transcribed from the module it names, with every magnitude reproduced by
running the code rather than recalled, and each says explicitly what its method is NOT and which of
its constants are anchored rather than measured.

| Document | What it covers |
|---|---|
| [methods/01_terrain-and-trafficability.md](methods/01_terrain-and-trafficability.md) | The elevation field over the pad, the original ground kept separately in `z0`, the crest of the current working level, the gradient test that decides where a machine may stand, and the five published fill types a stockpile is classified by. |
| [`methods/02_dump-plan-and-tips.md`](methods/02_dump-plan-and-tips.md) | Named areas, a bench schedule and a declared access corridor, and the ordered tip positions the two campaigns emit, produced without any reference to terrain so that what was planned stays distinguishable from what the pile allowed. |
| [`methods/03_placement-and-profiles.md`](methods/03_placement-and-profiles.md) | The two placement regimes, a paddock elliptical frustum sized by the truck and an edge cascade oriented on the crest normal, and the four dump shapes measured across 28 UAV-surveyed dumps with the geometry ranges that come with them. |
| [`methods/04_relaxation.md`](methods/04_relaxation.md) | Mass-conserving toppling that holds the angle of repose, the two-stage slope in which a heap is emplaced near 2:1 and slumps afterwards, and why the result is verified rather than assumed. |
| [`methods/05_dozer.md`](methods/05_dozer.md) | Levelling, ramp grading, pushing to the crest and berm building, the split between an access-only visit and a full one, and the displacement every pass reports because dozers mix material in intractable ways. |
| [methods/06_segregation.md](methods/06_segregation.md) | Gray-Thornton kinetic sieving with a Godunov flux, Gray-Chugunov diffusive remixing opposing it, the flux-limited and grain-limited regimes that scale in opposite directions with face angle, and the coupling that applies all of it to one cascading load. |
| [`methods/07_lot-ledger.md`](methods/07_lot-ledger.md) | Per-column parcels at truckload support rather than a fixed 3-D lattice, the grade uncertainty a load already carries before the truck moves, the displacement it accumulates afterwards, and the working-region rollups built on top. |
| [methods/08_reclaim.md](methods/08_reclaim.md) | Extraction from a face a machine can physically stand at and reach, in LIFO, FIFO or full-height order, the relaxation every cut must trigger, and the haul cycle that carries each cut off site. |
| [methods/09_blending-metrics.md](methods/09_blending-metrics.md) | Tonnage-weighted variance, the variance reduction ratio and the direction of its inequality, the derived `1/N` bound and the fraction of it real beds reach, experimental variograms with a spherical fit, and residence time placed between FIFO and LIFO references computed on the same event sequence. |
| [methods/10_stream-synthesis.md](methods/10_stream-synthesis.md) | The incoming loads generated from a dig sequence, so autocorrelation follows from how long a shovel dwells in one block, with `measured_range_t` reporting the range the generated stream actually has. |

## Which module is documented where

Seventeen modules, ten planned method documents, five of them written. The mapping is not one to one,
and this table is the honest version of it: the right-hand column says where a module is documented
TODAY, and "docstring only" means the plan has a page for it and nobody has written that page.

| Module | Documented in |
|---|---|
| `terrain`, `topography` | methods/01 |
| `design` | docstring only (methods/02 not written) |
| `dump` | docstring only (methods/03 not written) |
| `truck` | docstring only for spotting (methods/03 not written), architecture/01 for routing and refusal |
| `relax` | docstring only (methods/04 not written) |
| `dozer` | docstring only (methods/05 not written) |
| `segregation`, `facesegregation` | methods/06 |
| `blocks`, `sectors` | docstring only (methods/07 not written); `sectors` is also read for methods/09 |
| `reclaim` | methods/08 |
| `blending`, `rtd` | methods/09 |
| `stream` | methods/10 |
| `build` | architecture/01 |
| `material` | no dedicated document |

One correction belongs here rather than in the unwritten methods/02, because it is the kind of claim
that outlives the design it described. The access corridor is DECLARED but NOT RESERVED. `Area`
carries `access_xy`, `ramp_width_m` and an `on_ramp` test, so the corridor is a real object in the
plan, but `DumpPlan.paddock_tips` deliberately emits tips across the whole footprint including the
corridor, and `dozer.build_ramp` cuts the road back out of the fill on every dozer visit. The comment
in `paddock_tips` states it directly: the ramp is a cut maintained in the fill, not a void reserved
in it. An earlier design did reserve it, and the measured result recorded in `build_ramp` is why it
does not any more: the corridor stayed a trench with three-metre walls, the whole 1296-cell area came
out unreachable, and the pile stalled at 3.2 m. Anything in this wiki or in the package docstrings
that calls it a "reserved access ramp" is describing that abandoned design.

`material` is the gap in that table and it is named rather than papered over. It supplies the
properties every other stage reads, the density chain through swell and compaction, the
moisture-dependent repose angle, and the two-species size split that segregation acts on, and it is
covered in pieces by methods/06 and, once it is written, by methods/04, rather than in one place. Its
own docstring is the best single account of it today. The published bands it carries are real and sourced there:
`SWELL_HARD_ROCK` is `(0.3, 0.45)` and `COMPACTION_BAND` is `(0.05, 0.15)`, both fractions, and the
default `Material` is ROM ore at 2.7 t/m3 in situ, 0.38 swell, 37 degrees dry repose, 120 mm d50 and
a 0.35 coarse fraction.

## The anchored constants, in one place

Two coefficients in this theme are taken from the literature rather than fitted to a material, and
both are disclosed in the repository `README.md` under a test that fails if either the disclosure or
the constant disappears. `PERCOLATION_COEFFICIENT`, in `facesegregation.py`, is 0.30, the ratio of
the percolation velocity to the shear rate times the particle diameter; it is set so that the
segregation number for a reference dump lands inside the range of the source's own worked examples,
and a DEM run or a laboratory characterisation test is precisely what would replace it. Neither has
been run. `PECLET_DEFAULT`, in `segregation.py`, is 12.0, the ratio of sieving to remixing, held at
the middle of the order-ten range Gray and Chugunov report from chute experiments.

Two further numbers in the same modules are numerical rather than physical and should not be confused
with the above: `CFL` is 0.4 and `NZ_DEFAULT` is 32 depth cells. They control the solver, not the
material. Details, and what happens when each is pushed, are in methods/06 and
guides/03_calibration-and-limits.md.
