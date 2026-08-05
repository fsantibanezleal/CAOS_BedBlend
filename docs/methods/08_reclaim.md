# 08. Reclaim

Source: `bedblend/reclaim.py`. Tests: `tests/test_reclaim.py`.

Public names, all re-exported from the package root: `ReclaimMethod`, `ReclaimFace`, `LoaderSpec`,
`Cut`, `HaulCycle`, `cut`, `next_cut`, `campaign`, `advance`, `haul_cycle`. Two things a reader will
look for are deliberately not exported: `bedblend.reclaim.MAX_STANCES_TRIED` (the loop backstop, value
4096) lives on the module only, and the per-column extraction routine `_take` is private because the
method enum is the supported way to choose an order.

This module answers one question: given a pile that has already been built, what comes out of it, in
what order, dug by a machine with a real reach, and carried away by a truck that has to be able to get
there. Everything in it either removes material from the ledger or records how that removal was
physically possible.

---

## 1. Reclaim is the inverse of the build, which is itself the inverse of a pit

The engine's governing analogy is stated in `bedblend/terrain.py` and inherited here: a truck-built
stockpile is an open pit run backwards. A pit cuts benches downward, a stockpile adds lifts upward,
and both use the same primitives (a working level, a face standing at the angle of repose, a berm, and
a ramp of a given width and gradient that gives equipment access to the next level). Reclaim inverts
the inversion. It cuts the lifts back down again, and it does so with the same constraints that
governed placing them.

