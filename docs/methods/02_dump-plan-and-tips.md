# 02. The dump plan: areas, benches, the ramp, and tip positions

`bedblend/design.py` holds the design. It emits an ordered sequence of intended discharge positions and
nothing else: it does not place material, it does not know about terrain, and it never asks whether a
position can be reached. That separation is the point, because it is what lets a reader see the
difference between what was planned and what the pile allowed. Feasibility is document 01's subject and
happens at execution.

This document describes the module as of `bedblend` 0.07.002. Every number below was produced by
running the installed package.

---

## 1. Why the plan is the operational data model

Trucks do not discharge at arbitrary coordinates, and the operational record is what proves it. A
fleet-management dump event locates a load by the "name and bench height of dump location polygon"
(Young and Rogers, Minerals 2021, 11, 636, table 1). The area is named and predefined; the level is a
bench. So a plan is not a convenience wrapper over coordinates, it is the schema the real record uses,
and the engine's own event log mirrors it:

```python
# bedblend/design.py
@dataclass(frozen=True)
class TipPosition:
    x_m: float; y_m: float; heading_rad: float
    phase: Phase          # Phase.PADDOCK or Phase.EDGE; proposes the dump operator, see section 11
    area: str             # the name of the dump-location polygon
    bench: int            # which lift of that polygon
    seq: int              # position in the build order

# bedblend/build.py
@dataclass
class LoadRecord:
    seq: int; area: str; bench: int; phase: Phase; truck_id: int
    x_m: float; y_m: float                      # where the truck actually stood
    grade: float; source_block: int; placed: bool
    planned_x_m: float = 0.0                    # where the plan asked for it
    planned_y_m: float = 0.0
    spot_offset_m: float = 0.0                  # the distance between those two
    ...                                         # profile, geometry, segregation, refused_reason
```

The previous engine accepted any coordinate and had no area and no bench. That is the defect this
module removes, and it is why `area` and `bench` are carried on every load record whether or not
anything reads them.

The area label itself is free text. `Area.material_class` is documented as the operation's own
vocabulary ("high SMR", "low grade", "oxide") and **the engine never branches on it**. Routing is done
by a caller-supplied `route` callable passed to `build`, which maps a payload to the NAME of an area; the
class string is what a reader reads, not what the code dispatches on.

---

## 2. The yard in plan view

`rectangular_yard` is the constructor for the standard case. Its full signature, with the defaults that
matter to the figure:

```python
rectangular_yard(*, n_areas, area_width_m, area_length_m, bench_height_m, n_benches,
                 gap_m=20.0, classes=None, repose_deg=37.0,
                 ramp_width_m=25.0, margin_m=30.0) -> DumpPlan
```

Areas are laid out side by side along +x from the pad origin:

```
  x0(k) = margin_m + k * (area_width_m + gap_m)      k = 0 .. n_areas-1
  y0    = margin_m
  x1(k) = x0(k) + area_width_m
  y1    = margin_m + area_length_m
```

The figure below was generated from the object the constructor returns, for
`rectangular_yard(n_areas=2, area_width_m=150.0, area_length_m=57.0, bench_height_m=8.7, n_benches=2,
classes=["HIGH_SMR", "LOW_SMR"])` with every other argument left at its default. Each box interior is
29 characters wide for 150 m, so a character is roughly 5 m in x and the corridor is drawn about half a
character left of true centre; the six rows span the 57 m of area length. `#` is the reserved access
corridor.

```
                         access point                      access point
                           (105, 87)                         (275, 87)
                               v                                 v
y= 87.0         +===========#####=============+   +===========#####=============+
                |           #####             |   |           #####             |
                | HIGH_SMR  #####  bench top  |   | LOW_SMR   #####  bench top  |
                | 150 x 57  #####  8.7 m and  |   | 150 x 57  #####  8.7 m and  |
                | 2 benches #####  17.4 m     |   | 2 benches #####  17.4 m     |
y= 30.0         +===========#####=============+   +===========#####=============+
                               ^                                 ^
                      ramp_far (105, 30)                ramp_far (275, 30)
          |     |                             |   |                             |
          0    30                            180 200                           350
          |<--->|                             |<->|
          margin_m = 30 m                     gap_m = 20 m
          pad origin (0, 0)                   corridor is ramp_width_m = 25 m wide
```

The exact objects, printed from the constructor:

