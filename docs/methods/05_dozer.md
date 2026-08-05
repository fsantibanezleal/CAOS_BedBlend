# 05. The dozer

Source: `bedblend/dozer.py`. Public names: `DozerPass`, `level`, `push_to_crest`, `build_berm`,
`build_ramp`, and the two module constants `DEFAULT_PUSH_M` and `DEFAULT_BLADE_M3`. Four of the five
callables are re-exported from the package root; `build_ramp` is not, and neither constant is, so
both must be imported from the module itself, as `from bedblend.dozer import build_ramp`. Everything
in this document was read from that file or measured by running it against the source tree at VERSION
0.07.002 in this repository.

## What the module is, and what it is not

The dozer is the operator that finishes a lift and restores access. A paddock campaign leaves a
lattice of separate frustums with hollows between them. No truck crosses that, and there is no
continuous crest to tip over, so without a machine that turns a field of heaps into a working level
nothing in the model ever completes a bench or reaches the next one.

Four operations, and they are the whole module:

| Function | What it does | Called by the build as |
|---|---|---|
| `level(terrain, area, *, target_z=None, push_m=40.0, blade_m3=30.0, tolerance_m=0.05, band_m=None)` | Spreads the heaps in an area into a bench floor | `level(terrain, area)` |
| `push_to_crest(terrain, area, *, normal, depth_m=0.3, push_m=40.0)` | Shaves the floor and pushes the shavings out over the face | `push_to_crest(terrain, area, normal=n, depth_m=0.2, push_m=15.0)` |
| `build_berm(terrain, crest, *, height_m=1.5, source_depth_m=0.2, gap_every=8, gap_cells=3)` | Raises a safety windrow along the crest, out of the material behind it | `build_berm(terrain, crest, height_m=0.4, source_depth_m=0.1)` |
| `build_ramp(terrain, area, *, max_grade, push_m=40.0, tolerance_m=0.15, grade_frac=0.85)` | Cuts and fills the access corridor into a drivable road | `build_ramp(terrain, area, max_grade=fleet.max_grade)` |

This module is not a soil-mechanics model of a blade. There is no cutting force, no blade load curve,
no tractive-effort limit, no cycle time and no fuel. It is a set of mass-conserving elevation
rearrangements chosen so that the surface they leave is one a truck can drive on and a face can be
tipped over, plus a record of how far the material travelled while they did it. It is also not a
scheduler: the cadence at which a dozer visits an area lives in `build.py` and in `DumpPlan`, not
here. Every function in this file acts once, immediately, on the terrain it is handed, and mutates
`terrain.z` in place.

It does not model compaction, and this matters more than it looks. Real dozer traffic compacts a
lift; the sources cited below name compaction as one of the things dozers are there to achieve. Here
a transfer moves an elevation from one cell to another with the bulk density unchanged, so a levelled
floor holds exactly the volume the heaps held. `material.py` carries the density chain and a
`max_compaction` figure; nothing in `dozer.py` reads it.

## The key output is displacement

Every function returns a `DozerPass`, and the reason it exists is the honesty requirement rather than
the geometry. The literature the module cites is blunt about what a dozer does to a provenance claim:
these actions mix the material from its initial dumping location "in intractable ways", and dozers
"frequently displace stockpiled material from its original dump location, making it hard to know
where material is located within the stockpile" (Young and Rogers, Minerals 2021, 11, 636, sections
3.3 and 1.3). A previous product reported provenance fractions summing to one within 1e-12 and
presented that as an answer. With a dozer in the model, that precision is a property of the
simulation and not of the world.

So a pass reports what it moved and how far, and the ledger carries the distance onto the individual
parcels. `DozerPass` has five fields and no methods other than `merge`:

```
transfers            list[tuple[int, int, float]]   (from_cell, to_cell, volume_m3)
volume_moved_m3      float                          total volume in the transfers
mean_displacement_m  float                          volume-weighted mean travel distance
max_displacement_m   float                          worst single travel distance
cells_touched        int                            distinct cells appearing in the transfers
```

