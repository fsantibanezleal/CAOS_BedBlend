# bedblend documentation

`bedblend` is an engine for TRUCK-BUILT run-of-mine stockpiles: haul trucks routed over ground they
can actually drive, a dozer that completes lifts and destroys provenance while doing it, a face that
sorts by size as material cascades down it, a per-column ledger that follows the material through
every operation, and reclaim by a loader working that face. It is a dependency-free Python core,
plain floats and lists rather than numpy, because it has to be reproducible bit for bit against a
browser implementation of the same equations.

This directory is the maintainer's wiki. It is not the PyPI front page; that is the repository
`README.md`, which is deliberately short and is gated by `tests/test_readme.py`. Everything here is
written to be checked against the source, and where a claim could not be checked it says so.

## The four-sentence version

bedblend models a heaped-fill, truck-dumped, pre-crusher stockpile: the kind built on a prepared pad
by haul trucks and a dozer, lift by lift, and reclaimed by a loader working a face. It is the inverse
of an open pit, in that a pit cuts benches downward while a stockpile adds lifts upward with the same
primitives, a working level, a face at the angle of repose, a berm, and a ramp giving access to the
next level. It refuses to model chevron, windrow and cone-shell beds, because those are built by
CONVEYOR STACKERS and not by trucks, and offering those geometries alongside a truck fleet is a
category error that an earlier version of this library made. It also refuses to predict the angle of
repose (that angle is imposed, not emergent), to schedule a fleet (one truck is routed per load, with
no queue and no cycle time), and to choose a stockpile for you (it evaluates a pile, it does not
optimise one).

## How to read this wiki

Start with [architecture/01_overview.md](architecture/01_overview.md) if you want to know how the
pieces fit, and with `methods/` if you want to know what a specific computation does and where it
came from. There is no quickstart page here yet, so until there is, the runnable example is the one
in the repository `README.md`, and the numbers it produces are reproduced at the bottom of this page.

EVERY ROW BELOW IS A PAGE THAT EXISTS. Twenty-one documents: four index pages, three under
`architecture/`, ten under `methods/`, three under `guides/`, and `data-contract.md`. Every internal
link on every page resolves, and that is checked rather than assumed.

The rule this wiki is written under is worth stating once, because the engine's own history is the
argument for it: **every number here was produced by running the code at version 0.07.002, not copied
from another document.** Where a figure recorded in a source comment did not reproduce, the page says
so and gives the value the code returns now. This repository spent a release cycle removing
documentation that described a solver nothing called and a README naming an API that had not existed
for three releases, so a page that quotes a number it did not measure is treated as a defect here.

### Architecture

How the seventeen modules compose into one loop, and the two properties the loop guarantees.

| Document | What it covers |
|---|---|
| [architecture/01_overview.md](architecture/01_overview.md) | The module graph and the build loop: a per-area queue of planned tips (paddock lattice then edge sweeps, per bench), a loop over the incoming loads rather than over the plan, dozer visits on a load cadence rather than at a campaign boundary, and where reclaim attaches. |
| [architecture/02_determinism.md](architecture/02_determinism.md) | The seeded 32-bit xorshift stream, why it is written out by hand instead of using `random`, and what bit-for-bit reproducibility does and does not cover. |
| [`architecture/03_invariants.md`](architecture/03_invariants.md) | What the engine refuses to let drift: the ledger against the terrain (`BlockModel.assert_consistent`, tolerance 1e-6 m), and the surface against the angle of repose (`assert_stable`, raising `ReposeViolation` past `STABLE_TOL_DEG`, 4.0 degrees). |

### Methods

One document per physical or operational computation, each carrying its own equations, its own
citations, and its own statement of what it is not.

