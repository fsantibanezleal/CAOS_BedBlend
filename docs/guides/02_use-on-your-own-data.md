# Use it on your own data

[Guide 01](01_install-and-quickstart.md) drives the engine from synthetic inputs: a flat pad, a
generated dig sequence, a rectangular yard. This guide replaces every one of those with something that
came off site, and is explicit about which fields you must supply, in what units, and what the engine
silently does not read.

Everything below was checked against the working tree at `0.07.002`, by reading the source and by
running it. Where a claim is a measurement, the measurement is quoted.

## What `build` actually consumes

```python
bedblend.build(
    terrain: Terrain,
    plan: DumpPlan,
    fleet: Fleet,
    payloads: list[Payload],
    *,
    repose_deg: float = 37.0,
    face_angle_deg: float | None = None,
    seed: int = 20260801,
    crest_drop_m: float = 1.0,
    max_spot_offset_m: float = 25.0,
    paddock_frac: float = 0.18,
    snapshot_every: int = 0,
    material: Material = DEFAULT_MATERIAL,
    route: Callable[[Payload], str] | None = None,
    verify_every: int = 0,
    after_load: Callable[[int, Terrain, BlockModel], None] | None = None,
) -> BuildResult
```

Four positional inputs and nothing else. Everything you bring from site has to become one of those
four objects. `build` mutates `terrain` in place and creates its own `BlockModel`; you do not supply a
ledger.

## Units, exhaustively

The engine has no unit system and does no conversion anywhere. Every quantity is a bare `float` in the
unit its field name declares, and the name is the contract.

| Quantity | Unit | Where it appears |
|---|---|---|
| Horizontal distance, elevation, thickness, depth, width, length, reach, push | metres | every field suffixed `_m`; `Terrain.cell_m`, `Payload`-adjacent geometry, `LoaderSpec.dig_radius_m`, `DozerPass.mean_displacement_m` |
| Volume | cubic metres | every field suffixed `_m3`; `Bench.designed_volume_m3`, `TruckSpec.load_volume_m3`, `DozerPass.volume_moved_m3` |
| Mass | tonnes | every field suffixed `_t` or named `tonnes`; `Payload.tonnes`, `Cut.tonnes`, `TruckSpec.payload_t` |
| Density | tonnes per cubic metre | `_t_m3` suffix; `TruckSpec.loose_density_t_m3`, `BlockModel.bulk_density_t_m3`, `Material.insitu_density_t_m3` |
| Angle | DEGREES at every public boundary | `repose_deg`, `face_angle_deg`, `Material.repose_dry_deg`, `ProfileStats.mean_angle_deg`, `relief_stats()["max_slope_deg"]` |
| Angle, internal | radians | only `TipPosition.heading_rad`, `Truck.heading_rad`, `Placement.heading_rad`, `LoadRecord.heading_rad`. `TipPosition.heading_deg` is a convenience property |
| Slope limit | GRADIENT, rise over run, dimensionless | `Fleet.max_grade`, `max_grade=` arguments, `Terrain.gradient()`, `relief_stats()["max_gradient"]`. Not degrees and not percent |
| Particle size | MILLIMETRES | `Material.d50_mm`, the only millimetre quantity in the engine. It is divided by 1000 inside `avalanche_state` |
| Speed | metres per second | `Avalanche.u_ms`, `Avalanche.q_ms` |
| Flux | square metres per second, per unit width | `facesegregation.CASCADE_FLUX_M2_S` |
| Grade | a dimensionless scalar in whatever convention YOU choose | `Payload.grade`, `Parcel.grade`, `Cut.grade`, `Rollup.mean_grade` |
| Everything else proportional | a FRACTION in `[0, 1]`, never a percentage | `Material.coarse_fraction`, `swell`, `max_compaction`, `moisture`; `Payload.grade_uncertainty`; `paddock_frac`; `sweep_advance_frac`; `seed_frac_x/y`; `grade_frac`; `overrun_fraction`; `BuildResult.refusal_rate`; `Cut.provenance` values |

Two of those deserve elaboration.

**Grade is unit-agnostic and the engine never interprets it.** Nothing in `bedblend` reads a grade as
a percentage, a fraction, a ppm value or a ratio. It is summed, weighted and differenced, and that is
all. `payloads_from` clamps it at zero with `max(..., 0.0)` and nothing else constrains it. Pick one
convention and hold it across the whole run, because mixing conventions inside one stream produces a
variance that is meaningless and a VRR that looks fine. Two consequences worth knowing: `vrr`,
`mixing_effect` and `blending_efficiency` are ratios of variances and are therefore invariant under a
rescaling of grade, so they are safe to compare across conventions; the semivariogram `gamma` returned
by `experimental_variogram` and every field of `fit_spherical` except `range` carry grade SQUARED and
are not. Note that the synthetic default, `dig_sequence(mean_grade=0.62, block_sd=0.16)`, reads like
percent copper but is not interpreted as such anywhere.

**Gradients are not angles.** `Fleet.max_grade` is a rise over run. `Fleet.of(..., repose_deg=37.0)`
computes `tan(radians(37)) / 1.5 = 0.5024`, which is 26.7 degrees. If you have an equipment limit
quoted as a percentage grade, divide by 100. If it is quoted in degrees, take the tangent.

## The load stream

### `Payload` is the whole contract

```python
@dataclass
class Payload:
    tonnes: float
    grade: float
    source_block: int
    grade_uncertainty: float = 0.0
```

Four fields, three required. `build` takes `list[Payload]` in ARRIVAL ORDER, and that order is the
model: consecutive loads sit next to each other in the pile, so the autocorrelation of the list is the
autocorrelation of the stratigraphy. Do not sort it by grade, by truck, or by anything else. Sort it
by dispatch timestamp and leave it alone.

- `tonnes` is the load mass. Use the weightometer or the payload-monitoring figure, not the nominal
  truck capacity. It is what every downstream weighting uses.
- `grade` is one scalar per load, in your convention.
- `source_block` is an INTEGER key identifying the ore-control block the material was dug from. It is
  the only provenance the engine tracks and it flows all the way through: `Parcel.source_block`, then
  `Cut.provenance`, which is a `dict[int, float]` mapping block to its tonnage FRACTION of that cut,
  summing to one. Real dig blocks are named strings, so map them.
- `grade_uncertainty` is a RELATIVE uncertainty on the grade, as a fraction. It is carried, weighted
  and reported; it is never used to perturb the grade. Section below.

### Adapting a dispatch export

