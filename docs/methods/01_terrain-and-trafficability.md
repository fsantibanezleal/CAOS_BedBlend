# 01. Terrain and trafficability

The ground is an elevation field over a regular pad. Two things are derived from it, and between them
they decide everything a machine is allowed to do next: the **crest** of the current working level, and
**trafficability**, meaning which cells a haul truck can stand on and which steps between cells it can
climb. The code lives in `bedblend/terrain.py` (the field, the crest, the slope rules) and
`bedblend/truck.py` (the two masks and the router). This document describes what those functions
actually compute, as of `bedblend` 0.07.002.

The one fact that organises the whole module: **a truck-built pile constrains its own construction**.
Freshly placed material stands at the angle of repose. A haul truck works to a gradient that this
engine derives as the repose gradient divided by 1.5, which is two thirds of it exactly. A face at
repose is therefore steeper than the limit by a factor of 1.5 by construction, and no truck stands on
one. That ratio is derived below from `Fleet.of`, not asserted.

---

## 1. The height field

`Terrain` is a plain dataclass holding two row-major float lists over an `nx` by `ny` pad of square
cells `cell_m` on a side. `z` is the current surface; `z0` is the ground the pad started from and is
never overwritten. Keeping `z0` is what makes "how much material is here" answerable separately from
"how high is the surface", which stop being the same question the moment the pad is not flat.

```
indexing and geometry
---------------------
  idx(i, j)   = j * nx + i                       row-major, i is the x index, j the y index
  ij(c)       = (c mod nx, c div nx)
  xy(c)       = ((i + 0.5) * cell_m,             CELL CENTRE, in metres, not the corner
                 (j + 0.5) * cell_m)
  cell_at(x, y) = idx(floor(x / cell_m),         None when the point is off the pad
                      floor(y / cell_m))

what is here
------------
  thickness(c)   = z[c] - z0[c]                  metres of placed material
  has_material(c) = thickness(c) > EMPTY_M       EMPTY_M = 1e-4 m
  volume_m3()    = sum_c (z[c] - z0[c]) * cell_m^2
```

Centres rather than corners is deliberate: every distance in the dump operators is measured between a
truck position and a cell, and a half-cell bias there is a systematic error in the placed footprint.

`EMPTY_M = 1e-4` separates the bare pad from a cell carrying material. The docstring records why it
exists: colouring a zero-height cell as material at grade zero made an empty pad read as a full pile in
a shipped release. Note that this is a different threshold from `relax.BARE_M = 1e-3`, which is the
relaxation solver's own "material thinner than this is not material" cut. The two are independent
constants in independent modules and neither is derived from the other.

Constructors are `Terrain.flat(nx, ny, cell_m, base_m=0.0)` and
`Terrain.from_ground(nx, ny, cell_m, ground)`, the second raising `ValueError` if the ground list
length does not equal `nx * ny`. `Terrain.copy()` deep-copies both surfaces.

The neighbourhood is 8-connected, orthogonals first and then diagonals, in the module-level `_OFFSETS`
tuple. The ordering matters because it is shared with the relaxation solver in `relax.py`; a
4-neighbourhood produces visibly square cones, which a reader correctly reads as a bug.

---

## 2. Two slope rules, and only one of them constrains a truck

This is the single most important thing to know before changing anything in these two modules. The
engine contains **two different slope measures**, in two different files, and they answer two different
questions.

### 2.1 Steepest neighbour: `Terrain.gradient`

```
gradient(c) = max over the 8 in-bounds neighbours n of  |z[c] - z[n]| / run(c, n)

  run(c, n) = cell_m            for the 4 orthogonal neighbours
            = cell_m * sqrt(2)  for the 4 diagonal neighbours

slope_deg(c) = degrees(atan(gradient(c)))
trafficable(c, max_grade) = gradient(c) <= max_grade
```

It returns a rise over run rather than an angle because every consumer compares it against a tangent.
The absolute value means an uphill neighbour counts the same as a downhill one.

### 2.2 Central difference: `truck.passable_mask`

```
for each cell c = (i, j):

  dx = (z[i+1, j] - z[i-1, j]) / (cell_m * s_i)      s_i = 2 in the interior, 1 on the i boundary
  dy = (z[i, j+1] - z[i, j-1]) / (cell_m * s_j)      s_j = 2 in the interior, 1 on the j boundary

  passable[c] = sqrt(dx^2 + dy^2) <= max_grade
```