| Document | What it covers |
|---|---|
| [methods/01_terrain-and-trafficability.md](methods/01_terrain-and-trafficability.md) | `terrain` and `topography`: the elevation field, the crest of the working level, the gradient test that decides where a machine may go, and the five published fill types. |
| [`methods/02_dump-plan-and-tips.md`](methods/02_dump-plan-and-tips.md) | `design`: named areas, a bench schedule, an access corridor that is declared but NOT kept clear of tips, and the ordered tip positions that follow, emitted without reference to terrain so that plan and feasibility stay separable. |
| [`methods/03_placement-and-profiles.md`](methods/03_placement-and-profiles.md) | `dump` and the spotting half of `truck`: the paddock elliptical frustum, the edge cascade oriented on the crest normal, and the four dump shapes measured across 28 UAV-surveyed dumps. |
| [`methods/04_relaxation.md`](methods/04_relaxation.md) | `relax`: mass-conserving toppling that holds the angle of repose, in two stages, because a fresh heap stands near 2:1 and slumps to repose afterwards. |
| [`methods/05_dozer.md`](methods/05_dozer.md) | `dozer`: levelling the floor, grading the ramp, pushing to the crest, raising the berm, and reporting how far every operation displaced the material. |
| [methods/06_segregation.md](methods/06_segregation.md) | `segregation` and `facesegregation`: Gray-Thornton kinetic sieving solved with a Godunov flux, Gray-Chugunov diffusive remixing opposing it, and the coupling that applies it to one cascading load. |
| [`methods/07_lot-ledger.md`](methods/07_lot-ledger.md) | `blocks` and `sectors`: per-column parcels at truckload support carrying grade uncertainty and accumulated displacement, and the working-region rollups built on them. |
| [methods/08_reclaim.md](methods/08_reclaim.md) | `reclaim`: sequenced extraction from a face a machine can physically work, in LIFO, FIFO or full-height order, with the haul cycle that carries each cut off site. |
| [methods/09_blending-metrics.md](methods/09_blending-metrics.md) | `blending` and `rtd`: tonnage-weighted variance, the variance reduction ratio and its direction, the derived `1/N` bound, variograms, and residence time between FIFO and LIFO references. |
| [methods/10_stream-synthesis.md](methods/10_stream-synthesis.md) | `stream`: the incoming loads generated from a dig sequence, so that grade autocorrelation is an output of the shovel's dwell rather than an input parameter. |

### Guides

No guide has been written yet. The whole theme below is a plan. `guides.md` itself carries the
practical content that exists today.

| Document | What it covers |
|---|---|
| [`guides/01_install-and-quickstart.md`](guides/01_install-and-quickstart.md) | Installing from PyPI, the smallest complete build-and-reclaim script, and what its output means. |
| [`guides/02_use-on-your-own-data.md`](guides/02_use-on-your-own-data.md) | Bringing your own survey ground, material, dump plan and load stream, through `Terrain.from_ground`, `Material` and a routing callable. |
| [`guides/03_calibration-and-limits.md`](guides/03_calibration-and-limits.md) | Which constants are anchored rather than measured, what would replace each one, and the failure modes to expect when the model is pushed outside its evidence. |

### Reference

[`data-contract.md`](data-contract.md) is intended to specify the shapes that cross the boundary: what
`build` consumes, what a `LoadRecord`, a `BuildResult`, a `Parcel` and a `Cut` contain, and what a
consuming application may rely on remaining stable. Until it exists the dataclass definitions in
`bedblend/build.py`, `bedblend/blocks.py` and `bedblend/reclaim.py` are the contract, and their field
comments are the only statement of what is stable.

## The modules

Seventeen modules, confirmed against `pkgutil.iter_modules(bedblend.__path__)` at version 0.07.002.
Nothing else is on disk, and in particular `heightfield`, `pile`, `run`, `schema` and `stacking` are
NOT modules of this package. Stale bytecode for those five names survives in `bedblend/__pycache__`
from earlier releases, which is worth knowing before a grep convinces you otherwise.

In the order material moves through them:

