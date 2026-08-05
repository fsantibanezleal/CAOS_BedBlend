# Data contract

What crosses the boundary of `bedblend`: every field of every type a caller constructs or receives,
its unit, its default, and what the engine does when the value is wrong.

Everything below was read out of the source with `dataclasses.fields` and `inspect.signature`, or
produced by running the package, rather than transcribed from another document. Where a magnitude is
quoted it came from an actual run. Where a claim could not be verified it is not made.

---

## 1. Conventions, stated once

**Coordinates.** The pad is a regular grid of `nx` by `ny` square cells of side `cell_m`. The origin
is the outer corner of cell `(0, 0)`, so the pad occupies `x` in `[0, nx * cell_m)` and `y` in
`[0, ny * cell_m)`. A cell index is row major:

```
idx  = j * nx + i          i in [0, nx), j in [0, ny)
i    = idx mod nx
j    = idx div nx
x_c  = (i + 0.5) * cell_m    cell CENTRE, in metres
y_c  = (j + 0.5) * cell_m
```

Cell centres, not corners: `Terrain.xy` returns the centre because every distance in the dump
operators is measured between a truck position and a cell, and a half cell bias there is a systematic
error in the placed footprint. On a 64 by 48 pad at `cell_m = 2.5` the pad is 160 m by 120 m,
`Terrain.xy(0)` is `(1.25, 1.25)` and `Terrain.xy(3071)` is `(158.75, 118.75)`. `Terrain.cell_at`
floor divides from the origin and returns `None` off the pad: `cell_at(160.0, 120.0)` is `None`,
`cell_at(159.999, 119.999)` is 3071, and any negative coordinate is `None`.

**The pad edge is a wall.** Relaxation never moves material off the grid (`neighbour_table` in
`bedblend/relax.py`), and a dump whose footprint falls partly off the pad is concentrated on the part
that remains rather than losing tonnes over the edge (`_apply` in `bedblend/dump.py`). Mass is
conserved by construction; a pile that touches the boundary has to be flagged by the caller.

**Units.**

| Quantity | Unit | Where |
|---|---|---|
| Length, elevation, thickness, run out, drop | metres | every `*_m` field |
| Particle size | millimetres | `Material.d50_mm` only |
| Mass | tonnes | every `*_t` field, `Cut.tonnes`, `Rollup.tonnes` |
| Volume | cubic metres | every `*_m3` field |
| Density | tonnes per cubic metre | every `*_t_m3` field |
| Angles in the public API | degrees | every `*_deg` field and argument |
| Headings | radians from the `+x` axis | `heading_rad`, `TipPosition.heading_rad`, `Truck.heading_rad` |
| Slopes and trafficability limits | dimensionless rise over run | `max_grade`, `Terrain.gradient`, `FRESH_HEAP_SLOPE` |
| Grades, splits, fractions | dimensionless fractions, not percentages | `grade`, `coarse_fraction`, `overrun_fraction`, `paddock_frac`, `swell`, `moisture` |
| Speed | metres per second | `Avalanche.u_ms`, the layer's flow speed, and `Avalanche.q_ms`, the percolation velocity. Both are m/s: `q_ms` is `kappa * (u_ms / layer_h_m) * d_m`, which is a velocity despite reading like a flux, and it has to be for `Sr = q L / (H U)` to come out dimensionless |
| Volumetric flux per unit width | m2/s | `CASCADE_FLUX_M2_S = 1.0` in `bedblend/facesegregation.py`. A module constant, not a field of any type |

Headings are the one quantity stored in radians; `TipPosition.heading_deg` is the accessor that
converts. Two other degree valued accessors are derived rather than stored, both from gradients:
`Terrain.slope_deg(c)` and the module constant `FRESH_HEAP_DEG`, which is
`degrees(atan(FRESH_HEAP_SLOPE))` with `FRESH_HEAP_SLOPE = 2.0`, so 63.43494882292201 degrees.

**Grade is carried, never interpreted.** Nothing in the engine reads a unit into `grade`. It is
averaged by tonnage or by thickness and nothing else, so any linearly additive assay works: percent
copper, grams per tonne, a silica to magnesia ratio. Zero is a legitimate value and is not treated as
missing anywhere. The only places a grade is constrained are the two generators in
`bedblend/stream.py`, which clamp at zero with `max(grade, 0.0)`, so a stream produced by
`dig_sequence` and `payloads_from` can contain grade 0.0 but never a negative grade. A `Payload`
constructed by hand has no validation at all.

**Determinism.** Everything stochastic comes from the 32 bit xorshift in `bedblend/stream.py` and
`bedblend/build.py`, seeded explicitly, so a run is a pure function of parameters and seed. One
consequence a caller should know: the constructor does `self.state = (seed | 1) & 0xFFFFFFFF`, so
even and odd seeds collide in pairs. `Xorshift(2)` and `Xorshift(3)` produce the identical stream,
verified: both give `0.00018885, 0.0470053, 0.70441343` as their first three uniforms.

---

## 2. Inputs

### 2.1 `Terrain` (`bedblend/terrain.py`), mutable

The ground and the current surface. Every operator mutates `z` in place.

| Field | Type | Unit | Default |
|---|---|---|---|
| `nx` | `int` | cells | required |
| `ny` | `int` | cells | required |
| `cell_m` | `float` | m | required |
| `z` | `list[float]` | m elevation, length `nx * ny` | required |
| `z0` | `list[float]` | m elevation of the ORIGINAL ground | required |

Two constructors: `Terrain.flat(nx, ny, cell_m, base_m=0.0)` sets `z` and `z0` to the same constant,
and `Terrain.from_ground(nx, ny, cell_m, ground)` copies a supplied array into both. Survey ground
enters through the second. `bedblend/topography.py` generates analytic ground for the five published
fill types through `ground(fill, nx, ny, cell_m, *, relief_m=25.0, roughness_m=0.0, seed=1)`, with
`FillType` in `heaped, sidehill, valley, cross_valley, ridge_crest`.

`z0` is what makes "how much material is here" a different question from "how high is the surface":

```
thickness(c) = z[c] - z0[c]                     metres of placed material
has_material(c) is thickness(c) > EMPTY_M       EMPTY_M = 1e-4 m
volume_m3()  = sum over c of thickness(c) * cell_m^2
```

`EMPTY_M` exists because colouring a zero height cell as material at grade zero once made an empty
pad read as a full pile. Verified: adding 1e-5 m to a cell leaves `has_material` false, adding
1.01e-3 m makes it true.

Nothing prevents a caller from driving `z` below `z0`. Doing so gives a negative thickness, a false
`has_material`, and a negative `volume_m3`. Measured on a 3 by 3 pad at base 100 m with one cell set
to 98 m: `thickness` is `-2.0`, `has_material` is `False`, `volume_m3()` is `-50.0`. The engine's own
operators never do this, because `ReclaimFace.bite` caps the depth of a cut at `model.thickness(c)`.

### 2.2 `TruckSpec` (`bedblend/terrain.py`), frozen

The machine whose dimensions set the scale of everything placed. Defaults are the CAT 793F, the
machine measured in the companion dumping study (Young and Rogers, Mining 2022, 2, 86-102,
doi:10.3390/mining2010006); body length and dump height are approximate published figures for the
class and are exposed as parameters rather than presented as exact.