`_finalise` turns a transfer list into a pass record, and it is the only place the statistics are
computed from transfers; `DozerPass.merge`, below, recombines two records that have already been
finalised. The definitions:

```
For one pass with transfers (a_i, b_i, V_i), i = 1..n :

    d_i      = || xy(b_i) - xy(a_i) ||             straight-line distance, metres
    V_total  = SUM_i V_i                            volume_moved_m3
    d_mean   = ( SUM_i V_i * d_i ) / V_total        mean_displacement_m, 0 if V_total = 0
    d_max    = MAX_i d_i                            max_displacement_m
    touched  = | { a_i } UNION { b_i } |            cells_touched

where
    xy(c)    is the CENTRE of cell c in pad metres, from Terrain.xy
    V_i      is a VOLUME in cubic metres, never a thickness
    d_i      is HORIZONTAL only; no vertical component enters the distance
```

Three consequences a maintainer should hold on to. The distance is plan distance between cell
centres, so a push that drops material five metres down a face records only the horizontal run.
`cells_touched` counts sources and destinations together, so a pass that moves material between two
cells reports two, not one. And an empty `transfers` list yields a default `DozerPass` with every
statistic at zero, which is why the build tests `if p.transfers:` before doing anything with a pass
rather than testing the volume.

`DozerPass.merge` combines two passes:

```
    V       = V_P + V_Q
    d_mean  = ( d_mean_P * V_P + d_mean_Q * V_Q ) / V     if V > 0, else 0
    d_max   = max( d_max_P , d_max_Q )
    touched = touched_P + touched_Q                        a SUM, not a union
```

The mean is correctly volume-weighted; measured on two consecutive levelling passes, the merged mean
of 25.9563 m reproduces the hand-computed weighted mean to every printed digit. `cells_touched` is
not: the same two passes touched 509 and 152 cells and merged to 661, while the number of distinct
cells across both was 549. Read a merged `cells_touched` as a count of cell-visits, not of cells.
`merge` has no caller anywhere in `bedblend/` or `tests/`, so it is public surface with no coverage;
treat it accordingly.

## How displacement reaches the ledger

`dozer.py` never touches the block model. It returns transfers, and the caller is responsible for
moving the provenance with the material. The pattern, from `build._doze`:

```python
r = build_ramp(terrain, area, max_grade=max_grade)
if r.transfers:
    model.apply_transfers(r.transfers, distances=transfer_distances(terrain, r.transfers))
```

`transfer_distances` recomputes the same per-transfer distances that `_finalise` used, and
`BlockModel.apply_transfers` adds each one onto every parcel that moved. Nothing enforces this
pairing. A caller that applies the transfers without the distances gets a ledger that is perfectly
consistent with the terrain and silently claims the material never moved, which is exactly the
overclaim the module exists to prevent. If you add a fifth dozer operation, wire it through
`_doze` and pass the distances.

Note also the unit convention. `DozerPass.transfers` carries volumes in cubic metres, which is what
`apply_transfers` expects. Relaxation transfers from `relax.relax_to` carry thicknesses, and
`build._carry` multiplies by `model.cell_area_m2` before handing them over. Two callers of the same
method with two different units is a live trap; `_carry` exists so the conversion has exactly one
home.

## `level`: making a bench floor

`level` is the operation that makes the next lift possible. Its target elevation defaults to the
mass-conserving mean over the area, which is the height the material already there would reach if
spread flat:

```
    z_target = ( 1 / |C| ) * SUM_{c in C} z[c]        when target_z is None

    C        cells of the area, after the optional band_m filter
    z[c]     current surface elevation of cell c, in metres
```

Passing `target_z` explicitly is how a caller builds to a designed bench top rather than to whatever
mean the loads happen to have produced. The build never does; it always takes the default.

Sources are chosen once at the start of the pass, sorted highest first:

```
    H = { c in C : z[c] > z_target + tol  AND  z[c] - z0[c] > tol }

    z0[c]  original ground under c, from Terrain.z0
    tol    tolerance_m, default 0.05 m
```

The second clause in that set is the one worth knowing about. ONLY PLACED MATERIAL CAN BE PUSHED. A
dozer spreads a stockpile, it does not excavate the pad. Selecting high cells by elevation alone is
correct on a flat pad and catastrophic on any of the four sloping fill types, because on a sidehill
the high ground is the hill. The source records the failure: the blade drove a cell 4.43 m below the
original surface, which is excavation nobody performed, and it broke the ledger against the terrain.
The same reasoning caps the budget:

```
    budget_c = min( (z[c] - z_target) * A ,  blade_m3 ,  (z[c] - z0[c]) * A )

    A = cell_m^2, the plan area of one cell, in square metres
```

Three bounds: the excess over target, one blade load, and what is actually there.

### The relay, and why the receiver is the lowest cell rather than the nearest

An earlier version pushed only from cells above the target directly onto cells below it, and it
stalled: after one pass the remaining high ground sat on one edge and the remaining hollows on the
other, 52 m apart against a 40 m push limit, with everything between them already at target and
therefore not a valid receiver. A real dozer moves material that far by shoving it repeatedly, each
shove within its own working distance. So a push goes to any cell in reach that is simply lower than
the source, whether or not it is below the global target, and successive passes walk material across
the area.

Which cell in reach is a point where the docstring and the code disagree, and the code wins. The
`level` docstring says material moves "to the NEAREST cells below it" and calls this "the
nearest-first rule". The implementation builds `reach` as `(z[d], d)` pairs and calls `reach.sort()`,
so it is sorted by ELEVATION ascending and the blade always aims at the lowest ground within
`push_m`. Two comments in the body say so correctly: the block above the loop states that a push
goes to the LOWEST cell in reach, and the inline comment on `reach.sort()` reads "lowest ground
first: that is where a blade pushes". Measurement settles
it: on the reference paddock field, 200 of 200 sampled transfers had at least one strictly closer
cell that was also lower than the source, and the pass reported a mean displacement of 26.01 m
against a 40 m limit on a 2.5 m grid. A nearest-first rule would report a mean of a few metres. Treat
the docstring sentence as stale and the behaviour as lowest-first.

This matters for the ledger, not just for the geometry. Lowest-first means provenance does not smear
locally; it is thrown to the far side of the reach disc, and the displacement statistic reports that
honestly. If you ever want the smearing to be local, that is a change to the sort key here, and it
will move every displacement number in the product.

### The cap, and why the pass converges

Each individual transfer is capped at half the height difference, so a push can never invert a pair:

```
    h_i = min( budget_remaining / A , 0.5 * ( z[c] - z[d] ) )
    z[c] <- z[c] - h_i
    z[d] <- z[d] + h_i
    V_i  = h_i * A
```

That cap is also what makes convergence provable. Take the sum of squared elevations over the area as
a Lyapunov function:

```
    L = SUM_{c in C} z[c]^2

    one transfer of thickness h from c to d, with diff = z[c] - z[d] > 0 and h <= diff/2 :

    L_after - L_before = (z_c - h)^2 + (z_d + h)^2 - z_c^2 - z_d^2
                       = 2h^2 - 2h*diff
                       = 2h ( h - diff )
                       <= -h * diff
                       <  0
```

Every transfer strictly decreases L, and L is bounded below, so repeated passes terminate. Measured
over 15 consecutive passes on the reference field, L was monotone non-increasing at every step. The
inner loop's early `break` on `diff <= tolerance_m` is sound for the same reason the sort is: within
one source's inner loop the current candidate has not yet been raised, and every later candidate had
a higher snapshot elevation and has not been raised either, so nothing further down the list can be
lower.

### Measured behaviour

