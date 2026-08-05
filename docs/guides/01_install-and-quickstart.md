# Install and quickstart

This guide gets `bedblend` installed and puts a complete build-and-reclaim run in front of you, with
every number in the output explained. Everything quoted below was run against the working tree at
version `0.07.002` on CPython 3.13.0, and the output blocks are verbatim.

## Install

```bash
pip install bedblend
```

The distribution name and the import name are the same. There is nothing to compile and nothing to
download beyond the wheel itself.

The published version at the time of writing is `0.7.2`, confirmed against the index with
`pip index versions bedblend`, which also lists `0.7.1, 0.7.0, 0.6.1, 0.6.0, 0.5.2, 0.5.1, 0.5.0,
0.4.1, 0.3.2, 0.3.1, 0.3.0, 0.2.0, 0.1.0`. Note the two spellings of the same release. This repository
writes versions in the house `X.XX.XXX` form, so `pyproject.toml` says `0.07.002` and `VERSION` says
`0.07.002`, while the packaging toolchain normalises the padding away and PyPI serves it as `0.7.2`.
They are the same artifact. If you pin, pin the normalised form, because that is what the resolver
matches.

For a source checkout:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
```

The suite is 137 tests and took 85.13 s on the machine these notes were written on. It is slow
because several tests run whole builds rather than mocking them, which is deliberate: the defects
this engine has actually shipped were couplings between modules, not arithmetic inside one.

## Supported Python

`pyproject.toml` declares `requires-python = ">=3.10"` and classifies 3.10, 3.11, 3.12 and 3.13.
`[tool.ruff] target-version = "py310"`, so the syntax floor is enforced by the linter as well as
declared in the metadata. The engine uses `X | None` unions, `match`-free plain control flow, and
`zip(..., strict=True)`, all of which are 3.10 features. Only 3.13.0 was exercised while writing this
guide; the other three are declared, not verified here.

## The core is dependency-free, and that is a design constraint

```toml
dependencies = []
[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.6", "build>=1.0"]
```

Checked rather than trusted: walking the AST of all eighteen files in `bedblend/`, the seventeen
modules plus the package `__init__`, gives exactly seven distinct top-level imports, `__future__`,
`collections`, `dataclasses`, `enum`, `heapq`, `importlib` and `math`, and `sys.stdlib_module_names`
confirms all seven are standard library. Walk the seventeen modules alone and you get six of them:
`importlib` appears only in `__init__.py`, in the version lookup below. There is no numpy anywhere in
the engine. Elevations are `list[float]`, the block ledger is a list of lists of dataclasses, and the
random stream is a hand-written 32-bit xorshift rather than `random` or `numpy.random`.

The reason is stated in `pyproject.toml` and repeated in the package docstring: the engine has to be
reproducible bit for bit against an implementation of the same equations in another language, and a
language's built-in generator is not a portable contract. A dependency-free core also installs in
seconds anywhere, which matters when the consumer is a CI job or a browser toolchain rather than a
workstation. The cost is real and is paid in wall-clock time; see the timing note at the end of this
guide.

## Confirming the install, and one gotcha worth knowing first

```python
>>> import bedblend as bb
>>> bb.__version__
'0.5.0'
```

That is not a typo, and it is worth understanding before you trust a logged version. `__version__` is
not a literal in the source. It is:

```python
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("bedblend")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
```

So it reports the version recorded in the INSTALLED distribution metadata, which for an editable
install is whatever `pyproject.toml` said at the moment `pip install -e` last ran. The checkout used
for this guide is at `0.07.002` on disk and its editable metadata still says `0.5.0`, because nobody
reinstalled after the version bump. `pip show bedblend` confirms it.

There is a second, nastier wrinkle in the same mechanism, and the interpreter session above was run
from OUTSIDE the checkout for exactly this reason. `importlib.metadata` scans `sys.path` in order, and
a source tree that has ever been built carries a `bedblend.egg-info/` directory with its own
`PKG-INFO`. Start Python with the repository root on the path, which is what happens if you simply
`cd` into the checkout and type `python`, and that `egg-info` is found before the installed
distribution. In this checkout it says `0.7.1`, left over from an earlier build, so the same import
reports `'0.7.1'` from the repository root and `'0.5.0'` from anywhere else, on the same interpreter
and the same package. Neither is `0.07.002`. Three metadata records for one working tree, and the
answer depends on your working directory.

This is still the right trade. The previous design was a hand-maintained literal, and it had drifted
two releases behind `pyproject.toml`: the module reported `0.05.002` while `0.06.001` was on PyPI, so
anything logging the engine version alongside a result recorded the wrong engine. Metadata can go
stale in a development tree; a literal goes stale everywhere. If you are logging engine versions from
a source checkout, reinstall after a version bump, delete stale `egg-info` and `build` directories, or
read `VERSION` directly, which is the only file in the tree that cannot disagree with itself.

For a normal `pip install bedblend`, `bb.__version__` and the installed wheel always agree.

## The worked example

A 150 m square pad, one 90 m dump area with two 6 m benches, four haul trucks, 600 loads from a dig
schedule, then twenty-four full-height reclaim cuts and the blending verdict. Save this as
`quickstart.py`.

### 1. The ground

```python
import math
import bedblend as bb

terrain = bb.Terrain.flat(60, 60, 2.5)
```

`Terrain` is an elevation field over a regular pad. `flat(nx, ny, cell_m)` gives a 60 by 60 grid of
2.5 m cells, which is 150 m by 150 m, with both the live surface `z` and the original ground `z0` set
to zero. Keeping `z0` is what lets the engine answer "how much material is here" separately from "how
high is the surface", and those two answers diverge the moment the ground is not flat. Real survey
ground goes in through `Terrain.from_ground`; see [guide 02](02_use-on-your-own-data.md).

### 2. The plan

```python
plan = bb.rectangular_yard(
    n_areas=1, area_width_m=90.0, area_length_m=90.0,
    bench_height_m=6.0, n_benches=2, margin_m=30.0,
)
area = plan.areas[0]
```

Trucks do not discharge at arbitrary coordinates. A fleet-management dump event locates a load by the
name and bench height of a dump-location polygon, so the plan is the operational data model: named
areas, a bench schedule, and the ordered tip positions that follow from them.

`margin_m=30.0` offsets the area from the pad origin. That matters: a dump on the very edge of the
array cascades off the grid and the load is refused for having nowhere to land. A dump area has ground
around it in every direction, because that is where the run-out goes and where the haul road runs.

A bench's `designed_volume_m3` is not a fudged fraction of a box. Its sides stand at the angle of
repose, so the solid is a rectangular frustum and the volume follows from the footprint, the height
and the repose angle by the prismatoid rule, computed in `design._frustum_m3`.

### 3. The fleet

```python
spec = bb.TruckSpec()
fleet = bb.Fleet.of(4, spec, (15.0, 75.0), repose_deg=37.0)
```

`TruckSpec()` defaults to the CAT 793F, the machine measured in the companion dumping study: 231 t
payload, 7.334 m inside bed width. Body length 12.9 m and dump height 6.5 m are approximate published
figures for the class and are parameters rather than exact measurements.

`(15.0, 75.0)` is the shovel, and it must be OUTSIDE every dump area. `build` raises `ValueError` if
it is not, because the first load placed on the loading point buries it and every later load is
refused for having no drivable start.

`Fleet.of` derives the fleet's gradient limit as `tan(repose) / grade_limit_divisor` with the divisor
defaulting to 1.5. That divisor is a widely repeated operational rule of thumb, not a measured
constant; it is exposed exactly so you can see it and change it. See
[guide 03](03_calibration-and-limits.md).

### 4. The stream

```python
seq = bb.dig_sequence(n_loads=600, seed=7)
loads = bb.payloads_from(seq, seed=7)
```

Two steps, and the split is the point. `dig_sequence` builds the schedule a shovel works: blocks, each
with a grade and a number of loads. `payloads_from` turns that schedule into the ordered stream of
loads arriving at the stockpile. The autocorrelation of that stream is therefore an OUTPUT of the
shovel's dwell (`loads_per_block`, default 20) rather than a parameter anyone sets.
`measured_range_t` then reports the practical range the generated stream actually has, which closes
the loop in the honest direction.

### 5. The build

```python
built = bb.build(terrain, plan, fleet, loads, repose_deg=37.0, seed=20260801)
```

One call runs the whole loop: for each area, for each bench, a paddock campaign of heaps on a row
lattice, dozer visits that level the floor and grade the ramp, then an edge campaign of radial sweeps
whose loads cascade over the face they are aimed at. `build` mutates `terrain` in place and returns a
`BuildResult` carrying the same `Terrain`, the `BlockModel` ledger, one `LoadRecord` per offered load
(placed or refused), the dozer passes, and optional surface snapshots.

### 6. The reclaim

```python
face = bb.ReclaimFace(
    method=bb.ReclaimMethod.FULL_HEIGHT, position_m=30.0, direction=(1.0, 0.0),
    depth_m=10.0, width_m=90.0, loader=bb.LoaderSpec(),
)
cuts = bb.campaign(
    built.terrain, built.model, face,
    cut_tonnes=3000.0, n_cuts=24, repose_deg=37.0,
    exit_xy=fleet.shovel_xy, max_grade=fleet.max_grade,
)
```

`FULL_HEIGHT` takes a proportional slice of every parcel in a column, which is the vertical approach
that actually blends the lifts. `LIFO` works the top down and `FIFO` the bottom up; those are the two
orders the pre-crusher stockpile taxonomy names, and they blend far less.

Passing `exit_xy` and `max_grade` is optional and you should always pass them. Without them the
material still leaves the ledger correctly and the feed series is unchanged, but nothing is recorded
about how it got off site, which is how this engine once shipped a reclaim campaign that no machine
ever attended. With them, every cut carries a truck stand, an approach and a departure, and a cut the
campaign has undercut its own access to is reported with `stand=None` rather than teleported out.

### 7. The verdict

```python
var_in = bb.tonnage_weighted_variance([p.grade for p in loads], [p.tonnes for p in loads])
var_out = bb.tonnage_weighted_variance([c.grade for c in cuts], [c.tonnes for c in cuts])
print(bb.vrr(var_in, var_out))
```

Both variances are on a TONNAGE base. That is not a stylistic choice: a count-weighted variance lets a
231 t load and a 3000 t cut contribute equally, and since reclaim cuts are typically an order of
magnitude larger than the dumps that fed them, the ratio would be wrong by roughly that factor.
`tonnage_weighted_variance` is the only variance function in `blending` for this reason.

## What it prints

Run verbatim:

```text
area A1: x 30-120 m, y 30-120 m
access at (75.0, 120.0), ramp 25 m wide
  bench 0: top 6.0 m, designed 40,508 m3
  bench 1: top 12.0 m, designed 40,508 m3
truck CAT 793F: 231 t, 121.6 m3 per load
fleet gradient limit 0.5024 rise/run = 26.7 deg
design capacity 666 loads
30 dig blocks, 600 loads, 139,047 t
measured practical range 6,952 t
placed 480, refused 120 (20.0%)
   120  no drivable ground inside area 'A1' within 25 m of the planned tip
profiles {'paddock': 118, 'oval': 207, 'comet': 96, 'rectangular': 59}
221 dozer passes, 177,457 m3 bladed
peak 10.29 m, in place 58,358 m3
ledger 110,880 t, mean displacement 69.0 m
24 cuts, 72,000 t reclaimed
  first cut: 3,000 t, grade 0.6370, 45 cells, 24 dig blocks, displaced 17.6 m, coarse 0.3443
  stand (13.75, 43.75), loader (34.9, 46.1), approach 6 pts, departure 6 pts
  cuts a truck could reach: 24 of 24
var_in 0.038008, var_out 0.000272
VRR = var_out / var_in (lower is better)
VRR 0.0071, mixing effect E 11.83
mean dig blocks per cut 24.9, 1/N bound 0.0401, efficiency 1.000
```

## Reading that output

**The refusals are the model working, not failing.** 120 of 600 loads were refused, all for the same
reason: no drivable ground inside area `A1` within 25 m of the planned tip. Material placed at 37
degrees cannot be driven on by a truck limited to 26.7, so a pile constrains its own construction, and
the plan proposing a tip does not oblige the site to accept it. A refused load is recorded with
`placed=False` and a reason string, and `BuildResult.refusal_rate` is a genuine measure of how well
the plan matched the site. A build with a zero refusal rate on a real geometry should make you
suspicious rather than pleased.

Note what the refusals were NOT: none of them was "area is built out". The design capacity is 666
loads and only 600 were offered, so the plan never ran out of tips. If you feed more loads than the
designed volume can hold, the surplus is refused with `area 'A1' is built out; its planned programme
is complete`, and your refusal rate will read as a site problem when it is an arithmetic one. Size the
stream against `sum(b.designed_volume_m3) / TruckSpec.load_volume_m3`.

**The profile census is measured physics, not a setting.** 118 paddock heaps and 362 cascades split
oval 207, comet 96, rectangular 59. Which shape forms is chosen by the truck's distance to the live
crest: beyond one truck length back you get a sloughed heap, against the crest you get one of the
other three, drawn from their measured frequencies in the 28 UAV-surveyed dumps (oval 12, comet 6,
rectangular 4 of 22 at-crest dumps, so 0.545, 0.273, 0.182). The realised split here is 0.572, 0.265,
0.163, which is the measured frequency plus sampling noise on 362 draws. No sloughed heaps formed in
this scenario because every edge tip ended up within one truck length (12.9 m) of a crest cell.

**The dozer moved more material than the trucks did.** 177,457 m3 bladed against 58,358 m3 in place.
That is not a bug and it is the reason the ledger carries a displacement: material is levelled,
re-levelled, graded into a ramp and pushed to the crest, over and over, across 221 passes. The
tonnage-weighted mean displacement of 69.0 m is the honest caveat on every provenance number this
engine reports. Dozers displace stockpiled material from its original dump location and mix it in
intractable ways, so a model that prints provenance to twelve decimal places is asserting a precision
that belongs to the simulation and not to any operation.

**The tonnage round trip is exact, and that is a coincidence of two defaults.** 480 placed loads at
231 t is 110,880 t, which is exactly what the ledger reports. That holds because
`TruckSpec.loose_density_t_m3` is 1.9 (used to turn a payload into a placed volume, 231/1.9 = 121.58
m3) and `BlockModel.bulk_density_t_m3` is also 1.9 (used to turn a recorded thickness back into
tonnes). They are independent fields with the same default. Change one without the other and tonnes
stop round-tripping. See [guide 02](02_use-on-your-own-data.md), which covers the third density,
`Material.loose_density_t_m3`, which is 1.9565 and is not wired into the build path at all.

**The peak is 10.29 m against a designed bench top of 12.0 m.** The pile did not reach its design,
because 20 percent of the loads were refused and because the surface is levelled by the dozer on every
visit. `built.terrain.volume_m3()` of 58,358 m3 against a design of 81,016 m3 says the same thing.

**A cut is a machine working a face, not a slab.** The first cut took 3000 t from 45 cells, roughly
281 m2 at a 2.5 m cell, and reports 24 distinct dig blocks in its provenance. Both numbers are bounded
by the machine: `LoaderSpec.dig_radius_m` is 15 m and no cell outside that radius of the stance is a
candidate, and `min(max_face_m, max_cut_height_m)` caps how deep one pass takes from any single
column. When a stance cannot fill the order the machine trams and takes again, up to one sweep of the
face width.

**VRR is var_out over var_in, so lower is better.** 0.0071 means the reclaimed feed has 0.7 percent of
the incoming stream's variance. The reciprocal convention circulates in secondary sources and building
against it would invert every number and make a recommendation layer advise the worse method, which is
why `VRR_FORMULA_LABEL` exists and why it is printed next to the number. The mixing effect
`E = sigma_in / sigma_out = 11.83` is the same result in the units the bulk-handling literature quotes
design values in.

**The `1/N` bound needs an `N` you can defend, and this one does not defend itself.** The bound is
derived, not cited: if the `N` layers a cut crosses were independent draws from the input
distribution, the cut mean would have variance `var_in / N`. Here `N` was estimated as the mean number
of distinct dig blocks per cut, 24.9, giving a bound of 0.0401. The achieved VRR of 0.0071 is BELOW
that bound, and `blending_efficiency` returns exactly 1.000 because it is `min(1.0, ideal/achieved)`.
An efficiency pinned at 1.000 is not a triumph, it is the function telling you your `N` is wrong. A
full-height cut takes a proportional slice of every parcel in every column it engages, so it averages
far more independent material than the count of dig blocks it touched. The engine deliberately does
not choose `N` for you; picking it is an analyst's judgement and the number should be stated wherever
the efficiency is.

## What it costs

Timings from this machine, a Windows desktop running CPython 3.13.0, single-threaded:

- `build()` alone, 600 loads over a 3600-cell pad: 60.9 s, and 61.5 s on a second run.
- The whole script above, build plus a 24-cut campaign with haulage: 66.7 s wall clock.
- The same script with `exit_xy` and `max_grade` withheld, so the campaign runs without haulage:
  65.4 s. Routing a truck to all 24 cuts costs about a second and a half.
- The full test suite: 85.13 s for 137 tests.

The build dominates everything and the spread between two identical builds is a second or two, so
treat these as the right order of magnitude rather than a benchmark, and expect a loaded desktop to
move them. Most of the time is in the per-load work that cannot be amortised:
one full-pad trafficability mask and one flood fill per load, plus the relaxation cascade after every
placement. The engine already avoids the two worst versions of this, one A-star solve per candidate
spot (measured taking a build from 40 s past 500 s) and rebuilding the neighbour table inside the
relaxation loop, but it is plain Python and it stays plain Python for the portability reason above.

To iterate faster while you are learning the API, shrink the pad and the area rather than the load
count: cost scales with cells more sharply than with loads. A 40 by 40 pad at a 2.5 m cell with a
single 40 m area, one 5 m bench and 200 loads finishes in 0.43 s, and drops to 0.09 s on a 28 by 28
pad. Keep an eye on what it places, though: at 40 by 40 that scenario places 46 loads and refuses the
other 154 as built out, and at 28 by 28 it places 3. A fast run is not automatically a useful one.

## Determinism

A run is a pure function of its parameters and its seeds. Every stochastic choice comes from a seeded
32-bit xorshift written out explicitly, `stream.Xorshift` for the load stream and `build._Rand` for
the build. The only stochastic choice in the build itself is which of the three at-crest profiles
forms, drawn from their measured frequencies because the source is explicit that position alone does
not determine it.

Three seed arguments are in play, in two independent groups: `dig_sequence(seed=...)` and
`payloads_from(seed=...)` fix the stream, `build(seed=...)` fixes the profile draws. Changing the
build seed with the same stream re-rolls the profiles and nothing else.

## What to change first

- `dig_sequence(loads_per_block=...)`. This is the shovel's dwell and it sets the correlation length
  of the incoming stream. Shorten it and the pile has independent material to average, so VRR falls;
  lengthen it and whole layers share a grade and the bed can barely help. Watch `measured_range_t`
  move with it.
- `ReclaimFace.method`, but lower the lift cap with it or nothing will happen. Switching
  `FULL_HEIGHT` to `LIFO` or `FIFO` on the run above changes `var_out` by less than a part in a
  thousand, 0.000272, 0.000272 and 0.000271, and that is not the methods agreeing. A cut takes at most
  `min(ReclaimFace.max_face_m, LoaderSpec.max_cut_height_m)` from any column, both of which default to
  15 m, and this pile peaks at 10.29 m. Every method therefore removes the WHOLE column and there is
  no order left to choose. Re-run with `max_face_m=2.0` and `LoaderSpec(max_cut_height_m=2.0)` so the
  cap actually binds and the three separate hard: VRR 0.0051 full-height, 0.0817 LIFO, 0.1466 FIFO,
  a factor of sixteen and of twenty-nine. Only the vertical approach blends the lifts, and it can only
  do so on a pile taller than one pass.
- `bench_height_m` in `rectangular_yard`. A taller bench means a taller face, a longer cascade and
  stronger size segregation, visible in `LoadRecord.sr` and `LoadRecord.segregation_index`.
- `Fleet.of(grade_limit_divisor=...)`. Loosen it and the refusal rate falls; tighten it and the pile
  strangles its own access. Measured on the run above: 0 percent refused at a divisor of 1.25,
  20.0 percent at the default 1.5, 59.7 percent at 2.0. This is the single most leveraged parameter
  in the guide, and it is a rule of thumb.

## Where to go next

- [02_use-on-your-own-data.md](02_use-on-your-own-data.md) replaces every synthetic input above with
  a real one: a dispatch log instead of `dig_sequence`, a survey grid instead of `Terrain.flat`, your
  own areas and material.
- [03_calibration-and-limits.md](03_calibration-and-limits.md) is the list of every constant in the
  engine that is a choice rather than a measurement, and everything the engine does not model.
- [../methods/](../methods/) has one document per computation, each with its own equations and
  citations.

## References cited in this guide

Only sources the repository itself cites, in a module docstring or in the README reference list.
Nothing here was added by this guide.

- Young, A. and Rogers, W.P. (2021), *Modelling of pre-crusher stockpiles*, Minerals 11(6), 636.
  [doi:10.3390/min11060636](https://doi.org/10.3390/min11060636). The docstrings cite this paper by
  journal, volume and article number throughout and never give the DOI; the DOI is the README's.
- Young, A. and Rogers, W.P. (2022), Mining 2(1). The dump-geometry study of 28 UAV-surveyed dumps.
  [doi:10.3390/mining2010006](https://doi.org/10.3390/mining2010006). Note that this repository quotes
  two different page ranges for it, `86-102` in `bedblend/dump.py` and `terrain.py` and `92-114` in
  `README.md`; the DOI is consistent and is what to follow.
- Loubser, R. and de Korte, G.J. (2015), J. S. Afr. Inst. Min. Metall. 115(8), 773-780.
  [doi:10.17159/2411-9717/2015/v115n8a15](https://doi.org/10.17159/2411-9717/2015/v115n8a15). The
  source for the VRR direction.
- Neufeld, C., Lyall, G. and Deutsch, C.V. (2006), CCG Report 8, paper 306. The industrial stockpile
  simulation the dig-sequence model and the dozer cadence follow. No DOI is recorded in the source.