Indices are clamped to the pad, so a boundary cell gets a one-sided difference over one cell width
rather than a two-sided one over two. Only the four orthogonal neighbours enter; the diagonals do not,
because `hypot(dx, dy)` is already the magnitude of the surface gradient in two dimensions.

### 2.3 Which one runs

`passable_mask` is what constrains machines. `Terrain.trafficable_mask` is called by **nothing** in the
package and by nothing in the test suite. `Terrain.trafficable` is called only from
`tests/test_dozer.py` and `tests/test_terrain_relax_dump.py`. `Terrain.gradient` reaches package code at
exactly one place, `topography.buildable_fraction`, which uses it to score a candidate pad before
anything is built. `Terrain.slope_deg` wraps it and has no caller at all, in the package or in the
tests; `topography.relief_stats` reports a `max_slope_deg` but computes its own gradient inline over
four offsets rather than calling either. Every route, every flood fill and every spotting decision goes
through `passable_mask` and `step_ok`.

If you are reading a comment somewhere in this repository that says a surface is or is not
"trafficable", check which of the two functions it meant. They disagree, on purpose, and by a lot.

### 2.4 What the disagreement costs, measured

Fixture: a 48 by 48 pad of 2.5 m cells (120 m square), carrying a flat-topped platform 8.0 m high whose
top is 25 by 25 cells (62.5 m square) and whose sides fall one cell per step at 37 degrees, so each face
step drops `2.5 * tan(37 deg) = 1.8839 m`, a gradient of 0.7536. Truck limit 0.50237 (section 4).

```
                                       central difference   steepest neighbour
  cells passable, whole pad, of 2304          1964                 1744
  cells the two rules disagree on              220 (all central-yes, steepest-no; zero the other way)
     of those, on the flat top                  92
     of those, on the face itself              128
     of those, on the bare pad                   0

  the flat top, 625 cells
    passable                                   621                  529
    rejected                            4 (the corners)     96 (the entire perimeter ring)
```

The 96 rejected top cells are exactly the crest ring, verified cell by cell against
`max(|i-23|, |j-23|) == 12`, the platform being centred on index 23 of 0 to 47. Under the steepest
neighbour rule the whole crest of the working level is ground no truck may occupy, which makes edge
dumping impossible by construction: the truck has to stand on the crest to tip over it. The central
difference rejects only the four top corners, at `(11, 11)`, `(35, 11)`, `(11, 35)` and `(35, 35)`,
where `dx` and `dy` are each 0.3768 and their magnitude is 0.5328, just over the limit; the crest ring
accounts for 92 of the 220 disagreements, the four corners being rejected by both rules.

The toe of the face goes the same way once the face is not built one clean cell-step at a time. On a
50 by 50 pad of 2.0 m cells carrying an 8 m platform whose top is the 48 m square from 26 m to 74 m and
whose face is the repose surface **sampled at cell centres** rather than stepped, 136 of the 1344 bare
pad cells are rejected by the steepest neighbour rule and **none** by the central difference: the last
material cell of the face can stand most of a full step above bare ground, and every bare neighbour of
it then has one steep neighbour. The stepped fixture above happens to bring its face down to a 0.464 m
toe, a gradient of 0.19, so its bare pad passes under both rules; that is a property of that fixture,
not of the rule.

The `passable_mask` docstring records the measurement that forced the change: a clean 8 m platform with
a correctly graded 0.5 ramp cut into it came out with 30 of 1296 cells reachable, and the ramp cells
themselves read as impassable while their along-ramp gradient was exactly at the limit, because the
spoil beside them was not. That figure is quoted from the source, not re-measured here.

There is also a cost argument. `passable_mask` is O(cells) and is computed once per pad, not once per
A* edge visit, which the docstring credits with keeping a build at tens of seconds rather than
hundreds.

---

## 3. The crest, and the direction the material runs

```
crest_cells(min_drop_m) = [ c : has_material(c)
                                and exists a neighbour n with z[c] - z[n] >= min_drop_m ]
```

A one-sided test: only a drop counts, so the foot of a face is not a crest. `build` calls it with
`crest_drop_m`, default 1.0 m, once before every load and again after an access-only dozer visit has
reopened the ground; `build._doze` calls it a third time inside a **full** pass, because the crest is
what `push_to_crest` is aimed at and what `build_berm` is raised along.