```
  HIGH_SMR   x 30.0 .. 180.0   y 30.0 .. 87.0   access (105.0, 87.0)   ramp_far (105.0, 30.0)
  LOW_SMR    x 200.0 .. 350.0  y 30.0 .. 87.0   access (275.0, 87.0)   ramp_far (275.0, 30.0)
  each area: 150 x 57 m, plan area 8550.0 m2, ramp_width_m 25.0
  benches:   index 0 top 8.7 m, index 1 top 17.4 m, designed volume 55139.3 m3 each
```

**The margin is an offset from the pad origin, not a clearance on four sides.** The formulae above put
`margin_m` between the origin and the first area in both x and y, and nothing beyond `x1` or `y1`. If
the caller wants ground around the yard in every direction, and the `rectangular_yard` docstring is
explicit that a dump area needs it, because that is where the run-out goes and where the haul road runs,
then the caller must size the `Terrain` accordingly. The docstring records what the missing clearance
cost before the offset existed: 221 of 766 planned tips on the reference scenario refused for having
nowhere to land, which it calls "a fifth of the campaign lost to the edge of an array". The count is
the measurement; the fraction in that sentence is the docstring's own and it is loose, since 221 of 766
is closer to three tenths.

`rectangular_yard` raises `ValueError` when `classes` is shorter than `n_areas`. `Area.__post_init__`
raises `ValueError` on a non-positive extent, which matters in section 8.

---

## 3. Areas

```python
@dataclass
class Area:
    name: str
    x0_m: float; y0_m: float; x1_m: float; y1_m: float
    benches: list[Bench] = field(default_factory=list)
    material_class: str = ""
    access_xy: tuple[float, float] | None = None
    ramp_width_m: float = 25.0
```

```
  width_m      = x1 - x0
  length_m     = y1 - y0
  plan_area_m2 = width_m * length_m
  centre       = ((x0 + x1)/2, (y0 + y1)/2)
  contains(x, y) = x0 <= x <= x1 and y0 <= y <= y1          inclusive on all four bounds
  distance_from_access(x, y) = |(x, y) - access|
```

The footprint is an **axis-aligned rectangle**, and the docstring names this as a known simplification:
a general polygon is the honest representation of a real dump-location polygon, and a rectangle is
enough to carry a name, a schedule and a containment test, which is the only thing the rest of the
engine asks of it. If real survey polygons ever arrive, `contains`, `centre`, `inset` and `on_ramp` are
the four methods that have to change, and `on_ramp` is the hard one.

`DumpPlan.area(name)` raises `KeyError` listing the names it does have. `DumpPlan.area_at(x, y)` returns
the **first** area containing the point, so overlapping footprints resolve silently by list order.

---

## 4. Benches

```python
@dataclass(frozen=True)
class Bench:
    index: int
    top_m: float                # CUMULATIVE elevation of this lift's top above the pad
    designed_volume_m3: float   # what terminates the edge campaign
```

`rectangular_yard` sets `top_m = (index + 1) * bench_height_m`, so the tops of a two-bench 8.7 m schedule
are 8.7 and 17.4. `build` recovers the height of an individual bench with
`bench_height = max(bench.top_m - prev_top, 1e-6)`, because a bench's run-out depends on its own height
and not on how high its top sits above the pad: the second lift of a two-lift pile cascades over its own
face, not over both.

The stopping rule for the edge campaign is a **volume**, not a load count, because the source phrasing is
that edge dumping continues until it fills the designed volume for the given bench.

### 4.1 The designed volume is a frustum, computed

A bench is not a box. Its sides stand at the angle of repose, so the solid is a rectangular frustum and
its volume follows from the footprint, the height and the repose angle by the prismatoid rule:

```
_frustum_m3(w, l, h, repose_deg):

  inset = h / tan(repose_deg)          horizontal run of a face of height h
  wt    = max(w - 2*inset, 0)          top face width,  clamped at zero
  lt    = max(l - 2*inset, 0)          top face length, clamped at zero
  mid_w = (w + wt) / 2                 the mid-height section, prismatoid rule
  mid_l = (l + lt) / 2
  V     = (h / 6) * (w*l + 4*mid_w*mid_l + wt*lt)

  w, l   footprint width and length in metres
  h      bench height in metres
  V      volume in cubic metres
```

Measured for the figure's geometry (150 by 57 m, 8.7 m, 37 degrees):

```
  box                w * l * h            = 74385.0 m3
  _frustum_m3                             = 55139.3 m3        0.7413 of the box
  face inset at this height  h / tan(37)  =    11.545 m
```

