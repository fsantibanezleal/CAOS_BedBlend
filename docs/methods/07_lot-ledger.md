# 07. The lot ledger

Source: `bedblend/blocks.py`. Public names: `Parcel`, `BlockModel`, `transfer_distances`, all three
re-exported from the package root. The rollup that consumes the ledger lives in
`bedblend/sectors.py`, and the reclaim side that turns per-parcel `source_block` into a delivered
provenance fraction lives in `bedblend/reclaim.py`. Everything below was read from those files or
measured by running them against version 0.07.002 in this repository.

## What the ledger is

A per-column stack of parcels. Each parcel is one placement's contribution to one column, recorded as
a vertical interval with the grade, the dig block it came from, the event that placed it, the lift
and area it belongs to, and two honesty fields: how uncertain its grade was to begin with, and how
far it has been shoved since it was tipped.

The support is the truckload, because that is the unit that was measured, hauled and placed. Two
independent published models fix the resolution at or below half a load. Neufeld, Lyall and Deutsch
build a reference model "at the resolution of 1/2 of a truck load (15 to 20 tonne blocks), that is, a
2.5m by 2.5m by 2.5 m cell size" (CCG Report 8, paper 306, 2006). Young and Rogers build a stockpile
block model at 5 m blocks interpolated on 15 m centres (Minerals 2021, 11, 636). The quantified case
for tracking at this support, transcribed from the module docstring: sampling every truck gives a
density equal to the truck's capacity, 100 to 400 t per sample, against 175,000 t per sample for a
conventional stockpile campaign. Three orders of magnitude.

Parcels are intervals of a column rather than voxels of a fixed 3-D lattice, so a lift is represented
exactly rather than being rounded onto a vertical grid. The published inference method is coarser on
purpose, because "since the accuracy of each elevation value was limited to the value of the bench
level, each bench was modeled as a two-dimensional plane". That is a limitation of inferring from
sparse survey data, not a property of the object, and a simulation that knows its own ground truth
should not copy it. `to_blocks` exports onto a regular lattice on demand, so the coarser view is
available without becoming the stored truth.

## What the ledger is not

It is not a geostatistical model. There is no kriging, no variogram, no interpolation and no
estimation of any kind in this file. Every number in it was put there by a placement or moved there
by a transfer. `sectors.py` does the aggregation and the confidence intervals; `blending.py` does the
variograms.

It is not a mixing model. Material that arrives in a cell from two directions is two parcels in one
stack, each carrying its own history, not one blended parcel with a mixing length. `column_grade` and
`column_coarse` compute thickness-weighted means when a reader asks for them, and that averaging is a
VIEW, not a change to the stored state.

It does not know the terrain's ground offset. `BlockModel.over(terrain)` copies `nx`, `ny` and
`cell_m` and allocates one empty list per cell, and that is the entire coupling. The name
`terrain.z0` appears nowhere in the file, and `over`, `record` and `assert_consistent` are the only
three members that take a terrain at all. The ground offset does enter the invariant, but indirectly,
through `Terrain.thickness`.

## `Parcel`, field by field

Ten fields, in declaration order. That order is load-bearing history and the next section explains
why.

| # | Field | Type | Default | What it holds |
|---|---|---|---|---|
| 1 | `z0_m` | `float` | required | Bottom of the interval this placement occupies in this column |
| 2 | `z1_m` | `float` | required | Top of the interval |
| 3 | `grade` | `float` | required | The grade of the load, as delivered by the stream |
| 4 | `source_block` | `int` | required | The dig block the load came from. This is the provenance key |
| 5 | `event_id` | `int` | required | The placement that created it. Caller-assigned; the build passes the load sequence number |
| 6 | `lift` | `int` | required | The bench index this material belongs to |
| 7 | `area` | `str` | required | The named working region it was routed to |
| 8 | `grade_uncertainty` | `float` | `0.0` | The ore-control uncertainty the load arrived with |
| 9 | `displacement_m` | `float` | `0.0` | How far this material has been shoved since it was tipped |
| 10 | `coarse_fraction` | `float` | `0.0` | Local coarse fraction of THIS parcel, set per cell by the face-segregation model |