The crest is why the terrain module exists. The truck's distance to it selects which of the four
measured dump profiles forms, so without a crest there is no such distance and the engine can only ever
place one shape. `dump.distance_to_crest(terrain, x, y, crest)` returns the straight-line distance to
the nearest crest cell and returns infinity when the crest list is empty, which is the correct answer on
an empty pad: there is no face, so every load is a paddock heap.

The direction a load runs is `Terrain.outward_normal(c)`, the unit vector pointing down the face:

```
  i_lo = max(i-1, 0)   i_hi = min(i+1, nx-1)      j_lo, j_hi likewise
  dx_span = (i_hi - i_lo) * cell_m                counts the cells actually crossed
  dy_span = (j_hi - j_lo) * cell_m

  gx = -(z[i_hi, j] - z[i_lo, j]) / dx_span       negated gradient, so it points DOWNHILL
  gy = -(z[i, j_hi] - z[i, j_lo]) / dy_span
  mag = sqrt(gx^2 + gy^2)
  outward_normal(c) = (0, 0)               if mag < 1e-12
                    = (gx/mag, gy/mag)     otherwise
```

Spans count the cells actually crossed, so the value stays correct on the boundary where the stencil is
one-sided. A flat cell returns `(0, 0)` and the caller decides what that means, which is usually that
the load is a paddock heap rather than an edge dump. This is true steepest descent, not a snap to one
of eight compass directions, which matters because the measured rule the engine implements is that the
deposit runs perpendicular to the tangent of the dump location, and perpendicular to the crest tangent
is the same thing as along the outward normal.

`truck.spot(terrain, approach, tip, crest=...)` returns `(discharge heading, distance to crest)`. The
default heading is the reverse of the approach heading, because a rear-dump truck reverses into position
and the material leaves behind it. When the nearest crest cell is within `3.0 * tip_reach(terrain)` the
heading is overridden by that cell's outward normal instead. `tip_reach` is `4.0 * terrain.cell_m`, so
the override window is 12 cells, which is 30 m on a 2.5 m pad. Expressing it in cells is deliberate so
it scales with the pad's own resolution. Note that `spot` and `tip_reach` prefer the terrain over the
plan: the plan was written before the face moved, and the face is where the material actually goes.

`spot` is exported at package level; `tip_reach` and `step_ok` are not, and must be imported from
`bedblend.truck`.

---

## 4. The two-thirds rule, derived

Nothing in the engine hard-codes a truck gradient limit. `Fleet.of` derives one:

```python
# bedblend/truck.py
@classmethod
def of(cls, n, spec, shovel_xy, *, repose_deg=37.0, grade_limit_divisor=1.5) -> Fleet:
    max_grade = math.tan(math.radians(repose_deg)) / grade_limit_divisor
```

At the defaults, run against the installed package:

```
  tan(37 deg)                       = 0.7535540501027942     the repose GRADIENT
  max_grade = tan(37) / 1.5         = 0.5023693667351962     the truck limit, a rise over run
  max_grade / tan(37)               = 0.6666666666666667     exactly two thirds, by definition
  degrees(atan(max_grade))          = 26.67355198720938      the truck limit as an ANGLE
  26.6736 / 37.0                    = 0.7209068104651184     about 72 percent, not 67
```

So the "two thirds" is a ratio of **gradients**, and it is exact because it is the divisor itself. In
angle terms the truck works to roughly 72 percent of the repose angle, 26.7 degrees against 37. Quoting
the ratio as an angle ratio and the number as two thirds at the same time is wrong; they are two
different numbers for the same constant.

The consequence is arithmetic. A face standing at repose has gradient `tan(repose)`, which is
`grade_limit_divisor` times the limit, 1.5 times at the defaults. It cannot be climbed and it cannot be
stood on. A **fresh** heap is worse: `relax.FRESH_HEAP_SLOPE = 2.0` (a 2:1 slope, 63.43 degrees), which
is `2.0 / 0.50237 = 3.98` times the truck limit.

**What is true.** A slope at or above the repose angle is undrivable, always, by construction rather
than by measurement. That is why the dozer exists in the build loop, and why `build` reruns an
access-only dozer visit when a load is refused for having no drivable ground.