Reference field: a 60 by 60 pad at 2.5 m cells, one 60 m square area, `row_spacing_m = 8.0`, a full
paddock base layer of CAT 793F loads placed and then relaxed to 37 degrees. 576 cells lie inside the
area.

One `level` call with defaults produced 407 transfers moving 1550.07 m3, with a mean displacement of
26.01 m, a worst case of 39.53 m and 509 cells touched. Volume before and after differed by exactly
zero. The largest single transfer was 15.43 m3, well under the 30 m3 blade, because the half-the-
difference cap binds long before the blade does on a floor this shallow. The pass took 0.037 s,
steady to within a millisecond over five runs.

`push_m` is respected exactly: asking for 10 m gave a maximum of 10.0000 m and a mean of 7.04 m,
against 39.53 m and 26.01 m at 40 m. Convergence with a 60 m3 blade took two passes: the elevation
spread over the area fell from 4.9388 m to 0.3656 m and then to 0.0926 m, and the third call returned
no transfers at all. Over those two passes the ledger's tonnage-weighted mean displacement went from
0.831 m, which the relaxation alone had already produced, to 2.965 m, and `assert_consistent` passed.

### `band_m` is available and deliberately unused

`band_m` restricts the blade to cells within that distance of the current working level, which is
what a dozer working a bench actually does, and the default build never passes it. The source records
why: levelling the whole footprint to its mean flattens the frustum the plan is insetting lift by
lift, so the band was tried, and the measurement did not support it. The peak fell from 13.6 m to
12.0 m and three reclaim invariants broke, because a pile with untouched flanks drains differently
than the campaign assumes. Those two figures are recorded in the source; they were not re-measured
for this document. The parameter was left in with the result written down rather than removed and
rediscovered later.

## `push_to_crest`: advancing the tip head

This is the "dozed up the pile" operation. After a couple of paddock rows the accumulated heaps are
pushed forward, which both advances the crest and clears the floor. `depth_m` is what comes off the
surface in one pass and `normal` is the direction of the face, supplied by the caller from
`Terrain.outward_normal` at the middle crest cell.

The cells are processed from the downstream edge backwards, sorted by descending along-normal
coordinate, so material pushed forward is not picked up again by the same pass. A cell is skipped
entirely unless `terrain.thickness(c) > depth_m`, and the pass then removes exactly `depth_m`, so a
push can never take a cell below original ground.

The destination is found by offsetting `push_m` along the unit normal and snapping with
`terrain.cell_at`. That snap is worth knowing about, because the recorded displacement is the actual
centre-to-centre distance of the snapped cell and not the `push_m` you asked for. With a normal of
(1, 0), a 2.5 m grid and `push_m = 10.0`, every transfer recorded exactly 10.0 m. With a normal of
(1, 1), the same request recorded 10.6066 m on every transfer, a six percent overshoot, because the
offset lands three cells across and three cells up.

### A docstring claim the code does not implement

The docstring says: "Material that would leave the area is deposited at the last cell inside it
rather than being dropped." The code does not do that. It evaluates the destination and, if
`cell_at` returns `None`, or the destination equals the source, or `area.contains` rejects the
destination, it executes `continue` and makes no transfer at all. Nothing is lost, so mass
conservation holds, but the material stays where it was instead of being relocated to the boundary.

Measured on the levelled reference field with a normal of (1, 0), `depth_m = 0.2` and
`push_m = 10.0`: of 576 cells eligible as sources, 480 were pushed and 96 were skipped, and every
skipped cell had an x between 81.25 m and 88.75 m on an area whose x extent ends at 90 m. That is
exactly the 10 m boundary band. Volume before and after differed by zero. If the documented
behaviour is the wanted one, the fix is to walk the offset back until it lands inside the area; as it
stands, a strip one push wide along the downstream edge never advances.

## `build_berm`: the safety windrow, and why it has holes in it