One property, `thickness_m`, which is `max(0.0, z1_m - z0_m)`. Every weighting in the module uses it,
and the clamp at zero means a degenerate or inverted interval contributes nothing rather than
subtracting.

Field 8 exists because the grade on a load is already uncertain before the truck moves.
Misclassification of ore to waste or waste to ore from sampling error alone is commonly between 5 and
20 percent for base and precious metal mines, with a further 9 to 19 percent ore loss from blast
movement and dilution. Field 9 exists because the location degrades after placement, for the reason
`dozer.py` documents at length. Reporting provenance to twelve decimal places, as an earlier product
did, states a precision that belongs to the simulation and not to any real operation.

Field 10 is the one that carries the story. It is a per-cell value, not a per-load value, so a cell
near the toe of a dumped face records a coarser split than one near the crest of the same load.
Without it the ledger would report one size for a load the face has already sorted, and the whole
segregation half of the engine would have nowhere to land.

## `BlockModel`

Five fields: `nx`, `ny`, `cell_m`, `columns` (a list of parcel lists, one per cell, row-major with
`idx = j * nx + i`), and `bulk_density_t_m3`, default 1.9. That density is an anchored parameter, not
a measurement of anything in this repository. It is the loose bulk density of blasted hard rock, the
same figure `TruckSpec.loose_density_t_m3` carries, and the handbook band is 1.6 to 2.2. It converts
every thickness in the ledger into a tonnage, so it scales every tonnage the product reports; what
would replace it is a measured density for the specific material, which `material.py` is where to put
it.

Construct with `BlockModel.over(terrain, bulk_density_t_m3=1.9)`. `cell_area_m2` is `cell_m ** 2`,
6.25 m2 at the 2.5 m cell the tests use.

### The invariant

```
    T(c) = SUM over parcels p in column c of thickness_m(p)

    for every cell c:   | T(c) - ( z[c] - z0[c] ) |  <=  tol_m       default 1e-6 m
```

`assert_consistent(terrain, tol_m=1e-6)` scans every cell, keeps the worst disagreement, and raises
an `AssertionError` naming the cell and both numbers if it exceeds the tolerance. The message is
literal:

```
the ledger and the terrain disagree by 0.5 m at cell 0: ledger 1 m, terrain 1.5 m
```

A disagreement means material was placed without being recorded or recorded without being placed, and
every grade the product reports downstream is then attached to the wrong place. It is cheap and worth
running often: `build` takes a `verify_every` argument that runs it every N loads, off by default and
on in the tests, and it always runs once at the end of a build.

Know its limits. It compares THICKNESSES. It cannot see a wrong grade, a wrong provenance, a lost
coarse fraction, a displacement that was never accumulated, or a parcel filed at the wrong absolute
elevation. The next section is about the four hours of shipped output that fact cost.

## The cautionary tale: nine of ten fields

This is the clearest defect in the repository's history and the reason `dataclasses.replace` appears
where it does.

`BlockModel.take_from_top` splits a parcel when the requested thickness lands in the middle of one.
The departing upper slice used to be built by constructing a new `Parcel` positionally:

```python
# what it used to do
cut = p.z1_m - want
out.append(Parcel(cut, p.z1_m, p.grade, p.source_block, p.event_id, p.lift, p.area,
                  p.grade_uncertainty, p.displacement_m))
p.z1_m = cut
```

Nine arguments. `Parcel` has ten fields. The tenth is `coarse_fraction` and it defaults to zero, so
every slice that left a column was stamped with a coarse fraction of nothing. Reproduced here against
the current class, with a parent parcel carrying `coarse_fraction=0.42`:

```
positional rebuild of 9 of 10 fields -> coarse_fraction = 0.0
dataclasses.replace                  -> coarse_fraction = 0.42
every other field identical: True
```

Exactly one field wrong, and it was the last declared one.

### Why nothing caught it

Thickness is conserved exactly by the split, so `assert_consistent` passed. Grade, source block,
event id, lift, area, uncertainty and displacement were all inside the nine, so provenance and grade
both survived intact. The only field that died was the one no invariant covered, and it happens to be
the observable that every size-segregation result in the product is read from.

Stated as a conservation law, the defect is that the split conserved the first moment and destroyed
the second:

```
    a parcel p of thickness t, coarse fraction f, split at height `cut` into
        upper u, thickness t_u        (the slice that leaves)
        lower l, thickness t_l        (the slice that stays)

    FIRST moment  (thickness):   t_u + t_l = t                      always held
    SECOND moment (coarse):      t_u * f_u + t_l * f_l = t * f      held only if f_u = f_l = f
```

With `f_u = 0` the split lost `t_u * f` of coarse species mass on every departing slice, and the path
is hot. `apply_transfers` is the single route for every dozer pass and every relaxation transfer, and
reclaim goes through the same machinery, so material is split many times over a campaign.

### What it produced

The numbers, recorded in `CHANGELOG.md` for 0.06.001 and in the comment block above the regression
tests, measured on a consumer's shipped reference pile: a thickness-weighted coarse fraction of
0.2093 against the 0.35 that was placed, a 40.2 percent deficit, with 43 cells reading exactly zero,
which is impossible for material somebody put there. Downstream, a consumer's documentation had begun
explaining the resulting spread as physics. Those figures are transcribed, not re-measured here; the
shipped artifact they were taken from is not in this repository.

### The fix, and why it is the fix

```python
cut = p.z1_m - want
out.append(replace(p, z0_m=cut))
p.z1_m = cut
```

`dataclasses.replace` copies every DECLARED field and overrides only what is named. A field added to
`Parcel` in a later release is carried automatically, by nobody's memory. That is the actual fix: not
restoring one argument, but making the class of bug impossible. The same defect existed a second
time, in `reclaim._take`, in both the FIFO and the FULL_HEIGHT branches, and survived the first
repair because only `blocks.py` was looked at. Both now use `replace`, and the comment in
`reclaim._take` says why in one sentence so the next person does not have to find this document.

### Why the test iterates `fields(Parcel)`

`tests/test_blocks_sectors.py::test_a_split_slice_differs_from_its_parent_only_in_its_z_interval`
asserts the invariant this way:

```python
for f in fields(Parcel):
    if f.name in ("z0_m", "z1_m"):
        continue
    assert getattr(moved, f.name) == getattr(stayed, f.name)
```

Naming the fields one by one is precisely how the defect happened. A test that lists the nine fields
it knows about passes forever against code that copies the same nine. Iterating the declared fields
means the invariant is stated against the CLASS rather than against a remembered list, so field
eleven is covered the day it is added and nobody has to remember to cover it.

Two more regression tests sit beside it, and both exist because volume conservation alone was proven
insufficient. `test_species_mass_is_conserved_by_a_split` asserts the second moment across one split.
`test_species_mass_survives_many_transfers` runs 300 transfers around a four-cell ring through
`apply_transfers`, which is the path the dozer and the relaxation actually take, and asserts the
coarse species mass is unchanged. Measured now: 5.600000 before, 5.600000 after, drift 0.000e+00.

Know which of the two is the sensitive one, because it is not the one with 300 transfers in it.
Replaying the old positional rebuild against the split test loses exactly half, 0.7000 down to
0.3500. Replaying it against the ring loses 0.0028 of 5.6, five hundredths of one percent, because
the ring splits a parcel exactly ONCE: each transfer asks for 0.05 m3 over a 6.25 m2 cell, which is
0.008 m, and after the first cut the 0.008 m slice circulating around the ring is a whole parcel that
`take_from_top` pops rather than cuts. The ring test earns its place by exercising the real call
path, not by being the one that would have caught the defect.