**What is not true, and is worth saying because a comment in `build.py` says it.** That comment reads
"Measured directly, every single cell of a settled heap is undrivable." Measured here on one settled
paddock heap (`place_paddock` with one CAT 793F load, 121.579 m3, on a 40 by 40 pad of 2.5 m cells,
settled to 37 degrees, peak 2.517 m): 12 cells carry material, of which **0 pass `Terrain.trafficable`
and 4 pass `passable_mask`**, the rule the router actually uses. The four are the thin outer skirt. On a
merged field of nine such heaps, a 3 by 3 lattice 8 m apart on the same pad, each settled to 37 degrees
(peak 2.805 m), 108 cells carry material and **80 of them pass `passable_mask`** against 0 that pass
`Terrain.trafficable`. Heaps that have grown into each other are three quarters drivable under the rule
in force and wholly undrivable under the rule that is not. The statement to keep is about slopes at
repose, not about cells that contain material.

**Anchored, not measured.** `grade_limit_divisor = 1.5` is a rule of thumb, and both `Terrain.trafficable`
and `Fleet.of` say so in their docstrings: trucks should not travel on slopes approaching the angle of
repose, and dividing the repose gradient by about 1.5 is the commonly repeated version of that. It is
exposed as a parameter rather than hidden as a default precisely so the product can state where the
number came from instead of implying a law. What would replace it: a machine rimpull and retard curve
for the specific truck under load, or a site's own haul road design standard, which is normally
expressed as a percentage grade for sustained ramps (commonly 8 to 10 percent) rather than as a fraction
of repose. Nothing in this engine reads such a standard today.

`repose_deg = 37.0` is likewise a caller-facing default that appears independently in `Fleet.of`,
`DumpPlan.repose_deg`, `rectangular_yard` and `build`. They are four separate defaults with the same
value, not one constant referenced four times. Changing the material's repose angle means changing all
of the ones that apply.

---

## 5. Reachability by flood fill

`reachable_mask(terrain, start, max_grade, *, passable=None)` answers "where can a truck get to from
here", for the whole pad at once.

```
  ok = passable if given else passable_mask(terrain, max_grade)
  s  = cell_at(start)
  if s is None or not ok[s]:  return all False

  out[s] = True; stack = [s]
  while stack:
      c = stack.pop()
      for n in neighbours(c):                     8-connected
          if out[n] or not ok[n]:      continue   CAN THE TRUCK STAND THERE
          if not step_ok(c, n):        continue   CAN IT GET THERE FROM HERE
          out[n] = True; stack.append(n)

  fringe = every not-yet-set neighbour of every set cell
  out[f] = True for f in fringe                   ONE RING, added unconditionally
```

Two tests, and they are different questions. A gentle shelf on the far side of a 6 m step is standable
and unreachable, and only the per-step test says so.

The reason it is a flood fill and not repeated routing is measured and recorded in the docstring:
choosing where a truck can spot means asking "is this reachable" for many candidate positions, and
answering that with one A* solve per candidate took a build from 40 seconds to over 500. One fill
answers it for every cell, after which a single A* solve produces the path.

**The fringe ring, and its caveat.** The final ring exists because a truck spots AT the edge of a face:
the crest cell it tips over is by definition steep on one side, and excluding it would make edge dumping
impossible. On the section 2.4 platform fixture, a fill started from (3.0, 60.0) on the bare pad reaches
1463 cells of which **120 are fringe**, cells reported reachable that do not themselves pass the
passability test. None of the 625 flat-top cells is reached, which is correct: that fixture has no ramp,
so a platform whose sides stand at repose has no drivable way onto it.

The ring is added **without a step test**. Demonstrated on a flat 2.5 m pad with a single cell raised to
3.0 m: the raised cell passes `passable_mask` for the reason in section 6.1, its neighbours are
reachable, the step up onto it has gradient 1.2 against a limit of 0.502 and `step_ok` refuses it, and
`reachable_mask` reports it as reachable anyway. So `reachable_mask` is an over-approximation by exactly
one ring. Callers that need a cell a truck can actually drive onto must confirm with
`solve_route(..., strict_goal=True)`; `reclaim.py` is the caller that does.