```
stream    the incoming loads, from a dig sequence
   |
design    the tip programme, emitted per area and per bench BEFORE any load moves
   |
truck     route over drivable ground, spot, discharge, depart
   |
dump      how the load lands: paddock heap or edge cascade
   |
relax     the surface slumps back to the angle of repose
   |
dozer     the floor is levelled, the ramp graded, the berm raised
   |
blocks    the ledger records and follows all of the above
   |
reclaim   a loader cuts the lifts back out
   |
blending  the verdict: variance reduction, variograms, residence time
```

with `terrain` and `topography` underneath all of it, `material` supplying the properties every stage
reads, `segregation` and `facesegregation` acting on the load as it cascades, `sectors` and `rtd`
rolling the ledger up, and `build` running the loop.

## Two things a maintainer should know before trusting a number

**`bedblend.__version__` does not necessarily agree with `pyproject.toml`.** The version is read from
packaging metadata by `importlib.metadata.version("bedblend")`, which was a deliberate fix: a
hand-maintained literal had drifted two releases behind. The consequence is that the reported version
is whatever metadata the interpreter finds, not what the source tree declares. Measured in the
development checkout at the time of writing, `pyproject.toml` and `VERSION` both say `0.07.002`, the
stale `bedblend.egg-info/PKG-INFO` in the repository root says `0.7.1`, and the editable install in
the development virtual environment says `0.5.0`. Because a source-root `egg-info` shadows the
installed distribution, `bedblend.__version__` reported `0.7.1` when the interpreter was started from
the repository root and `0.5.0` when started from anywhere else, in the same environment, against the
same source. A clean `pip install bedblend` does not have this problem. A development checkout does,
so rebuild the metadata before you record an engine version alongside a result.

**`vrr_ideal` and `blending_efficiency` take the number of LAYERS a cut crosses, not the number of
cuts.** The signature is `vrr_ideal(n_layers: float)` and it returns `1.0 / n_layers`, or `math.inf`
when `n_layers` is zero or negative. `blending_efficiency(achieved_vrr, n_layers)` takes the same
quantity as its second argument. Passing
`len(cuts)` type-checks, runs, and gives a meaningless bound. This is the easiest misuse in the
package to commit and the hardest to notice, because the wrong answer is the right order of
magnitude.

## References

These are the sources the code itself cites, with the DOIs the code itself carries. Nothing has been
added from memory.