| Field | Type | Unit | Default |
|---|---|---|---|
| `name` | `str` | text | `"CAT 793F"` |
| `payload_t` | `float` | t | `231.0` |
| `bed_width_m` | `float` | m | `7.334` |
| `body_length_m` | `float` | m | `12.9` |
| `dump_height_m` | `float` | m | `6.5` |
| `loose_density_t_m3` | `float` | t/m3 | `1.9` |

```
load_volume_m3 = payload_t / loose_density_t_m3
```

This is the single quantity that sizes every placement: 231.0 / 1.9 = 121.578947 m3 per load with the
defaults. `dump_height_m` is declared and carried but is not read by any operator in the package.

### 2.3 `Material` and `SizeSplit` (`bedblend/material.py`), frozen

| `Material` field | Type | Unit | Default |
|---|---|---|---|
| `name` | `str` | text | `"ROM ore"` |
| `insitu_density_t_m3` | `float` | t/m3 | `2.70` |
| `swell` | `float` | fraction of in situ volume | `0.38` |
| `max_compaction` | `float` | fraction of loose volume | `0.10` |
| `repose_dry_deg` | `float` | degrees | `37.0` |
| `moisture` | `float` | fraction of dry mass | `0.03` |
| `saturation_moisture` | `float` | fraction of dry mass | `0.20` |
| `d50_mm` | `float` | mm | `120.0` |
| `coarse_fraction` | `float` | fraction | `0.35` |
| `repose_coarse_deg` | `float` | degrees | `40.0` |
| `repose_fine_deg` | `float` | degrees | `34.0` |

`DEFAULT_MATERIAL` is exactly `Material()`, verified by equality.

The density chain. Rock in the ground, rock as tipped, and rock after traffic are three different
numbers, and carrying one figure for all three means tonnage and volume cannot both be right:

```
loose_density     = insitu_density / (1 + swell)
compacted_density = loose_density / (1 - max_compaction)
density(passes)   = loose_density / (1 - max_compaction * (1 - exp(-k * passes)))
                    with k = 3 / PASSES_FOR_FULL_COMPACTION, PASSES_FOR_FULL_COMPACTION = 25.0
```

`insitu_density` is the solid rock density in t/m3, `swell` the fractional volume increase on
blasting and loading, `max_compaction` the fractional volume reduction achievable under traffic, and
`passes` a count of equipment passes over the layer. `exp(-3)` is about 5 percent, so 25 passes reach
about 95 percent of the achievable gain. Verified on the defaults: loose 1.956522, compacted
2.173913, `density_after_passes` returns 1.956522 at 0 or fewer passes, 2.103517 at 10, 2.161953 at
25 and 2.173912 at 100.

Moisture dependent repose. This is NOT a constant of the ore, and the module says so: the shape is a
published qualitative relationship, marked UNVERIFIED as a quantitative model in the docstring. What
is defensible is the direction and the existence of a peak.

```
w  = moisture supplied, or self.moisture when the argument is omitted
ws = saturation_moisture
d  = repose_dry_deg
p  = ws / 3                                  the peak, at a third of the way to saturation

w <= 0    :  repose = d
w >= ws   :  repose = 0.66 * d               cohesion is gone; a floor, not a measurement
otherwise :  repose = max(d + gain - drop, 0.66 * d)
             gain = 5 * sin(pi * min(w / ws, 1))
             drop = 0                            if w <= p
                  = (w - p) / (ws - p) * 8       if w >  p
```

Verified on the defaults (`d = 37`, `ws = 0.20`, so `p = 0.066667` and the floor is 24.42):

| moisture | 0 or less | 0.01 | 0.03 | 0.0666 | 0.10 | 0.15 | 0.199 | 0.20 and above |
|---|---|---|---|---|---|---|---|---|
| `repose_deg` | 37.000 | 37.782 | 39.270 | 41.328 | 40.000 | 35.536 | 29.139 | 24.420 |

The curve is discontinuous at saturation. Measured, `repose_deg(0.199999)` is 29.000139 and
`repose_deg(0.20)` is 24.42, a jump of 4.58 degrees across an arbitrarily small change in moisture.
That is a property of the piecewise definition, not of any material, and a caller sweeping moisture
across saturation will see a step. `is_wet()` is the plain test `moisture >= saturation_moisture`,
so 0.199 is dry and 0.200 is wet.

`SizeSplit` is the two species split and it is the one input type that validates itself:

| Field | Type | Unit | Default |
|---|---|---|---|
| `coarse` | `float` | fraction | required |
| `fine` | `float` | fraction | required |

`__post_init__` raises `ValueError` when `coarse + fine` is zero or negative, or when it differs from
one by more than 1e-9. Verified: `SizeSplit(0.5, 0.4)` raises with the message
`a size split must sum to one, got coarse+fine = 0.9`; `SizeSplit(0.5, 0.5 + 1e-10)` is accepted;
`SizeSplit(0.5, 0.5 + 1e-8)` raises. It checks the SUM and nothing else, so `SizeSplit(1.5, -0.5)`
is accepted: a negative species fraction is not caught. Use the classmethod `SizeSplit.of(c)`, which
clamps: `of(1.4)` gives `(1.0, 0.0)` and `of(-0.2)` gives `(0.0, 1.0)`.

### 2.4 The stream: `DigBlock`, `DigSequence`, `Payload`

`DigBlock` (`bedblend/stream.py`, frozen) is one ore control block, and it is the correlated unit:
block grades are drawn once and every load from that block sits near it.

| Field | Type | Unit | Default |
|---|---|---|---|
| `index` | `int` | block identifier | required |
| `grade` | `float` | dimensionless | required |
| `n_loads` | `int` | count of truck loads | required |
| `bench` | `int` | pit bench index | `0` |

`DigSequence` (frozen) holds `blocks: list[DigBlock]` and a `n_loads` property that sums them. The
dataclass is frozen but the list it holds is not, so the sequence is only shallowly immutable.

`Payload` (`bedblend/truck.py`, mutable) is what a truck carries.

| Field | Type | Unit | Default |
|---|---|---|---|
| `tonnes` | `float` | t | required |
| `grade` | `float` | dimensionless | required |
| `source_block` | `int` | `DigBlock.index` | required |
| `grade_uncertainty` | `float` | fraction, relative | `0.0` |

`grade_uncertainty` carries the published ore control misclassification, 5 to 20 percent for base and
precious metal mines, and `payloads_from` defaults it to 0.12, the middle of that band. It is CARRIED
AND AVERAGED ONLY. Grepping the package for `grade_uncertainty` finds the field on `Payload`, on
`Parcel`, on `Cut`, the plumbing that copies it between them, and the tonnage weighted average in
`bedblend/reclaim.py`. Nothing perturbs a grade with it. A caller that wants an uncertainty band has
to apply it downstream.

Generators:

```
dig_sequence(*, n_loads, seed, loads_per_block=20, mean_grade=0.62, block_sd=0.16,
             bench_trend=0.0, n_benches=1) -> DigSequence
payloads_from(seq, *, seed, tonnes_per_truck=231.0, truck_spread=0.06,
              within_block_sd=0.02, grade_uncertainty=0.12) -> list[Payload]
measured_range_t(payloads, *, n_lags=30) -> float
cumulative_tonnes(payloads) -> list[float]
```

`loads_per_block` is the shovel's dwell and it is what sets the stream's correlation length;
`measured_range_t` REPORTS the practical range of the stream that came out, in tonnes, as the lag at
which the experimental semivariogram first reaches 95 percent of the series variance. It returns
`0.0` rather than raising in three cases, all verified: fewer than four payloads, zero grade
variance, and zero total tonnage.

`dig_sequence(n_loads=0, ...)` returns `DigSequence(blocks=[])` and `payloads_from` on it returns an
empty list. Both generators clamp grade at zero: asking for `mean_grade=0.05, block_sd=1.0` produced
block grades `[3.08659, 2.54673, 0.0, 0.0]`, where the two negatives were clamped rather than
rejected.

### 2.5 The plan: `Area`, `Bench`, `DumpPlan`, `TipPosition`

`Area` (`bedblend/design.py`, mutable) is a named working region, an axis aligned rectangle in pad
metres. A general polygon is the honest representation of a real dump location polygon and the
rectangle is a stated simplification.

| Field | Type | Unit | Default |
|---|---|---|---|
| `name` | `str` | text | required |
| `x0_m`, `y0_m`, `x1_m`, `y1_m` | `float` | m, pad coordinates | required |
| `benches` | `list[Bench]` | schedule | `[]` |
| `material_class` | `str` | free text label, never branched on | `""` |
| `access_xy` | `tuple[float, float] \| None` | m | `None` |
| `ramp_width_m` | `float` | m | `25.0` |

`__post_init__` raises `ValueError` when `x1_m <= x0_m` or `y1_m <= y0_m`, message
`area 'a' has a non-positive extent`. When `access_xy` is `None` the `access` property returns the
midpoint of the `+y` edge, `((x0 + x1) / 2, y1)`, not a corner: verified as `(45.0, 90.0)` for a
0 to 90 square.

`Bench` (frozen): `index: int`, `top_m: float` in metres above the pad datum, and
`designed_volume_m3: float`. It has no validation, so a negative `top_m` or a negative
`designed_volume_m3` is accepted. `designed_volume_m3` is what terminates the edge campaign, and
`rectangular_yard` computes it as a rectangular frustum at repose by the prismatoid rule rather than
as a fraction of a box:

```
inset = h / tan(repose)
w_t   = max(w - 2 * inset, 0)          top face width
l_t   = max(l - 2 * inset, 0)          top face length
V     = (h / 6) * (w * l + 4 * ((w + w_t)/2) * ((l + l_t)/2) + w_t * l_t)
```

`w` and `l` are the base footprint in metres, `h` the bench height in metres, `repose` in degrees.
Verified: a 40 m by 40 m area 4 m high at 37 degrees gives 4851.66 m3, which at the default load
volume is a programme of 40 loads.

`DumpPlan` (mutable) is the whole design.

| Field | Type | Unit | Default |
|---|---|---|---|
| `areas` | `list[Area]` | | required |
| `row_spacing_m` | `float` | m between paddock rows | `25.0` |
| `tip_spacing_m` | `float` | m between loads along a row | `3.0` |
| `loads_per_dozer_pass` | `int` | placed loads between ACCESS passes | `12` |
| `loads_per_full_pass` | `int` | placed loads between FULL passes | `60` |
| `lift_thickness_m` | `float` | m | `1.5` |
| `repose_deg` | `float` | degrees, used to inset the lifts | `37.0` |
| `sweep_advance_frac` | `float` | fraction of run out per sweep | `0.6` |
| `seed_frac_x`, `seed_frac_y` | `float` | fraction across the area | `0.25` |

`plan.area(name)` raises `KeyError` listing the names it does have; `plan.area_at(x, y)` returns
`None` off every footprint rather than raising.

`TipPosition` (frozen) is one intended discharge: `x_m`, `y_m`, `heading_rad`, `phase` (`Phase.PADDOCK`
or `Phase.EDGE`), `area` name, `bench` index, `seq`. All required. For an edge dump the heading is
provisional; execution resolves it against the live crest normal.

`rectangular_yard` is the convenience constructor:

```
rectangular_yard(*, n_areas, area_width_m, area_length_m, bench_height_m, n_benches,
                 gap_m=20.0, classes=None, repose_deg=37.0, ramp_width_m=25.0,
                 margin_m=30.0) -> DumpPlan
```

`margin_m` offsets the areas from the pad origin, which matters: with the areas flush against it a
dump on the south or west edge cascades off the grid and the load is refused for having nowhere to
land. It raises `ValueError` when `classes` is shorter than `n_areas`.

### 2.6 The machines: `Fleet`, `Truck`, `Route`

`Fleet.of(n, spec, shovel_xy, *, repose_deg=37.0, grade_limit_divisor=1.5)` derives the gradient
limit with its provenance stated:

```
max_grade = tan(repose_deg) / grade_limit_divisor          dimensionless rise over run
```

The divisor is the commonly repeated operational rule of thumb that trucks should not work slopes
approaching the angle of repose. It is NOT a measured constant; it is a parameter so a reader can see
and change it. At the defaults `max_grade` is 0.502369.

`Fleet` holds `trucks: list[Truck]`, `shovel_xy: tuple[float, float]` in pad metres, and
`max_grade: float`. `Truck` holds `truck_id`, `spec`, position `x_m`/`y_m`, `heading_rad`, a
`CycleState` (`loading, haul_loaded, queued_at_dump, spotting, dumping, haul_empty,
queued_at_shovel`), an optional `Payload`, retained `approach` and `departure` `Route`s, and an
optional `assigned_tip`. `Route` holds `points: list[tuple[float, float]]`, the simplified polyline
in pad metres, and `cells: list[int]`, the unsimplified grid path. Both are kept because the per step
gradient rule is only meaningful between adjacent cells: applying it to consecutive simplified points
divides a fifty metre segment's rise by one cell width.

### 2.7 The reclaim machine: `LoaderSpec`, `ReclaimFace`

`LoaderSpec` (frozen). The defaults are the working envelope of the large hydraulic front shovel
class and are a declared parameter of the run, not a measured fit to a particular machine.

| Field | Type | Unit | Default |
|---|---|---|---|
| `name` | `str` | text | `"hydraulic front shovel, 60 t payload class"` |
| `bucket_m3` | `float` | m3 | `34.0` |
| `payload_t` | `float` | t | `60.0` |
| `dig_radius_m` | `float` | m, reach from one stance | `15.0` |
| `max_cut_height_m` | `float` | m | `15.0` |

`passes_for(load_t, bulk_density_t_m3)` returns `load_t / (bucket_m3 * bulk_density_t_m3)` and clamps
a negative `load_t` to zero. It takes the density as an argument because a bucket is a volume; an
earlier version divided the machine's own payload by its own bucket volume and returned a density
under the name of a count.

`ReclaimFace` (mutable).