This replaced a blunt 0.55 fraction of the box, and the docstring records why: that constant asked a 60 m
square to hold 51,500 m3 of a shape whose capacity at repose is far less, so the plan kept issuing tips
for material the pile could not hold, the surplus spread past the area boundary, and the refusal rate
stopped meaning anything.

### 4.2 Two things about that volume which the docstrings get wrong

**The formula does not degrade to a pyramid.** `rectangular_yard`'s docstring says that where the height
is enough to close the frustum to a point the solid is a pyramid and the formula degrades to that on its
own. It does not. Once `2 * inset` exceeds the shorter footprint dimension, `wt` and `lt` clamp at zero
but `h` keeps multiplying, so the returned volume keeps growing linearly with a height the pile cannot
physically reach. Measured on a 60 m square at 37 degrees, where the pile closes to a ridge at
`30 * tan(37) = 22.607 m` and holds 27,128 m3 there:

```
  h        _frustum_m3     ratio to the true capacity
  11.303 m      23737           0.875
  22.607 m      27128           1.000     exact at closure
  25.998 m      31197           1.150
  33.910 m      40692           1.500
  45.213 m      54256           2.000
```

The formula is exact up to closure and an overestimate above it, unbounded. The docstring's own quoted
27,100 for the 60 m square at 26 m is the **capacity**, not what the function returns for that call;
`_frustum_m3(60, 60, 26, 37)` returns 31,200. A caller who sets `bench_height_m` above
`min(width, length) / 2 * tan(repose)` gets a designed volume the footprint cannot hold, which reproduces
exactly the failure the frustum was introduced to fix. There is no guard in the code today. The guard
would be a check in `rectangular_yard` that `bench_height_m` is below the closure height, or clamping
`h` to it inside `_frustum_m3`.

**Every bench gets the same volume.** `rectangular_yard` computes `per_bench` once, from the **full**
footprint, and gives that same figure to every bench in the schedule. A two-bench 8.7 m yard is therefore
designed as two identical full-footprint frusta stacked, not as one tapering solid whose upper bench sits
inside the lower one. Measured above: both benches of both areas came out at 55,139.3 m3. Whether that is
what you want depends on the operation, but it is not what the geometry of a single frustum of total
height `n_benches * bench_height_m` would give, and nothing in the module says so.

---

## 5. The reserved access ramp

Waste dump design reserves access. A footprint is built up by lifts, with access to successive lifts
achieved by establishing ramps of a suitable width, super elevation and gradient (Cogent Engineering
4(1), 1387955). Without a reserved corridor the pile grows over its own access and the plan starts asking
for tips no truck can reach. `Area`'s comment records the measurement from before the corridor existed,
in its own words: a third of all planned tips refused, 79 of 80 for having no drivable route.

### 5.1 Where the access point is

```python
@property
def access(self):
    return self.access_xy if self.access_xy is not None else ((self.x0_m + self.x1_m) / 2.0, self.y1_m)
```

The default is **the midpoint of the +y edge**, not a corner. The comment above the property explains the
change: areas are laid out along +x from the origin, so the `(x0, y0)` corner it used to default to is
the one buried deepest in the layout. For a single 90 m area on a 140 m pad that corner sat in the pad
corner with the area itself between it and every approach, and no truck could reach the entrance at all.
An edge midpoint on the open side is where a haul road actually meets a dump.

Do not trust the comment on the `access_xy` FIELD, twenty lines earlier in the same class. It still says
"Defaults to the area's own lower-left corner, which is where a yard laid out from the origin is
normally entered", which is the behaviour that was replaced. The property is what runs.

`access_xy` overrides it, and callers do: the end-to-end test fixture in `tests/test_build.py` sets
`(90.0, 90.0)`. Note that this is **not** a corner. That area runs 30 to 120 m in both axes, so
`(90, 90)` is an interior point two thirds of the way toward the pit side, where the shovel at
`(140, 140)` is. The comment gives the reason: entering from the pit side makes the crest advance back
toward the way out. `ramp_far` is then `2 * centre - access = (60, 60)`, so the corridor runs on the
pad diagonal rather than down an axis.

### 5.2 The corridor

```
  ramp_far = 2 * centre - access                the access point reflected through the centre

  on_ramp(x, y):
      v      = (ramp_far - access)              vector across the whole area
      span   = |v|
      if span < 1e-9:  return False
      u      = v / span                         unit vector along the corridor
      d      = (x, y) - access
      along  = d . u                            distance from the access point along the corridor
      if along < 0 or along > span:  return False
      across = |-d_y * u_x + d_x * u_y|         perpendicular offset from the centre line
      return across <= ramp_width_m / 2
```