```python
import csv
import bedblend as bb

block_ids: dict[str, int] = {}
def block_index(name: str) -> int:
    """Stable small integers for named ore-control blocks. Insertion order, so a run is repeatable."""
    return block_ids.setdefault(name, len(block_ids))

with open("dispatch_2026-03-01.csv", newline="", encoding="utf-8") as fh:
    rows = sorted(csv.DictReader(fh), key=lambda r: r["timestamp"])

payloads = [
    bb.Payload(
        tonnes=float(r["payload_tonnes"]),
        grade=float(r["cu_pct"]) / 100.0,          # percent on the export, FRACTION in the run
        source_block=block_index(r["dig_block"]),
        grade_uncertainty=float(r.get("assay_rel_sd") or 0.12),
    )
    for r in rows
]
```

Run against a five-row sample this produces, verbatim:

```text
payloads: [Payload(tonnes=228.4, grade=0.0070999999999999995, source_block=0, grade_uncertainty=0.14),
           Payload(tonnes=241.9, grade=0.0068000000000000005, source_block=0, grade_uncertainty=0.14),
           Payload(tonnes=219.0, grade=0.0044, source_block=0, grade_uncertainty=0.19),
           Payload(tonnes=236.1, grade=0.0075, source_block=1, grade_uncertainty=0.14),
           Payload(tonnes=225.7, grade=0.0039000000000000003, source_block=1, grade_uncertainty=0.19)]
block ids: {'PB3-1204': 0, 'PB3-1205': 1}
```

Do not use `hash(name)` for `source_block`. Python's string hash is salted per process unless
`PYTHONHASHSEED` is fixed, so a run would not be reproducible, which is the one property the whole
engine is built around. A `setdefault` counter over the sorted rows is stable and small.

### Missing grade uncertainty

If your export has no uncertainty column, do not pass zero. Zero is the dataclass default and it means
"this grade is exact", which is false before a truck moves. The published figure the engine is built
on is that misclassification of ore to waste or waste to ore from sampling error alone is commonly
between 5 and 20 percent for base and precious metal mines, with a further 9 to 19 percent ore loss
from blast movement and dilution. `payloads_from` defaults `grade_uncertainty=0.12`, the middle of the
5 to 20 band, and that is the right stand-in: use `0.12` and say in your report that it is a published
band midpoint rather than a site figure.

What it buys you is downstream. `Parcel.grade_uncertainty` carries it, `Cut.grade_uncertainty` is its
tonnage-weighted mean over the parcels a cut removed, and `Rollup.ci` gives confidence half-widths on
a sector mean. Measured on a run with the default: every cut came back with `grade_uncertainty`
exactly `0.120`, because a uniform input uncertainty averages to itself. Vary it per load and the
variation shows up per cut.

### Where `DigSequence` and `payloads_from` still help

`DigBlock`, `DigSequence` and `payloads_from` are a SYNTHESISER. If you have per-load grades you do
not need them at all: build `Payload` objects directly, as above.

```python
@dataclass(frozen=True)
class DigBlock:
    index: int
    grade: float
    n_loads: int
    bench: int = 0

@dataclass(frozen=True)
class DigSequence:
    blocks: list[DigBlock]          # consumed in order; `n_loads` property sums them
```

They are still the right tool in one common situation: you have block-model grades and a shovel
schedule, but no per-load assay. Then hand-build the sequence and let `payloads_from` expand it.

```python
seq = bb.DigSequence(blocks=[
    bb.DigBlock(index=block_index(name), grade=g, n_loads=n, bench=b)
    for name, g, n, b in shovel_schedule            # in the order the shovel worked them
])
loads = bb.payloads_from(seq, seed=7, tonnes_per_truck=231.0, truck_spread=0.06,
                         within_block_sd=0.02, grade_uncertainty=0.12)
```

`payloads_from` emits `sum(b.n_loads)` payloads, each with `tonnes = tonnes_per_truck * (1 + truck_spread * N(0,1))`
and `grade = max(block_grade + within_block_sd * N(0,1), 0)`. `within_block_sd` defaults to 0.02 and
is deliberately small: a block is the unit the ore-control model calls uniform, and if loads inside one
varied as much as loads between blocks there would be no correlation left to blend away. Note that
`DigBlock.bench` is carried on the dataclass and `dig_sequence` fills it from `n_benches` and the
block's own position in the schedule, `(k * n_benches) // n_blocks`; `bench_trend` is a separate
argument that uses that bench number to drift the grade between benches. `payloads_from` reads
neither: it only reads `index`, `grade` and `n_loads`. `bench` is metadata for your own reporting.

### Diagnostics on your own stream

Two functions work on any `list[Payload]`, synthetic or real, and you should run both before you build
anything.

```python
print(bb.measured_range_t(loads))            # practical range in TONNES
pos = bb.cumulative_tonnes(loads)            # running tonnage, the x-axis for anything along the stream
cen, gam, cnt = bb.experimental_variogram([p.grade for p in loads], pos, n_lags=20)
print(bb.fit_spherical(cen, gam, cnt))
```

`measured_range_t` is the lag at which the experimental semivariogram first reaches 95 percent of the
series variance, linearly interpolated, expressed in tonnes by multiplying by the mean payload. It
defaults to `n_lags=30` and is capped at `n // 2`, and both ends of that are traps on a short stream.
If the variogram never reaches the threshold inside the cap it returns `max_lag * mean_tonnes`, which
is the cap and not a measurement. If it reaches the threshold at the very first lag, which is what
five uncorrelated loads do, it interpolates BELOW lag one and returns a number smaller than a single
truck: on the five-row sample above it returns 136.08 t, from a crossing at lag 0.591, against a mean
payload of 230.22 t and a cap of 460.44 t. Neither answer is a range. It needs hundreds of loads to
mean anything. On a 120-load synthetic stream, `dig_sequence(n_loads=120, seed=7)` through
`payloads_from(seed=7)`, it returns 6,934 t; on the 600-load quickstart stream, 6,952 t.

The variogram positions are CUMULATIVE TONNAGE, not clock time. A stockpile's input is a
one-dimensional lot in Gy's sense and its heterogeneity is a function of mass along the stream, not of
how long the trucks took. Using time would make the answer depend on how busy the shift was.
`experimental_variogram` defaults `max_lag` to one third of the span. Lags with few pairs are still
returned, with their `counts`, so you can grey them out rather than silently trusting a noisy tail;
`fit_spherical` discards lags with fewer than 5 pairs and needs at least 4 surviving points, returning
all zeros if it cannot fit.

## The ground

### A real survey grid

`Terrain` requires a REGULAR grid with ONE cell size in both axes, stored row-major as
`idx = j * nx + i`, with `xy(c)` returning cell CENTRES at `((i + 0.5) * cell_m, (j + 0.5) * cell_m)`.
There is no rotation, no origin offset and no coordinate reference system: the pad's own origin is
`(0, 0)` and everything is in pad metres.

```python
@classmethod
def from_ground(cls, nx: int, ny: int, cell_m: float, ground: list[float]) -> Terrain
```

It validates length and nothing else:

```text
>>> bb.Terrain.from_ground(4, 4, 1.0, [0.0] * 15)
ValueError: ground has 15 cells, pad is 4x4=16
```

To bring in a survey you therefore have three jobs before you call it, and the engine will not do any
of them for you.

1. **Resample to a regular grid.** If you have an ASCII grid (ESRI `.asc`, `.grd`) you already have
   one; read the header for `ncols`, `nrows`, `cellsize`, and flatten in the engine's row order.
   Beware that ASCII grids are written top row first while `bedblend` indexes `j` upward, so reverse
   the row order. If you have a TIN, a point cloud or an irregular XYZ set, grid it in whatever tool
   you already trust and export the raster.
2. **Translate to pad coordinates.** Subtract the survey origin so the lower-left cell centre lands at
   `(0.5 * cell_m, 0.5 * cell_m)`. Every area, tip, shovel position and reclaim face you then define
   is in the same pad metres.
3. **Fill the nodata.** There is no nodata sentinel. A `-9999` left in the array is an elevation, and
   it will produce a cliff that the relaxation solver correctly declines to relax because it is
   original ground, and a trafficability mask that reads as static.

```python
def terrain_from_ascii_grid(path: str) -> bb.Terrain:
    """ESRI ASCII grid to Terrain. Rows come top-first, the engine wants +y up."""
    with open(path, encoding="utf-8") as fh:
        head = {}
        while True:
            pos = fh.tell()
            parts = fh.readline().split()
            if not parts or parts[0][0].isdigit() or parts[0][0] == "-":
                fh.seek(pos)
                break
            head[parts[0].lower()] = float(parts[1])
        rows = [[float(v) for v in line.split()] for line in fh if line.strip()]
    nx, ny = int(head["ncols"]), int(head["nrows"])
    cell = head["cellsize"]
    nodata = head.get("nodata_value", -9999.0)
    rows.reverse()                                   # +y up
    z = [v for row in rows for v in row]
    if len(z) != nx * ny:
        raise ValueError(f"grid says {nx}x{ny} but carries {len(z)} values")
    good = [v for v in z if v != nodata]
    fill = sum(good) / len(good)                     # decide this deliberately, do not default to it
    z = [fill if v == nodata else v for v in z]
    return bb.Terrain.from_ground(nx, ny, cell, z)
```

That function was run against a 4 by 3 grid at a 5 m cell with one nodata hole, and it produces:

```text
nx,ny,cell: 4 3 5.0
z rows bottom-up:
   [8.0, 8.5, 9.0, 9.5]
   [9.0, 10.0909, 10.0, 11.0]
   [10.0, 11.0, 12.0, 13.0]
z == z0: True
relief_stats: {'min_m': 8.0, 'max_m': 13.0, 'relief_m': 5.0, 'mean_m': 10.0909,
               'max_gradient': 0.4243, 'max_slope_deg': 22.9898}
cell_at(2.5, 2.5) -> 0    xy(0) -> (2.5, 2.5)
```

Note the row reversal doing its job: the grid's top row `10 11 12 13` comes out at the HIGHEST `j`,
and cell 0 is the lower-left corner at `(2.5, 2.5)`, which is the centre of the first 5 m cell. The
nodata hole was filled with the mean of the good values, `10.0909`, which is a placeholder and not a
recommendation.

### Sizing the pad

Cost scales with cells more sharply than with loads, so the pad is the first thing to keep honest.
The quickstart uses 60 by 60 cells at 2.5 m and a 600-load build takes about 64 s. Two constraints
bound the cell size from below and above:

- The cell must be small compared with a dump. Measured dump footprints are 13 to 46 m long and 11 to
  23 m wide, and the paddock heap is sized by the truck at 12.9 m by 7.334 m. A 2.5 m cell puts three
  cells across a truck bed, which is about the coarsest that still produces a shape rather than a
  pixel.
- The pad must be larger than the area plus the run-out plus the haul road. `rectangular_yard`
  defaults `margin_m=30.0` for this reason; before the margin existed, a measured 221 of 766 planned
  tips were refused for having nowhere to land, a fifth of the campaign lost to the edge of an array.

### Analytic ground, and why it is not a substitute for a survey

`topography.ground` builds the five published fill types as analytic surfaces:

```python
bb.ground(bb.FillType.SIDEHILL, nx, ny, cell_m, relief_m=25.0, roughness_m=0.0, seed=1)
```

`FillType` is `HEAPED`, `SIDEHILL`, `VALLEY`, `CROSS_VALLEY`, `RIDGE_CREST`. These are for scenarios,
not for site work: they are deliberately clean shapes so a scenario reproduces bit for bit and so the
interaction between construction and relief is visible. Real ground goes through `from_ground`, and
that path is unchanged by any of this.

Two diagnostics run against ANY terrain, analytic or surveyed, and both report against `z0` rather
than the live surface, so they keep describing the landform after material is placed:

```text
>>> g = bb.ground(bb.FillType.SIDEHILL, 32, 32, 4.0, relief_m=12.0, roughness_m=0.4, seed=3)
>>> bb.relief_stats(g)
{'min_m': 0.0, 'max_m': 13.755249759736492, 'relief_m': 13.755249759736492,
 'mean_m': 6.123869803963824, 'max_gradient': 0.14255037477254362,
 'max_slope_deg': 8.11287662866645}
>>> bb.buildable_fraction(g, 0.5024)
1.0
```

`buildable_fraction` is the fraction of the ORIGINAL ground a truck could already drive on before
anything is built. On a flat pad it is 1.0; on a sidehill at the equipment limit it can be a small
fraction, and every load then has to reach a working area that was cut or filled first. Run it on your
survey before you plan anything: if it is low, the plan you are about to write is not feasible and the
refusals will tell you so 600 loads later.

If `roughness_m` is used, note that it is applied as two octaves of smoothed value noise at 40 m and
20 m wavelengths on a 2.5 m cell, deliberately long-wavelength: white noise of the same amplitude
makes every cell locally steep and the trafficability mask comes out as static.

## The plan

### `rectangular_yard`, or hand-built areas

`rectangular_yard` lays `n_areas` axis-aligned rectangles side by side along `+x`, offset from the pad
origin by `margin_m` and separated by `gap_m`, each with `n_benches` benches of `bench_height_m`.

```text
>>> plan = bb.rectangular_yard(n_areas=2, area_width_m=30.0, area_length_m=30.0,
...                            bench_height_m=4.0, n_benches=1, gap_m=10.0, margin_m=12.0,
...                            classes=["STK-A", "STK-B"])
area STK-A: x 12.0-42.0, y 12.0-42.0, access (27.0, 42.0), designed 2476 m3
area STK-B: x 52.0-82.0, y 12.0-42.0, access (67.0, 42.0), designed 2476 m3
```

For anything else, build `Area` and `Bench` yourself:

```python
area = bb.Area(
    name="STK-A",
    x0_m=120.0, y0_m=40.0, x1_m=270.0, y1_m=97.0,   # pad metres, axis-aligned
    material_class="high SMR",                       # free text, the engine never branches on it
    access_xy=(195.0, 30.0),                         # where the haul road meets the dump
    ramp_width_m=25.0,
)
area.benches = [bb.Bench(index=0, top_m=8.7, designed_volume_m3=...)]
plan = bb.DumpPlan(areas=[area], tip_spacing_m=3.0, row_spacing_m=25.0)
```

`Area` is an axis-aligned RECTANGLE. A real dump-location polygon is a general polygon and this is a
known simplification, stated in the source: the rectangle carries a name, a schedule and a containment
test, and the containment test is the only thing the rest of the engine asks of it. If your polygon is
strongly non-rectangular, the honest options are to use the inscribed rectangle and accept the smaller
footprint, or to split it into several `Area` objects and route between them.

`Area.__post_init__` raises `ValueError` on a non-positive extent. `Area.access` defaults to the
midpoint of the `+y` edge, `((x0 + x1) / 2, y1)`, not a corner: laid out from the origin, the
`(x0, y0)` corner is the one buried deepest and no truck could reach it.

If you build benches by hand, compute `designed_volume_m3` as a frustum at repose rather than as a
box. `rectangular_yard` uses `design._frustum_m3(w, l, h, repose_deg)` (the prismatoid rule with the
top face inset by `h / tan(repose)` on every side, clamping to a pyramid). A blunt fraction of a box
was wrong in the direction that matters: 0.55 asked a 60 m square to hold 51,500 m3 of a shape whose
geometric capacity at repose is 27,100, so the plan kept issuing tips for material the pile could not
hold and the refusal rate stopped meaning anything. `_frustum_m3` is private; if you need it, either
call `rectangular_yard` for one area and read the bench back, or reimplement the prismatoid
arithmetic, which is five lines.

### Size the stream to the designed volume

This is the single most common way to make a run look broken when it is not.

```python
capacity_loads = sum(b.designed_volume_m3 for a in plan.areas for b in a.benches) \
                 / spec.load_volume_m3
```

Offer more loads than that and the surplus is refused with `area 'X' is built out; its planned
programme is complete`. Measured on a 100 m square pad at a 2.5 m cell: a 40 m square area with one
5 m bench at `margin_m=30.0` has a designed volume of
5,639.4 m3, which at 121.58 m3 per load is 46.38 loads, so `bench_program` emits 46 tips. Feeding it
200 loads placed exactly 46 and refused 154, all 154 of them `built out`: a 77 percent refusal rate
that says nothing at all about trafficability. In a two-area
routed run on a 120 m by 100 m pad, 30 m areas with one 4 m bench each at `margin_m=12.0` and
`gap_m=10.0`, the design totals 4,952.6 m3 or 40.74 loads, and offering
120 gave exactly 40 placed and 80 refused, 34 against STK-A and 46 against STK-B, every one of them
reading `built out`. That is the run the reclaim section below cuts into.

A routed load with nowhere left to go is refused rather than silently redirected, deliberately:
redirecting would break the one guarantee routing exists to provide, that a declared class ends up
where it was sent.

### The shovel must be outside every area

```text
>>> bb.build(terrain, plan, bb.Fleet.of(1, spec, plan.areas[0].centre), payloads)
ValueError: the shovel at (27.0, 27.0) is inside dump area 'STK-A'. The first load placed there
will bury the loading point and every later load will be refused for having no drivable start.
Put the shovel outside every area's footprint.
```

### Routing loads to areas

```python
def route(p: bb.Payload) -> str:
    return "STK-A" if p.grade >= 0.0175 else "STK-B"

built = bb.build(terrain, plan, fleet, payloads, route=route)
```

`route` maps a load to the NAME of an area. With it, several areas are under construction at once and
a declared class ends up where it was sent. Without it, areas are worked one at a time in `plan.areas`
order. Routing is the mechanism by which sectors exist at all, so a yard with no router has one sector
and nothing to compare.

The decision is made from the ESTIMATE and before placement, which is the point: a misclassified load
lands in the wrong pile and stays there, which is a real and reportable outcome rather than something
to correct afterwards. Route on `p.grade`, on a threshold you can defend, and record the threshold.
The industrial precedent the module cites routes on a silica-to-magnesia ratio at 1.75, with one high
pile and one low pile under construction simultaneously.

An unknown name is a hard error, not a fallback:

```text
KeyError: "the router sent a load to area 'STK-Z', which is not in the plan;
           the plan has ['STK-A', 'STK-B']"
```

## Material

`Material` is a frozen dataclass with eleven fields, ten of them numeric and the eleventh a label.
The build path reads THREE of them. This was
checked two ways, by walking the AST for attribute access and by rebuilding the same small pile once
per numeric field, changing one field per run and comparing the placed count, the peak elevation, the
ledger tonnage, the mean ledger coarse fraction and the summed segregation number.

The scenario, stated so the table can be re-run: an 80 m square pad, `Terrain.flat(32, 32, 2.5)`; one
30 m area with a single 5 m bench at `margin_m=15.0`; two trucks at the default `TruckSpec` with the
shovel at `(7.5, 40.0)`; twenty loads from `dig_sequence(n_loads=20, seed=7)` through
`payloads_from(seed=7)`; `build(repose_deg=37.0, seed=20260801)`.

```text
baseline                        (20, 6.727143554, 4620.0, 0.348464685, 1.833243043)
insitu_density_t_m3   =3.2      unchanged
swell                 =0.55     unchanged
max_compaction        =0.15     unchanged
moisture              =0.18     unchanged
saturation_moisture   =0.35     unchanged
repose_coarse_deg     =45.0     unchanged
repose_fine_deg       =28.0     unchanged
repose_dry_deg        =41.0     (20, 6.727143554, 4620.0, 0.35, 0.0)                 CHANGED
d50_mm                =25.0     (20, 6.727143554, 4620.0, 0.349419116, 0.811206344)  CHANGED
coarse_fraction       =0.55     (20, 6.727143554, 4620.0, 0.54914028, 1.833243043)   CHANGED
```

Read the first three columns as a control: the placed count, the peak and the ledger tonnage are
bit-identical in every row, including the three that changed something. No `Material` field touches
the geometry or the mass. All the movement is in the last two columns, which are the size split and
the sorting.

So:

- **`coarse_fraction`** sets the two-species split the segregation solver separates. It is what the
  ledger records per cell and what `Cut.coarse_fraction` reports. Set it from a sieve analysis: it is
  the mass fraction above whatever you call the coarse/fine cut, as a FRACTION. `intensity` uses
  `4c(1-c)`, so the effect is maximal at an even split and vanishes at 0 or 1; measured at an 11 m
  drop, the on-face sorting index runs 0.0000, 0.0981, 0.3661, 0.5116, 0.5574, 0.2224, 0.0000 for
  `c = 0.0, 0.1, 0.35, 0.5, 0.65, 0.9, 1.0`.