| Field | Type | Unit | Default |
|---|---|---|---|
| `method` | `ReclaimMethod` | `lifo`, `fifo`, `full_height` | `FULL_HEIGHT` |
| `position_m` | `float` | m along `direction` from the pad origin | `0.0` |
| `direction` | `tuple[float, float]` | unit vector in pad coordinates | `(1.0, 0.0)` |
| `depth_m` | `float` | m one cut reaches into the pile | `5.0` |
| `width_m` | `float` | m across face extent of the FACE | `30.0` |
| `max_face_m` | `float` | m safe working face height | `15.0` |
| `loader` | `LoaderSpec` | | `LoaderSpec()` |
| `offset_m` | `float` | m across the face from the near edge | `0.0` |
| `centre_t_m` | `float \| None` | m along the across face axis | `None` |
| `origin_m` | `float` | m, `init=False`, set to `position_m` in `__post_init__` | `0.0` |

`centre_t_m` defaults to the middle of the pad, which is only right when the pile is pad centred. A
yard tiles several areas and each face belongs to one of them, so a caller that knows the area should
pass its centre. `direction` is normalised internally; a degenerate `(0, 0)` direction makes
`engaged_cells` return an empty list and `stance` return `(0.0, 0.0)` rather than raising.

---

## 3. Outputs

### 3.1 `LoadRecord` (`bedblend/build.py`), mutable

One truck load from dispatch to placement. This is the event log, and it is the only place a refusal
is reported.

| Field | Type | Unit | Default |
|---|---|---|---|
| `seq` | `int` | position in the arrival stream | required |
| `area` | `str` | area name | required |
| `bench` | `int` | bench index, `-1` on a built out refusal | required |
| `phase` | `Phase` | `paddock` or `edge` | required |
| `truck_id` | `int` | `-1` when no truck was dispatched | required |
| `x_m`, `y_m` | `float` | m, where the truck ACTUALLY stood | required |
| `grade` | `float` | dimensionless | required |
| `source_block` | `int` | | required |
| `placed` | `bool` | | required |
| `planned_x_m`, `planned_y_m` | `float` | m, where the plan asked for the load | `0.0` |
| `spot_offset_m` | `float` | m between planned and actual | `0.0` |
| `profile` | `DumpProfile \| None` | | `None` |
| `distance_to_crest_m` | `float` | m | `0.0` |
| `heading_rad` | `float` | radians | `0.0` |
| `length_m`, `width_m` | `float` | m, REALISED, measured off the placed field | `0.0` |
| `max_thickness_m` | `float` | m | `0.0` |
| `approach`, `departure` | `Route \| None` | | `None` |
| `segregation_index` | `float` | difference in coarse fraction, toe half minus crest half | `0.0` |
| `sr` | `float` | segregation number the layer was solved at | `0.0` |
| `overrun_fraction` | `float` | fraction of the load past the toe | `0.0` |
| `overrun_coarse_fraction` | `float` | fraction | `0.0` |
| `drop_m` | `float` | m the load fell | `0.0` |
| `refused_reason` | `str` | empty when placed | `""` |

`segregation_index` is the MEASURED sorting of this load, not the strength of the drivers. It used to
be `intensity`, which is an input to the physics rather than a result of it. `sr` is exposed beside it
so a reader can check the driver and the result separately. Both are zero for a paddock heap, which
has no face to sort along, verified across every paddock record of a 240 load build.

Sample from a real run, the last placed record of a 240 load build on a 64 by 64 pad at 2.5 m:

```
seq 239, area ROM, bench 0, phase edge, truck_id 3
x_m 36.618  y_m 98.407   planned (36.618, 98.407)   spot_offset_m 0.0
profile oval   distance_to_crest_m 0.503   heading_rad -1.9554
length_m 12.707   width_m 14.583   max_thickness_m 1.9692
segregation_index 0.15911   sr 0.43702   overrun_fraction 0.00491
overrun_coarse_fraction 0.93942   drop_m 2.63
approach 20 points, departure 25 points, refused_reason ""
```

### 3.2 `BuildResult` (`bedblend/build.py`), mutable

| Field | Type | Unit | Default |
|---|---|---|---|
| `terrain` | `Terrain` | the mutated input, not a copy | required |
| `model` | `BlockModel` | | required |
| `loads` | `list[LoadRecord]` | one per offered payload | `[]` |
| `dozer_passes` | `list[DozerPass]` | | `[]` |
| `snapshots` | `list[tuple[int, int, list[float]]]` | `(seq of the load just placed, loads placed so far, copy of z)` | `[]` |

Properties `placed`, `refused`, `refusal_rate` (which is `0.0` on an empty load list rather than a
division error) and the method `profile_counts()`. A real 240 load build gave
`{'paddock': 75, 'oval': 97, 'comet': 37, 'rectangular': 28, 'sloughed_heap': 3}`, 20 dozer passes
and, with `snapshot_every=50`, snapshots at `(49, 50)`, `(99, 100)`, `(149, 150)`, `(199, 200)` and a
closing `(240, 240)`, each carrying 4096 floats for the 64 by 64 pad.

`DozerPass` (`bedblend/dozer.py`) carries `transfers: list[tuple[int, int, float]]` as
`(from_cell, to_cell, volume_m3)`, `volume_moved_m3`, `mean_displacement_m`, `max_displacement_m` and
`cells_touched`, all defaulting to empty or zero.

### 3.3 `Parcel` and `BlockModel` (`bedblend/blocks.py`), the ledger

`Parcel` is one placement's contribution to one column, as a vertical interval. The support is the
truck load, because that is the unit that was measured, hauled and placed.

| Field | Type | Unit | Default |
|---|---|---|---|
| `z0_m`, `z1_m` | `float` | m, see the datum caveat below | required |
| `grade` | `float` | dimensionless | required |
| `source_block` | `int` | | required |
| `event_id` | `int` | the `LoadRecord.seq` that placed it | required |
| `lift` | `int` | bench index | required |
| `area` | `str` | area name | required |
| `grade_uncertainty` | `float` | fraction, relative | `0.0` |
| `displacement_m` | `float` | m accumulated since it was tipped | `0.0` |
| `coarse_fraction` | `float` | fraction, local to THIS parcel | `0.0` |

`thickness_m` is `max(0.0, z1_m - z0_m)`.

**The vertical datum of a parcel is not guaranteed to be terrain elevation.** `record` files a parcel
against the terrain (`z0_m = terrain.z[c] - dz`, `z1_m = terrain.z[c]`), so a freshly tipped parcel is
in true elevation. But `_stack_onto` restarts a column at `base_z(c)`, which returns `0.0` for an
empty column, and `_restack` in `bedblend/reclaim.py` re-lays a column from `0.0` after a FIFO or full
height removal. Measured on a build whose pad sits at 100 m: of 474 columns carrying material, 312
had their top parcel exactly at the terrain elevation and 162 were rebased, sitting exactly 100.0 m
low. Demonstrated directly on a 3 by 3 pad at base 100 m: two records produce parcels spanning
`(100.0, 102.0)` and `(102.0, 103.0)`; after one FIFO cut the same column reads `(0.0, 0.947)` and
`(0.947, 1.947)` while the terrain stands at 101.9474.