If the start cell is not passable the mask is all False and no exception is raised. The routing
equivalent is louder: `solve_route` raises `NoRoute("the truck cannot stand at its start ...")`.

---

## 6. The per-step rule

```
step_ok(terrain, a, b, max_grade):
    run = cell_m              if a and b share a row or a column
        = cell_m * sqrt(2)    if a and b are diagonal neighbours
    return |z[b] - z[a]| / run <= max_grade
```

This is the gradient of the step, which is what a machine climbs. A cell being at the lip of a face says
nothing about whether the move along the lip is drivable, and the two masks in section 5 exist because
those are separate facts.

### 6.1 A central difference cannot see a one-cell feature

The stencil in section 2.2 samples `i-1` and `i+1` and never `i`, so a spike or a pit exactly one cell
wide is invisible to it. Measured on a flat 2.5 m pad with one cell raised to +3.0 m and another dropped
to -3.0 m:

```
  cell             passable_mask     Terrain.gradient
  +3.0 m spike        True                 1.20
  -3.0 m pit          True                 1.20
```

The spike's four orthogonal neighbours are correctly rejected, because for them the spike lies on one
axis; its four diagonal neighbours are accepted, because for them it lies on neither. `step_ok` refuses
the step onto the spike, so nothing routes over it, and this is the division of labour the design
intends: the mask says whether the ground tilts under the machine, the step test says whether the move
is climbable. It does mean that **`passable_mask` alone is not a safe drivability test**. Anything that
consumes the mask without also applying `step_ok` will accept single-cell artefacts, which is exactly
what a fresh dump on an otherwise flat floor can look like at coarse cell sizes.

`step_ok` is only meaningful between **adjacent** cells. `Route` keeps both a simplified `points`
polyline and the unsimplified `cells` path for exactly this reason: the docstring records that a check
applying `step_ok` to consecutive `points` divides a fifty metre segment's rise by one cell width and
overstates its gradient twentyfold, and that the reclaim route test did exactly that and passed for
releases because its long segments happened to be flat. Validate routes against `Route.cells`.

**A float knife edge.** The comparison is `<=` against a value that is itself the result of a division,
so a ramp graded at *exactly* `max_grade` is not reliably drivable. Measured: a 10-cell ramp whose cell
`i` sits at `i * cell_m * max_grade` had **2 of its 9 steps rejected** by `step_ok`, because
`(i+1)*c*G - i*c*G` does not always round to `c*G`. `dozer.build_ramp` sidesteps this by grading to
`grade_frac = 0.85` of the limit rather than to the limit. A ramp generator that targets the limit
exactly will produce intermittent, position-dependent refusals.

---

## 7. Routing: A* on true travel distance

`solve_route(terrain, start, goal, *, max_grade, simplify=True, passable=None, strict_goal=False)`.

```
  edge cost  g(c, n) = |xy(n) - xy(c)|         = cell_m for an orthogonal step
                                               = cell_m * sqrt(2) for a diagonal step
  heuristic  h(c)    = |xy(goal) - xy(c)|      straight-line, hence admissible on this cost
  priority           = g + h
```

Because the heuristic never overestimates a cost measured in the same metres, the path returned is
optimal. Using a step count as the cost instead is what produces the staircase paths that make a route
drawing look like a bug.

Measured on an empty 60 by 60 pad of 2.5 m cells, routing from (10, 10) to (130, 130):

```
  cells in the grid path              49        so 48 steps, all diagonal
  polyline points after simplify       2
  route length                   169.7056 m
  straight-line distance         169.7056 m     ratio 1.000000
  what a step-count cost scores  120.0000 m     48 steps * 2.5 m, which is 0.707 of the truth
```

Failure modes, all of them `NoRoute`, which is a named exception because refusing an unreachable tip is
a result and not an error to be swallowed:

* `start` or `goal` off the pad: "start ... or goal ... is off the pad".
* the start cell not passable: "the truck cannot stand at its start ...".
* no drivable path: "no drivable route to ...: the pile has grown over its own access, or the tip sits
  on ground steeper than the equipment limit".

`_simplify` drops interior points that lie on a straight run, tested by the cross product of the two
adjoining segments against `tol = 1e-6`, comparing each candidate against the last **kept** point rather
than its immediate predecessor. `Route.length_m` is computed over the simplified `points`.
`Route.position_at(frac)` walks that polyline for animation, and `Route.heading_at_end()` returns the
direction of the final segment, which is the truck's approach heading and therefore the input to
spotting.