The general lesson, which applies to any field added to `Parcel` from here on: if a quantity is
carried per parcel and is intensive (a fraction, a concentration, a rate), write the conservation law
for `thickness * quantity` and assert it, because the thickness invariant will not.

## `record`: getting material into the ledger

```python
BlockModel.record(terrain, cells, added_m, *, grade, source_block, event_id, lift, area,
                  grade_uncertainty=0.0, coarse_fraction=0.0) -> None
```

`cells` and `added_m` are zipped with `strict=True`, so a length mismatch raises rather than
truncating. `added_m` must be the thickness the dump operator ADDED, per cell, and the terrain must
ALREADY have been updated, because the parcel is filed at the top of the column:

```
    for each (c, dz) with dz > 0 :
        top = terrain.z[c]
        parcel interval = [ top - dz , top ]
```

Passing the pre-dump terrain files every parcel one load too low. Nothing detects that, because the
thicknesses are still right and `assert_consistent` only compares thicknesses.

Cells with `dz <= 0` produce no parcel at all. Verified: recording `added_m = [0.0, 0.5]` over two
cells leaves the first column empty.

`coarse_fraction` accepts either a scalar or a per-cell list, and the branch is a plain
`isinstance(coarse_fraction, list)`. This is how face segregation reaches the ledger:
`build._run_one_load` computes a coarse fraction per cell from `facesegregation.segregate_face` when
the load cascaded down a face, and passes `[split.coarse] * len(pl.cells)` when it did not, because a
load tipped on flat ground has no face to sort along. Verified: a list of `[0.6, 0.35, 0.2]` records
those three values on those three columns, and a scalar `0.35` records 0.35 on all of them. A tuple
would silently be treated as a scalar and fail later; the check is `isinstance(..., list)`, not
`isinstance(..., Sequence)`.

## `take_from_top`: removing material

```python
BlockModel.take_from_top(c, thickness_m) -> list[Parcel]
```

Removes `thickness_m` from the top of a column and returns what came off, splitting the last parcel
if the request lands in the middle of one. Whole parcels are popped while `t <= want + 1e-12`; the
final partial parcel is split with `replace`. The loop guard is `want > 1e-12`, so a request smaller
than a picometre is a no-op.

The returned list is REVERSED before it is handed back, so it comes out bottom-up, preserving the
original stacking order for whatever receives it. Demonstrated on a three-parcel column of unit
thickness, taking 1.5 m:

```
column 0 before:            [(0.0, 1.0, e0), (1.0, 2.0, e1), (2.0, 3.0, e2)]
taken, in returned order:   [(1.5, 2.0, e1), (2.0, 3.0, e2)]
column 0 after:             [(0.0, 1.0, e0), (1.0, 1.5, e1)]
```

Material comes off the top because that is what a blade and an avalanche both engage. Taking it from
the bottom would invert the stratigraphy the whole product exists to show. Reclaim needs the other
orders, and it implements them itself in `reclaim._take`: LIFO delegates straight to this method,
FIFO pops from index 0 and splits the bottom parcel with `replace(p, z1_m=cut_z)`, and FULL_HEIGHT
takes a proportional slice of every parcel in the column, which is what a vertical face through all
the lifts delivers and the only one of the three that actually blends them. FIFO and FULL_HEIGHT then
call `reclaim._restack` to close the gaps.

## `apply_transfers`: moving material, and moving its record with it

```python
BlockModel.apply_transfers(transfers, *, distances=None) -> None
```

The single route by which material moves between columns after placement. Both the dozer and the
relaxation go through it.