- **`d50_mm`** sets the particle diameter in the percolation velocity and the minimum layer
  thickness, `h_min = 5 * d50`. It moves the answer a long way and non-monotonically; see
  [guide 03](03_calibration-and-limits.md).
- **`repose_dry_deg`** sets the DYNAMIC friction angle, `repose_dry_deg - 4`, and therefore whether
  the face avalanches at all. It does NOT set the geometry: the geometry uses `build(repose_deg=...)`,
  a separate argument. Setting `Material.repose_dry_deg = 41.0` while building at 37 degrees switched
  all size segregation off, which is the `0.35` flat coarse field and the `0.0` summed `sr` in the
  table above. This is a real trap and it has its own section in guide 03.

The other eight fields, `name`, `insitu_density_t_m3`, `swell`, `max_compaction`, `moisture`,
`saturation_moisture`, `repose_coarse_deg` and `repose_fine_deg`, do not reach the build at all. Two
of them are read SOMEWHERE in the package, and it is worth knowing where: `repose_coarse_deg` and
`repose_fine_deg` are read by `SizeSplit.blended_repose_deg`, whose only caller is
`facesegregation.apparent_repose_deg`, and `build` does not import `apparent_repose_deg`. It is a
function you call yourself on a `FaceSegregation`, which is why the table above shows both fields
inert.

Separately, `Material` carries eight caller-facing methods and properties, and NONE of them is called
from anywhere inside the package: `loose_density_t_m3`,
`compacted_density_t_m3`, `density_after_passes`, `tonnes_from_loose_m3`, `loose_m3_from_tonnes`,
`insitu_m3_from_tonnes`, `repose_deg(moisture=...)` and `is_wet()`. All eight are defined, all
documented, all correct, and all useful for
reconciling against the pit. They are not wired into the build. Do not assume that setting
`Material.moisture` changes the pile: the only thing that reads it is `Material.repose_deg()`, and
nothing calls that.

## The three densities, and how to keep tonnes honest

There are three loose-density values in the engine and they are independent:

| Field | Default | What it controls |
|---|---|---|
| `TruckSpec.loose_density_t_m3` | 1.9 | `load_volume_m3 = payload_t / this`. The VOLUME a load occupies when placed |
| `BlockModel.bulk_density_t_m3` | 1.9 | `tonnes(c) = thickness * cell_area * this`. The tonnes the ledger reports |
| `Material.loose_density_t_m3` | 1.9565 (derived from `insitu 2.70 / (1 + swell 0.38)`) | Nothing inside the engine |

The tonnage round trip in guide 01 is exact only because the first two share a default:

```text
TruckSpec.load_volume_m3 = 231.0 / 1.9 = 121.57894736842105
BlockModel.over default bulk_density_t_m3 = 1.9
=> a placed load of 231.0 t is recorded as 231.0 t by the ledger
   with a Material-consistent ledger density it would be 237.87185354691078 t
```

If you set a site density, set BOTH:

```python
rho = 2.05
spec = bb.TruckSpec(payload_t=231.0, loose_density_t_m3=rho)
# ... build ...
built.model.bulk_density_t_m3 = rho     # BlockModel.over is called inside build with the default
```

`build` calls `BlockModel.over(terrain)` with no density argument, so there is no way to pass one in
through `build`. Setting it on the returned model afterwards is correct, and here is why: the field is
read in exactly five places, `BlockModel.tonnes`, `BlockModel.to_blocks`, `ReclaimFace.bite`,
`reclaim.cut` and `sectors.rollup_by_lift`, and none of them runs during the build. The build only
ever records THICKNESSES, and every thickness in the ledger is already right. So set it any time after
`build` returns and before you reclaim or report; `bite` sizes a cut in tonnes and will use it. The
alternative, if you want it set from the start, is to construct the model yourself and drive the
lower-level operators, which is a much larger commitment.

Cross-check the round trip on every run:

```python
placed_t = sum(p.tonnes for r, p in zip(built.loads, payloads, strict=True) if r.placed)
assert abs(built.model.total_tonnes() - placed_t) / placed_t < 0.01
```

## Reclaim against your own pile

```python
@dataclass
class ReclaimFace:
    method: ReclaimMethod = ReclaimMethod.FULL_HEIGHT
    position_m: float = 0.0                 # how far the face has advanced ALONG `direction`
    direction: tuple[float, float] = (1.0, 0.0)
    depth_m: float = 5.0                    # how far into the pile one cut reaches
    width_m: float = 30.0                   # across-face extent of the FACE, not of one cut
    max_face_m: float = 15.0                # safe working face height
    loader: LoaderSpec = field(default_factory=LoaderSpec)
    offset_m: float = 0.0                   # where the machine stands ACROSS the face
    centre_t_m: float | None = None         # where the across-face window is CENTRED
    origin_m: float = field(init=False, default=0.0)   # set from position_m in __post_init__
```

`origin_m` is not a constructor argument. `__post_init__` copies `position_m` into it and
`rewind()` puts the face back there, which is the concurrent-campaign behaviour described further
down. Setting `position_m` after construction moves the face without moving the point it rewinds to.

Three things to get right for a real pile.

**`position_m` is a projection, not an x coordinate.** It is the dot product of a cell centre with the
unit `direction`. With the default `direction=(1, 0)` it is an x coordinate; rotate the direction and
it stops being one. Start it at the near edge of the material, which for an area is `area.x0_m` when
advancing in `+x`.

**`centre_t_m` must be set on a multi-area yard.** It defaults to the middle of the PAD along the
across-face axis, which is only correct when the pile is pad-centred. A yard tiles several areas and
each face belongs to one of them, so pass the area's own centre:

```python
a = plan.area("STK-A")
face = bb.ReclaimFace(method=bb.ReclaimMethod.FULL_HEIGHT,
                      position_m=a.x0_m, direction=(1.0, 0.0),
                      depth_m=6.0, width_m=a.length_m, centre_t_m=a.centre[1])
```

Leave it at the default on a two-area yard and the face window sits between the piles.

**Pass `exit_xy` and `max_grade` to `campaign`.** They are optional only so an existing caller does
not break. With them every cut gets a truck stand, an approach and a departure, solved on the surface
the cut LEFT BEHIND, and a cut that cannot be served comes back with `stand=None`. Measured on the
quickstart pile of [guide 01](01_install-and-quickstart.md), 24 of 24 cuts were servable. The check is
only worth running because it can fail: a campaign that has undercut its own access cannot be served,
and saying so is the point of modelling the haulage at all.