---

## 8. The goal-cell exemption, and why a parked truck withdraws it

By default the **goal cell alone** is exempt from both the passability test and the per-step test:

```python
exempt = n == g and not strict_goal
if not exempt and not ok[n]:                    continue
if not exempt and not step_ok(terrain, c, n, max_grade):  continue
```

A truck spots at the crest, and the crest is by definition steep on one side. Requiring the discharge
cell to be flat would make it impossible to ever tip over an edge, which is the whole of the edge dumping
campaign. Every other cell on the path still has to pass both tests.

`strict_goal=True` withdraws the exemption. Tipping over an edge and standing to be loaded are different
manoeuvres, and only the first justifies an unclimbable last step. A truck routed to a place where it
will simply **park** must withdraw it.

Demonstrated on a flat 20 by 20 pad of 2.5 m cells with cell `(16, 16)` raised to 3.0 m, routing from
(3.0, 3.0) to (41.0, 41.0), so the only approach step has gradient 1.2 against a limit of 0.502:

```
  goal cell passes passable_mask       True
  the step onto it, step_ok            False       (gradient 1.2)
  solve_route(...)                     path found, 16 cells, ends on the goal,
                                       and its LAST STEP is not climbable
  solve_route(..., strict_goal=True)   NoRoute: no drivable route to (41.0, 41.0)
```

The only caller in the package that passes `strict_goal=True` is `reclaim.py`, for both the approach to
and the departure from a loader stand, with the comment that the truck parks there to be loaded and does
not tip over an edge. `Fleet.dispatch` and `Fleet.depart` both route with the default, which is correct
for them: `dispatch` is taking a truck to a tip, and `depart` starts from one.

`solve_route`'s docstring is explicit that adding `strict_goal` changed no route on the scenarios in the
repository, because the reclaim stand is already chosen from the passability mask and the flood fill, so
the ground around it is climbable anyway. It is a correction of the semantics, not the repair of an
observed defect.

---

## 9. Cost, and where this bites

`passable_mask` is a full pad sweep. Counted with an instrumented build of 10 loads on a 40 by 40 pad,
it runs **exactly 3 times per load**: once inside the `reachable_mask` that `build` computes before the
load, once inside `Fleet.dispatch`, and once inside `Fleet.depart`. Neither `dispatch` nor `depart`
accepts a caller-supplied mask, so the mask `build` already holds cannot be reused by them. A build of
240 loads on a 64 by 64 pad took 9.5 s end to end on the machine this was written on. If routing ever
becomes the bottleneck, threading the existing mask into `Fleet.dispatch` and `Fleet.depart` is the first
change to try, remembering that `depart` must be solved against the surface **after** the load has been
placed, because the load changed it.

---

## 10. What this is, and what it is not

It **is** a heightfield with two derived masks and a shortest-path solver over them, sufficient to make
access a real constraint on where material can be placed.

It is **not** a soil mechanics model. Nothing here computes bearing capacity, rutting, rolling
resistance or traction. "Trafficable" means one thing only: the local surface gradient is at or below a
caller-supplied limit.

It is **not** a vehicle dynamics model. There is no turning radius, no wheelbase, no reversing envelope
and no speed. A route is a sequence of cell centres; a real truck cannot follow an arbitrary 8-connected
path, and the polyline this produces is an idealisation of one.

It is **not** a scheduler. `Fleet` says so in its own docstring: queue times, bunching and dispatch
optimisation are a different product. One truck is routed per load.

It does **not** model the ramp as a reserved void. The plan reserves a corridor and the dozer cuts the
road back into what the trucks filled; see `dozer.build_ramp` and document 02.

---

## 11. Names a caller uses

```python
from bedblend import Terrain, TruckSpec, EMPTY_M          # bedblend/terrain.py
from bedblend import Fleet, Truck, Payload, Route, CycleState, NoRoute
from bedblend import passable_mask, reachable_mask, solve_route, spot
from bedblend.truck import step_ok, tip_reach              # NOT exported at package level
```

