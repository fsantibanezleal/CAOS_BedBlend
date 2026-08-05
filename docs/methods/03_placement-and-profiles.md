# 03. Placement and dump profiles

Source: `bedblend/dump.py`. Public API: `DumpProfile`, `ProfileStats`, `PROFILE_STATS`,
`MEASURED_LENGTH_M`, `MEASURED_WIDTH_M`, `MEASURED_THICKNESS_M`, `MEASURED_ANGLE_DEG`,
`MEASURED_VOLUME_M3`, `Placement`, `classify`, `place_paddock`, `place_edge`, `run_out_for_bench`,
`distance_to_crest`. All of these are re-exported from the package root, so `bedblend.place_edge` and
`bedblend.dump.place_edge` are the same object. `SLOUGH_EXTENT` and `SLOUGH_DISTANCE_TRUCK_LENGTHS`,
both discussed below, are module-level but are NOT in the package `__all__`; import them from
`bedblend.dump`.

This module answers one question: when a haul truck tips a load, which cells of the elevation field
gain material, and how much does each gain. Nothing here relaxes anything; the surface it leaves
behind is usually far steeper than the material can stand, and the caller is expected to hand it to
`relax.settle` immediately afterwards. That split is documented in
[04. Relaxation](04_relaxation.md).

## What this replaced, and why the replacement was necessary

The predecessor engine placed every load as an isotropic cosine bell of fixed 4.5 m radius, with no
heading and no face. The module docstring states the objection and the source of it: twenty-eight real
dumps measured by UAV photogrammetry are 13 to 46 m long, 11 to 23 m wide and 0.37 to 2.03 m thick,
they are strongly directional, and they come in four distinct shapes. A 4.5 m isotropic disc is an
order of magnitude short in the down-face axis and carries no direction at all.

Those survey numbers are not prose in this repository. They are constants the code reads:

```
MEASURED_LENGTH_M    = (13.0, 46.0)      whole-population length range, metres
MEASURED_WIDTH_M     = (11.0, 23.0)      whole-population width range, metres
MEASURED_THICKNESS_M = (0.368, 2.032)    whole-population thickness range, metres
MEASURED_ANGLE_DEG   = (12.0, 36.0)      whole-population deposit angle range, degrees
MEASURED_VOLUME_M3   = (94.0, 155.0)     whole-population per-dump volume range, cubic metres
```

Only three of the five are actually asserted against anything. `test_edge_dump_matches_measured_envelope`
compares a realised placement against `MEASURED_LENGTH_M`, `MEASURED_WIDTH_M` and
`MEASURED_THICKNESS_M`, and `test_build.py` re-checks the first two over a whole build.
`MEASURED_ANGLE_DEG` and `MEASURED_VOLUME_M3` are read by no code path and by no test: they are
exported reference data, not part of the calibration gate. A grep for either name outside `dump.py`
and `__init__.py` returns nothing.

## The two regimes are different objects, not variants

The companion paper is quoted in the docstring: material "forms a small heap if it is dumped on a flat
surface, or cascades along the edge of a dump face if dumped over a developing dump, stockpile or
dump/heap leach". `place_paddock` is the first case and `place_edge` is the second. They do not share
a shape function, they do not share an orientation rule, and they do not produce the same fields on a
`Placement`.

`DumpProfile` has five members and the asymmetry is deliberate:

```
OVAL           cascade profile, measured
COMET          cascade profile, measured
RECTANGULAR    cascade profile, measured
SLOUGHED_HEAP  cascade profile, measured
PADDOCK        not one of the four; a load tipped on flat ground
```

`PADDOCK` is not a fifth measured cascade type. The four measured types are all shapes taken by
material that went over a face, and collapsing a flat-ground heap into that taxonomy would misreport
what was placed.

## The four measured profiles and their statistics

`ProfileStats` is a frozen dataclass with five fields: `mean_volume_m3`, `mean_angle_deg`,
`mean_width_m`, `mean_thickness_m` and `count`. The counts are the 28 classified dumps of table 5; the
means are read from the per-type box charts of figures 2 to 7. The literal table in the code is:

```
profile         mean_volume_m3  mean_angle_deg  mean_width_m  mean_thickness_m  count
oval                     128.0            34.5          14.8              1.00     12
comet                    134.0            33.5          19.4              1.50      6
rectangular              137.0            34.0          13.0              0.95      4
sloughed_heap            129.0            24.5          14.6              1.40      6
                                                                                 ----
                                                                                   28
```

Two of those five fields do work at runtime and three do not, and a maintainer should know which is
which before trusting them. Only `mean_width_m` and `count` are read by any code path:
`mean_width_m` sets the maximum width of an edge dump in `place_edge`, and `count` sets the selection
frequencies in `classify`. `mean_volume_m3`, `mean_angle_deg` and `mean_thickness_m` are carried as
reference data and are read by nothing in the package, not even by the tests. They are worth keeping,
because they are the published values a future calibration would be judged against, but nothing
currently checks the engine against them.

The sloughed heap's mean angle of 24.5 degrees against 33.5 to 34.5 for the other three is the one
per-type statistic with an explanation attached in the source: a sloughed heap "does not typically
extend the full length of the dump face", so its deposit lies at a flatter overall angle. That
explanation is what the `SLOUGH_EXTENT` constant encodes, below.

### The survey

Young, A. and Rogers, W.P. (2022). Mining 2(1), 86-102.
[doi:10.3390/mining2010006](https://doi.org/10.3390/mining2010006). Table 5 for the population ranges
and the per-type counts, figures 2 to 7 for the per-type means, section 4.2 for the position rule in
`classify`.

Young, A. and Rogers, W.P. (2021). Minerals 11, 636. Figure 11 for the elliptical frustum and the 2:1
emplacement slope, figure 13 for the edge-dump volume of influence. The module docstring cites this
paper by journal, volume and figure without a DOI; the repository README's reference list gives
[doi:10.3390/min11060636](https://doi.org/10.3390/min11060636) for it.

One inconsistency to be aware of, because it is in the repository and I did not resolve it: `dump.py`
and `terrain.py` both cite the Mining 2022 paper as pages 86-102, while the README's reference list
gives pages 92-114 for the same DOI. The DOI is identical in both places and is the identifier to
trust. The page range needs one look at the publisher record to settle, and this document does not
settle it.

## Regime one: the paddock heap

```python
place_paddock(terrain, x_m, y_m, heading_rad, volume_m3, truck, *, spread=1.0) -> Placement
```

The published description is an elliptical frustum whose "height, length and width of the heap are
dependent on the respective height, width and length of the haul truck used". The implementation takes
that literally: the semi-axes come from the machine and nothing else.

```
a = 0.5 * truck.body_length_m * spread        semi-axis along the heading, metres
b = 0.5 * truck.bed_width_m   * spread        semi-axis across the heading, metres

ux, uy = cos(heading_rad), sin(heading_rad)   unit vector along the heading
px, py = -uy, ux                              unit vector across it

for each candidate cell c with centre (cx, cy):
    dx, dy = cx - x_m, cy - y_m
    r = hypot( (dx*ux + dy*uy) / a ,  (dx*px + dy*py) / b )     normalised elliptical radius

    w(r) = 1                if r <= 0.4
    w(r) = (1 - r) / 0.6    if 0.4 < r <= 1
    (cells with r > 1 are skipped entirely)
```

`w` is continuous at `r = 0.4`, where `(1 - 0.4)/0.6` is exactly 1. Height is not an argument to the
function: it falls out of conserving the requested volume, which is why the shape can be stated from
the truck alone.

Read the flat top carefully. The docstring says "a flat top over the inner 40 percent of the
footprint", and 0.4 is a fraction of the normalised RADIUS, so the flat top covers 0.4 squared, that
is 16 percent, of the footprint AREA.

The mean of `w` over the unit disc is exactly 0.52, integrating `w(r) * 2r` from 0 to 1. That gives a
closed-form peak thickness for a load that fits entirely on the pad:

```
peak thickness  =  V / (pi * a * b * 0.52)
```

For the default `TruckSpec` (CAT 793F: `body_length_m` 12.9, `bed_width_m` 7.334, `payload_t` 231.0,
`loose_density_t_m3` 1.9, so `load_volume_m3` 121.5789) that formula gives 3.1465 m. Placed on a flat
pad at 2.5 m cells, the engine produces a peak of 3.1509 m, a footprint of 8 cells, and a realised
`length_m` of 10.00 m by `width_m` 5.00 m. The gap between 12.9 by 7.334 and 10.00 by 5.00 is pure
discretisation: at 2.5 m cells only 8 cell centres fall inside the ellipse. The calibration test
allows two cells of slack for exactly this reason.

`spread` exists to express the two caveats the source attaches to the frustum: truck movement during
discharge extends the heap "not the width", and the width "may also expand beyond the original width
of the truck if the truck does not move forward". Measured effect on a flat pad with the default load:

```
spread   realised length   realised width   peak thickness
  1.0            10.00 m           5.00 m         3.1509 m
  1.5            20.00 m          10.00 m         1.3789 m
  2.0            25.00 m          15.00 m         0.7891 m
```

No caller inside the package ever passes `spread`. `build` uses the default of 1.0 for every paddock
load, so the two caveats are available to a caller and are not currently exercised by the engine
itself.

A paddock `Placement` records `distance_to_crest_m` as positive infinity and leaves `s_frac` empty.
Both are correct rather than missing: a heap on flat ground has no face, so there is no down-face
coordinate for segregation to sort along, and `build` consequently gives every cell of a paddock load
the material's unsegregated size split.

## Regime two: the edge dump

```python
place_edge(terrain, x_m, y_m, volume_m3, truck, *, profile, run_out_m,
           normal=None, distance_to_crest_m=0.0, width_scale=1.0) -> Placement
```

The load runs down the face along the outward normal, because the measured statement is that the
volume of influence "runs perpendicular to the tangent of the dump location", and perpendicular to the
crest tangent is the outward normal of the face. When `normal` is not supplied it is taken from
`Terrain.outward_normal` at the dump cell, which is the negated elevation gradient by central
differences.

Read the call path before relying on that default, because `build` never uses it. `_run_one_load`
always passes `normal=(cos(heading), sin(heading))`, where `heading` came back from `fleet.dispatch`
and therefore from `truck.spot`. The deposit still ends up oriented by the terrain rather than by the
truck's compass heading, but by a different route: `spot` overwrites the truck's reversed drive-in
heading with `Terrain.outward_normal` at the nearest crest cell whenever that crest is within
`3 * tip_reach`. So the terrain-derived default inside `place_edge` is a convenience for a direct
caller, not the path the engine takes, and the two can disagree, since `spot` reads the normal at the
CREST cell while the default would read it at the DISCHARGE cell.

Two guard clauses come before any geometry. If the tip point is off the pad, the function returns an
empty `Placement` carrying the requested profile, and `build` turns that into a refusal with the
reason "the load had nowhere to land on the pad". If the terrain normal at the dump cell is the zero
vector, meaning there is no face there, the call falls back to `place_paddock`. That fallback is not a
convenience: manufacturing a streak where the terrain has nowhere to send material would invent the
exact geometry this module exists to stop inventing. The returned `Placement` then carries
`DumpProfile.PADDOCK`, so the caller can see the substitution rather than being told a comet was
placed. Note that this second guard cannot fire from `build`, which always hands in a unit vector
built from `cos`/`sin` of a heading; it protects a direct caller who omits `normal` on flat ground,
which is what `test_edge_dump_on_flat_ground_falls_back_to_a_heap` exercises. `build` reaches the
same outcome earlier and by a different test, its `at_face` check on the distance to the crest.

The deposit is built in a face-aligned frame:

```
nx_, ny_ = the outward face normal, unit length
px , py  = -ny_, nx_                          the crest tangent

for each candidate cell c with centre (cx, cy):
    dx, dy = cx - x_m, cy - y_m
    s_m = dx*nx_ + dy*ny_                     distance DOWN the face, metres
    t_m = dx*px  + dy*py                      distance ACROSS the face, metres
    (skip the cell unless 0 <= s_m <= run_out_m)
    s   = s_m / run_out_m                     down-face position, 0 at the crest, 1 at the toe
```

Width at each down-face station comes from a per-profile shape function `g(s)`, floored at the width
of the tray that poured the material:

```
w_max      = PROFILE_STATS[profile].mean_width_m * width_scale
crest_frac = min(1, truck.bed_width_m / w_max)
half(s)    = 0.5 * w_max * max( g(s), crest_frac )

(skip the cell unless |t_m| <= half(s), and skip it if g(s) <= 0)
lateral    = 1 - ( |t_m| / half(s) )^2        across-face taper, so the streak has edges
weight(c)  = m(s) * lateral
```

with the four width shapes and the two mass shapes:

```
g(s) = sin(pi * s) ^ 0.6                              OVAL
g(s) = s ^ 0.8                                        COMET
g(s) = 1                                              RECTANGULAR
g(s) = sin(pi * min(s / 0.85, 1)) ^ 0.5   if s <= 0.85, else 0        SLOUGHED_HEAP

m(s) = 0.35 + 0.65 * s                                OVAL, COMET, RECTANGULAR
m(s) = max(0, 1 - s / 0.85)                           SLOUGHED_HEAP
```

Each `g` is the paper's verbal description of that shape turned into the simplest function that
reproduces it, and the source claims nothing more for the functional forms than that. The oval is
"narrow at crest and toe, maximum width midway down the dump face"; the comet is "large volume near
the base, narrow trail extending up the face"; the rectangular "covers the whole dump face evenly to
uniform width". The mass shape `m` for the three cascading types encodes the measured statement that
material "aggregates more at the bottom of the dumping area under normal conditions and less near the
top crest", so areal mass grows linearly from 0.35 at the crest to 1.0 at the toe. The sloughed heap
is the opposite by definition, because it never got there.

Evaluated, the shapes are:

```
s                 0.00    0.25    0.50    0.75    0.85    0.90    1.00
oval        g   0.0000  0.8123  1.0000  0.8123  0.6226  0.4943  0.0000
comet       g   0.0000  0.3299  0.5743  0.7944  0.8781  0.9192  1.0000
rectangular g   1.0000  1.0000  1.0000  1.0000  1.0000  1.0000  1.0000
slough      g   0.0000  0.8933  0.9807  0.6010  0.0000  0.0000  0.0000

three types m   0.3500  0.5125  0.6750  0.8375  0.9025  0.9350  1.0000
slough      m   1.0000  0.7059  0.4118  0.1176  0.0000  0.0000  0.0000
```

### The width is the measured one, not the truck's

This is the one place where the implementation deliberately departs from the source's stated
assumption, and it says so. Figure 13 of Minerals 2021 assumes a volume of influence of "width equal
to the width of the haul truck", but the widths actually measured across the 28 surveyed dumps are 11
to 23 m against a 7.334 m bed. Material spreads as it descends, and the paper supplies the mechanism
for the widest type: comet profiles are "the result of additional material from the dump face
aggregating with the dump mass as it cascades, resulting in an increase in width". So `w_max` is the
measured per-type mean width, and the truck's bed width enters only through `crest_frac`, which sets
the streak's width at the crest where nothing has spread yet. For the default truck:

```
profile         w_max     crest_frac = bed_width / w_max
oval             14.8 m   0.4955
comet            19.4 m   0.3780
rectangular      13.0 m   0.5642
sloughed_heap    14.6 m   0.5023
```

One trap for a maintainer reading the source rather than this page. `place_edge`'s own docstring still
says "Base width is the truck's bed width, per the measurement, scaled by `width_scale`", and that
sentence is stale: the line it describes is `w_max = PROFILE_STATS[profile].mean_width_m * width_scale`,
so `width_scale` scales the MEASURED per-type width and the bed width enters only through
`crest_frac`. The inline comment immediately below the docstring states the real rule. Believe the
comment and the code; the docstring's first sentence on width is wrong.

### `SLOUGH_EXTENT`

```
SLOUGH_EXTENT = 0.85
```

How far down the face a sloughed heap reaches, as a fraction of the full run-out. It appears in both
`g` and `m` for that type. The source's justification is arithmetic on the survey: the six sloughed
heaps in table 5 measure 13, 16, 27, 28, 29 and 39 m long, a mean of about 25 m, against run-outs of
roughly 30 m at these bench heights. On the 20 m bench at 34 degrees used by the calibration test the
run-out is 29.6512 m, so 0.85 of it is 25.204 m, and the realised length comes out at 25.00 m. This
constant is fitted to one summary statistic of six dumps. It is the weakest of the geometric numbers
in the module and it would be replaced by a per-dump regression of sloughed-heap length against bench
height if the underlying survey data became available.

### What the operator actually produces

Every profile placed at (59, 150) on a 120 by 120 pad at 2.5 m cells, over a flat-topped 20 m bench
whose face falls away at 34 degrees, with the default truck's 121.5789 m3 load and
`run_out_m = run_out_for_bench(20, 34) = 29.6512`:

```
profile         length   width   peak thick   mean thick   cells   crest-half / toe-half mass
oval            27.50 m  15.00 m     0.708 m      0.389 m     50            0.462 / 0.538
comet           27.50 m  20.00 m     0.738 m      0.389 m     50            0.293 / 0.707
rectangular     27.50 m  15.00 m     0.702 m      0.295 m     66            0.434 / 0.566
sloughed_heap   25.00 m  15.00 m     1.086 m      0.405 m     48            0.856 / 0.144
```

All four sit inside the measured envelope on all three axes, which is the kill criterion the plan
states and which `test_edge_dump_matches_measured_envelope` enforces. The mass split confirms the
intended asymmetry: the three cascading types put more mass below the halfway point, most strongly the
comet at 0.707, while the sloughed heap puts 0.856 of its mass in the upper half.

Three honest qualifications on that table. First, the calibration compares a per-cell MAXIMUM
thickness against `MEASURED_THICKNESS_M`, a whole-population range whose statistic the code does not
state; the realised mean thicknesses, 0.295 to 0.405 m, are a different quantity again, and nothing
compares them to the per-type `mean_thickness_m` of 0.95 to 1.50 m. Second, the envelope is checked at
one bench geometry. The realised length tracks `run_out_m` almost exactly, so a short bench falls out
of the published band:

```
bench height   face angle   run_out_m   realised length (oval)
      8.0 m      34 deg      11.86 m           10.00 m     below MEASURED_LENGTH_M[0] = 13.0
     12.0 m      34 deg      17.79 m           17.50 m     inside
     20.0 m      34 deg      29.65 m           27.50 m     inside
     30.0 m      34 deg      44.48 m           42.50 m     inside
     20.0 m      40 deg      23.84 m           22.50 m     inside
```

The surveyed dumps came from benches tall enough to produce 13 to 46 m deposits, so a model run on a
6 or 8 m lift is outside the conditions the envelope was measured under. It is not a solver failure;
it is a scenario the calibration does not cover, and `test_build.py` acknowledges this by checking
only the upper bounds, with 20 percent of slack, on a full build.

Third, the per-load volume placed is 121.5789 m3, which is inside `MEASURED_VOLUME_M3` of 94 to 155
but below all four per-type means of 128 to 137. That is a consequence of the `TruckSpec` defaults
(231 t at 1.9 t per cubic metre) rather than a calibration choice.

`width_scale` behaves as described above, scaling the measured per-type width, but it is never passed
by any caller in the package. Measured on the comet at 0.75, 1.0 and 1.5 the realised widths are
15.00, 20.00 and 25.00 m.

## `run_out_for_bench`

```python
run_out_for_bench(bench_height_m, face_angle_deg) -> float
```

```
angle   = clamp(face_angle_deg, 1.0, 89.0)              degrees
run_out = bench_height_m / tan(radians(angle))          metres
```

This is the "length equal to the horizontal component of the bench slope" from figure 13, and it is
the single quantity that makes an edge dump 13 to 46 m long while a paddock heap is a truck long. A
20 m bench at 34 degrees runs out 29.6512 m, which sits in the middle of the measured length band; the
source treats that agreement as a check on the whole geometry rather than a coincidence.

The clamp matters at both ends. A face angle of zero would divide by zero, so it is clamped to 1
degree, which yields a 1145.8 m run-out for a 20 m bench, an absurd number that will be visible rather
than a crash. Above 89 degrees the run-out collapses to 0.349 m for the same bench. Passing
`run_out_m = 0` to `place_edge` produces a `Placement` with zero cells, because the cell filter
`0 <= s_m <= run_out_m` then admits nothing.

The caller computes this rather than the operator, because the dump operator does not know the bench
schedule. In `build` the run-out for a bench uses that bench's OWN height, `bench.top_m` minus the
previous bench top, not the height of the whole pile: the second lift of a two-lift pile cascades over
its own face, not over both. The face angle defaults to the repose angle, which is what a tipped face
stands at.

## `distance_to_crest`

```python
distance_to_crest(terrain, x_m, y_m, crest) -> float
```

```
d(x, y) = min over c in crest of hypot(cx - x, cy - y)      metres
d(x, y) = +infinity                                          if crest is empty
```

A straight-line distance to the nearest crest cell, where `crest` is whatever `Terrain.crest_cells`
returned, that is, cells carrying material with a drop of at least `min_drop_m` to some neighbour.
Infinity on an empty crest is the correct answer rather than a sentinel: with no face there is nothing
to dump over, every load is a paddock heap, and that is exactly the state a stockpile starts in.

The function is Euclidean and ignores the terrain in between. It does not know whether the crest cell
is reachable, whether a berm stands between the truck and the face, or whether the nearest crest
belongs to a different area. Measured on the calibration face, the 120 by 120 pad at 2.5 m cells with
a flat-topped 20 m bench falling at 34 degrees that `_face()` in `tests/test_terrain_relax_dump.py`
builds: at `min_drop_m = 0.5` the crest set is 1560 cells and the function returns 8.8388 m from
(50, 150) and 1.2748 m from (59, 150); at the `crest_drop_m = 1.0` that `build` actually defaults to,
the crest set is 1320 cells and the same two queries return 11.3192 m and 2.5739 m. The answer moves
with the crest definition, so quoting a distance without the drop threshold that produced it is
meaningless. The cost is linear in the number of crest cells.

**Nothing in the engine calls this function.** It is defined here, exported from the package root and
covered by one test, and that test only asserts the empty-crest case returns infinity. The distance
that actually reaches `classify` and is recorded on every `LoadRecord` is computed by `truck.spot`,
which re-implements the same minimum over the same crest list inline. So `distance_to_crest` is a
correct public utility whose non-degenerate behaviour is untested and whose result no build depends
on; the number that matters comes from a second copy of the same three lines in another module. Either
`truck.spot` should call this function or this function should be documented as caller-facing only.

Two differences between the two copies are worth knowing. `truck.spot` measures from the position the
truck is standing at, the `TipPosition` handed to `Fleet.dispatch`, which in `build` is the output of
`_nearest_reachable` and so is the ACTUAL spot rather than the planned one when the plan could not be
occupied. The material, meanwhile, lands at `truck.discharge_xy()`, which is 0.66 body lengths from
the truck's own position along the discharge heading, behind the tail of a rear-dump machine. So the
distance recorded on the `LoadRecord`, and the distance `classify` sees, is measured from a point up
to 8.5 m away from where the deposit is written. And `truck.spot` uses its minimum for a second
purpose: if the nearest crest is within `3 * tip_reach`, and `tip_reach` is `4.0 * terrain.cell_m`, so
12 cells, it overrides the truck's discharge heading with the face's outward normal at that crest
cell, which is how the terrain comes to orient the deposit.

## `classify`, and why the shape is drawn rather than derived

```python
classify(distance_to_crest_m, truck, *, rand=0.5,
         slough_truck_lengths=SLOUGH_DISTANCE_TRUCK_LENGTHS) -> DumpProfile
```

```
if distance_to_crest_m > slough_truck_lengths * truck.body_length_m:
    return SLOUGHED_HEAP

otherwise, with rand in [0, 1):
    rand <  12/22 = 0.545455   ->  OVAL
    rand <  18/22 = 0.818182   ->  COMET
    rand <  22/22 = 1.000000   ->  RECTANGULAR
    anything else              ->  OVAL          (the loop's fall-through)
```

The first branch is a measured result, not an assumption: "if the truck dumps far from the crest of
the dump face, it will create a sloughed heap. When the truck dumps against the crest of the dump
face, the type of the resulting dump profile is either comet, oval or rectangular" (Mining 2022,
section 4.2). This is the direct answer to how a truck's position defines the area it feeds.

The second branch is where the model stops claiming to know something. The paper is explicit that it
could not say which of comet, oval or rectangular forms from position alone, and that its hypothesis
about uneven tray loading was never tested: "the exact interplay between how the trucks were loaded
and the resulting dump profiles remains unclear, and no information on truck loading was gathered
during this study". So the choice among the three is drawn from the measured relative frequencies of
the 22 at-crest dumps, 12 oval, 6 comet, 4 rectangular. The frequencies are real; the selection is
admittedly stochastic, and it is stochastic because the mechanism that would make it deterministic was
not measured. What would replace it is a study that records tray loading alongside the resulting
profile.

The draw is not internal. `rand` is supplied by the caller from a seeded stream, `rng.next()` in
`build`, so a run is reproducible bit for bit. Over 100000 uniform draws the realised split is 54546
oval, 27273 comet, 18181 rectangular, matching 12/22, 6/22 and 4/22 to the last load. Values of `rand`
at or above 1, and negative values, fall through the loop and return `OVAL`; the function does not
validate its input.

### `SLOUGH_DISTANCE_TRUCK_LENGTHS`, an anchored constant

```
SLOUGH_DISTANCE_TRUCK_LENGTHS = 1.0
```

This is a rule of thumb and the source says so in as many words. Beyond roughly one truck length back
from the crest the load can no longer reach the face, so it bunches and only partly sloughs over, and
the operational rule of thumb is to tip about one truck length back from an edge. For the default
793F that puts the threshold at 12.90 m. It is a keyword parameter of `classify` rather than a hidden
literal, so a caller with a site rule can pass its own value, and `build` does not: it always uses the
default. Comparison is strictly greater than, so a distance of exactly 12.9 m still classifies as an
at-crest dump.

What would replace it is a measured distribution of tip distance against resulting profile from the
same kind of UAV survey. The 2022 paper reports the qualitative rule but not the distance at which the
transition happens.

One more integration detail worth knowing, because it is not in this module: `build` does not call
`classify` for every load in an edge campaign. It first tests `tip.phase is Phase.EDGE and d_crest <=
3.0 * terrain.cell_m * 4.0`, that is, twelve cells, and only then classifies and calls `place_edge`.
A tip nominally in the edge campaign that has no face within that radius is placed as a paddock heap,
because that is what the material does. So the effective SLOUGHED_HEAP window in a build run is the
band between one truck length and twelve cells from the crest, and at the default 2.5 m cell that is
12.9 m to 30.0 m.

## Mass conservation, and what `Placement` reports

`_apply` normalises the weight map and adds it to the surface:

```
scale  = volume_m3 / ( sum_k w_k * cell_m^2 )
dz_c   = w_c * scale                       for every cell with w_c > 0
z[c]  += dz_c
```

so `sum_c dz_c * cell_m^2` equals the requested volume by construction, with no clipping afterwards.
Measured both ways on both cases, a centred paddock load and a load whose footprint hangs off the pad:
`Terrain.volume_m3()` minus the requested volume is exactly 0.0 m3 in both, while summing `added_m`
and multiplying by the cell area leaves 1.4210854715202004e-14 m3 in both. The residual is the
summation order, not the placement: 1.4e-14 is float noise on 121.5789.

That second case is a modelling decision worth stating plainly. A load whose footprint falls partly
off the pad is CONCENTRATED on the part that remains rather than losing tonnes over the edge, matching
the pad-as-a-wall convention the relaxation solver uses. The consequence is measurable: the same load
tipped 1 m from the west edge of a 50 by 50 m pad lands on 6 cells instead of 8 and peaks at 4.9807 m
instead of 3.1509 m. Mass is conserved and the geometry is wrong, in the direction of being too thick.
A pile that touches the pad boundary is a scenario problem, not a solver problem, and the caller is
expected to notice.

`Placement` carries ten fields, in this order for positional construction:

```
profile              DumpProfile
cells                list[int]         cell indices that gained material
added_m              list[float]       metres added, parallel to cells
volume_m3            float             as requested
length_m             float             realised, measured off the placed field
width_m              float             realised, measured off the placed field
max_thickness_m      float             realised, the maximum of added_m
heading_rad          float             atan2 of the face normal for an edge dump
distance_to_crest_m  float             as supplied; +inf for a paddock heap
s_frac               list[float]       down-face position per cell; empty for a paddock heap
```

`length_m`, `width_m` and `max_thickness_m` are measured back off the placed field by `_measure`, not
copied from the request, because those are the quantities the calibration test compares against the
published table. The extents are taken between cell centres and widened by one cell, since a
single-cell deposit occupies a cell rather than a point:

```
length = max_c (p_c . u)      - min_c (p_c . u)      + cell_m
width  = max_c (p_c . u_perp) - min_c (p_c . u_perp) + cell_m
```

where `u` is the heading for a paddock heap and the face normal for an edge dump, and `u_perp` is `u`
rotated by 90 degrees.

`s_frac` is the field that makes size segregation possible at all. It is the down-face coordinate of
each cell, parallel to `cells`, and it is the axis the coarse-to-toe sorting is distributed along;
without it the solver has no coordinate to sort on. Note what consumes it: `build` maps each cell's
`s_frac` into a bin of the `FaceSegregation` result. It does NOT come from the relaxation solver's
move ordering. On the measured 20 m bench the realised range is 0.0759 to 0.9190 for the three
cascading types and 0.0759 to 0.8347 for the sloughed heap, the ends being set by cell centres and by
`SLOUGH_EXTENT` respectively.

## Performance

`_cells_within` does a bounding-box scan rather than a whole-pad sweep, clipped to the pad:

```
i0 = max( floor((x_m - reach_m) / cell_m), 0 )
i1 = min( floor((x_m + reach_m) / cell_m), nx - 1 )
j0 = max( floor((y_m - reach_m) / cell_m), 0 )
j1 = min( floor((y_m + reach_m) / cell_m), ny - 1 )
```

with `reach_m` equal to `max(a, b) + cell_m` for a paddock heap and `run_out_m + half_w + cell_m` for
an edge dump. On a 300 by 300 pad the source states the difference between scanning a 40 m
neighbourhood and scanning 90000 cells per load as the difference between a responsive model and an
unusable one.

## What this module is not

It is not a granular flow solver. Nothing here integrates a trajectory, a momentum balance or a
contact law. It is a parameterised deposit shape fitted to a photogrammetric survey of 28 dumps, and
its authority is exactly the authority of that survey: one operation, one truck class, the bench
geometries that survey covered.

It is not a stability model. The surface `place_paddock` leaves behind stands at 51.57 degrees for a
single default load, well over any ore's repose angle. Every caller must relax afterwards.

It does not decide which regime applies. `classify` decides which of the four cascade profiles forms,
but the choice between `place_paddock` and `place_edge` is the caller's, made in `build` from the
tip's declared phase and the measured distance to the crest.

It does not model what rolls beyond the toe. The survey notes that round and large material "may also
roll beyond the floor of the bench, especially at higher bench heights"; the deposit here stops at
`run_out_m` exactly. Overrun is handled by the face segregation module, separately, as a reported
magnitude.

It has no notion of compaction, of the previous load's shape, or of the truck's tipping dynamics. Two
loads placed on the same cell simply add.

## References

* Young, A. and Rogers, W.P. (2022). Mining 2(1), 86-102.
  [doi:10.3390/mining2010006](https://doi.org/10.3390/mining2010006). The 28-dump UAV survey: table 5
  for the population ranges and the per-type counts, figures 2 to 7 for the per-type means, section
  4.2 for the distance-to-crest rule. The DOI appears once, in the `dump.py` module docstring, which
  is also where the section-4.2 quote lives; `DumpProfile` and `ProfileStats` cite the paper by name
  and table. `classify` carries NO citation of its own, so a reader who lands on that function has to
  go back to the module docstring for the evidence behind its first branch.
* Young, A. and Rogers, W.P. (2021). Minerals 11, 636. Figure 11 for the elliptical frustum and the
  truck-dependent heap dimensions, figure 13 for the edge-dump volume of influence and the
  perpendicular-to-the-tangent rule. Cited in `dump.py` and in `terrain.py`; the DOI
  [doi:10.3390/min11060636](https://doi.org/10.3390/min11060636) is carried in the repository README
  rather than in the module.