```python
cuts = bb.campaign(built.terrain, built.model, face,
                   cut_tonnes=800.0, n_cuts=8, repose_deg=37.0,
                   exit_xy=fleet.shovel_xy, max_grade=fleet.max_grade)
```

Output from that run, verbatim. The pile is the routed two-area yard measured earlier in this guide,
a 120 m by 100 m pad at a 2.5 m cell, two 30 m areas with one 4 m bench each at `margin_m=12.0` and
`gap_m=10.0`, the shovel at `(6.0, 80.0)`, 120 loads routed on `grade >= 0.62`:

```text
   800.0 t grade 1.0935 coarse 0.3372 disp  16.7 m unc 0.120 cells 62 blocks 1 stand (26.25, 26.25)
   800.0 t grade 1.0988 coarse 0.3277 disp  22.6 m unc 0.120 cells 74 blocks 1 stand (36.25, 26.25)
   800.0 t grade 0.6415 coarse 0.3638 disp   2.3 m unc 0.120 cells 36 blocks 3 stand (41.25, 21.25)
   800.0 t grade 0.5859 coarse 0.3151 disp  15.1 m unc 0.120 cells 46 blocks 2 stand (61.25, 31.25)
   800.0 t grade 0.5794 coarse 0.3189 disp   9.8 m unc 0.120 cells 45 blocks 2 stand (63.75, 26.25)
   800.0 t grade 0.5895 coarse 0.3405 disp  15.8 m unc 0.120 cells 46 blocks 2 stand (71.25, 26.25)
   362.0 t grade 0.7636 coarse 0.3253 disp  15.5 m unc 0.120 cells 25 blocks 3 stand (51.25, 23.75)
    54.4 t grade 1.1108 coarse 0.3384 disp   5.2 m unc 0.120 cells  6 blocks 1 stand (23.75, 16.25)
```

Two things in that block are the model being honest rather than the model failing. The last two cuts
came back SHORT, 362.0 t and 54.4 t against an order of 800: `next_cut` will tram the machine one
sweep of the face width and no further, so when the reachable ground cannot supply the parcel the
parcel is short, which is the real operational answer. And the truck stands walk from x 26 out to
x 71 across a yard whose two areas sit at x 12 to 42 and x 52 to 82, so the campaign has left STK-A
and is working STK-B. `centre_t_m` and `width_m` bound the window ACROSS the face and nothing bounds
it along the face: `position_m` simply advances by `depth_m` until the material runs out. If you mean
one area, size `n_cuts` and `depth_m` to that area's own extent, or stop when the stands leave it.

`Cut.approach` and `Cut.departure` are lists of `(x, y)` polyline points; `approach_cells` and
`departure_cells` are the unsimplified grid paths behind them. Use the polylines to draw and the cells
to check gradients, because `step_ok` divides by ONE cell width and a simplified segment can span
twenty.

`LoaderSpec.passes_for(load_t, bulk_density_t_m3)` needs the material's density because a bucket is a
volume: `passes_for(800.0, 1.9)` returns `12.38`. It takes the density as an argument rather than
reading one, so pass the same figure you used everywhere else.

## Building and reclaiming at the same time

Some operations fill a pile and then take it down; plenty of others feed and draw at once, and the two
produce different piles from the same ore, because the material a cut crosses depends on how much of
the campaign had arrived when it was taken. The `after_load` hook runs after every PLACED load:

```python
cuts: list[bb.Cut] = []
face = bb.ReclaimFace(method=bb.ReclaimMethod.FULL_HEIGHT, position_m=a0.x0_m,
                      direction=(1.0, 0.0), depth_m=5.0, width_m=a0.length_m,
                      centre_t_m=a0.centre[1])

def after_load(n_placed: int, terr: bb.Terrain, model: bb.BlockModel) -> None:
    if n_placed % 40 == 0:
        c = bb.next_cut(terr, model, face, 500.0, repose_deg=37.0)
        if c is not None:
            cuts.append(c)

built = bb.build(terrain, plan, fleet, payloads, after_load=after_load, verify_every=20)
```

The signature is `(n_placed, terrain, model)` where `n_placed` is the running count of PLACED loads,
not the offered sequence number. The ledger stays consistent through it, and `verify_every=20` is
what proves it, at no cost worth measuring on a small pad. Note that the two counters are NOT the
same one: `verify_every` is keyed on the OFFERED sequence number, `seq % verify_every == 0`, and the
check sits after the refusal `continue`, so a run with refusals verifies on fewer than every twentieth
offered load and on no fixed multiple of the placed ones. Turn it on to catch drift, not to count.

One behaviour to know: a concurrent face can work its way past the end of the material simply because
the reclaim is ahead of the trucks. `next_cut` handles that by calling `ReclaimFace.rewind()` once per
call, putting the face back at `origin_m` and `offset_m = 0`. Without it a face parked out beyond the
pile finds nothing forever and the campaign silently stops while still returning a plausible-looking
feed series; measured before the rewind existed, a concurrent scenario fell from 28 cuts to 2. You can
call `face.rewind()` yourself between phases.

## What you get back

`BuildResult` carries `terrain`, `model`, `loads`, `dozer_passes`, `snapshots`, and the derived
`placed`, `refused`, `refusal_rate` and `profile_counts()`.

One `LoadRecord` per OFFERED load, placed or not. This is `built.loads[173]` from the quickstart build
of [guide 01](01_install-and-quickstart.md), picked because one record happens to show both of the
traps below:

```text
seq                        = 173
area                       = A1
bench                      = 0
phase                      = Phase.EDGE
truck_id                   = 1
x_m                        = 41.190011153707836        # where the truck actually stood
y_m                        = 48.53848038205737
grade                      = 0.7987622620473406
source_block               = 8
placed                     = True
planned_x_m                = 41.190011153707836        # where the plan asked for it
planned_y_m                = 48.53848038205737
spot_offset_m              = 0.0                       # the distance between the two
profile                    = DumpProfile.COMET
distance_to_crest_m        = 0.21986179853276033
heading_rad                = -1.7522987000187673
length_m                   = 9.22294277905683          # realised, measured off the placed field
width_m                    = 17.704872877953672
max_thickness_m            = 2.3479811931920174
approach                   = Route(8 pts, 15 cells)
departure                  = Route(1 pts, 0 cells)
segregation_index          = 0.0
sr                         = 0.0
overrun_fraction           = 0.0
overrun_coarse_fraction    = 0.35
drop_m                     = 0.0
refused_reason             = ''
```

Read that record carefully, because it shows two things worth knowing.

A one-point `departure` Route means the truck could not solve a way out after its own load changed the
surface. `Fleet.depart` catches the `NoRoute` and records `Route([(truck.x_m, truck.y_m)])` with no
cells at all, rather than pretending the truck teleported home: it is how a badly sequenced plan
strands equipment. 55 of the 480 placed loads in that build end that way.