A berm is what stops a reversing truck going over the edge, and it is why a tip head is kept sloped
back from the void. It is modelled as a mass-conserving transfer onto each crest cell from its own
non-crest neighbours, so the berm costs material rather than appearing from nowhere. The docstring
calls those donors the cells "just behind" the crest; the code has no such notion of behind, and the
second caveat below says what it selects instead.

A berm has gaps in it, and leaving them out was a measured defect. A continuous berm along every
crest cell walls the working area off from itself. The source records the numbers: refusals went up
as the dozer ran more often, 62 percent at a pass per 10 loads against 33 percent at a pass per 40,
because each pass added more unbroken wall. Real tip heads have breaks so equipment can pass through
and a grader can reach the face. The pattern:

```
    period = max( 1, gap_every + max(0, gap_cells) )

    the crest cell at position pos is bermed  iff
        gap_cells == 0    OR    ( pos mod period ) < gap_every

    defaults 8 and 3 give period 11 and a duty-cycle ceiling of 8/11 = 0.727
```

Setting `gap_cells = 0` restores the continuous berm and reproduces the defect, which is why it is a
parameter rather than a constant.

Three caveats the code carries and the docstring does not.

First, `height_m` is a request, not a result, and nothing reports the shortfall. Each crest cell
walks its eight neighbours taking at most `source_depth_m` from each until `need` is satisfied, and
if the eligible neighbours run out the loop simply ends. Measured on 248 crest cells with
`height_m = 0.5` and `source_depth_m = 0.1`: 240 transfers raised 110 cells, of which zero reached
the requested 0.5 m. The mean height actually built was 0.2182 m, the minimum 0.1 m and the maximum
0.4 m. The duty-cycle ceiling would have allowed 0.727 of the crest to be bermed; donor availability
brought it to 110 of 248, or 0.4435. With `gap_cells = 0` the same field bermed 147 of 248, again
donor-limited rather than pattern-limited.

Second, the docstring says the material is taken from "uphill neighbours". The code applies no
elevation test at all. A neighbour qualifies if it is not itself in the crest set and has more than
`source_depth_m` of material on it. Measured on the same field, 132 of 240 transfers took from a cell
LOWER than the crest cell it fed, 79 from a higher one and 29 from one at the same elevation. What
the code does guarantee is that no donor is driven below original ground: the thickness test is
re-evaluated for each take, and a 2.0 m berm request at 0.5 m per donor left a minimum thickness over
the whole pad of exactly 0.0 m with no cell below the pad.

Third, `pos` is a position in the list the caller passed, and `Terrain.crest_cells` returns cells in
row-major index order rather than walking the crest line. On a pile whose crest is a closed ring,
consecutive entries jump between the two sides every time the raster wraps a row. Measured: of 247
consecutive pairs, 191 were 8-neighbours and 56 were not, so about a fifth of the pattern's steps
teleport across the pile. The gaps therefore land in a raster pattern rather than at even arc-length
intervals along the crest. If you need evenly spaced gates, order the crest list yourself before
calling.

## `build_ramp`: the road is cut into the fill, not reserved in it

This is the largest operation in the module and the one with the most history attached. The whole
mechanic is in one sentence: the ramp is a CUT IN THE FILL, not a void reserved in it. The trucks
fill the whole area, corridor included, and the dozer cuts the road back into what they filled, every
pass, so the material is always right where the blade needs it.

The alternative was tried first and cannot work. Reserving the corridor in plan and keeping every tip
off it means a corridor 25 m wide and 58 m long has to rise to the working level using as much
material as a sizeable fraction of the lift, all of it shoved in sideways by a blade, while the
trucks that could have supplied it are forbidden from driving there. The source records what that
measured: an entire 1296-cell area unreachable at a peak of 3.2 m, because the corridor stayed a
trench with 3 m walls on both sides. Before any access modelling existed at all, a 70 m area with an
18 m bench refused 69.8 percent of planned tips and stalled at 9.6 m. A version that only RAISED
cells below the target profile, without cutting the ones above it, left a single-cell step of 0.63
grade against a truck limit of 0.50 and refused 92.7 percent of tips, stalling at 4.07 m. Those
figures are recorded in the source and are not re-measured here.