The published framing is exactly this, and it is quoted in the module docstring. Modelling the
stockpile "makes stockpile processing similar to mining of a large muck pile and subject to the same
methods of ore control and mine planning previously established", and engineering software can then
"create an optimized sequence for processing the stockpile which reduces the variability of the feed
entering the mill" (Young and Rogers, *Minerals* 2021, 11, 636, section 4.1,
[doi:10.3390/min11060636](https://doi.org/10.3390/min11060636)).

Two consequences follow, and both are load-bearing in the code.

The order of extraction is a **plan**, not a free choice. A loader needs a level to stand on and keeps
a safe face height, and removing material advances the face and lowers the level. `advance` moves the
face one `depth_m` deeper in a fixed direction rather than jumping to wherever the best grade sits,
because a sequencing decision that is allowed to teleport is not a sequencing decision.

Reclaim must **relax**. Removing material undercuts whatever stood above it. `cut` calls
`relax_to(terrain, repose_deg, active=set(touched))` itself and applies the resulting transfers to the
block ledger, rather than leaving that to the caller, because the previous engine ran the cascade only
on deposition and a reclaimed face could therefore stand vertically forever.

---

## 2. The objects, and the call surface

`ReclaimFace` is the plan: where the face is, which way it advances, how deep one cut reaches, how wide
the face is, and how high a face the operation will stand. `LoaderSpec` is the machine that works it.
`Cut` is one parcel of feed delivered to the plant, with everything known about what it was made of.
`HaulCycle` is the truck that came for it.

The three entry points nest:

```
campaign(...)          n_cuts parcels of feed, optionally each with its haul cycle
  next_cut(...)        ONE parcel of the tonnage asked for, assembled across stances
    cut(...)           what one stance yields, plus the relaxation it triggers
      face.bite(...)   the cells that stance digs, and how deep into each
```

`cut` is usable on its own and the tests use it that way, but a caller that wants a parcel of a stated
size wants `next_cut`, because a stance yields only what stands within reach of it. On the reference
fixture that reach bound is 2280.7 t, so a 1500 t order does come out of one stance and `next_cut`
returns exactly what `cut` returns, 1500.0 t over 26 cells; ask for 2500 t and `cut` stops at 2280.7 t
over 46 cells while `next_cut` trams and delivers 2500.0 t over 49. See section 6.

---

## 3. The geometry of the face

`ReclaimFace` carries a `direction` unit vector. Everything else is expressed in the basis that vector
induces:

```
(dx, dy) = direction / |direction|            along-face advance axis, call the coordinate s
(px, py) = (-dy, dx)                          across-face axis,        call the coordinate t

for a cell c at pad coordinates (x, y):
    s_c = x*dx + y*dy
    t_c = x*px + y*py
```

`_basis` returns `None` for a degenerate direction (magnitude below 1e-12), and every method that
depends on it degrades quietly: `engaged_cells` returns an empty list, `stance` returns the origin.

### The envelope, which is not the footprint

```
engaged_cells(terrain) = { c :  terrain.has_material(c)
                              and position_m <= s_c < position_m + depth_m
                              and |t_c - t_centre| <= width_m / 2 }
```

`t_centre` is `centre_t_m` when the caller supplied one, otherwise the across-face coordinate of the
pad centre. The default is only correct for a pad-centred pile, which is why the field exists: a yard
tiles several areas, and the caller that knows which area this face belongs to passes that area's
centre.

The envelope is **the ground the face covers**, that is, the stretch the machine may work its way
along. It is emphatically not the footprint of one cut. Confusing the two is the defect this module
documents at length in `LoaderSpec`, and it is why the docstring on `engaged_cells` points at `bite`.

### Where the machine stands

`stance` derives the position from where the material actually is, not from the nominal width window,
because the window is a bound and not a description. A caller that wants no across-face limit passes a
width wider than the pad, and deriving a position from that would put the machine off the edge of the
world.

`_occupied` returns `(s_near, t_lo, t_hi)` over the envelope. Then:

```
R    = loader.dig_radius_m
span = t_hi - t_lo

if span <= 2R:   t = (t_lo + t_hi) / 2                        short pile: stand in the middle
else:            t = t_lo + min(offset_m + R, span - R)       stand one radius in from the edge

stance = (s_near*dx + t*px,  s_near*dy + t*py)
```

The machine stands at the near edge of the material along the advance direction, which is where a face
is, and one dig radius in from the near edge of the stretch it is working, because the stretch it can
reach is a radius either side of it.

When there is nothing in front of the face `stance` still returns a point (the face position and the
window centre) rather than `None`, so callers do not have to special-case it. `bite` then correctly
returns nothing from it.

### Stepping along, and advancing

```
step():
    offset_m <- offset_m + 2R                                 tram by the stretch just worked
    if occupied and offset_m + R < span:  return True         still material across the face
    offset_m <- 0
    return advance(face, terrain)

advance(face, terrain):
    position_m <- position_m + depth_m
    return position_m <= max{ s_c : terrain.has_material(c) }
```

Both return the same thing: whether there is anything left ahead. Measured on the reference fixture of
section 12, where the material standing in front of the face runs 67.5 m across (`_occupied` returns
`t_lo = 28.75` and `t_hi = 96.25`, wider than the 60 m area because the loads cascaded and relaxed
past its edges) and `R` is 15 m, the machine takes exactly two stances (pad coordinates
`(31.25, 43.75)` then `(31.25, 73.75)`, 30.00 m apart, which is `2R`) before the sweep is exhausted,
`offset_m` resets to zero and the face advances 10 m to `position_m = 40.0`, putting the machine at
`(41.25, 43.75)`.

`_along`, which `advance` calls, scans **every** cell carrying material, not only the cells inside this
face's width window. A face working one area of a wide yard therefore keeps returning `True` while
material stands anywhere further along the advance direction, including material it will never reach.
That is a known looseness, not a modelled behaviour; the bound that actually stops the search is
`next_cut` finding nothing.

### Rewind

`rewind` puts the face back at `origin_m` (captured in `__post_init__`) with `offset_m = 0`. It exists
for concurrent campaigns, where reclaim runs on a pile that is still being built, so a face that has
worked past the end of the material is not finished, it is merely ahead of the trucks. The docstring
carries the measurement that motivated it: left parked out there, "the concurrent scenario fell from 28
cuts to 2 and the surge scenario from 74 to 2, both of them still delivering a plausible-looking feed
series from the handful that got through".

Verified on the reference fixture: driving `advance` until it refuses walks the face from 30.0 m to
100.0 m in seven steps of 10 m, a `cut` from out there returns 0.0 t, and the very next `next_cut`
returns a full 1500.0 t with the face back at `position_m = 30.0` and `offset_m = 0.0`.

---

## 4. The machine, and the bite

```
@dataclass(frozen=True)
class LoaderSpec:
    name: str = "hydraulic front shovel, 60 t payload class"
    bucket_m3: float = 34.0
    payload_t: float = 60.0
    dig_radius_m: float = 15.0
    max_cut_height_m: float = 15.0
```

Two of those five numbers bound a cut and the other three are reporting.

`dig_radius_m` is how far the machine works from one stance before it has to tram along the face. No
cell outside that radius is a candidate, whatever the tonnage asked for.

`max_cut_height_m` is how high a face it can safely cut in one pass. Together with the face's own
`max_face_m` it is what stops a cut taking a column top to bottom:

```
lift = min(face.max_face_m, face.loader.max_cut_height_m)          [m]
```

With both defaults at 15.0, `lift` is 15.0 m, which is taller than most piles this engine builds, and
that has a consequence for the extraction orders that section 5 spends its length on.

`passes_for(load_t, bulk_density_t_m3)` returns bucket passes and needs the density because a bucket
is a **volume**:

```
per_bucket_t = bucket_m3 * rho_b
passes       = load_t / per_bucket_t
```

At the default bucket and `rho_b = 1.9 t/m3` a bucket holds 64.6 t, so `passes_for(60.0, 1.9)` is
0.929 and `passes_for(231.0, 1.9)`, a CAT 793F load, is 3.58. The docstring records that an earlier
version divided the machine's own payload by its own bucket volume and returned 1.76, which is tonnes
per cubic metre, a density, not a count of anything. A number near two is also a plausible pass count,
which is how the unit error survived.

### `bite`: the cells this cut actually digs

```
bite(terrain, model, tonnes_wanted) -> list[(cell_index, depth_m)]
```

The selection, transcribed from the code:

```
per_m = model.cell_area_m2 * model.bulk_density_t_m3      tonnes per vertical metre of one cell
lift  = min(max_face_m, max_cut_height_m)
R2    = dig_radius_m ** 2
S     = stance(terrain, envelope)

candidates C = { c in envelope :  (x_c - S_x)^2 + (y_c - S_y)^2 <= R2
                                and depth_c = min(model.thickness(c), lift) > 1e-9 }

sort C by the key  (-depth_c, d2_c, c)                    deepest first, nearest to break the tie,
                                                          index last so a run is reproducible

greedy fill, in that order:
    t_c = depth_c * per_m
    if got + t_c > tonnes_wanted:                         the last cell is partial
        depth_c = (tonnes_wanted - got) / per_m
        t_c     = tonnes_wanted - got
    emit (c, depth_c); got += t_c
    stop when got >= tonnes_wanted - 1e-9
```

Two hard bounds follow from that, and both are the machine rather than the plan. Nothing outside the
dig radius can be dug, and no cell gives up more than one lift. If the reachable ground cannot supply
the tonnage the cut simply comes out smaller, which is the honest answer: the machine has to tram.

### Why deepest first, and not nearest first

A machine works the **standing face**. It does not skim the thin apron in front of it because that
apron happens to be closer. Ordering purely by distance made a cut on a pile with a shallow near edge
spread outward instead of digging in, and the docstring carries the measurement: on the concurrent
scenario "a 3000 tonne cut took 1035 square metres at a mean depth of 1.45 m, which is a skim over a
third of an acre rather than a shovel working a face".

The depth is capped at one lift **before** sorting, so every cell with a full lift standing on it ties
on the first key and the distance decides between them. That is the face, worked nearest first.

Reproduced here on the reference fixture by re-running the same selection with the distance key alone,
`(d2_c, c)`, same terrain state, same stance, same tonnage. The tie-break is worth stating because it
moves the answer: sorting by `(d2_c, -depth_c, c)` instead gives 12 cells at 600 t rather than 13.

| tonnage asked | deepest first | nearest first |
|---|---|---|
| 300 t | 5 cells, 31.2 m2, mean depth 5.05 m | 7 cells, 43.8 m2, mean depth 3.61 m |
| 600 t | 9 cells, 56.2 m2, mean depth 5.61 m | 13 cells, 81.2 m2, mean depth 3.89 m |
| 900 t | 14 cells, 87.5 m2, mean depth 5.41 m | 18 cells, 112.5 m2, mean depth 4.21 m |

Same tonnage, roughly two thirds of the hole.

### The footprint scales with the tonnage

That is the whole point of the rewrite, and it is directly measurable. On the reference fixture, with
one call to `cut` (one stance):

| asked | delivered | cells | footprint | furthest cell from the stance | dig blocks in the provenance |
|---|---|---|---|---|---|
| 300 t | 300.0 t | 5 | 31.2 m2 | 14.58 m | 3 |
| 900 t | 900.0 t | 14 | 87.5 m2 | 14.58 m | 4 |
| 3000 t | 2280.7 t | 46 | 287.5 m2 | 15.00 m | 4 |
| 10 000 000 t | 2280.7 t | 46 | 287.5 m2 | 15.00 m | 4 |

The last two rows are the reach bound doing its job: 2280.7 t is everything standing within 15.00 m of
that stance, and asking for four thousand times more changes nothing. The envelope on that face is 112
cells, 700 m2, so even the supply-limited cut engages 41 percent of the ground the face covers, and the
900 t cut engages 12.5 percent of it.

---

## 5. The three orders of extraction

```python
class ReclaimMethod(str, Enum):
    LIFO = "lifo"                  # work back from the last-placed face, newest out first
    FIFO = "fifo"                  # work from the oldest end, first placed out first
    FULL_HEIGHT = "full_height"    # cut vertically through every lift at once
```

These are **orders of extraction**, not machine geometries invented for the product. The pre-crusher
stockpile taxonomy classifies truck-built piles by exactly this distinction, last in first out or first
in first out (Young and Rogers 2021, figure 1, types 3 and 4). The full-height method is what a
bench-height face does and what the paper means by "processing the stockpile in parallel vertical
approaches".

The order is applied per column by `_take(model, c, thickness_m, method)`, after `bite` has already
decided which columns and how deep into each. Parcels are stored bottom-up in `model.columns[c]`, and
within a lift they are appended in time order, so the bottom of the column is the oldest material in it.

```
LIFO           model.take_from_top(c, want)
               removes from the end of the parcel list, splitting the last one with `replace`

FIFO           pops from index 0 until `want` is satisfied; the partial parcel is split as
                   out.append(replace(p, z1_m = p.z0_m + want));  p.z0_m = p.z0_m + want
               then `_restack` closes the gap so the column stays contiguous from its base up

FULL_HEIGHT    f = min(1, want / H_c)          where H_c = model.thickness(c)
               every parcel gives up f of its thickness:
                   out.append(replace(p, z0_m=p.z0_m, z1_m=p.z0_m + f*h_p));  p.z1_m -= f*h_p
               then `_restack`
```

Both splits use `dataclasses.replace`, never a positional rebuild. That is not a style preference. A
positional rebuild that names nine of `Parcel`'s ten fields silently zeroes the tenth, and this exact
bug shipped once from `bedblend/blocks.py`: `coarse_fraction` was the field with no invariant covering
it, and a reference pile came out at a thickness-weighted coarse fraction of 0.2093 against the 0.35
that was placed, with 43 cells at exactly zero. `replace` copies every declared field and overrides
only what is named, so a field added later is carried without anyone having to remember it.

### What each order delivers, on a column you can check by hand

One column, three parcels of 2.00 m each, bottom to top at grades 0.10, 0.50 and 0.90, so the column
mean is 0.50. Taking 3.00 m:

| method | takes | grade out | leaves | grade left |
|---|---|---|---|---|
| `LIFO` | the 0.90 parcel and half of 0.50 | 0.7667 | 3.00 m | 0.2333 |
| `FIFO` | the 0.10 parcel and half of 0.50 | 0.2333 | 3.00 m | 0.7667 |
| `FULL_HEIGHT` | 1.00 m of each of the three | 0.5000 | 3.00 m | 0.5000 |

The full-height row is not a coincidence, it is an identity. A proportional slice returns the column
mean grade exactly:

```
g_full = sum_p (f * h_p * g_p) / sum_p (f * h_p)
       = sum_p (h_p * g_p) / sum_p h_p          because f is the same for every parcel
       = the tonnage-weighted mean grade of the whole column
```

That identity is why full height is the only one of the three that actually blends the lifts: every
cut from a column returns that column's mean, so within-column variance never reaches the plant. LIFO
and FIFO pass the stratigraphy straight through.

Measured over a campaign rather than a column, with the face height held short at `max_face_m = 2.0` so
the orders can differ at all, 20 cuts of 1500 t on the reference fixture gave a feed-grade variance of
3.092e-03 for `FULL_HEIGHT`, 3.103e-03 for `LIFO` and 3.300e-03 for `FIFO`. The ordering is the one the
theory predicts, and the margin over `LIFO` is 0.33 percent of the `LIFO` variance, which is small
enough that a maintainer should not quote it as a headline result without saying what pile it came
from.

### The degeneracy: when a cut takes a whole column, the three agree

If the bite takes a column **whole**, all three orders return the same set of parcels, so the tonnage
and the grade are identical. That is arithmetic, not a limitation of the model:

```
LIFO        pops from the top until `want` is met; want >= H_c empties the column
FIFO        pops from the bottom until `want` is met; want >= H_c empties the column
FULL_HEIGHT f = min(1, want / H_c) = 1, so every parcel gives up all of itself

three different traversals of the same multiset of parcels; the tonnage-weighted
mean of a multiset does not depend on the order you visit it in
```

Checked directly on the hand column above: asking for 6.00 m (the whole column) returns 6.00 m at grade
0.5000 for all three methods and leaves zero parcels behind; asking for 9.00 m returns the same 6.00 m,
because there is no more.

Checked on the fixture pile, one 3000 t cut, all three methods:

| `max_face_m` | LIFO | FIFO | FULL_HEIGHT |
|---|---|---|---|
| 50.0 (whole columns come out) | 2280.725182 t at 0.43905206 | 2280.725182 t at 0.43905206 | 2280.725182 t at 0.43905206 |
| 3.0 (columns are cut part way) | 1586.840355 t at 0.43917633 | 1586.840355 t at 0.42753729 | 1586.840355 t at 0.43301132 |

The tonnage is identical on both rows because `bite` fixes the depths before `_take` ever runs. Only
the grade can differ, and it can only differ while there is column left above or below the cut.

This matters more than it looks, because the pile the reference fixture builds is about 6.6 m at its
thickest and the default `lift` is 15.0 m. **On a shallow pile with default machine settings, the
extraction order is a no-op.** A caller who wants the order to mean anything has to set `max_face_m`
(or `LoaderSpec.max_cut_height_m`) below the column height, and `tests/test_reclaim.py` does exactly
that in `test_lifo_and_fifo_deliver_different_grades`, then asserts the degeneracy itself in
`test_a_full_column_cut_makes_the_order_within_it_irrelevant`. The previous engine's proportional skim
never took a full column, so the degeneracy could not arise, and its absence was mistaken for the
extraction order always mattering.

One nuance for anyone reading a campaign rather than a single cut. The **last** cell of a bite is
partial by construction (it takes only the remainder), so even a campaign that otherwise takes whole
columns keeps one partial column per cut, and the orders diverge slightly there. Measured with the full
lift allowed, 20 cuts of 1500 t, feed variance came out 1.2300e-02 for `FULL_HEIGHT` against 1.2295e-02
for `LIFO`: agreement to three significant figures, and the two feed series were not element-wise
identical.

---

## 6. A cut is a quantity of feed, not one bucket from one spot

The reach of the machine bounds what it can take from **one stance**. It must not also bound the parcel
the plant asked for. `next_cut` is where that distinction lives:

```
sweep = max(2, ceil(width_m / (2R)))          how many stances make one sweep of the face
owed  = tonnes_wanted
loop, at most MAX_STANCES_TRIED = 4096 times:
    take a `cut` of `owed` from the current stance; append it, decrement `owed`
    if the machine has already loaded somewhere (parts is non-empty):
        stop if it has already trammed `sweep` times
        otherwise count this tram
    step the face; if the step runs off the end of the material, `rewind` once and keep going
return `_merge(parts)`, or None if nothing was taken anywhere
```

Getting this wrong is visible immediately in the tonnage. The docstring records that the first version
returned the first non-empty stance and "cut the delivered feed to a quarter of what the campaign asked
for, leaving most of the pile standing".

Two details in that loop are deliberate and easy to break.

Tramming is only counted **once the machine is loading**. Getting to the first productive stance is
searching, not tramming, and a face whose near ground is worked out must still be allowed to find the
material. The rewind fires at most once per call; a second run-off with nothing found means there
really is nothing.

The tram bound is what makes a **short cut** possible, and a short cut is a real operational answer. A
loader filling one parcel works a stretch of face, not the whole yard. If that stretch cannot supply
the tonnage then the parcel is short, and the engine says so by delivering less. Unbounded assembly
instead sweeps ground until the order is filled, and the docstring records what that produced: the
surge scenario "came out at 3303 square metres per cut removing 0.31 m, a skim across most of the pad",
dressed up as a full parcel.

Verified both ways. On a deliberately thin pile (0.4 m over an entire 48 by 48 pad at 2.5 m cells,
2304 cells and 10 944.0 t in total), asking `next_cut` for 100 000 t returns 1073.5 t over 226 cells,
1412.5 m2, against the `(sweep + 1)` working discs of 3534 m2 that the test allows, with `sweep = 4`
for that face's 120 m width. On the reference fixture, which can supply the order, nothing is cut
short:

| asked | delivered | cells | footprint | dig blocks |
|---|---|---|---|---|
| 1500 t | 1500.0 t | 26 | 162.5 m2 | 4 |
| 3000 t | 3000.0 t | 57 | 356.2 m2 | 7 |
| 6000 t | 6000.0 t | 114 | 712.5 m2 | 8 |

### Merging the stances into one parcel

`_merge` combines the loads from several stances into the one parcel of feed they make up. Everything
intensive is tonnage-weighted, which is the only correct weighting for a quantity that will later be
averaged against other cuts:

```
T          = sum_k T_k
grade      = sum_k (g_k * T_k) / T                     and likewise displacement_m,
                                                       grade_uncertainty, coarse_fraction
prov[b]    = sum_k (prov_k[b] * T_k) / T               so the fractions still sum to 1
cells      = the union, in first-seen order
```

The haulage fields are left unset by `_merge` on purpose: the caller routes the truck once, for the
assembled cut, over the surface all of it left behind.

### What a `Cut` carries

`tonnes`, `grade`, `provenance` (dig block index to tonnage fraction, summing to one),
`displacement_m`, `grade_uncertainty`, `cells`, `coarse_fraction`, and then the haulage:
`stand`, `loader`, `approach`, `departure`, `approach_cells`, `departure_cells`.

`coarse_fraction` is the field that makes the segregation half of the engine mean anything
operationally. Coarse runs to the toe of a dumped face, so a campaign that cuts the toe delivers coarse
feed and one that cuts the crest delivers fines. Before this field existed the engine modelled the
sorting in detail and then discarded the answer at the moment it became a plant-facing number.

`displacement_m` is the tonnage-weighted mean distance the material had been shoved before it was
reclaimed, and it is the honest caveat on the provenance: the further it moved, the less its dump
record means. It is not zero even on a pile that was never dozed, because relaxation moves material
too. Measured on the reference fixture, which is built by paddock dumping and relaxation alone, the
whole ledger sits at a mean displacement of 1.215 m and a 1500 t cut came out at 0.617 m.

`grade_uncertainty` on a cut is the tonnage-weighted mean of its parcels' uncertainties. That is a
conservative pass-through and it is **not** the uncertainty of an average of independent errors, which
would fall roughly as one over the square root of the number of independent sources. The code makes no
independence claim anywhere, and replacing the weighted mean with a variance combination would require
one, plus a model of how correlated two loads from the same dig block are.

---

## 7. Relaxation, and the apron that is larger than the bite

`cut` finishes by relaxing the cells it touched and carrying the ledger along with the movement:

```python
moves = relax_to(terrain, repose_deg, active=set(touched))
if moves:
    model.apply_transfers(
        [(a, b, v * model.cell_area_m2) for a, b, v in moves],
        distances=transfer_distances(terrain, moves),
    )
```

Doing it here rather than leaving it to the caller is deliberate, because forgetting exactly this is
what the previous engine did. Relaxation **moves material**, and a ledger that is not told about the
movement drifts away from the terrain, after which every grade reported is attached to the wrong place.

The seeding on `touched` is documented in the code as a matter of the work following the machine rather
than a fix for a visible defect, and it was measured before anything was claimed for it: "768 against
767 square metres of surface moved per cut on the reference scenario", because a pile that was stable
before the cut has nothing to relax anywhere except around the cut. `relax_to` sweeps the whole pad
regardless if anything is left standing over the angle, so correctness does not depend on the seed.

The surface that moves is legitimately **larger** than the bite, and a reader checking a rendered
footprint against the machine's reach needs to know that. Undercutting 4.5 m into ground standing at 37
degrees pulls material in from about 6 m around, so the code's comment records a 336 m2 bite showing up
as roughly 770 m2 of surface change. Measured here on the reference fixture with a 3000 t cut, the bite
was 46 cells (287.5 m2) and the surface changed on 69 cells (431.2 m2). That apron is the slump. It is
the physics, and it is not the machine reaching further than it can.

---

## 8. The haul cycle

A reclaim campaign used to remove material from a face and report a tonnage. Nothing came for it,
nothing carried it, and on screen the pile simply lost volume with no machine in sight. `haul_cycle` is
the mirror of the build side, and it deliberately uses the same primitives from `bedblend/truck.py`
(`passable_mask`, `reachable_mask`, `solve_route`, `NoRoute`) so that "a truck can get there" means the
same thing in both directions and a reclaim truck cannot drive somewhere a haul truck could not.

```
haul_cycle(terrain, cells, *, exit_xy, max_grade) -> HaulCycle
HaulCycle(stand, loader, approach: Route | None, departure: Route | None)
HaulCycle.apply_to(cut)     writes stand, loader, both polylines and both grid paths onto the Cut
```

`HaulCycle` is a record rather than a tuple because it carries four things, two of which are routes
that each come with a grid path behind their polyline, and positional unpacking at two call sites is
how a caller silently assigns the departure to the approach.

### The truck does not stand on the face

A loader digs the face; the truck stands beside it on ground it can climb and is loaded over the side.
So the stand is chosen as the nearest cell to the **loader** (the centroid of the dug cells) that is
simultaneously passable, reachable from `exit_xy`, and **not one of the cells the loader is digging**:

```
loader   = centroid of `cells`
passable = passable_mask(terrain, max_grade)                 local gradient by central differences
reach    = reachable_mask(terrain, exit_xy, max_grade, passable=passable)     flood fill
stand    = argmin over c of  dist(c, loader)^2
                subject to  c not in set(cells)  and  passable[c]  and  reach[c]
```

The exclusion of dug cells is not defensive programming. Two machines cannot occupy one cell, and this
module exists partly because the previous engine let them: the stacker and the reclaimer were measured
inside the same cell in 5 of 51 cuts. The exclusion was not needed while a cut spread over the whole
face, because the centroid of a 594 m2 skim was never a cell a truck would pick anyway. Once the bite
became compact the centroid landed on freshly levelled, perfectly drivable ground and the nearest stand
became the loader's own cell: measured on the `intensive_drain` scenario, a separation of exactly zero.
A smaller footprint is the right answer, and this is what it uncovered underneath.

Measured on the reference fixture over eight consecutive 1500 t cuts, the truck stood between 0.78 m
and 7.10 m from the loader, every stand was on a passable cell, and no stand was ever one of the dug
cells.

### Two legs, solved separately

The approach and the departure are solved by two independent A* calls rather than one being the
reverse of the other, because the surface changes between them: the cut has just been taken and the
face relaxed, so the way out is not always the way in. Both use `strict_goal=True`, which withdraws the
`solve_route` exemption that lets a haul truck spot at a crest and tip over an edge. A truck parking to
be loaded is doing the opposite manoeuvre and does not inherit that exemption. The docstring in
`bedblend/truck.py` is honest that this changes no route on the current scenarios, because the stand is
already picked from the passability mask and the flood fill; it is a correction of semantics, not the
repair of an observed defect.

If the outbound solve raises `NoRoute` the departure falls back to the reversed approach, which the
code justifies as the only honest fallback since the surface has not changed between the two solves.

Both polylines and both grid paths are stored on the `Cut`. The polyline (`approach`, `departure`) is
what gets drawn; the grid path (`approach_cells`, `departure_cells`) is what the per-step gradient rule
can actually be checked against, because `step_ok` divides by **one** cell width and a simplified
segment can span twenty. The reclaim route test used to check the polyline and passed for releases only
because its long segments happened to be flat. Measured on the fixture, an approach came out as 9
polyline points over 21 grid cells, and its longest single segment spanned 14.1 cell widths. `step_ok`
divides by `cell_m` (or `cell_m * sqrt(2)` on a diagonal), so applied across that segment it reports a
gradient about fourteen times the real one: the check was not lenient, it was meaningless, and it
passed only because that segment's rise was near zero.

### Refusal is a result

`HaulCycle.stand` is `None` when nothing drivable is within reach of the cut, and that is reported
rather than hidden. A campaign that has undercut its own access cannot be served, and saying so is the
point of modelling the haulage at all. `campaign` still returns the cut; the material still leaves the
ledger; only the haulage fields stay empty.

Verified: with `exit_xy` placed off the pad the stand is `None` and both routes are `None`; with every
cell on the pad passed as dug, the stand is `None`. Over a 60-cut drain of the reference fixture, 59
cuts were served and 1 was refused, so the refusal path fires in ordinary use, not only in contrived
cases.

One edge case a maintainer should know about: `haul_cycle(terrain, [], ...)` does not refuse. An empty
cell list puts the centroid at the pad origin `(0.0, 0.0)` and the nearest passable, reachable cell to
that origin is returned as a stand. `campaign` never does this (it only routes cuts that delivered
tonnage), but a direct caller can.

### Wiring it into a campaign

```python
cuts = bb.campaign(terrain, model, face,
                   cut_tonnes=1500.0, n_cuts=24, repose_deg=37.0,
                   exit_xy=(x_road, y_road), max_grade=math.tan(math.radians(37.0)) / 1.5)
```

`exit_xy` and `max_grade` are optional **only** so that an existing caller does not break. Without them
the material still leaves the ledger correctly and the feed series is unchanged, but nothing is
recorded about how it got off site, which is how this engine once shipped a reclaim campaign that no
machine ever attended. The haulage is strictly additive: `tests/test_reclaim.py` asserts that the
tonnages and grades of a plain campaign and a hauled one agree to six decimals.

The routing happens **after** the cut, on the surface the cut left behind, because that is the ground
the truck actually drives on.

The `max_grade` in the example is the same rule of thumb the build side uses, the repose gradient
divided by 1.5. `Fleet.of` in `bedblend/truck.py` documents that divisor as a commonly repeated
operational rule of thumb and states plainly that it is not a measured constant. `haul_cycle` itself
has no default: the caller supplies the number, so the product can say where it came from.

---

## 9. The picture

```
PLAN VIEW, looking down on the pad. The face advances to the right, along +s.

        t (across-face axis)
        ^        |<--------------- depth_m --------------->|
        |        |                                         |
  t_hi  +  . . . +=========================================+ . . . .
        |        |#########################################|
        |        |#########################################|   material
        |        |######......................#############|   still
        |        |####...                  ...#############|   standing
        |        |###.        b i t e         .############|
        |   T    |##.            R             .###########|   envelope =
        |  [o]===S=============================>###########|   engaged_cells
        |   ^    |##.                          .###########|
        |   |    |###.                        .############|
        |   |    |####...                  ...#############|
        |   |    |######......................#############|
  t_lo  +  .|. . +=========================================+ . . . .
        |   |    ^                                         ^
        |   |    s_near, the face line            position_m + depth_m
        +---+-----------------------------------------------------------> s
            |
            approach and departure, solved separately, to and from exit_xy

  S    stance(): near edge of the material, offset_m across it, one radius R in
  R    loader.dig_radius_m; no cell outside this circle can be dug from S
  T    the truck stand: nearest passable AND reachable cell to the centroid of
       the bite, and never one of the cells the loader is digging
  #    material;  .  the reach circle;  = the envelope bounds


SECTION through the stance, looking along the face (+s to the right).

    z
    ^                                              crest
    |                            __________________________
    |                           /##########################
    |          lift  { - - - - /###########################
    |          |              /############################
    |          v      .......'#############################
    |    [o]          : bite :#############################
    |     T           :......:#############################
    +=================+======+=============================> s
     pad (z0)         ^      ^
                      |      one lift deep at most:
                      |      lift = min(max_face_m, max_cut_height_m)
                      |
                      the truck stands on the pad beside the face, never on
                      a cell the loader is digging; the loader stands on the cut
```

---

## 10. The measured history the code carries

These figures live in the docstrings and comments of `bedblend/reclaim.py`, and they were measured on
shipped artifacts of the consuming product. They are the record of what the previous behaviour was, so
they cannot be reproduced from this repository alone; treat them as provenance, not as regression
targets.

**The footprint before.** A cut was a tonnage taken from a slab, and the slab was the whole working
face: `depth_m` deep by `width_m` across, every cell of it engaged on every cut no matter how little
material the cut removed. "Measured on the shipped artifacts that came to a mean footprint of 594
square metres per cut across 632 cuts, and the worst case was the entire slab, 900 square metres. One
scenario took 355 tonnes while touching 486 square metres, which is a seven centimetre skim off half a
football pitch rather than anything a loader does."

**The provenance tell.** This is the part worth remembering, because it needed no geometry at all to
spot: "a single 881 tonne cut reported material from 108 distinct dig blocks. Fifteen bucket passes
cannot sample 108 dig blocks." A number that is impossible for the physical operation is a defect
report that any reader could have filed from the artifact alone.

**The footprint after.** On the reference fixture of section 12, a 1500 t cut assembled across stances
touches 26 cells (162.5 m2) and reports 4 dig blocks; 3000 t touches 57 cells (356.2 m2) and reports 7;
6000 t touches 114 cells (712.5 m2) and reports 8. A single-stance 300 t cut touches 5 cells (31.2 m2)
and reports 3. The provenance count now tracks the tonnage, because the footprint does.

The other measurements the code carries, each stated where it applies above: the stacker and the
reclaimer inside one cell in 5 of 51 cuts (module docstring); the concurrent scenario falling from 28
cuts to 2 and the surge scenario from 74 to 2 without `rewind` (`ReclaimFace.rewind`); the 3000 t cut
taking 1035 m2 at 1.45 m mean depth under distance-only ordering (`ReclaimFace.bite`); 3303 m2 per cut
removing 0.31 m under unbounded assembly (`next_cut`); 768 against 767 m2 of surface moved per cut with
and without seeding the relaxation (`cut`); a separation of exactly zero between truck and loader on
`intensive_drain` before dug cells were excluded (`haul_cycle`); and `passes_for` returning 1.76, a
density, before the bucket was given a material to fill it with (`LoaderSpec.passes_for`).

---

## 11. Where this fails, and what is anchored rather than measured

**There is no fleet.** One truck is routed per cut. There is no truck identity, no queue, no bunching,
no dispatch and no second machine anywhere on the pad. `bedblend/truck.py` has a `Fleet`, and its own
docstring says it is deliberately not a discrete-event simulator; `haul_cycle` does not even use it.

**There is no cycle time.** Nothing in this module has units of time. There is no travel speed, no
spot time, no load time, no bucket-pass duration, and therefore no answer to "how many tonnes per hour
can this face deliver". `LoaderSpec.passes_for` returns a pass count and stops there. A caller who
needs a rate has to supply the time model, and the cut sequence this module produces is an ordering,
not a schedule.

**One machine class, and only its envelope.** `LoaderSpec` defaults describe the working envelope of a
large hydraulic front shovel class, and the docstring is explicit that this is a parameter of the run,
declared and adjustable, not a measured fit to a particular machine. There is no wheel loader versus
shovel versus surface miner distinction, no bucket-wheel or bridge reclaimer, no apron feeder or dozer
trap. What does not depend on the exact figures is the shape of the result: the footprint of a cut
scales with the tonnage removed and is bounded by the reach of the machine.

**Nobody checks that the loader can get to its stance.** `stance` is derived purely from where the
material is. Trafficability is tested for the **truck** and only for the truck. A loader can therefore
be placed at a stance no machine could have driven to, which is the one place where the reclaim side is
weaker than the build side.

**The loader has no position of its own.** `Cut.loader` is the centroid of the dug cells, computed
after the fact by `_centroid`, and it is only populated when a haul cycle is applied. It has no
heading, no footprint and no continuity between cuts.

**A campaign ends in a long tail of near-zero cuts.** `next_cut` returns a `Cut` whenever any tonnage
at all came out, so as a face works itself out the returned series decays rather than stopping. Draining
the reference fixture with 60 cuts of 1500 t delivered 33 307.1 t of 36 960.0 t (90.1 percent), and the
tail included cuts of 0.6 t, 0.1 t and several rounding to 0.0 t. Filter on `c.tonnes > 0` (or on a
sensible minimum parcel) before computing feed statistics; the tests do.

**`n_cuts` is a maximum.** `campaign` stops early only when `next_cut` returns `None`, which happens
when nothing was found anywhere in the sweep, including after one rewind.

**Anchored constants, named.** `LoaderSpec` defaults (bucket 34.0 m3, payload 60.0 t, dig radius
15.0 m, max cut height 15.0 m) are a declared machine class, and what would replace them is a
manufacturer reach diagram or a surveyed reach envelope for the actual machine. `ReclaimFace` defaults
(`depth_m` 5.0, `width_m` 30.0, `max_face_m` 15.0) are plan parameters, and `max_face_m` in particular
should come from the site's own geotechnical face-height limit. The tram step of exactly `2R` per
stance assumes a full-diameter sweep with no overlap, which is geometry, not observation. The `sweep`
floor of 2 exists so that a face narrower than one machine stretch still gets a second stance.
`MAX_STANCES_TRIED = 4096` is a backstop against a pathological geometry spinning, generous enough
never to bind on a real pad, and carries no physical meaning. The tolerances are numerical: `1e-9` on
tonnage in `bite` and `next_cut`, and also the minimum standing depth a cell must carry in `bite` to be
a candidate at all; `1e-12` on parcel thickness in `_take` and `_restack`, and on the direction
magnitude in `_basis`.

**And one caveat about performance rather than correctness.** `bite` computes the envelope once and
passes it to `stance`, which is what keeps a wide yard from paying four full grid scans per attempt.
`next_cut` then calls `face.step(terrain)` without an envelope, so `step` rescans the pad through
`_occupied`, and when the sweep resets `advance` calls `_along`, which scans it again. Every stance
attempt therefore costs two full passes over the pad, three when the sweep resets, plus the
relaxation. The 60-cut drain above, with haulage, ran in 1.4 to 2.1 s over three runs on a 48 by 48
pad; that is wall clock on one machine rather than a benchmark, so the order of magnitude is the
claim and not the digits.

---

## 12. Reproducing the numbers in this document

Every measured figure above, except the ones attributed to shipped artifacts in section 10, came from
the fixture below. A 48 by 48 pad at 2.5 m cells, one 60 m by 60 m area with a 30 m margin, 160
paddock loads placed with a `TruckSpec` default machine, grades rising along the build so the
extraction order can matter, and a relaxation to 37 degrees after every load with the ledger carried
along.

It is `_stocked` from `tests/test_reclaim.py` with one addition: the uniform `coarse_fraction` of 0.35,
which that test records only in its separate `_stocked_with_coarse` variant. It is here so the
`coarse_fraction` a cut reports is readable rather than zero, and it changes nothing else, checked both
ways: a 3000 t cut is 2280.725182 t at grade 0.43905206 over 46 cells with the field recorded and
without it.

```python
import math
from bedblend.blocks import BlockModel, transfer_distances
from bedblend.design import rectangular_yard
from bedblend.dump import place_paddock
from bedblend.reclaim import ReclaimFace, ReclaimMethod, cut, next_cut, campaign
from bedblend.relax import relax_to
from bedblend.terrain import Terrain, TruckSpec

REPOSE, CELL = 37.0, 2.5

def stocked(n_loads=160):
    t = Terrain.flat(48, 48, CELL)
    plan = rectangular_yard(n_areas=1, area_width_m=60.0, area_length_m=60.0,
                            bench_height_m=6.0, n_benches=1, margin_m=30.0)
    plan.row_spacing_m = 8.0
    area, truck, model = plan.areas[0], TruckSpec(), BlockModel.over(t)
    for k, tp in enumerate(plan.paddock_tips(area, area.benches[0])[:n_loads]):
        pl = place_paddock(t, tp.x_m, tp.y_m, tp.heading_rad, truck.load_volume_m3, truck)
        model.record(t, pl.cells, pl.added_m, grade=0.30 + 0.004 * k, source_block=k // 20,
                     event_id=k, lift=0, area=area.name,
                     coarse_fraction=[0.35] * len(pl.cells))
        moves = relax_to(t, REPOSE, active=set(pl.cells))
        if moves:
            model.apply_transfers(
                [(a, b, v * model.cell_area_m2) for a, b, v in moves],
                distances=transfer_distances(t, moves),
            )
    model.assert_consistent(t)
    return t, model

face = ReclaimFace(method=ReclaimMethod.FULL_HEIGHT, position_m=30.0, direction=(1.0, 0.0),
                   depth_m=10.0, width_m=200.0, max_face_m=15.0)
```

That pile holds 36 960.0 t over 770 cells carrying material, mean thickness 4.042 m and maximum
6.634 m. The face's envelope is 112 cells (700 m2) and its first stance is at pad coordinates
`(31.25, 43.75)`.

After a 60-cut drain the ledger still agrees with the terrain (`model.assert_consistent(terrain)`) and
the pile is still stable (`assert_stable(terrain, 37.0)`). Both are cheap and both are worth asserting
in any caller that runs a long campaign, because a reclaim bug shows up as ledger drift long before it
shows up as an implausible grade.

---

## 13. References

The module cites one paper, and this document cites nothing the source does not.

* Young, A. and Rogers, W.P. (2021), *Modelling of pre-crusher stockpiles*, Minerals 11(6), 636.
  [doi:10.3390/min11060636](https://doi.org/10.3390/min11060636).
  Section 4.1 for the framing quoted in section 1 above (stockpile processing treated as mining a muck
  pile, and software producing an optimized processing sequence that reduces feed variability), and
  figure 1 types 3 and 4 for the last-in-first-out and first-in-first-out taxonomy that `ReclaimMethod`
  encodes. The phrase "processing the stockpile in parallel vertical approaches" that `FULL_HEIGHT`
  quotes is from the same paper.

Related modules, for the primitives this one builds on: `bedblend/terrain.py` (the pad, material
thickness, the pit inversion framing, and the trafficability caveat), `bedblend/blocks.py` (the parcel
ledger, `take_from_top`, and the `replace`-not-positional-rebuild rule), `bedblend/relax.py`
(`relax_to` and the repose cascade), and `bedblend/truck.py` (`passable_mask`, `reachable_mask`,
`solve_route`, `step_ok`, `Route`, `NoRoute`, and the repose-over-1.5 gradient rule of thumb).