The invariant the engine asserts is on THICKNESS, not on elevation, and it still passes in that state.
Anything that consumes `Parcel.z0_m` or `Parcel.z1_m` as an absolute elevation, including the `k`
index of `to_blocks`, has to account for this. The fix would be for `base_z` to return the terrain's
`z0[c]` and for `_restack` to start there; the docstring on `base_z` already records that the ground
offset is left to the caller.

`BlockModel`:

| Field | Type | Unit | Default |
|---|---|---|---|
| `nx`, `ny` | `int` | cells | required |
| `cell_m` | `float` | m | required |
| `columns` | `list[list[Parcel]]` | one stack per cell, bottom up | `[]` |
| `bulk_density_t_m3` | `float` | t/m3 | `1.9` |

```
cell_area_m2 = cell_m^2
thickness(c) = sum of parcel thicknesses in column c            metres
tonnes(c)    = thickness(c) * cell_area_m2 * bulk_density_t_m3  tonnes
```

`column_grade(c)` and `column_coarse(c)` are thickness weighted and return `None`, not zero, where
the column is empty; `grade_field()` and `coarse_field()` are therefore `list[float | None]`.
`mean_displacement_m()` is the thickness weighted mean over the whole model, and it is the headline
honesty number: how far, on average, material has moved from where its dump record says it was
tipped. A 240 load build measured 22.0448 m.

`to_blocks(dz_m=5.0)` exports a regular lattice as `(i, j, k, grade, tonnes)` and is a VIEW computed
on demand. Verified on a real build with `dz_m=2.0`: 782 blocks, `k` from 0 to 52, and the block
tonnage sums to 10626.0 against `total_tonnes()` of 10626.0.

`assert_consistent(terrain, tol_m=1e-6)` raises `AssertionError` naming the worst cell, for example
`the ledger and the terrain disagree by 3 m at cell 2: ledger 0 m, terrain 3 m`.

### 3.4 `Cut` and `HaulCycle` (`bedblend/reclaim.py`)

`Cut` is one parcel of material delivered to the plant.

| Field | Type | Unit | Default |
|---|---|---|---|
| `tonnes` | `float` | t | required |
| `grade` | `float` | dimensionless, tonnage weighted | required |
| `provenance` | `dict[int, float]` | `source_block` to tonnage fraction, sums to one | `{}` |
| `displacement_m` | `float` | m, tonnage weighted | `0.0` |
| `grade_uncertainty` | `float` | fraction, tonnage weighted | `0.0` |
| `cells` | `list[int]` | the ground actually dug | `[]` |
| `coarse_fraction` | `float` | fraction, tonnage weighted | `0.0` |
| `stand` | `tuple[float, float] \| None` | m, where the truck parked | `None` |
| `approach`, `departure` | `list[tuple[float, float]]` | m, polylines | `[]` |
| `approach_cells`, `departure_cells` | `list[int]` | grid paths | `[]` |
| `loader` | `tuple[float, float] \| None` | m, centroid of `cells` | `None` |

Note the asymmetry with `LoadRecord`: a load carries `Route` objects, a cut carries bare point lists
plus separate cell lists. `HaulCycle.apply_to(cut)` is what performs that conversion, and it exists as
a record rather than a tuple because positional unpacking of five values at two call sites is how a
caller silently assigns the departure to the approach.

Measured on the first three cuts of a real six cut campaign at 1500 t: `provenance` spanned 8 to 12
dig blocks and summed to 1.000000000 in each, `displacement_m` ran 0.98, 1.34 and 13.40 m,
`coarse_fraction` 0.408, 0.339 and 0.345, and `grade_uncertainty` was 0.12 in all three because that
is what every payload carried.

`HaulCycle` (frozen) holds `stand`, `loader`, `approach: Route | None` and `departure: Route | None`.
`stand is None` is the refusal signal.

### 3.5 `Rollup` and `Comparison` (`bedblend/sectors.py`), frozen

| `Rollup` field | Type | Unit |
|---|---|---|
| `name` | `str` | text |
| `tonnes` | `float` | t |
| `mean_grade` | `float` | dimensionless |
| `stdev` | `float` | dimensionless |
| `n` | `int` | count of observations, not of tonnes |
| `ci` | `dict[float, float]` | confidence level to HALF WIDTH on the mean |

```
mean = sum(v_i * w_i) / sum(w_i)
var  = sum(w_i * (v_i - mean)^2) / sum(w_i)
sd   = sqrt(var)
se   = sd / sqrt(n)
ci[level] = z(level) * se        z = 1.6448536269514722, 1.959963984540054, 2.5758293035489004
```

`v_i` is a column grade, `w_i` its tonnage, `n` the number of columns that contributed. The standard
error uses the COUNT, not the weight total: the weights express how much material each observation
speaks for, not how many independent measurements were made. `CONFIDENCE_LEVELS` is
`(0.90, 0.95, 0.99)` and `ci` carries exactly those three keys. `interval(level)` uses
`ci.get(level, 0.0)`, so an unknown level returns `(mean, mean)` rather than raising.

Verified on a real area: tonnes 5883.57, mean 0.33252, sd 0.00789, n 256, ci
`{0.9: 0.000811, 0.95: 0.000967, 0.99: 0.001271}`, which is `1.959964 * 0.00789 / sqrt(256)` for the
middle one.

An area with no material returns a fully zeroed `Rollup` with `n = 0` and every `ci` entry zero, not
`None` and not an exception.

`Comparison` holds `region`, `data` and `model`, both `Rollup`. `compare` builds the data side from
`observations: list[tuple[x, y, grade]]` filtered to the area, with UNIT weights and
`tonnes = 0.0` always, so `Comparison.data.tonnes` is structurally zero and means nothing.
`model_is_tighter(level)` compares the two half widths.

`homogeneity_map(model, terrain, *, window=3)` returns `list[float | None]`, `None` where fewer than
three columns in the neighbourhood carry material rather than a zero that would read as perfect
uniformity.

### 3.6 `Placement`, `FaceSegregation`, `Avalanche`

`Placement` (`bedblend/dump.py`, frozen) is what one dump did: `profile`, parallel `cells: list[int]`
and `added_m: list[float]` in metres, `volume_m3`, and the REALISED `length_m`, `width_m` and
`max_thickness_m` measured back off the placed field rather than copied from the request.
`heading_rad`, `distance_to_crest_m`, and `s_frac: list[float]`, the down face position of each cell
with 0 at the crest and 1 at the toe, empty for a paddock heap.

`FaceSegregation` (`bedblend/facesegregation.py`, frozen) carries `coarse_profile` and `fine_profile`
as per bin shares of each species, `overrun_fraction`, `intensity`, `drop_m`, `face_angle_deg`,
`overrun_coarse_fraction` and an optional `Avalanche`. `Avalanche` carries `path_m`, `layer_h_m`,
`u_ms`, `q_ms`, `sr` and `flows`. `flows` is false when the face stands below the material's dynamic
friction angle, and then nothing sieves.