The corridor runs **across** the area to the reflected point, not merely to the centre, and the docstring
says why: the run available is what limits the lift a ramp can serve. At a working gradient of about 0.43
a corridor half the area long tops out around 19 m, and a bench schedule that designs past that produces
a working level nothing can climb to.

That arithmetic checks out and generalises to

```
  max lift a corridor can serve = span * max_grade * grade_frac

  max_grade  = tan(repose) / grade_limit_divisor  = 0.50237 at the defaults (document 01, section 4)
  grade_frac = 0.85, the constant dozer.build_ramp grades to
  so          max_grade * grade_frac              = 0.42701
```

For the figure's 57 m span: `57 * 0.42701 = 24.34 m`, and half of that span serves 12.17 m. For the 90 m
area the docstring is talking about, half the span is 45 m and serves 19.2 m, which is the 19 in the text,
and the full span serves 38.4 m, which is the "roughly doubles it".

Note that `on_ramp` tests the corridor geometry only. It does **not** test containment in the area, so a
point outside the rectangle but within the corridor band returns True. Callers filter by area first;
`dozer.build_ramp` starts from `_cells_of(terrain, area)`.

### 5.3 The corridor is a cut in the fill, not a void in it

This is the part most likely to be misread from the plan alone. `paddock_tips` fills **the whole area,
including the access corridor**, and the comment in the loop says so explicitly, pointing at
`dozer.build_ramp`: the ramp is a cut maintained in the fill, not a void reserved in it.

`build_ramp`'s docstring records why the obvious design fails. A corridor 25 m wide and 58 m long that has
to rise to the working level needs as much material as a sizeable fraction of the lift itself, all of it
shoved in sideways by a blade with a fifteen-metre reach, while the trucks that could have supplied it are
forbidden from driving there. Measured on a 90 m area: the entire 1296-cell area came out unreachable at a
peak of 3.2 m, because the corridor stayed a trench with 3 m walls on both sides and there was no way up
out of it. So the trucks fill everything and the dozer cuts the road back into what they filled, every
pass, and the material is then always right where the blade needs it.

The consequence for anyone reading `design.py` in isolation: **the corridor has no effect on tip
generation at all**. `on_ramp` is not called from `design.py`. Its only callers are in `dozer.py`. The
corridor exists in the plan so that the dozer knows where to cut, and for no other reason.

---

## 6. Phase one: the paddock lattice

The specification, quoted in the module docstring from Young and Rogers 2021 section 3:

> "In a heaped fill stockpiling scenario, dumping occurs in two phases. The first phase is a series of
> paddock dumps to form the base layer of the stockpile. The second phase involves building an upper layer
> above an area of the paddock dumps from which a campaign of edge dumps occurs until the bench is
> completed."

`DumpPlan.paddock_tips(area, bench, *, start_seq=0)` emits the base layer:

```
  rows:  y_k = y0 + row_spacing_m / 2 + k * row_spacing_m,   taken while y_k <= y1
  along: x_m = x0 + tip_spacing_m / 2 + m * tip_spacing_m,   taken while x_m <= x1

  the half-spacing inset keeps the lattice inside the polygon rather than on its boundary

  rows are then SORTED by  -distance_from_access(midpoint of the row)
  row k is walked in reverse when k is odd (serpentine)
  heading_rad = 0    on even rows (travelling +x)
              = pi   on odd rows  (travelling -x)
```

Three things are load-bearing here.

**Work away from the access.** Rows furthest from the entry point are filled first, so the truck never has
to cross material it has already placed. Filling the near rows first walls the machine out of its own dump
area, and the comment records that this is what the measured refusals were.

**Serpentine order is physical, not cosmetic.** The truck that finishes a row is at its far end and the
next row starts from there. It matters for the material as well: consecutive loads come from consecutive
trucks and therefore from nearby material in the pit, so the serpentine order puts correlated grades next
to each other instead of scattering them.

**Heading is the direction of travel.** The tray discharges behind the truck, so the load lands opposite
the way it drove in. `Truck.discharge_xy` applies that offset at execution time.

Measured on the figure's HIGH_SMR area at the `DumpPlan` defaults (`row_spacing_m=25.0`,
`tip_spacing_m=3.0`):