### The target profile

```
    v        = ( ramp_far - access ) / || ramp_far - access ||     unit vector along the corridor
    along(c) = ( xy(c) - access ) . v                              projection, metres
    want(c)  = min( z0[c] + along(c) * max_grade * grade_frac , top )

    access   Area.access, the middle of the +y edge by default
    ramp_far Area.ramp_far, the access point reflected through the area centre
    z0[c]    ORIGINAL ground under cell c
    top      the 75th percentile of z over area cells that are NOT on the corridor
             and DO carry material
    cells with along(c) < 0 are skipped entirely
```

`grade_frac` defaults to 0.85, so with a truck limit of 0.5 the road is graded at 0.425 and keeps 15
percent in hand. `top` being the 75th percentile rather than the maximum is a measured trade recorded
in the source: the sixtieth percentile leaves the road at mid-height while the crest advances above
it, and the ninetieth cuts so much of the pile into the road that the peak falls, measured 13.3 m to
11.1 m. It is deliberately not the highest cell, because one fresh dump should not redefine the road.

### The three phases

The function runs cut, spoil, then fill, and the ordering is the point.

The CUT comes first. Corridor cells standing above the target profile are bladed down to
`max(want, z0[c])`, never below original ground, and what comes off is collected in a list of
`[cell, available]` entries. That material is offered to the corridor cells that are short, deepest
deficit first, so the worst part of the trench closes rather than every cell getting a smear. There
is deliberately NO early return when nothing is below the profile, and the comment explains why: that
is the common case and the case that matters, since a corridor buried level with the platform has
nothing below the target, only material above it. Bailing there meant the ramp was never cut and the
area stayed walled off, measured as 0 of 1296 cells reachable before and after.

The SPOIL phase shoves whatever the corridor still has to shed onto the nearest cell of the working
area outside the corridor. This is the one place in the module where `push_m` does not bind: the
`min(pool, key=_dist)` search has no distance limit, and the nearest non-corridor cell is taken
however far away it is. Measured on the 240-load reference build, `build_ramp` was the only operation
whose recorded displacement ever exceeded `DEFAULT_PUSH_M`, in three passes at 42.720 m, 40.311 m and
43.661 m. So "no material travels more than `push_m` in one pass" is NOT an invariant of this module,
and a test asserting it will fail on a real build.

The FILL phase re-measures the corridor against the profile it now has and makes up the remainder out
of the pile beside it, nearest donor first, breaking out once the nearest remaining donor is beyond
`push_m`. A donor never gives up more than half its height advantage over the cell it is feeding,
which stops the blade digging a new hole beside the road instead of grading it.

Every one of those movements is a recorded transfer. A scalar spoil bucket would balance the terrain
and silently desynchronise the provenance record the whole product rests on.

### Measured behaviour, and where it stops being true

On a flat pad with a 60 m area buried level at 3.0 m, `build_ramp(t, area, max_grade=0.5)` made 30
transfers moving 263.67 m3, with a mean displacement of 7.50 m and a worst case of 12.50 m, and
conserved volume exactly. The delivered profile matched the equation to three decimals: the first
corridor cell, at an along-distance of 1.25 m, came out at 0.531 m against a predicted
1.25 x 0.425 = 0.53125 m, and the profile reached the 3.0 m platform level and stayed there. 224 of
240 corridor cells were trafficable at 0.5, and the worst neighbour-to-neighbour gradient inside the
corridor was 0.425, exactly the design gradient.