That last point is observable end to end, on the 40 load programme of section 2.5: one 40 m by 40 m
area with a single 4 m bench, on a 64 by 64 pad at 2.5 m, which places 7 paddock heaps and 33 edge
dumps. Run with `Material(repose_dry_deg=52.0, coarse_fraction=0.9, d50_mm=5.0, ...)` it produced
`sr = 0.0` on every one of the 40 placed loads and recorded a flat coarse fraction of exactly 0.900,
because a 37 degree face does not avalanche for a material whose dynamic friction angle is 48. The
same programme with the default material produced 24 loads with a nonzero `sr` and a coarse field
spanning 0.1545 to 0.6722 around a mean of 0.3372, against a placed 0.35. On a longer 240 load build
the recorded coarse field spanned 0.2438 to 0.8443 around a mean of 0.3499, which is the sorting the
face put into the ledger. Both means are over the non `None` entries of `coarse_field()`.

---

## 4. What crosses the boundary and is NOT read

Three groups of fields are part of the contract but are inert inside the engine. Naming them is the
point of this section: a caller that sets them expecting an effect will not get one.

**The whole moisture and density chain of `Material`.** Grepping the package for reads of `mat.` and
`material.` outside `bedblend/material.py` finds five, over three distinct fields: `coarse_fraction`
three times (`bedblend/build.py` line 470, `bedblend/facesegregation.py` lines 270 and 312), `d50_mm`
once and `repose_dry_deg` once (both in `avalanche_state`). `moisture`, `saturation_moisture`,
`is_wet()`, `repose_deg()`,
`insitu_density_t_m3`, `swell`, `max_compaction`, `loose_density_t_m3`, `compacted_density_t_m3`,
`density_after_passes`, `tonnes_from_loose_m3`, `loose_m3_from_tonnes` and `insitu_m3_from_tonnes`
are never called by the engine. `repose_coarse_deg` and `repose_fine_deg` are read only through
`SizeSplit.blended_repose_deg`, which only `apparent_repose_deg` calls.

Verified end to end: two identical 40 load builds, one with `Material()` and one with
`Material(moisture=0.60)` whose `is_wet()` is true and whose `repose_deg()` is 24.42, produced
BYTE IDENTICAL terrain. So did a build with a wholly different material (`insitu_density_t_m3=4.0`,
`swell=0.6`, `repose_dry_deg=52.0`, `d50_mm=5.0`, `coarse_fraction=0.9`). The angle the pile is
relaxed to comes from `build(..., repose_deg=37.0, face_angle_deg=None)`, which are separate scalar
arguments. If a caller wants a wet pile to stand flatter, the caller must compute
`material.repose_deg()` and pass it as `repose_deg`.

**`Payload.tonnes`.** It appears nowhere in `bedblend/build.py` or `bedblend/dump.py`. The volume
placed is `TruckSpec.load_volume_m3` and nothing else. Verified: three 40 load builds with payloads
declared at 231 t, 1,000,000 t and -231 t produced byte identical terrain and an identical ledger
tonnage of 9240.0 t. `Payload.tonnes` is consumed only by the stream statistics
(`measured_range_t`, `cumulative_tonnes`) and by whatever the caller passes to
`tonnage_weighted_variance`.

**Three densities that are not reconciled.** `TruckSpec.loose_density_t_m3` (default 1.9) sizes the
placement, `BlockModel.bulk_density_t_m3` (default 1.9) converts thickness to tonnes, and
`Material.loose_density_t_m3` (derived, 1.956522 at the defaults) is used by neither. `build` always
calls `BlockModel.over(terrain)` with the default, so the ledger density can never be set through
`build` at all. At the defaults the two 1.9 values coincide and the ledger tonnage matches the stream
tonnage exactly: a 240 load build gave 29178.95 m3 of terrain and 55440.0 t of ledger against
240 times 231 = 55440 t of stream. Change one of them and they diverge silently. Verified with
`TruckSpec(loose_density_t_m3=1.6)`: 34 loads placed, ledger 9326.625 t, stream 7854.0 t, a
divergence of 1472.625 t that nothing raises on.

---

## 5. Bad data: what raises, what clamps, what is recorded

### 5.1 The summary

| Situation | Behaviour | Verified evidence |
|---|---|---|
| Size split not summing to one | RAISES `ValueError` | `a size split must sum to one, got coarse+fine = 0.9` |
| Size split summing to one with a negative species | ACCEPTED | `SizeSplit(1.5, -0.5)` constructs |
| `SizeSplit.of(c)` with `c` outside [0, 1] | CLAMPS | `of(1.4)` gives `(1.0, 0.0)` |
| Grade of exactly zero | ACCEPTED, never treated as missing | recorded and returned by `column_grade` as `0.0` |
| Negative grade from a generator | CLAMPED at zero | block grades came out `[..., 0.0, 0.0]` |
| Negative grade on a hand built `Payload` | ACCEPTED, no validation | `Payload(-100.0, -1.0, -5)` constructs |
| Negative or absurd `Payload.tonnes` | IGNORED by the build entirely | identical terrain and ledger at 231, 1e6 and -231 t |
| Moisture past saturation | CLAMPS `repose_deg` to `0.66 * repose_dry_deg`, `is_wet()` true, and has NO effect on the build | 24.42 degrees at any moisture at or above 0.20 |
| Ground array of the wrong length | RAISES `ValueError` | `ground has 8 cells, pad is 3x3=9` |
| Area with non positive extent | RAISES `ValueError` | `area 'a' has a non-positive extent` |
| `Area.inset` by at least half the extent | RAISES `ValueError`, contrary to its own docstring | see 5.4 |
| Unknown area name from `DumpPlan.area` | RAISES `KeyError` listing the valid names | |
| Point outside every area, `DumpPlan.area_at` | RETURNS `None` | |
| Shovel placed inside a dump area | RAISES `ValueError` before any load is run | see 5.2 |
| Router returning an unplanned area name | RAISES `KeyError` | see 5.2 |
| Planned tip unreachable | RECORDED as a refusal with a reason | see 5.3 |
| Area programme exhausted | RECORDED as a refusal with a reason | see 5.3 |
| Load with an empty footprint | RECORDED as a refusal with a reason | see 5.3 |
| `cut` with zero or negative tonnage | RETURNS an empty `Cut(0.0, 0.0)` | verified at 0.0 and -500.0 |
| `cut` on ground with nothing on it | RETURNS an empty `Cut(0.0, 0.0)` | |
| `next_cut` with nothing left | RETURNS `None`, which ends a campaign | `campaign` on an empty pad returns `[]` |
| Cut that no truck can reach | `HaulCycle.stand is None`, cut still delivered | see 5.5 |
| `record` with mismatched list lengths | RAISES `ValueError`, NOT atomic | see 5.4 |
| Ledger and terrain disagreeing | RAISES `AssertionError` naming the worst cell | `assert_consistent` |
| Surface left over the angle of repose | RAISES `ReposeViolation` (an `AssertionError`) | see 5.6 |
| Zero divisors on `Material` and `TruckSpec` | RAISE `ZeroDivisionError`, unguarded | `swell = -1.0`, `max_compaction = 1.0`, `loose_density_t_m3 = 0.0` |
| Negative payload or negative density | ACCEPTED, produce negative volumes and densities | `TruckSpec(payload_t=-231).load_volume_m3` is -121.579; `Material(insitu_density_t_m3=-1).loose_density_t_m3` is -0.7246 |