```
    for each k, (src, dst, V_k) in enumerate(transfers) :
        skip if V_k <= 0 or src == dst
        want   = V_k / cell_area_m2          a VOLUME becomes a THICKNESS here
        moved  = take_from_top(src, want)
        d_k    = distances[k] if distances is not None else 0.0
        for p in moved:  p.displacement_m += d_k
        _stack_onto(dst, moved)
```

Four things to know.

The transfer volumes are CUBIC METRES. `DozerPass.transfers` already carries volumes, so dozer passes
are handed over directly. `relax.relax_to` returns THICKNESSES, so `build._carry` multiplies by
`cell_area_m2` first. Getting that conversion wrong is silent and catastrophic, which is why
`_carry` exists and why every relaxation call in the package goes through it.

The `distances` list is indexed by `k` from `enumerate(transfers)`, so it must be parallel to the
FULL transfers list including any entries the loop skips. `transfer_distances(terrain, transfers)`
produces exactly that, one straight-line centre-to-centre distance per transfer, in the same order.
Passing a filtered list would misattribute every distance after the first skip.

Displacement is accumulated as PATH LENGTH, not net offset. Each move adds its own distance to
whatever the parcel already carried. Material shoved 20 m east and then 20 m west reports 40 m of
displacement while sitting where it started. Demonstrable on the four-cell ring of
`test_species_mass_survives_many_transfers`, though not BY that test, which passes no `distances` and
therefore reports a mean displacement of exactly zero. Re-run the same 300 transfers over a 4 by 1
pad at 2.5 m with `transfer_distances` supplied and the model reports a thickness-weighted mean
displacement of 0.562500 m for material that ends the run in the column it started in. This is the
intended reading: the number answers "how much handling has this material seen", which is the right
caveat on a provenance claim, and it is an upper bound on the distance from the dump record, never an
estimate of it.

Omitting `distances` is legal and defaults every distance to zero. That produces a ledger that is
perfectly consistent with the terrain and silently claims the material never moved. There is no
warning. Every call site in `bedblend/` passes distances; a new one must too.

`_stack_onto` is the private counterpart. It reassigns the interval of each arriving parcel from the
destination column's own top, in the order the list arrives, which is why `take_from_top` reverses.

## `transfer_distances`

```python
transfer_distances(terrain, transfers) -> list[float]
```

One `math.hypot` per transfer between cell centres, ignoring the volume entirely. It is a free
function rather than a method because it needs the terrain's geometry and the model does not hold a
terrain. It is the same computation `dozer._finalise` performs internally, done a second time; the
two are not shared, so if the definition of distance ever changes it must change in both places.

## Reading the ledger

| Method | Returns | Notes |
|---|---|---|
| `thickness(c)` | metres | Sum of parcel thicknesses in the column |
| `tonnes(c)` | tonnes | `thickness(c) * cell_area_m2 * bulk_density_t_m3` |
| `column_grade(c)` | grade or `None` | Thickness-weighted mean; `None` where there is no material |
| `column_coarse(c)` | fraction or `None` | Thickness-weighted mean; `None` where there is no material |
| `grade_field()` | list over all cells | `column_grade` for every cell, `None` included |
| `coarse_field()` | list over all cells | `column_coarse` for every cell, `None` included |
| `total_tonnes()` | tonnes | Sum over the pad |
| `mean_displacement_m()` | metres | Thickness-weighted over the whole model |
| `to_blocks(dz_m=5.0)` | `(i, j, k, grade, tonnes)` | A regular lattice VIEW, computed on demand |

```
    grade(c)  = ( SUM_p thickness_m(p) * p.grade ) / T(c)                  None if T(c) = 0
    coarse(c) = ( SUM_p thickness_m(p) * p.coarse_fraction ) / T(c)        None if T(c) = 0
    D         = ( SUM_all_p thickness_m(p) * p.displacement_m ) / SUM_all_p thickness_m(p)
```