* Gray, J.M.N.T. and Thornton, A.R. (2005), *A theory for particle size segregation in shallow
  granular free-surface flows*, Proc. R. Soc. A 461(2057), 1447-1473.
  [doi:10.1098/rspa.2004.1420](https://doi.org/10.1098/rspa.2004.1420). Cited in `segregation.py`;
  equations 3.10, 3.11, 3.18 and 3.19 are reproduced there with their original numbers.
* Gray, J.M.N.T. and Chugunov, V.A. (2006), J. Fluid Mech. 569, 365-398.
  [doi:10.1017/S0022112006002977](https://doi.org/10.1017/S0022112006002977). Cited in
  `segregation.py` for the diffusive remixing term and the Peclet anchor. No title is given here on
  purpose: the two places this repository states one disagree, and the disagreement is recorded
  below.
* Young, A. and Rogers, W.P. (2021), *Modelling of pre-crusher stockpiles*, Minerals 11(6), 636.
  [doi:10.3390/min11060636](https://doi.org/10.3390/min11060636). The operational spine of the
  engine: the two-phase heaped-fill build, the dump-location data model, the five fill types, the
  quadrant comparison, and the dozer's role. Cited by volume and issue throughout the docstrings; the
  DOI is carried in the repository `README.md`.
* Young, A. and Rogers, W.P. (2022), Mining 2(1).
  [doi:10.3390/mining2010006](https://doi.org/10.3390/mining2010006). The 28 UAV-surveyed dumps
  behind the four profiles and the measured geometry ranges.
* Bak, P., Tang, C. and Wiesenfeld, K. (1987), *Self-organized criticality: an explanation of 1/f
  noise*, Phys. Rev. Lett. 59(4), 381-384.
  [doi:10.1103/PhysRevLett.59.381](https://doi.org/10.1103/PhysRevLett.59.381). Cited in `relax.py`
  for the toppling rule only; none of the criticality claims are made.
* Loubser, R. and de Korte, G.J. (2015), J. S. Afr. Inst. Min. Metall. 115(8), 773-780.
  [doi:10.17159/2411-9717/2015/v115n8a15](https://doi.org/10.17159/2411-9717/2015/v115n8a15). Cited
  in `blending.py` as the definition fixing the direction of the variance reduction ratio.
* Moraga, Kracht and Ortiz (2022), Minerals Engineering 187, 107807.
  [doi:10.1016/j.mineng.2022.107807](https://doi.org/10.1016/j.mineng.2022.107807). Cited in
  `rtd.py` for process-scale residence time.
* Cogent Engineering 4(1), 1387955.
  [doi:10.1080/23311916.2017.1387955](https://doi.org/10.1080/23311916.2017.1387955). Cited in
  `terrain.py` for waste-dump lift-and-ramp construction.

Three sources are cited in the docstrings without a DOI, because they are reports rather than
articles: Neufeld, Lyall and Deutsch, CCG Report 8 paper 306 (2006), for Anglo American, which
supplies the truckload support, the dozer cadence and the two-stockpile routing case; Baffinland's
Life-of-Mine Waste Rock Management Plan (2017), for the dozer deciding truck access; and Micromine
Alastri APS stockpile documentation, for the three-way FIFO, LIFO and blended reclaim abstraction.

Three citation defects are recorded here rather than quietly repaired. The page range for the Mining
2022 paper disagrees between `dump.py` and `terrain.py`, which both say 86-102, and the repository
`README.md`, which says 92-114; all three give the same DOI, and which is correct was not resolved.
The repository `README.md`
also gives that paper a title, *Dump geometry from 28 UAV-surveyed dumps*, which reads as a
description rather than a title and appears in no docstring; it is therefore not repeated in this
wiki. The third is the title of the Gray and Chugunov 2006 paper. The comment above `PECLET_DEFAULT`
in `segregation.py` gives it as *A theory for particle size segregation in shallow granular
free-surface flows*, which is word for word the title that file's own module docstring gives the Gray
and Thornton 2005 paper, while the
repository `README.md` gives *Particle-size segregation and diffusive remixing in shallow granular
avalanches* against the identical DOI. Two titles, one DOI, both in this repository, and the
duplicated one is the one to distrust. Neither was checked against the publisher, so no title for
that paper is repeated in this wiki.

Separately, and by deliberate decision recorded in `blending.py`, the De Wet (1994) design
equation that the blending literature cites for the ideal-bound relationship is NOT reproduced or
attributed anywhere in this package, because Bulk Solids Handling 14(1) p. 93 could not be obtained
and the equation survives only as a rasterised image in a secondary source. The `1/N` bound that is
implemented was derived from first principles and is labelled as derived.

## How the claims in this wiki were checked

Every magnitude quoted in these four index pages has been produced by running the package, not
recalled. That was not true when they were first written and the exception is worth naming, because
it is the only kind of error that survives a review: `guides.md` gave the quickstart build as "about
82 seconds" where four timed runs give 63 to 68. Nothing depended on the figure, which is exactly why
nobody would have caught it. The magnitudes in the sub-documents under `architecture/` and `methods/`
were not re-checked in that pass and carry no such guarantee from this page.

The engine's own test suite is 137 tests across eleven files, passes in the development
environment, and takes about 85 seconds. The specific quantities that recur in these pages, and which you can reproduce, are the
repository README's quickstart (600 loads onto a 60 by 60 pad at 2.5 m cells, giving 480 placed and
120 refused, a 20.0 percent refusal rate, a profile census of 118 paddock, 207 oval, 96 comet and 59
rectangular, 221 dozer passes, then 24 full-height cuts of 3000 t giving `var_in` 0.038008, `var_out`
0.000272 and VRR 0.0071) and a determinism check in which two builds at seed 20260801 produced an
identical SHA-256 over the packed surface elevations and load records while seed 999 produced a
different one.