### 5.2 Caller errors that stop the build before it starts

Two conditions are checked eagerly, because both otherwise show up as a wall of refusals whose cause
is invisible.

The shovel must be outside every dump area. `build` raises:

```
ValueError: the shovel at (60.0, 60.0) is inside dump area 'ROM'. The first load placed there
will bury the loading point and every later load will be refused for having no drivable start.
Put the shovel outside every area's footprint.
```

A router must name an area that exists:

```
KeyError: "the router sent a load to area 'NOPE', which is not in the plan; the plan has ['ROM']"
```

The routed load is NOT silently redirected. Redirecting it would break the one guarantee routing
exists to provide, that a class ends up where it was sent.

### 5.3 Refusals: recorded, never dropped

A load the pile will not accept is appended to `BuildResult.loads` with `placed=False` and a
non empty `refused_reason`. It is never removed from the list, so `len(result.loads)` always equals
the number of payloads offered and `refusal_rate` is meaningful. There are four kinds of reason.
Three are authored in `bedblend/build.py`; the fourth is propagated verbatim from `NoRoute`, whose
three message forms are raised in `bedblend/truck.py`.

**The area is built out.** Its planned programme is complete and there is nothing left to serve:

```
area 'ROM' is built out; its planned programme is complete
```

The record is a stub: `bench = -1`, `truck_id = -1`, `x_m = y_m = 0.0`, `profile = None`,
`approach = departure = None`, but `grade` and `source_block` are still carried from the payload.
Verified by over feeding a 40 load programme with 160 payloads: 40 placed, 120 refused, refusal rate
0.75, every refusal with this reason.

**No drivable ground near the planned tip.** The truck could not be spotted anywhere inside the area
within `max_spot_offset_m` of the plan:

```
no drivable ground inside area 'ROM' within 25 m of the planned tip: the pile has grown over its
own access here
```

Verified by putting a 40 m bedrock ridge across the pad between the shovel and the dump area: 30 of
30 loads refused, all with this reason. Note that the plan is always tried first and an unreachable
tip is not an immediate refusal; the operator spots at the nearest reachable cell INSIDE THE AREA and
the deviation is recorded in `spot_offset_m`. Only when no such cell exists is the load refused. This
is also the one reason string the build reacts to: a refusal containing the substring
`no drivable ground` triggers an access only dozer visit, rate limited to at most one every two
loads, and the load is then retried once.

**No route.** Propagated verbatim from the `NoRoute` exception raised by `solve_route`, one of:

```
start (2.0, 2.0) or goal (500.0, 500.0) is off the pad
the truck cannot stand at its start (2.0, 2.0)
no drivable route to (26.25, 26.25): the pile has grown over its own access, or the tip sits on
ground steeper than the equipment limit
```

**Nowhere to land.** The placement operator returned an empty footprint:

```
the load had nowhere to land on the pad
```

Two code paths produce an empty `Placement`: the discharge point falls off the pad, verified with
`place_edge` at `(1000, 1000)` returning `cells=[]` and `volume_m3=0.0`, and a weight map that sums
to zero, verified with `run_out_m=0.0` returning zero cells.

A build that offers no payloads at all is not an error: it returns a `BuildResult` with zero loads,
zero dozer passes, an empty `profile_counts()` and `refusal_rate` of `0.0`.

### 5.4 Two places where the code and its own documentation disagree

**`Area.inset` raises where its docstring promises a degenerate area.** The docstring says "It clamps
rather than inverting, so a caller can ask for more inset than the area has and get a degenerate area
back to stop on". It does clamp the half extents at zero, but the `Area` it then constructs runs
through `__post_init__`, which rejects a zero extent. Measured on a 90 m square, half extent 45:
`inset(44.9)` gives a 0.2 m square, `inset(44.999)` gives 0.002 m, and `inset(45.0)` and `inset(60.0)`
both raise `ValueError: area 'A1' has a non-positive extent`. `bench_program` calls `inset` and only
then breaks out of its lift loop when the face is narrower than two tip spacings, so the guard is
checked after the constructor that raises. On the default lattice the guard still fires first,
because the per lift inset is `lift_thickness_m / tan(repose_deg)`, 1.9906 m at the defaults, which
is smaller than the 3.0 m tip spacing and so cannot step from a face wider than the guard straight
past zero. A plan whose per lift inset exceeds its tip spacing can make that jump. It would be fixed
either by clamping to a small positive extent or by relaxing `__post_init__` to allow a zero extent.

**`BlockModel.record` is not atomic.** It iterates `zip(cells, added_m, strict=True)`, appending as
it goes, so a length mismatch raises only when the shorter list runs out and every parcel before that
point has already been written. Verified: `record(terrain, [0, 1], [1.0], ...)` raises
`ValueError: zip() argument 2 is shorter than argument 1`, leaves one parcel on cell 0 and none on
cell 1, and a following `assert_consistent` then fails with
`the ledger and the terrain disagree by 1 m at cell 1: ledger 0 m, terrain 1 m`. A caller that
catches the `ValueError` and continues is carrying a corrupt ledger. Validate the lengths before
calling, or treat the exception as fatal.

### 5.5 A cut that cannot be served

`haul_cycle(terrain, cells, *, exit_xy, max_grade)` routes an empty truck in to the cut and a loaded
one back out, and it returns `HaulCycle(stand=None, loader=<centroid>)` when nothing drivable is
within reach, or when either leg cannot be routed. That is a real refusal and it is reported rather
than hidden. Verified by routing from an exit point off the pad: `stand` came back `None` with the
loader position still populated, and `apply_to` then left `Cut.stand` as `None` with
`approach`, `departure`, `approach_cells` and `departure_cells` all empty lists.

The material still leaves the ledger. A refused haul cycle does not cancel the cut, and `campaign`
appends the cut regardless. A consumer that wants only served cuts must filter on
`cut.stand is not None`.

Two constraints are worth stating because they are easy to trip. The truck stand excludes every cell
in `cut.cells`, so two machines cannot occupy one cell; before the bite became compact this exclusion
was not needed and its absence was measured as a loader to truck separation of exactly zero. And the
approach and departure are solved SEPARATELY, on the surface after the cut, with `strict_goal=True`
because the truck parks rather than tipping over an edge; if the departure fails to route the
approach is reversed as the only honest fallback.

One rough edge: `haul_cycle` with an empty `cells` list does not refuse. `_centroid(terrain, [])` returns
`(0.0, 0.0)`, so the function looks for the nearest drivable cell to the pad origin and returns a
stand there, measured as `(1.25, 1.25)` on a 2.5 m pad. `campaign` never calls it that way, because
a zero tonnage cut ends the campaign first, but a direct caller should not.

### 5.6 Surfaces left over the angle of repose

`assert_stable(terrain, repose_deg, *, tol_deg=STABLE_TOL_DEG)` raises `ReposeViolation`, a subclass of
`AssertionError`, and is called at the end of `settle` and by default at the end of `relax_to`:

```
ReposeViolation: 8 cell pairs stand more than 4.0 deg over the imposed repose angle of 37.0;
the worst local slope is 82.9 deg. Not relaxed.
```