```
  one call returns 100 tips: 2 rows of 50
  row y values, in emission order: 42.5 then 67.5      (access is at y=87, so 42.5 is farther)
  first three tips: (31.5, 42.5, 0 deg), (34.5, 42.5, 0 deg), (37.5, 42.5, 0 deg)
  headings present: 0 deg and 180 deg only
```

One call is one pass over the footprint. `bench_program` calls it repeatedly until the paddock target is
met.

---

## 7. Phase two: radial sweeps from a seed

`DumpPlan.edge_tips(area, bench, *, n_tips, run_out_m, start_seq=0, lift=0)` emits **one lift** of the
upper layer, not a whole bench. The measured pattern is a radial progression from an initial cluster
point, with material added in sweeping radial movements, and the resulting plot is a set of nested arcs
rather than rows (Minerals 2021, figure 12).

```
  F     = the one of the four area corners maximising distance_from_access
  C     = area centre
  S     = (F_x + seed_frac_x * (C_x - F_x),  F_y + seed_frac_y * (C_y - F_y))     the seed
  step  = max(run_out_m * sweep_advance_frac, tip_spacing_m)

  seed cluster:
      n_seed = max(3, n_tips // 20)
      for k in 0 .. n_seed-1:
          a = 2*pi*k / n_seed
          r = step * 0.25
          P = S + r * (cos a, sin a);  if P is outside the area, P = S
          heading_rad = a

  sweeps:
      max_r = hypot( max(S_x - x0, x1 - S_x),  max(S_y - y0, y1 - S_y) )
      ring  = 1, 2, 3, ...  while ring*step <= max_r and fewer than n_tips emitted
          r         = ring * step
          n_on_ring = max(4, int(2*pi*r / tip_spacing_m))
          for k in 0 .. n_on_ring-1:
              a = 2*pi * (k + 0.5 * (lift mod 2)) / n_on_ring
              P = S + r * (cos a, sin a)
              SKIP P entirely if it is outside the area           (no clamping, no projection)
              heading_rad = a
```

Arc length between tips is held at the lattice spacing, so outer sweeps carry more loads than inner ones.
That is correct behaviour: a longer crest needs more dumps to advance it by the same amount.

**Seed opposite the access**, for the same reason the paddock rows are sorted that way. The upper layer
starts as a cluster and sweeps outward, so seeding it beside the entry point buries the entry point first
and walls the machine out of the area it is meant to be filling.

**`lift` rotates the ring phase** by half a step of arc, so successive lifts do not drop every load on the
seam left by the one below.

**`heading_rad` here is provisional.** It is set radially outward from the seed, which is the right answer
while the face is a growing disc, but the execution step resolves it against the live crest normal
because that is what the measurement actually specifies. See document 01, section 3.

Measured on the figure's HIGH_SMR area, asking for 200 tips at the default lift run-out:

```
  seed corner F         = (30.0, 30.0), the corner farthest from access (105, 87)
  seed S                = (48.75, 37.125)
  first tips returned   = (49.5, 37.1), (49.4, 37.6), (49.0, 37.8), (48.5, 37.8), (48.1, 37.6)
  n_seed                = max(3, 200 // 20) = 10
  tips returned         = 200
```

Note what `step` comes out as at the defaults. With `lift_thickness_m = 1.5` and `repose_deg = 37.0` the
lift run-out is `1.5 / tan(37) = 1.9906 m`, so `1.9906 * 0.6 = 1.19 m`, which is **below** `tip_spacing_m`
and the `max(...)` clamps the ring step to 3.0 m. At the shipped defaults `sweep_advance_frac` therefore
has no effect on the sweep spacing; the lattice spacing sets it. That is worth knowing before tuning
`sweep_advance_frac` and expecting anything to move.

---

## 8. Putting a bench together

```python
DumpPlan.bench_program(area, bench, *, load_volume_m3, run_out_m, paddock_frac=0.35)
DumpPlan.program(*, load_volume_m3, run_out_m, paddock_frac=0.35)
```

```
  total_loads      = max(1, round(bench.designed_volume_m3 / load_volume_m3))
  n_paddock_target = round(total_loads * paddock_frac)

  PHASE 1: call paddock_tips repeatedly over the FULL footprint, truncating the last batch,
           until n_paddock_target tips exist. Break if a call returns nothing.

  PHASE 2: run_per_lift = lift_thickness_m / tan(repose_deg)
           lift = 0, 1, 2, ... while fewer than total_loads tips exist:
               face = area.inset(lift * run_per_lift)
               STOP if face.width_m < 2*tip_spacing_m or face.length_m < 2*tip_spacing_m
               n_lift        = max(1, round(face.plan_area_m2 * lift_thickness_m / load_volume_m3))
               lift_run_out  = lift_thickness_m / tan(repose_deg)
               sweep = edge_tips(face, bench, n_tips=min(total_loads - emitted, n_lift),
                                 run_out_m=lift_run_out, start_seq=emitted, lift=lift)
               STOP if sweep is empty
```