Note the weight. All three weight by THICKNESS, while the docstrings on `column_grade` and
`mean_displacement_m` both say "tonnage-weighted". Nothing is broken by that: `cell_area_m2` and
`bulk_density_t_m3` are model-wide constants, so tonnage is thickness times a constant and the two
weightings agree to the last bit. It stops being a wording question the moment either is made
per-cell, and at that point it is the code that has to change, not the docstring.

The `None` matters. An empty column is not a column at grade zero, and colouring it as one made an
empty pad read as a full pile in a shipped release; `terrain.EMPTY_M` exists for the same reason.
Every consumer of `grade_field` and `coarse_field` has to handle `None`.

`column_coarse` is the field that makes segregation visible: a cut through the toe of a face should
read coarser than one through its crest, and if it does not, the sorting never reached the ledger.
That is the observable the split defect was destroying.

`to_blocks` bins parcels onto a vertical lattice by overlap:

```
    overlap(p, k) = min(p.z1_m, (k+1)*dz) - max(p.z0_m, k*dz)          kept only if > 0
    grade(i,j,k)  = ( SUM_p overlap * p.grade ) / SUM_p overlap
    tonnes(i,j,k) = ( SUM_p overlap ) * cell_area_m2 * bulk_density_t_m3
```

It is a view, so the coarse representation never becomes the stored truth, and it must neither invent
nor lose material. Measured on the 240-load reference build: 1756 blocks at `dz_m = 5.0` totalling
55440.0 t against a model total of 55440.0 t. Note that `to_blocks` carries grade and tonnage only.
Coarse fraction, displacement, provenance and uncertainty do not survive the export, which is a real
limitation if a downstream planning package is the consumer.

### A z-coordinate inconsistency worth knowing about

`record` files parcels at ABSOLUTE elevation, taken from `terrain.z[c]`. `base_z` returns the bottom
of an existing column, or `0.0` for an empty one, and `_stack_onto` uses it, so a column that is
emptied completely and then refilled restacks from zero rather than from the ground under it.
Demonstrated on a pad whose ground sits at 100 m:

```
recorded parcel interval on ground at 100 m:      (100.0, 104.0)
base_z of an empty column:                        0.0
after moving that whole column to a new cell:     (0.0, 4.0)
assert_consistent still passes:                   True
to_blocks(dz_m=5) k index for that parcel:        0
```