`STABLE_TOL_DEG` is 4.0 and it is a PHYSICAL tolerance, not a numerical one: published handbook
repose values for ores span 34 to 60 degrees, so asserting a surface to a micrometre against a
quantity known to a few degrees is asserting the wrong thing. The counter itself skips two cases that
no solver can fix, and both matter to anyone reading the number: a cell carrying less than
`BARE_M = 1e-3` m of material is not asked to stand at an angle of repose, and a pair whose steepness
survives removing every grain the cell holds is inherited from the ground rather than from the fill.

Related tolerances, all in `bedblend/relax.py`: `CONVERGE_TOL_M = 1e-9` for the solver,
`VERIFY_TOL_M = 1e-6` for the checker (deliberately looser, because a converged field accumulates
rounding and was measured at 37.00000004 degrees against an imposed 37), and `MAX_MOVES = 2000000`
as a backstop.

---

## 6. Clamps and silent fallbacks worth knowing

These do not raise and do not appear in any record, so they are invisible unless you look for them.

`run_out_for_bench(bench_height_m, face_angle_deg)` clamps the angle into [1, 89] degrees before
taking the tangent. Verified: at a bench height of 8 m, an angle of 0 and an angle of 1 both give
458.3197 m, and angles of 89, 90 and 179 all give 0.1396 m. A negative bench height passes straight
through and gives a negative run out, -10.6164 m at 37 degrees.

`classify(distance_to_crest_m, truck, *, rand=0.5, slough_truck_lengths=1.0)` returns
`SLOUGHED_HEAP` for any distance past one body length, including infinity, and otherwise walks the
measured frequencies of oval, comet and rectangular (12, 6 and 4 of the 28 classified dumps in
Mining 2022 table 5). A `rand` outside [0, 1) is not rejected: `rand=1.0` falls through to the
trailing `return DumpProfile.OVAL` and `rand=-5.0` selects oval as the first bucket. Verified all
four cases.

`place_edge` with no usable face falls back to `place_paddock`, returning `profile=PADDOCK`,
`s_frac=[]` and `distance_to_crest_m=inf`. Verified on genuinely flat ground.

`distance_to_crest(terrain, x, y, crest)` returns `inf` on an empty crest list, which is the correct
answer on an empty pad and is what makes every early load a paddock heap.

`Terrain.outward_normal(c)` returns `(0.0, 0.0)` on a flat cell. The caller decides what that means,
which is usually that the load is a heap rather than a cascade.

`solve_route` exempts the GOAL cell from the gradient test unless `strict_goal=True`, because a truck
spots at the crest and the crest is by definition steep on one side. Verified: a goal on a 50 m tower
raises `NoRoute` with `strict_goal=True` and returns a two point route without it. A caller routing a
truck somewhere it will merely PARK has to set `strict_goal=True`; `haul_cycle` does.

`reachable_mask` deliberately includes one ring of cells beyond the flood filled set, even when those
cells are too steep to stand on, because standing at the lip of a face is exactly what an edge dump
requires.

`next_cut` bounds how far the machine will tram for one parcel at one sweep of the face,
`max(2, ceil(width_m / (2 * dig_radius_m)))` stances, with `MAX_STANCES_TRIED = 4096` as a
pathological backstop. A face that cannot supply the tonnage returns a SHORT cut rather than sweeping
the yard to hide it. Verified in a real campaign: the first of six 1500 t cuts came back at 589.85 t.

---

## 7. Engine version reported alongside a result

`bedblend.__version__` is read at import from installed packaging metadata,
`importlib.metadata.version("bedblend")`, falling back to `"0.0.0+unknown"` in a source tree that was
never installed. It is not read from the `VERSION` file or from `pyproject.toml`. In this working
tree the three disagree, and the value even depends on the working directory, because the resolver
picks up whichever distribution metadata is first on `sys.path`: importing from the repository root
reports `0.7.1` from the local `bedblend.egg-info`, importing the same source from elsewhere reports
`0.5.0` from the virtual environment's `dist-info`, while `pyproject.toml` declares `0.07.002`.
Anything that logs the engine version beside a result should record how it obtained it, or reinstall
before the run.

---

## 8. References, as the source code cites them

Only the citations that appear in the engine's own docstrings are listed. The Minerals 2021 paper is
cited throughout the code by journal, volume and article number without a DOI.

* Gray, J.M.N.T. and Thornton, A.R. (2005), a theory for particle size segregation in shallow granular
  free surface flows, Proc. R. Soc. A 461, 1447-1473. doi:10.1098/rspa.2004.1420
  (cited in `bedblend/segregation.py`)
* Gray, J.M.N.T. and Chugunov, V.A. (2006), particle size segregation and diffusive remixing in
  shallow granular avalanches, J. Fluid Mech. 569, 365-398. doi:10.1017/S0022112006002977
  (cited in `bedblend/segregation.py`). The title above is the real one; the comment in
  `bedblend/segregation.py` that carries this DOI repeats the 2005 paper's title instead, so a reader
  matching titles between the two entries will think they are the same paper. Journal, volume, pages
  and DOI in the source are all correct for the 2006 paper; only the quoted title is wrong.
* Young, A. and Rogers, W.P. (2021), Minerals 11, 636. The most heavily cited source in the package,
  and the only one with no DOI anywhere in the source. It appears in fourteen modules:
  `bedblend/__init__.py`, `bedblend/blocks.py`, `bedblend/build.py`, `bedblend/design.py`,
  `bedblend/dozer.py`, `bedblend/dump.py`, `bedblend/facesegregation.py`, `bedblend/reclaim.py`,
  `bedblend/relax.py`, `bedblend/sectors.py`, `bedblend/stream.py`, `bedblend/terrain.py`,
  `bedblend/topography.py` and `bedblend/truck.py`. Note when grepping for it that the citation is
  line wrapped in `bedblend/relax.py`, so a search for the literal "Minerals 2021" misses that one.
* Young, A. and Rogers, W.P. (2022), Mining 2, 86-102. doi:10.3390/mining2010006
  (cited in `bedblend/terrain.py` and `bedblend/dump.py`)
* Bak, P., Tang, C. and Wiesenfeld, K. (1987), Phys. Rev. Lett. 59(4), 381-384.
  doi:10.1103/PhysRevLett.59.381 (cited in `bedblend/relax.py`)
* Loubser and de Korte (2015), J. S. Afr. Inst. Min. Metall. 115(8), 773-780.
  doi:10.17159/2411-9717/2015/v115n8a15 (cited in `bedblend/blending.py`)
* Cogent Engineering 4(1), 1387955. doi:10.1080/23311916.2017.1387955
  (cited in `bedblend/terrain.py` and `bedblend/design.py`)
* Moraga, Kracht and Ortiz (2022), Minerals Engineering 187, 107807.
  doi:10.1016/j.mineng.2022.107807 (cited in `bedblend/rtd.py`)
* Neufeld, Lyall and Deutsch (2006), CCG Report 8 paper 306. No DOI is given in the source. Cited in
  `bedblend/blocks.py`, `bedblend/build.py`, `bedblend/design.py`, `bedblend/dozer.py`,
  `bedblend/sectors.py` and `bedblend/stream.py`.