`sr = 0.0`, `drop_m = 0.0` and `overrun_coarse_fraction = 0.35` together mean the face did not
avalanche, even though the profile says COMET. Profile and sorting are decided separately: `classify`
picks the shape from the distance to the crest, while the drop is measured afterwards from the placed
footprint, and a load that tips at the crest onto ground barely below it has a cascade shape and no
fall. When there is no flow, `overrun_coarse_fraction` falls back to the material's own coarse
fraction, so it is the unsorted split rather than a result. Test `sr > 0` or `drop_m > 0`, never
`overrun_coarse_fraction != 0`, when you want to know whether a load sorted. Measured on that build:
362 of 480 placed loads got a cascade profile, but only 240 of those had a non-zero
drop, and exactly those 240 had `sr > 0` and a non-zero `segregation_index`. The other 122 all report
`sr = 0.0` and `overrun_coarse_fraction = 0.35` exactly, which is the material default and not a
measurement.

`snapshot_every=N` fills `BuildResult.snapshots` with
`(sequence number of the load just placed, loads placed so far, a copy of the surface)`. A snapshot is
one float per cell, so a couple of dozen keeps an artifact small while still animating the build. A
final snapshot is always appended when `snapshot_every` is non-zero. On the quickstart build with
`snapshot_every=25`, that is 20 entries for 480 placed loads: nineteen on the cadence, starting at
`(24, 25)` because the load that took the count to 25 was offered 25th and refused none before it,
plus the closing `(600, 480)`. The cadence counts PLACED loads and the first element is the OFFERED
sequence number, so the two diverge as refusals accumulate.

The ledger is per-column parcel stacks. A `Parcel` is a vertical interval of one column contributed by
one placement. This is the bottom parcel of the first non-empty column of the same quickstart build:

```text
Parcel(z0_m=0.0, z1_m=0.04875210833167665, grade=0.648419124094483, source_block=22,
       event_id=449, lift=1, area='A1', grade_uncertainty=0.12,
       displacement_m=7.5, coarse_fraction=0.3344129357649191)
```

Note `event_id=449` sitting at the BOTTOM of a column, `z0_m=0.0`. Parcels are stacked bottom-up in
placement order within a column, but a dozer or a relaxation can strip a column to bare ground and
refill it later, and `_stack_onto` restacks the arrivals from the base. A low parcel is not
necessarily an early one. `displacement_m=7.5` on this one says so directly: three cell widths of
accumulated travel at a 2.5 m cell, so this material was carried here rather than tipped here.

`event_id` is the `LoadRecord.seq` that placed it, so the two records join. `displacement_m` grows
every time a dozer or a relaxation moves that material. Read the ledger through
`column_grade`, `column_coarse`, `grade_field`, `coarse_field`, `tonnes`, `total_tonnes`,
`mean_displacement_m`, and `to_blocks(dz_m=5.0)` for a regular lattice view in the form a mine
planning package consumes. `to_blocks` is a VIEW computed on demand, so the coarse representation
never becomes the stored truth.

Sector rollups aggregate the ledger over an `Area`, tonnage-weighted, with confidence half-widths at
0.90, 0.95 and 0.99. On the quickstart build's single area:

```text
rollup A1: 85,927 t, mean 0.6534, sd 0.0303, n 1296, ci95 0.00165,
           interval (0.6517530950424902, 0.6550543561452117)
compare model tighter at 0.95: True   data ci 0.01776   model ci 0.00165
```

`n` is the number of COLUMNS carrying material inside the area, not the number of loads, and the
standard error divides by `sqrt(n)` on that count. 1296 columns is the whole 90 m area at a 2.5 m
cell, so this interval is narrow because the pile covers its footprint, not because the grade is well
known.

`compare(model, terrain, area, observations)` takes `observations` as `(x, y, grade)` per dump event,
which is exactly what a fleet-management export gives, and reproduces the published quadrant
comparison: the interpolated model's interval comes out narrower than the raw data's, which is a
genuine property of interpolation and also the reason a sector rollup can look reassuring while the
raw field underneath it is not.

Do not read that as a guarantee. What the repository actually pins is
`test_model_interval_is_tighter_than_the_data_in_every_quadrant`, which asserts it per quadrant, at
all three confidence levels, on that test's own scenario, and skips any quadrant with fewer than three
observations on either side. It is not an invariant of the function. Measured on the routed two-area
yard used earlier in this guide, where 40 placed loads are split across both areas and STK-A's rollup
comes back with 15 columns and a weighted sd of 0.0973, `compare` on STK-A returns a model interval of
0.04923 against a data interval of 0.00922, so `model_is_tighter(0.95)` is False. The published result
is a property of enough loads per column for the averaging to have happened, not a property of the
function. Read the flag; do not assume it.

## A complete adapter