`assert_consistent` compares thicknesses, so it cannot see this. `to_blocks` bins on absolute z, so
it can: the same material reports `k = 20` when it was recorded in place on a 100 m pad and `k = 0`
after a transfer emptied and refilled its column. On a pad at elevation zero, which is what
`Terrain.flat` gives by default and what every test uses, the two conventions coincide and nothing
shows. The `base_z` docstring states the intent plainly ("Zero here; the terrain's own ground offset
is applied by the caller"), so the intended convention is thickness-space, and `record` is the
member that departs from it. If a non-zero-base pad ever reaches `to_blocks`, this is the first place
to look.

## The provenance rollup

Provenance in this engine is not a separate structure. It is the `source_block` field on every
parcel, and it becomes a reported quantity at exactly two places.

### From parcels to a delivered cut

`reclaim.cut` accumulates over the parcels a cut removed, weighting everything by tonnage:

```
    per_m       = cell_area_m2 * bulk_density_t_m3          tonnes per metre of column
    t_p         = thickness_m(p) * per_m                    tonnes in parcel p
    got         = SUM_p t_p

    grade       = ( SUM_p t_p * p.grade )             / got
    displacement= ( SUM_p t_p * p.displacement_m )    / got
    uncertainty = ( SUM_p t_p * p.grade_uncertainty ) / got
    coarse      = ( SUM_p t_p * p.coarse_fraction )   / got
    prov[b]     = SUM over p with p.source_block == b of t_p
    provenance  = { b : prov[b] / got }
```

Every intensive quantity is tonnage-weighted, which is the only correct weighting for something that
will be averaged against other cuts downstream, and the provenance fractions sum to one by
construction. `reclaim._merge` recombines several stances into one parcel of feed on the same basis:

```
    total          = SUM_j tonnes_j
    provenance[b]  = ( SUM_j share_j(b) * tonnes_j ) / total
    every other intensive field = ( SUM_j field_j * tonnes_j ) / total
```

`Cut.displacement_m` sitting next to `Cut.provenance` is the whole design. The provenance is exact
arithmetic over the ledger and the displacement is the caveat on it: the further the material moved,
the less its dump record means.

Measured on the 240-load reference build, reclaimed by twelve 800 t full-height cuts on the face
`tests/test_build.py` uses (position 0 m, direction (1, 0), 10 m deep, 200 m wide, 15 m maximum face
height, default `LoaderSpec`): the provenance fractions deviated from one by at most 4.44e-16, the
cuts drew on up to 12 distinct dig blocks each out of the 12 placed in the pile, the largest
single-block share in any cut was 0.4047, and the reported displacement ranged from 0.74 m to
32.42 m. Those two facts belong in the same sentence whenever the product presents them. A fraction
correct to sixteen digits, attached to material whose median parcel has been shoved eighteen metres,
is a precise statement about the simulation and a rough one about the pile.

The provenance dictionary is also a defect detector in its own right. `reclaim.LoaderSpec` exists
because a single 881 tonne cut once reported material from 108 distinct dig blocks, and fifteen
bucket passes cannot sample 108 dig blocks. The cut geometry was wrong and the provenance said so
before any geometric check did.

### From parcels to a sector

`sectors.rollup(model, terrain, area)` aggregates the raw ledger over a named area, weighting each
column's `column_grade` by that column's tonnage and returning a `Rollup` with the tonnage, the
weighted mean and standard deviation, the count of contributing columns, and confidence half-widths
at 90, 95 and 99 percent. Tonnage weighting is not optional there: a column holding one load and a
column holding forty must not count equally. `rollup_by_lift` restricts to one lift, which is what
exposes what a whole-sector average hides.

## Measured behaviour of the ledger under a real build

The 240-load reference build (a 64 by 64 pad at 2.5 m, one 90 m square area with two 8 m benches,
`loads_per_dozer_pass = 40`, four CAT 793F trucks, repose 37 degrees, 20 dozer passes, 12076 blade
transfers plus every relaxation transfer):

| Quantity | Measured |
|---|---|
| Occupied columns | 1740 |
| Parcels | 19782 |
| Mean parcels per occupied column | 11.37 |
| Deepest column | 383 parcels |
| Total tonnage | 55440.0 t, exactly 240 x 231 t |
| Tonnage-weighted mean displacement | 22.045 m |
| Coarse fraction over occupied columns | min 0.2438, mean 0.3499, max 0.8443 |
| Columns reading exactly zero coarse | 0 |
| `assert_consistent` | passes |

Contrast the last two rows with the shipped defect: 0.2093 thickness-weighted against 0.35 placed,
with 43 cells at exactly zero.

The stronger check is conservation end to end. Instrumenting `BlockModel.record` to accumulate the
coarse species mass HANDED to the ledger and comparing it against the mass the ledger HELD after the
whole build:

```
coarse species mass handed to the ledger : 1624.942858381 m
coarse species mass held by the ledger   : 1624.942858381 m
drift                                    : -6.821e-13 m
thickness handed 4668.631578947 m, held 4668.631578947 m, drift -9.095e-12 m
```

The ledger holds exactly what it was given, to floating-point noise, across 240 placements and
thousands of splits. The model-wide thickness-weighted coarse fraction is 0.348055, and the value as
handed in is also 0.348055, so the 0.5 percent gap from the material's declared 0.35 is entirely the
face-segregation model's per-cell split and not a ledger loss. That distinction is exactly what the
old code made impossible to draw.

Displacement is not uniform, and a single mean hides that. Thickness-weighted over the same build:
the median parcel has moved 18.20 m, the 90th percentile 51.61 m, the 99th 87.12 m, the worst
156.26 m, and 35.23 percent of the material has never been moved at all. Anyone presenting
`mean_displacement_m` as the honesty number should know that a third of the pile is untouched and the
tail runs to eight times the mean.

## Where it fails

Parcels are never merged. Two adjacent slices from the same event with identical fields stay two
parcels forever, so the count grows with the amount of handling rather than with the amount of
material. 240 loads produced 19782 parcels and one column reached 383. There is no compaction pass
and no cap. A long campaign on a small pad will make `column_grade`, `column_coarse`,
`assert_consistent` and `to_blocks` progressively slower, all of which are linear in the parcel
count.

`assert_consistent` is O(cells) and compares thicknesses only. It cannot detect a wrong grade, a lost
intensive field, a missing displacement, or the absolute-z inconsistency above. Every one of those
needs its own invariant, and the pattern for writing one is in `tests/test_blocks_sectors.py`.

There is no persistence, no serialisation and no schema version. A `BlockModel` is live Python
objects; anything that wants to store one has to define its own format, and a stored format will
silently lose any field added to `Parcel` later unless it too iterates `fields(Parcel)`.

`base_z` returning zero for an empty column, combined with `record` filing absolute elevations, means
the model is only unambiguous on a pad whose ground is at zero.

And the honest limit: this ledger is the simulation's own ground truth. It is exact by construction
because the simulation put every gram of it there. A real operation has none of this, which is the
point of the comparison in `sectors.compare`, and no number out of `blocks.py` should ever be
presented as something a real stockpile could report about itself.

## References

These are the sources `bedblend/blocks.py` cites, transcribed from its docstrings. Nothing has been
added that the code does not carry.

* Neufeld, Lyall and Deutsch, CCG Report 8, paper 306, 2006. The reference model built "at the
  resolution of 1/2 of a truck load (15 to 20 tonne blocks), that is, a 2.5m by 2.5m by 2.5 m cell
  size". This is the support argument for parcels at truckload resolution.
* Young and Rogers, Minerals 2021, 11, 636. The stockpile block model at 5 m blocks interpolated on
  15 m centres; the statement that each bench was modelled as a two-dimensional plane because
  elevation accuracy was limited to the bench level; and the displacement statement that motivates
  `displacement_m`. The source does not carry a DOI for this article and none is invented here.
* The misclassification figures behind `grade_uncertainty`, commonly between 5 and 20 percent for
  base and precious metal mines with a further 9 to 19 percent ore loss from blast movement and
  dilution, are stated in the `blocks.py` module docstring without an attached citation. Treat them
  as UNVERIFIED against a primary source until one is added to the docstring.

## Reproducing the numbers in this document

The split, species-mass and 300-transfer results are the three regression tests at the bottom of
`tests/test_blocks_sectors.py`. The 240-load build is `tests/test_build.py::_build_once` with
`n_loads=240, n_benches=2`. The conservation figures came from monkeypatching `BlockModel.record` to
accumulate `sum(dz * coarse_fraction)` over its arguments and comparing against
`sum(p.thickness_m * p.coarse_fraction)` over the finished model. The reclaim figures came from
`reclaim.campaign` against that build with `cut_tonnes=800.0`, `n_cuts=12`, `repose_deg=37.0` and the
face `tests/test_build.py::test_reclaim_blends_the_input_stream` constructs, which is
`ReclaimFace(method=ReclaimMethod.FULL_HEIGHT, position_m=0.0, direction=(1.0, 0.0), depth_m=10.0,
width_m=200.0, max_face_m=15.0)` with the default `LoaderSpec`. The face geometry has to be stated:
the same twelve cuts against the `ReclaimFace` defaults report a different largest single-block
share, 0.2138 rather than 0.4047. The full suite is 137 tests and passes at 0.07.002.