```
Terrain          flat, from_ground, copy, n_cells, idx, ij, xy, cell_at, neighbours,
                 thickness, has_material, volume_m3,
                 gradient, slope_deg, trafficable, trafficable_mask,
                 crest_cells, outward_normal

TruckSpec        name="CAT 793F", payload_t=231.0, bed_width_m=7.334, body_length_m=12.9,
                 dump_height_m=6.5, loose_density_t_m3=1.9
                 load_volume_m3 = payload_t / loose_density_t_m3 = 121.5789... m3

Truck.discharge_xy()   the release point, offset 0.66 * body_length_m from the truck centre
                       ALONG heading_rad, which is 8.514 m for the default spec. It reads
                       as "behind the truck" because by the time this is called
                       `heading_rad` is the DISCHARGE heading that `spot` returned, which
                       is the approach heading plus pi. The function itself does no
                       reversing; it adds (cos, sin) * off. Placing the load at the truck's
                       own coordinate strands the machine on its own load every cycle.

Fleet.of(n, spec, shovel_xy, *, repose_deg=37.0, grade_limit_divisor=1.5)
Fleet.dispatch(terrain, truck, tip, payload, *, crest=None) -> (heading, distance to crest)
Fleet.depart(terrain, truck, *, exit_xy=None) -> Route
```

Only two of the `TruckSpec` numbers are measured. The docstring attributes the 231 t payload and the
7.334 m inside bed width to the 2022 dump study, and says plainly that body length and dump height are
approximate published figures for the class and are exposed as parameters rather than presented as
exact. `loose_density_t_m3 = 1.9` is a pick from the 1.6 to 2.2 t/m3 handbook band for hard rock, and it
sets the volume of every load placed, so it propagates into the tip count of every bench (document 02,
section 8).

`Fleet.depart` swallows `NoRoute` on purpose and records a one-point departure at the truck's own
position: the load just placed can cut off the way out, which is how a badly sequenced plan strands
equipment, and that is a reportable situation rather than a crash. Read the code before relying on the
docstring's "rather than pretending the truck teleported home", because that is only half true. The
`Route` is honest, but `truck.x_m, truck.y_m = target` sits **outside** the `try`, so the truck's own
coordinates are set to the exit point whether or not a route was found. A caller detecting a stranding
must test the departure route (one point, or `length_m == 0`), not the truck's position.
`Fleet.dispatch` does not swallow it; a tip that cannot be reached raises, and `build` turns that into a
refused `LoadRecord`.

---

## References

Only what the source itself cites.

* Young, A. and Rogers, W.P. (2021), *Modelling of pre-crusher stockpiles*, Minerals 11(6), 636.
  [doi:10.3390/min11060636](https://doi.org/10.3390/min11060636). The source of the dumping-phase
  specification, the truck-scaled heap dimensions (figure 11), the radial sweep pattern (figure 12) and
  the rule that the deposit runs perpendicular to the tangent of the dump location (figure 13), which is
  what `outward_normal` computes. The docstrings cite it by author, year, volume and article number
  only; the title and the DOI are the ones the repository `README.md` carries.
* Young, A. and Rogers, W.P. (2022), Mining 2(1).
  [doi:10.3390/mining2010006](https://doi.org/10.3390/mining2010006). The CAT 793F payload and inside bed
  width in `TruckSpec`, and the profile geometry measured across 28 UAV-surveyed dumps. It is **not** the
  source of `body_length_m` or `dump_height_m`. The page range is cited inconsistently inside this
  repository (86-102 in `terrain.py` and `dump.py`, 92-114 in the README); the DOI is the reliable
  identifier.
* Cogent Engineering 4(1), 1387955.
  [doi:10.1080/23311916.2017.1387955](https://doi.org/10.1080/23311916.2017.1387955). Waste dump
  construction by lifts with ramp access of a suitable width, super elevation and gradient. Cited in
  `terrain.py` without an author line; the DOI is what the source gives.
* Bak, P., Tang, C. and Wiesenfeld, K. (1987), *Self-organized criticality: an explanation of 1/f
  noise*, Phys. Rev. Lett. 59(4), 381-384.
  [doi:10.1103/PhysRevLett.59.381](https://doi.org/10.1103/PhysRevLett.59.381). The toppling
  rule reused by `relax.py`, which is what puts a face at repose for this module to refuse. `relax.py`
  cites the journal, volume, pages, year and DOI but no title; the title above is the one the
  repository `README.md` and `docs/README.md` give.