On sloping ground it degrades, and the mechanism is visible in the equation. Because `want` is
anchored on each cell's OWN `z0`, the delivered surface is the original ground PLUS a 0.425 plane, so
the achieved gradient is the sum of the two. On a sidehill built by `topography.ground(FillType.
SIDEHILL, 60, 60, 2.5, relief_m=12.0)`, the original ground rises along the corridor at up to 0.0967
per metre. Buried at 3 m and ramped at `max_grade = 0.5`, the pass made 733 transfers moving 1420.5
m3 with a worst displacement of 47.43 m, conserved volume exactly, and left a worst neighbour
gradient inside the corridor of 0.556, above the 0.5 limit, with only 149 of 240 corridor cells
trafficable against 224 on flat ground.

The 15 percent headroom is what absorbs the ground's own slope, and it runs out when the ground rises
faster than `max_grade * (1 - grade_frac)`, which is 0.075 with the defaults. Here it rises at up to
0.0967, so the corridor is over the limit by construction; `tolerance_m` of 0.15 m across one 2.5 m
cell can add another 0.06 on top. If a sloping-ground campaign needs a guaranteed grade, the honest
fix is to anchor the profile on a single plane through the access point rather than on each cell's
own ground, and to lower `grade_frac`. Nothing in the current code checks the delivered gradient or
reports that it missed.

## The constants, and which of them are measured

Two module constants:

```
DEFAULT_PUSH_M   = 40.0    typical efficient push distance for a large track dozer
DEFAULT_BLADE_M3 = 30.0    blade capacity per pass, as a volume
```

Neither is a measured constant, and the source says so for the first: it is an operational figure
that bounds how far one pass can move material before an operator would rehandle instead, and it is a
parameter everywhere it is used. `DEFAULT_BLADE_M3` bounds how much a single cell can shed in one
pass, so that levelling is progressive rather than instantaneous; it has no citation behind it at
all. What would replace both is a machine specification: a named dozer class with a published blade
capacity and a push-distance-versus-production curve, in the way `TruckSpec` names the CAT 793F and
carries its measured bed width. That specification does not exist in this repo today.

Every other number in the four operations is a keyword argument with a default, and the build
overrides most of them. The values the reference build actually runs at are `depth_m = 0.2` and
`push_m = 15.0` for the crest push, `height_m = 0.4` and `source_depth_m = 0.1` for the berm with the
gap pattern left at 8 and 3, and `max_grade` taken from `Fleet.max_grade`, which for a 37 degree
repose is `tan(37 deg) / 1.5 = 0.5024`. That divisor of 1.5 is a rule of thumb and is documented as
such in `terrain.trafficable`; it is not a law and it is not fitted to anything here.

## Where the module sits in a build

`build._doze` is the only caller inside the package. It runs the ramp first, then the level, and if
`access_only` is false it also runs the crest push and the berm, relaxing the surface at the end
because a blade leaves material standing steeper than it can hold. The split between an access visit
and a full visit is itself a measured decision recorded in `build.py`: a berm is by construction a
wall, so running it on the fast cadence rings the area, while running access work on the slow cadence
refuses the ninety-nine loads between passes. Access often, furniture rarely. The cadences are
`DumpPlan.loads_per_dozer_pass`, default 12, and `DumpPlan.loads_per_full_pass`, default 60.

Measured end to end on a 240-load build (a 64 by 64 pad at 2.5 m, one 90 m square area with two 8 m
benches, `loads_per_dozer_pass = 40`, access at (90, 90), four CAT 793F trucks, shovel at (140, 140),
repose 37 degrees), the build placed all 240 loads with no refusals and reached a peak of 7.1475 m.
Wall time is worth only an order of magnitude: three runs on one machine took 9.6, 11.4 and 14.7 s.
It recorded 20 dozer passes carrying 12076 transfers and moving 27852.3 m3, against
29178.9 m3 of material placed. The blade moved 0.95 times the volume that the trucks delivered. The
volume-weighted mean displacement over all passes was 22.817 m.

By operation, over that build:

| Operation | Passes with transfers | Volume moved (m3) | Volume-weighted mean displacement (m) | Worst displacement (m) |
|---|---|---|---|---|
| `build_ramp` | 7 | 5697.9 | 14.068 | 43.661 |
| `level` | 7 | 17143.7 | 28.887 | 40.000 |
| `push_to_crest` | 3 | 3871.2 | 14.647 | 15.207 |
| `build_berm` | 3 | 1139.4 | 3.004 | 3.536 |

Levelling dominates both the volume and the displacement, which follows directly from the lowest-
first receiver rule and the 40 m default reach. If a future change makes provenance smear locally
instead, this table is where it will show.

## Where it fails

The area is an axis-aligned rectangle, because `Area` is. `_cells_of` tests every cell of the pad
against `area.contains`, so a real dump-location polygon cannot be expressed and a corridor cannot
bend.

`_cells_of` is O(cells in the pad) and the `level` reach scan is O(cells in the area squared) per
pass, with no spatial index. At 576 in-area cells a pass costs 0.037 s, which is fine; at ten times
the area it will not be.

`level` picks its sources once per pass from the elevations at the start of the pass, so a cell that
falls below target mid-pass is skipped by the `excess_m <= tolerance_m` guard rather than
re-evaluated, and a cell that rises above target mid-pass is not considered until the next call. The
build compensates by calling repeatedly on a cadence, and convergence is proved rather than assumed,
but a single call is not a fixed point.

The four operations are independent and order-dependent, and nothing enforces the order. Running the
berm before the level, or the level before the ramp, produces a different and generally worse
surface. `_doze` encodes the correct order; a caller reaching into `dozer.py` directly has to know it.

And the honest limit of the whole module: displacement is a distance, not a mixing model. Two
parcels that end up in the same cell after being pushed from opposite directions are recorded as one
stack of parcels each carrying its own travel distance, not as a blend with a mixing length. The
number the product reports is "how far this material has been shoved", which is a caveat on
provenance, and it should never be presented as a variance or a mixing coefficient.

## References

These are the sources `bedblend/dozer.py` itself cites, transcribed from its docstrings. No citation
has been added here that the code does not carry.

* Baffinland, Life-of-Mine Waste Rock Management Plan, 2017. The statement that material delivered to
  stockpiles is dumped and spread by dozer in shallow lifts, and that dozer operators determine how
  haul trucks access the dump and in what order.
* Neufeld, Lyall and Deutsch, CCG Report 8, paper 306, 2006, for Anglo American. The fixed cadence:
  "The material is dozed up the pile after two rows have been dumped." This is `DumpPlan.
  loads_per_dozer_pass`, expressed in loads rather than rows.
* Young and Rogers, Minerals 2021, 11, 636. Section 3.2 on paddock dumping being handled by dozers
  only around the perimeter; section 3.3 on dozers keeping the cascade clean, ensuring compaction and
  maintaining safety berms, and on the mixing being intractable; section 1.3 on displacement from the
  original dump location. The source does not carry a DOI for this article and none is invented here.
* Cogent Engineering 4(1), 1387955, doi:10.1080/23311916.2017.1387955. Cited in `bedblend/terrain.py`
  for dump construction by lifts with access to successive lifts established by ramps of suitable
  width and gradient. This is the design statement `build_ramp` implements.

## Reproducing the numbers in this document

Every measured figure above came from running the installed package. The reference paddock field is
the one `tests/test_dozer.py::_paddock_field` builds: `Terrain.flat(60, 60, 2.5)`, a single 60 m
square area from `rectangular_yard`, `row_spacing_m = 8.0`, one full pass of `plan.paddock_tips`
placed with `place_paddock` at the default `TruckSpec` load volume, then `relax_to(t, 37.0)`. The
240-load build is the one `tests/test_build.py::_build_once` runs with `n_loads=240, n_benches=2`.
The sloping-ground case is `topography.ground(FillType.SIDEHILL, 60, 60, 2.5, relief_m=12.0)` with
the area buried flat at 3 m above its own original ground before the ramp is cut. The full test suite
is 137 tests and passes at 0.07.002.