`Area.inset(d)` shrinks the rectangle by `d` on every side about its centre, keeping the name, the
material class, the access point, the ramp width and the bench list. It is what makes a bench a bench:
every lift sits inside the one below it by the horizontal run of the face, so the sides of the finished
solid stand at the angle of repose. The comment records the alternative measured: filling every lift over
the full footprint on a 90 m square designed to 26 m gave the right volume and a peak of 14.6 m, because
the loads were spread over 8100 square metres at every level instead of climbing a shrinking one.

Two more corrections are recorded in the comments, and both are about the sweep budget. Letting a sweep
run until the ring lattice was exhausted made every lift as thick as its coverage allowed, nearly three
metres on the full footprint against an inset sized for one and a half, so the first lifts consumed the
whole load budget on the widest part of the solid and the pile never climbed. And passing the **bench's**
run-out rather than the **lift's** spaced the rings twenty metres apart on a lift a metre and a half thick,
which produced 551 tips against a designed 766 and returned the shortfall as "this area is built out".

Measured, for the figure's HIGH_SMR bench 0 at the `bench_program` default `paddock_frac=0.35` and the
default CAT 793F load volume of 121.579 m3:

```
  designed volume         55139.3 m3
  total_loads             454              round(55139.3 / 121.579)
  n_paddock_target        159              round(454 * 0.35)
  tips emitted            454              159 paddock + 295 edge
  run per lift            1.9906 m         1.5 / tan(37)
  whole plan (2 areas x 2 benches)   1816 tips, the first area completed before the second starts
```

`program` walks areas in list order and, within an area, benches sorted by index, matching the practice of
building one pile per material class at a time.

### 8.1 `run_out_m` is accepted and ignored

`bench_program` and `program` both require a `run_out_m` keyword and **neither reads it**. The lift loop
computes `lift_run_out` from `lift_thickness_m` and `repose_deg` and passes that to `edge_tips`. Verified
by running the figure's HIGH_SMR bench 0 with `run_out_m=1.0` and with `run_out_m=999.0`: 454 tips both
times, and the two lists compare equal, so identical coordinates, headings, phases and sequence numbers.

`build` still computes `run_out_for_bench(bench_height, face_deg)` and passes it in, but it also keeps its
own copy in the work queue and uses that copy for the placement physics, which is where run-out genuinely
matters. So the parameter is dead in the planner and live in the builder. Removing it from the two planner
signatures is an API break; leaving it is a trap for the next reader who tries to tune sweep spacing
through it.

### 8.2 `Area.inset` raises where its docstring says it clamps

The docstring says inset "clamps rather than inverting, so a caller can ask for more inset than the area
has and get a degenerate area back to stop on". It does clamp the half-extents at zero, and then
`Area.__post_init__` rejects the result:

```
  Area(name="ROM", x0=30, y0=30, x1=120, y1=120).inset(44.9)   ->  width 0.2 m, fine
  Area(name="ROM", x0=30, y0=30, x1=120, y1=120).inset(45.0)   ->  ValueError: area 'ROM' has a
                                                                   non-positive extent
```

`bench_program` is usually protected by its `2 * tip_spacing_m` guard, but only usually. The guard fires
on the first lift whose width falls below `2 * tip_spacing_m`, and that lift must still have been
constructed by `inset` before the guard can look at it. Successive lift widths fall by
`2 * lift_thickness_m / tan(repose_deg)`, which is 3.98 m at the defaults, so the last positive width is
`min(width, length) mod 3.98`, and the guard only catches it if that remainder is below
`2 * tip_spacing_m`. The guard is therefore **guaranteed** only when
`tip_spacing_m >= lift_thickness_m / tan(repose_deg)`, which is 1.99 m at the defaults. Below that it
depends on the footprint. On the 22 m square below the last positive width is 2.09 m, so `tip_spacing_m`
of 0.5 and 1.0 both raise while 1.5, 2.0 and 3.0 return normally. Reproduced:

```python
a = Area(name="X", x0_m=0.0, y0_m=0.0, x1_m=22.0, y1_m=22.0)
b = Bench(index=0, top_m=40.0, designed_volume_m3=400000.0)
a.benches = [b]
plan = DumpPlan(areas=[a], tip_spacing_m=0.5, row_spacing_m=5.0)
plan.bench_program(a, b, load_volume_m3=121.57894736842105, run_out_m=5.0, paddock_frac=0.02)
# ValueError: area 'X' has a non-positive extent
```

The lift widths for that area run 22.00, 18.02, 14.04, 10.06, 6.08, 2.09, and then the seventh inset
exceeds the half-width and the constructor rejects it. At the shipped defaults
(`tip_spacing_m=3.0`, guard 6.0, decrement 3.98) the guard is 6.0 against a decrement of 3.98 and so
always fires first, which is why this has never been seen in a build. The fix is either to make `inset`
return the degenerate area its docstring promises, or to move the guard above the `inset` call.

### 8.3 The other anchored constants

```
  paddock_frac       0.35 in bench_program and program, 0.18 in build
  sweep_advance_frac 0.6      inert at the default lift thickness, see section 7
  seed_frac_x/y      0.25     off-centre because the measured pattern seeds near one corner
  lift_thickness_m   1.5      "a dump is of the order of a metre thick and the dozer spreads it"
  row_spacing_m      25.0     "roughly two truck lengths", a site choice, not from the source
  tip_spacing_m      3.0      this one IS from the source: CCG 2006, 50 loads 3 m apart along a 150 m row
  loads_per_dozer_pass 12     access work: grade the ramp, level the floor
  loads_per_full_pass  60     adds the crest push and the safety berm on top of an access pass
```

`paddock_frac` is the one to be careful with. The source describes the base layer as "a series of paddock
dumps" without quantifying it, so the default is an exposed parameter rather than a measured number, and
the two defaults in the codebase disagree: `bench_program` says 0.35 and `build` passes 0.18. `build`'s
comment gives the reason, which is that the base layer is one lift of heaps and against a tall bench that
is a small fraction of its volume, and that setting it too high starves the edge campaign so no face is
ever formed and none of the cascade physics runs at all. Anyone calling `bench_program` directly gets 0.35
and a different pile.

`tip_spacing_m = 3.0` is the only lattice constant traceable to a measurement: the CCG industrial
simulation dumped 50 loads 3 m apart along a 150 m row, with the material dozed up the pile after two rows
(Neufeld, Lyall and Deutsch, CCG Report 8 paper 306, 2006, for Anglo American). `loads_per_dozer_pass` is
that rule expressed in loads rather than rows so a caller can tighten or loosen it without restructuring
the lattice.

---

## 9. The plan proposes, the site disposes

`build` consumes the programme as a per-area queue and records what actually happened. A planned tip that
cannot be occupied is not an immediate refusal: the operator spots at the nearest workable point within
`max_spot_offset_m` (default 25 m) inside the same area, and the deviation is recorded in
`LoadRecord.spot_offset_m`, because the gap between planned and actual dump locations is what a
fleet-management export shows and is a genuine measure of how good the plan was. Only when there is no
drivable ground inside the area within that radius is the load refused, and the refusal carries its reason.

Measured end to end, on a 64 by 64 pad of 2.5 m cells with
`rectangular_yard(n_areas=1, area_width_m=90.0, area_length_m=90.0, bench_height_m=8.0, n_benches=2,
classes=["ROM"])`, `row_spacing_m=10.0`, `tip_spacing_m=8.0`, `loads_per_dozer_pass=40`, four CAT 793Fs
loading at a shovel at (140, 140), and 240 loads:

```
  bench 0 programme, at build's paddock_frac=0.18:   417 tips (75 paddock, 342 edge)
  placed 240, refused 0, refusal rate 0.0
  spot offsets: all zero, so every planned tip was directly occupiable
  profiles: paddock 75, oval 97, comet 37, rectangular 28, sloughed heap 3
  peak thickness 7.15 m, volume 29178.9 m3, 20 dozer passes
  the finished surface: 3860 of 4096 cells passable, 4092 reachable from the shovel
```

Where the access point sits changes the result, at 300 loads and everything else identical:

```
  access_xy = (90, 90), toward the pit side:  300 placed, 0 refused, 0 spot offsets, peak 8.26 m
  access left at the default (75, 120):       300 placed, 0 refused, 2 spot offsets (max 2.21 m),
                                              peak 6.59 m
  volume placed is 36473.7 m3 in both cases
```

Same material, same plan, 1.67 m of difference in the peak, driven entirely by which side the machines
come in from. That is the coupling the module exists to express.