```python
"""Drive bedblend from a dispatch export and a survey grid."""
import csv
import bedblend as bb

RHO = 1.95                      # site loose density, t/m3, used in BOTH places
REPOSE_DEG = 37.0
UNCERTAINTY_FALLBACK = 0.12     # published 5 to 20 percent band, midpoint

# --- 1. ground -------------------------------------------------------------------------------
terrain = terrain_from_ascii_grid("pad_survey.asc")     # defined earlier in this guide
print("buildable before we start:", bb.buildable_fraction(terrain, 0.50))

# --- 2. plan ---------------------------------------------------------------------------------
stk = bb.Area(name="STK-A", x0_m=120.0, y0_m=40.0, x1_m=270.0, y1_m=97.0,
              material_class="high SMR", access_xy=(195.0, 30.0), ramp_width_m=25.0)
stk.benches = [bb.Bench(index=0, top_m=8.7, designed_volume_m3=95_000.0)]
plan = bb.DumpPlan(areas=[stk], tip_spacing_m=3.0, row_spacing_m=25.0, repose_deg=REPOSE_DEG)

# --- 3. fleet --------------------------------------------------------------------------------
spec = bb.TruckSpec(name="CAT 793F", payload_t=231.0, bed_width_m=7.334,
                    body_length_m=12.9, loose_density_t_m3=RHO)
fleet = bb.Fleet.of(4, spec, shovel_xy=(40.0, 20.0), repose_deg=REPOSE_DEG,
                    grade_limit_divisor=1.5)
assert plan.area_at(*fleet.shovel_xy) is None, "the shovel is inside a dump area"

# --- 4. stream -------------------------------------------------------------------------------
block_ids: dict[str, int] = {}
with open("dispatch.csv", newline="", encoding="utf-8") as fh:
    rows = sorted(csv.DictReader(fh), key=lambda r: r["timestamp"])
payloads = [
    bb.Payload(tonnes=float(r["payload_tonnes"]),
               grade=float(r["cu_pct"]) / 100.0,
               source_block=block_ids.setdefault(r["dig_block"], len(block_ids)),
               grade_uncertainty=float(r.get("assay_rel_sd") or UNCERTAINTY_FALLBACK))
    for r in rows
]
capacity = sum(b.designed_volume_m3 for b in stk.benches) / spec.load_volume_m3
print(f"{len(payloads)} loads offered against a design capacity of {capacity:.0f}")
print(f"stream practical range {bb.measured_range_t(payloads):,.0f} t")

# --- 5. material -----------------------------------------------------------------------------
mat = bb.Material(name="ROM ore", coarse_fraction=0.41, d50_mm=95.0, repose_dry_deg=REPOSE_DEG)

# --- 6. build --------------------------------------------------------------------------------
built = bb.build(terrain, plan, fleet, payloads, repose_deg=REPOSE_DEG,
                 material=mat, seed=20260801, snapshot_every=25, verify_every=50)
built.model.bulk_density_t_m3 = RHO          # keep the ledger's density with the truck's
print(f"placed {len(built.placed)} refused {len(built.refused)} ({built.refusal_rate:.1%})")
reasons: dict[str, int] = {}
for r in built.refused:                       # the text before the colon is the reason class
    key = r.refused_reason.split(":")[0]
    reasons[key] = reasons.get(key, 0) + 1
for key, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
    print(f"  {n:5d}  {key}")
print("profiles", built.profile_counts())
print(f"mean displacement {built.model.mean_displacement_m():.1f} m")

# --- 7. reclaim ------------------------------------------------------------------------------
face = bb.ReclaimFace(method=bb.ReclaimMethod.FULL_HEIGHT, position_m=stk.x0_m,
                      direction=(1.0, 0.0), depth_m=8.0, width_m=stk.length_m,
                      centre_t_m=stk.centre[1], max_face_m=8.7,
                      loader=bb.LoaderSpec(dig_radius_m=15.0, max_cut_height_m=8.7))
cuts = bb.campaign(built.terrain, built.model, face, cut_tonnes=2500.0, n_cuts=40,
                   repose_deg=REPOSE_DEG, exit_xy=fleet.shovel_xy, max_grade=fleet.max_grade)
unserved = [k for k, c in enumerate(cuts) if c.stand is None]
if unserved:
    print(f"WARNING cuts with no truck access: {unserved}")

# --- 8. verdict ------------------------------------------------------------------------------
var_in = bb.tonnage_weighted_variance([p.grade for p in payloads], [p.tonnes for p in payloads])
var_out = bb.tonnage_weighted_variance([c.grade for c in cuts], [c.tonnes for c in cuts])
print(bb.VRR_FORMULA_LABEL)
print(f"VRR {bb.vrr(var_in, var_out):.4f}   E {bb.mixing_effect(var_in, var_out):.2f}")
```

## Failure modes, with the exact messages

| Message | Cause | Fix |
|---|---|---|
| `ground has N cells, pad is nx x ny=M` | `Terrain.from_ground` length mismatch | Check the row order and the header |
| `the shovel at (x, y) is inside dump area 'A'` | Loading point inside a footprint | Move the shovel outside every area |
| `the router sent a load to area 'Z', which is not in the plan` | `route` returned an unknown name | Return only names in `plan.areas` |
| `no area named 'Z'; have [...]` | `DumpPlan.area(name)` lookup miss | Same |
| `area 'A' is built out; its planned programme is complete` | More loads offered than the designed volume holds | Size the stream, or raise `designed_volume_m3` |
| `no drivable ground inside area 'A' within 25 m of the planned tip` | The pile has grown over its own access | Loosen `grade_limit_divisor`, raise `max_spot_offset_m`, tighten `loads_per_dozer_pass`, or accept it as a real result |
| `no drivable route to (x, y): the pile has grown over its own access` | `NoRoute` from A-star | Same |
| `area 'A' has a non-positive extent` | `Area` with `x1 <= x0` or `y1 <= y0` | Order the corners |
| `a size split must sum to one, got coarse+fine = 0.6` | `SizeSplit` built directly | Use `SizeSplit.of(coarse_fraction)`, which clamps and completes |
| `the ledger and the terrain disagree by D m at cell C` | `assert_consistent` failed | An operator moved material without carrying the ledger. This is an engine bug; report it with the seed |
| `N cell pairs stand more than 4.0 deg over the imposed repose angle` | `ReposeViolation` from `assert_stable` | Usually a caller passing a different angle than the build used |

## What is exported and what is not

`bedblend.__all__` has 115 names and every one of them resolves. Some things you will reach for are
NOT at the package root and must be imported from their module:

```python
from bedblend.dozer import build_ramp, DEFAULT_PUSH_M, DEFAULT_BLADE_M3
from bedblend.facesegregation import PERCOLATION_COEFFICIENT, CASCADE_FLUX_M2_S, \
    LAYER_MIN_DIAMETERS, FLOW_HYSTERESIS_DEG, REFERENCE_DROP_M
from bedblend.relax import STABLE_TOL_DEG, BARE_M, cells_over_repose
from bedblend.rtd import fifo_lifo_references, theoretical_plug_flow_variance
from bedblend.truck import step_ok, tip_reach
from bedblend.material import SWELL_ALL_MATERIALS
```

The asymmetry is worth noting because the repository README's honesty section names two anchored
coefficients, `PERCOLATION_COEFFICIENT` and `PECLET_DEFAULT`, and only the second is importable from
the root.

## References cited in this guide

Only sources the repository itself cites, in a module docstring or in the README reference list.
Nothing here was added by this guide.

- Young, A. and Rogers, W.P. (2021), *Modelling of pre-crusher stockpiles*, Minerals 11(6), 636.
  [doi:10.3390/min11060636](https://doi.org/10.3390/min11060636), the DOI from the README; the
  docstrings cite it by journal, volume and article number. Source of the dump-location-polygon
  data model, the two-phase bench construction, the 5 to 20 percent ore-control misclassification
  band, the dozer's role, and the quadrant confidence comparison.
- Young, A. and Rogers, W.P. (2022), Mining 2(1).
  [doi:10.3390/mining2010006](https://doi.org/10.3390/mining2010006). The 28 UAV-surveyed dumps: the
  13 to 46 m by 11 to 23 m footprint envelope and the four cascade profiles.
- Neufeld, C., Lyall, G. and Deutsch, C.V. (2006), CCG Report 8, paper 306. The dig-sequence model,
  the paddock lattice figures, and the routing precedent at a silica-to-magnesia ratio of 1.75. No DOI
  recorded in the source.
- Cogent Engineering 4(1), 1387955.
  [doi:10.1080/23311916.2017.1387955](https://doi.org/10.1080/23311916.2017.1387955). Dump design by
  lifts with ramps of suitable width and gradient, which is where the reserved access corridor comes
  from.