---

## 10. What this module is, and what it is not

It **is** a generator of ordered, named, benched discharge positions with a phase label, plus the geometry
needed to reserve access and to size a bench.

It is **not** aware of terrain. Nothing in `design.py` imports `Terrain`, reads an elevation, or asks
whether a tip can be reached. `TipPosition` has no z.

It is **not** a feasibility check, and deliberately so. A position that cannot be reached is refused at
execution and recorded there, not quietly dropped here.

It is **not** a polygon model. Areas are axis-aligned rectangles, and `contains`, `inset` and `on_ramp`
all assume it.

It is **not** a scheduler. There are no times, no truck assignments and no fleet in the plan; `build`
assigns a truck by `seq % len(fleet.trucks)`.

It does **not** reserve the corridor from dumping. The corridor is filled like everything else and cut
back by the dozer, section 5.3.

---

## 11. Names a caller uses

```python
from bedblend import Area, Bench, DumpPlan, Phase, TipPosition, rectangular_yard

plan = rectangular_yard(n_areas=2, area_width_m=150.0, area_length_m=57.0,
                        bench_height_m=8.7, n_benches=2, classes=["HIGH_SMR", "LOW_SMR"])
plan.area("HIGH_SMR")                       # KeyError lists the names that do exist
plan.area_at(105.0, 60.0)                   # first containing area, or None
plan.paddock_tips(area, bench, start_seq=0)
plan.edge_tips(area, bench, n_tips=..., run_out_m=..., start_seq=0, lift=0)
plan.bench_program(area, bench, load_volume_m3=..., run_out_m=..., paddock_frac=0.35)
plan.program(load_volume_m3=..., run_out_m=..., paddock_frac=0.35)
```

`_frustum_m3` is private and not exported. `Phase` is a `str` Enum with values `"paddock"` and `"edge"`,
and its docstring says the value is the dump operator that will run. That is nearly true and the
exception matters: `build` computes

```python
at_face = tip.phase is Phase.EDGE and d_crest <= 3.0 * terrain.cell_m * 4.0
```

so `Phase.EDGE` selects `place_edge` only when the live crest is within three tip reaches. A tip
nominally in the edge campaign with no face in front of it is placed as a heap, because that is what the
material does. The plan's label proposes an operator; the terrain confirms it.

---

## References

Only what the source itself cites.

* Young, A. and Rogers, W.P. (2021), *Modelling of pre-crusher stockpiles*, Minerals 11(6), 636.
  [doi:10.3390/min11060636](https://doi.org/10.3390/min11060636). Table 1 for the dump record schema that
  makes an area name and a bench height the identity of a load; section 3 for the two-phase specification
  quoted in section 6; figure 12 for the radial sweep pattern reproduced by `edge_tips`. `design.py`
  cites it by author, year, volume and article number only; the title and the DOI are the ones the
  repository `README.md` carries.
* Cogent Engineering 4(1), 1387955.
  [doi:10.1080/23311916.2017.1387955](https://doi.org/10.1080/23311916.2017.1387955). Dump construction by
  lifts with ramp access of suitable width, super elevation and gradient, which is what `Area.access`,
  `Area.ramp_width_m` and `on_ramp` reserve. Cited in `terrain.py` and `design.py` without an author line.
* Neufeld, C., Lyall, G. and Deutsch, C.V. (2006), CCG Report 8, paper 306, for Anglo American. The source
  of `tip_spacing_m = 3.0` (50 loads 3 m apart along a 150 m row), of the dozer cadence (the material is
  dozed up the pile after two rows), and of the routing practice the `route` callable models (low and high
  SMR ore sent to separate stockpiles, one of each under construction at a time, split on a
  silica-to-magnesia threshold of 1.75). This is a report rather than a journal article and the source
  code gives no DOI for it.
* Young, A. and Rogers, W.P. (2022), Mining 2(1).
  [doi:10.3390/mining2010006](https://doi.org/10.3390/mining2010006). The source of the CAT 793F payload
  of 231 t in `TruckSpec`, which is the numerator of `load_volume_m3` and therefore what turns a designed
  volume into a tip count. It is **not** the source of `loose_density_t_m3 = 1.9`, the denominator: the
  docstring calls that a pick from the 1.6 to 2.2 t/m3 handbook band for hard rock. The page range is
  cited inconsistently in this repository (86-102 in `terrain.py` and `dump.py`, 92-114 in the
  repository `README.md`); the DOI is the reliable identifier.
