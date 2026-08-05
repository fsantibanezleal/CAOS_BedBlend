# Method 6: kinetic size segregation

Source files: `bedblend/segregation.py` (the solver) and `bedblend/facesegregation.py` (the coupling
to a real dumped face). The `6` in the title is this page's position in the docs theme listed in
`docs/methods.md`, and it is not the number the code uses: `segregation.py` and
`tests/test_segregation.py` both open with "Method 4", which belongs to a different and undocumented
ladder (`rtd.py` is "Method 12" on the same one, and no other module carries a number at all). Expect
the mismatch rather than assume one of them is stale.

Public names re-exported from the package root: `FlowingLayer`,
`segregation_number`, `NZ_DEFAULT`, `CFL`, `PECLET_DEFAULT`, `Avalanche`, `avalanche_state`,
`FaceSegregation`, `segregate_face`, `segregation_index`, `total_segregation_index`,
`apparent_repose_deg`, `intensity`.

Every number in this document was produced by running the code in this repository at version
0.07.002, not copied from another document. Where a figure recorded in a source comment did not
reproduce, the section says so and gives the value the code returns now. Seven such disagreements are
collected at the end.

---

## 1. What this is, and what it is not

It **is** a numerical solution of Gray and Thornton's binary-mixture segregation equation, reduced to
one space dimension in depth and marched down the slope, with Gray and Chugunov's diffusive remixing
opposing the sieving. Concentration shocks are resolved with an exact Godunov flux rather than
smeared. Species mass is conserved to machine precision (measured drift `1.11e-16` over 40 marching
steps at `Sr = 2`), and the fine fraction never leaves `[0, 1]` (measured worst excursion `0.0` over
80 steps at `Sr = 6`).

It **is not**:

* a model of **trajectory segregation**. Coarse rock that leaves the crest with enough momentum to fly
  and bounce past the toe is ballistic, not diffusive, and Gray and Thornton's equation does not
  contain it. Section 9 says exactly what the code does instead.
* a **particle-size distribution** model. There are two species, coarse and fine, because that is what
  the conservation law integrates and what `material.SizeSplit` carries. A full PSD is a different and
  much larger claim.
* a model of **where the mass lands** down the face. That distribution is imposed from a published
  operational observation (section 6.3) and is deliberately kept separate from the sieving so that the
  two claims can be checked independently.
* a **fitted curve**. It was one, for several releases, and the file headers of both modules record
  that at length. `intensity()` is the surviving fitted object and it no longer touches the size
  distribution at all; it drives only the overrun magnitude.
* **calibrated**. Two coefficients are anchored to the literature rather than measured on any
  material. Section 8.

---

## 2. The mechanism

### 2.1 Kinetic sieving

A granular avalanche flowing over a rough bed is sheared: the free surface moves faster than the base.
Shear opens and closes transient voids between grains. A void of a given size is more likely to be
filled by a grain that fits into it, so small grains preferentially fall through the matrix under
gravity. Once a small grain has moved down, the large grains it displaced must go somewhere, and they
are levered upward by squeeze expulsion. The net effect is that fines migrate to the **base** of the
flowing layer and coarse rides on top. This is the entire physical content of the method, and it runs
in the opposite direction from intuition about a shaken box, because the driver is the shear profile,
not the vibration.

Savage and Lun gave the first quantitative statistical-mechanical treatment of this in inclined chute
flow, deriving percolation rates from a void-filling probability argument
(doi:10.1017/S002211208800103X). Gray's review of the field is a good entry point
(doi:10.1146/annurev-fluid-122316-045201). Neither of those two papers is cited in this engine's
source; they are given here as the background the reader will want, and section 9 marks them as such.

### 2.2 Gray and Thornton's binary mixture theory

Gray and Thornton (doi:10.1098/rspa.2004.1420) put kinetic sieving into a mixture-theory framework.
Each species gets its own mass and momentum balance; the interaction between them is a
partial-pressure argument in which the large particles carry more than their share of the overburden
and the small particles less. That imbalance is what drives the two species apart, and it produces
percolation velocities that are proportional to the concentration of the *other* species. The result
is a scalar equation for the small-particle volume fraction with a quadratic, and therefore convex,
flux. The convexity is not incidental: it is what makes the solver in section 4 exact.

---

## 3. The equations, with the source's numbering

The equation numbers below are Gray and Thornton's own, and they are the numbers carried in the
module docstring of `bedblend/segregation.py`.

### 3.1 Percolation velocities, equation (3.10)

```
    w_l - w  =  + q * phi_s          large particles are levered up
    w_s - w  =  - q * phi_l          small particles drain down
```

| symbol  | meaning |
|---|---|
| `w_l`   | velocity component of the LARGE (coarse) species normal to the bed, positive away from the bed |
| `w_s`   | velocity component of the SMALL (fine) species normal to the bed |
| `w`     | velocity component of the BULK mixture normal to the bed |
| `phi_s` | volume fraction of the small species within the granular skeleton |
| `phi_l` | volume fraction of the large species, `phi_l = 1 - phi_s` |
| `q`     | mean segregation velocity, equation (3.11), units of velocity |

Read the pair together and the shape of the whole method is already visible. A species stops
segregating when the *other* species runs out: if `phi_l` reaches zero there is nothing left for the
fines to fall through, and if `phi_s` reaches zero there is nothing left to lever the coarse. That is
the `phi (1 - phi)` factor, and it is why the solver cannot overshoot into an unphysical
concentration.

### 3.2 Mean segregation velocity, equation (3.11)

```
    q  =  (B / c) * g * cos(zeta)
```

| symbol | meaning |
|---|---|
| `B`    | the coefficient of the inter-particle pressure perturbation, dimensionless |
| `c`    | the inter-particle drag coefficient |
| `g`    | gravitational acceleration |
| `zeta` | slope angle measured from the horizontal |

This engine does not evaluate `B` and `c`. It replaces the whole group with a shear-rate scaling and
one anchored coefficient: the scaling is `q = kappa (U/H) d` in section 6.1, and the coefficient is
`PERCOLATION_COEFFICIENT` in section 8.

### 3.3 The non-dimensionalised balance, equation (3.18)

Substituting (3.10) into the small-particle mass balance and non-dimensionalising with the standard
shallow-avalanche scalings gives

```
    d(phi)/dt + d(phi u)/dx + d(phi v)/dy + d(phi w)/dz
        - Sr * d/dz[ phi (1 - phi) ]  =  0
```

| symbol   | meaning |
|---|---|
| `phi`    | volume fraction of the SMALL species; this is the solved variable throughout the code |
| `t`      | non-dimensional time |
| `x`, `y` | non-dimensional downslope and cross-slope coordinates |
| `z`      | non-dimensional coordinate normal to the bed, `z = 0` at the base and `z = 1` at the free surface |
| `u,v,w`  | non-dimensional bulk velocity components along `x`, `y`, `z` |
| `Sr`     | the segregation number, equation (3.19) |

### 3.4 The segregation number, equation (3.19)

```
    Sr  =  q * L / (H * U)
```

| symbol | meaning | code |
|---|---|---|
| `q` | mean segregation velocity, m/s | `Avalanche.q_ms` |
| `L` | downslope path length of the avalanche, m | `Avalanche.path_m` |
| `H` | thickness of the flowing layer, m | `Avalanche.layer_h_m` |
| `U` | typical downslope flow speed, m/s | `Avalanche.u_ms` |

`Sr` is the ratio of the mean segregation velocity to the typical normal bulk velocity, that is, how
much sieving happens per unit of travel. It is the single dimensionless group the whole method turns
on. The function `segregation_number(q_ms, path_m, layer_h_m, u_ms)` in `bedblend/segregation.py` is
this formula and nothing else; it returns `0.0` when `layer_h_m * u_ms <= 0` and clamps negatives to
zero.

`Sr = 0` degenerates the equation to pure tracer advection: no segregation at all. That limit is the
product's negative control and it is produced by the same solver rather than by a separate code path,
which is what makes the control worth anything. `FlowingLayer.advance` returns immediately when
`sr <= 0.0`, so the profile is left bit-identical, and the test asserts equality (`p == 0.37`), not
near-equality.

---

## 4. The reduced law that is actually solved

On a stockpile flank the avalanche is a shallow layer of roughly uniform thickness running over a
static bed. Taking plug flow (no dependence on `y`, and `u` uniform through the depth) and marching in
the downslope coordinate `x` instead of in time reduces (3.18) to a one-dimensional scalar
conservation law in depth:

```
    d(phi)/dx + d(F)/dz  =  0,        F(phi)  =  - Sr * phi * (1 - phi)
```

with no flux through the free surface (`z = 1`) or through the base (`z = 0`). `phi` is the volume
fraction of the SMALL species, and index `0` of `FlowingLayer.phi` is the BASE of the layer while
index `nz - 1` is the free surface.

### 4.1 Why a Godunov flux is exact here

`F` is convex. Writing it out, `F(phi) = Sr (phi^2 - phi)`, so `F''(phi) = 2 Sr >= 0`, with the
minimum at `phi = 0.5`. For a convex flux the exact solution of the Riemann problem at an interface
between a left state `pl` and a right state `pr` is

```
    pl <= pr :   F_god  =  min over [pl, pr] of F         (a rarefaction)
    pl >  pr :   F_god  =  max over [pr, pl] of F         (a shock)
```

and for a convex `F` the maximum over an interval is always attained at an endpoint, while the
minimum is attained at the interior stationary point `phi = 0.5` when that point lies inside the
interval and at an endpoint otherwise. That is precisely the branch structure of `_godunov_flux`:

```python
if pl <= pr:
    if pl <= 0.5 <= pr:
        return f(0.5)
    return min(f(pl), f(pr))
if pr <= 0.5 <= pl:
    return max(f(pl), f(pr))
return max(f(pl), f(pr))
```

Verified by brute force: over a 201 by 201 grid of Riemann pairs on `[0, 1]` at `Sr = 2`, the function
agrees with the textbook Godunov value to `0.000e+00` in all 40401 cases. Note that the third branch
is **redundant**: `10200` of those pairs enter `pr <= 0.5 <= pl` and it returns exactly the same
expression as the fallthrough underneath it, because the max of a convex function over an interval
does not care whether the interval straddles the stationary point. The branch is correct and dead. It
is left in because it makes the shock case explicit next to the rarefaction case, but a maintainer
deleting it would not change a single output.

The alternative most people reach for, a Lax-Friedrichs flux, would smear the concentration shock over
several cells. The shock is a real feature of the 2005 solution and an observed feature of chute
experiments, so it is kept.

### 4.2 Discretisation, and the two stability limits

`FlowingLayer` holds `nz` cells (`NZ_DEFAULT = 32`) of uniform thickness `dz = 1 / nz`. `advance(dx_nd)`
marches the profile `dx_nd` in non-dimensional downslope distance, sub-stepped so both stability
limits are honoured:

```
    hyperbolic (Godunov)    max |F'(phi)| = Sr |1 - 2 phi| <= Sr
                            step limit  =  CFL * dz / Sr

    parabolic (remixing)    step limit  =  CFL * dz^2 / (2 * Dr)

    n_sub = max(1, int(dx_nd / min(both limits)) + 1)
```

with `CFL = 0.4`. Measured sub-step counts for one deposition bin of the shipped 12-bin march
(`dx_nd = 1/12`):

| `Sr` | `Dr = Sr/Pe` | hyperbolic limit | parabolic limit | sub-steps per bin |
|---:|---:|---:|---:|---:|
| 1.80 | 0.1500 | 0.00694 | 0.00130 | 64 |
| 4.00 | 0.3333 | 0.00313 | 0.00059 | 143 |
| 15.00 | 1.2500 | 0.00083 | 0.00016 | 534 |

The remixing term is the binding constraint at every `Sr` the product reaches, not the advection term.
That is worth knowing before anyone tries to speed the solver up by loosening `CFL`.

No-flux walls are imposed by leaving `flux[0]` and `flux[nz]` at zero, and by using a zero-gradient
ghost value for the diffusive stencil at both ends. Both terms therefore telescope exactly, which is
why the mass test passes at `1e-9` rather than at some looser tolerance chosen to make it pass.

The module docstring calls the whole thing "a few hundred floating-point operations per avalanche
generation". **It is not**, and the figure should not be repeated. Counted by wrapping
`_godunov_flux` and `advance` on the reference face (11 m at 37 degrees, default material, 12 bins,
`nz = 32`): 65 sub-steps per bin, 780 sub-steps in total, 24180 evaluations of `_godunov_flux` and
24960 cell updates, at about 9 ms per face in CPython on the machine this was written on. That is
hundreds of thousands of floating-point operations, not hundreds. The docstring's companion claim,
that the continuum model is cheaper than the fitted parametric curve it replaced, does not hold
either: `intensity()` is a three-term closed form and costs a handful of operations. What survives is
the conclusion rather than the arithmetic, and it survives comfortably. Nine milliseconds per load is
cheap enough to run inside the build loop, so there is no performance excuse for not solving the
equation. See section 13.

---

## 5. Diffusive remixing, and why it is not optional

### 5.1 The term

Gray and Chugunov (doi:10.1017/S0022112006002977) are the direct successor to the 2005 paper and add
the one term it leaves out: random collisional remixing, which opposes the sieving. The depth equation
becomes

```
    d(phi)/dx + d/dz[ - Sr phi (1 - phi) ]  =  d/dz[ Dr * d(phi)/dz ]
```

with

```
    Pe  =  Sr / Dr            the Peclet number, sieving against remixing
    Dr  =  Sr / Pe            the code's `FlowingLayer.diffusivity`
```

`PECLET_DEFAULT = 12.0`. Gray and Chugunov fit `Pe` against chute experiments and report values of
order ten; `12.0` sits in the middle of that range. `FlowingLayer.diffusivity` returns `0.0` when
`pe <= 0` or `pe` is infinite, so "off" and "infinite Peclet" both recover the pure 2005 hyperbolic
model exactly, and `Dr` is zero whenever `Sr` is zero, which keeps the passive-tracer control exact.

### 5.2 Without it the model saturates

The pure hyperbolic flux separates the two species completely and then stops, because `F` shuts off at
a pure phase. Beyond a modest `Sr` every face returns the same answer. This is the measurement, run
here rather than quoted: the on-face sorting index (`segregation_index`, section 6.4) for the default
material over a 12-bin march with no overrun, at `nz = 32`.

| `Sr` | index, remixing OFF (`Pe = inf`) | index, remixing ON (`Pe = 12`) |
|---:|---:|---:|
| 0.5 | 0.196510 | 0.182839 |
| 1.0 | 0.391821 | 0.308654 |
| 1.5 | 0.512605 | 0.384548 |
| 1.8 | 0.514297 | 0.414263 |
| 2.0 | 0.515173 | 0.429476 |
| 2.5 | 0.515996 | 0.456350 |
| 3.0 | 0.516152 | 0.472894 |
| 4.0 | 0.516194 | 0.490660 |
| 6.0 | 0.516195 | 0.504152 |
| 10.0 | 0.516195 | 0.511218 |
| 15.0 | 0.516195 | 0.513044 |
| 30.0 | 0.516195 | 0.513525 |

Read the left column at the two ends of the band that real dumps occupy, `Sr = 1.8` to `Sr = 4.0`:
`0.514297` and `0.516194`, a spread of `0.0019`. Every scenario in the consuming product would have
reported the same segregation whatever its drop height or face angle. Over a factor of twenty in `Sr`,
from 1.5 to 30, the hyperbolic model moves by `0.0036` in total and is converged to six figures by
`Sr = 6`. With remixing on, the same operational band spreads `0.414263` to `0.490660`, which is
`0.0764`, roughly forty times more responsive. That is the difference between a product that can tell
two benches apart and one that cannot.

Shocks are not removed by the remixing; they acquire a finite thickness, and that thickness is what
carries the information. Measured on a layer started uniform at `phi0 = 0.5`, `Sr = 3`, `nz = 32`,
after 40 calls of `advance(0.05)`:

```
    remixing off  (Dr = 0.00)   0 of 32 cells lie strictly between 0.02 and 0.98
      1.00 1.00 1.00 1.00 1.00 1.00 1.00 1.00 1.00 1.00 1.00 1.00 1.00 1.00 1.00 1.00
      0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00 0.00

    remixing on   (Dr = 0.25)  24 of 32 cells lie strictly between 0.02 and 0.98
      0.99 0.99 0.99 0.98 0.98 0.97 0.96 0.95 0.93 0.90 0.87 0.83 0.78 0.71 0.63 0.55
      0.45 0.37 0.29 0.22 0.17 0.13 0.10 0.07 0.05 0.04 0.03 0.02 0.02 0.01 0.01 0.01
```

Index 0 is the base. Both profiles have a depth-averaged `phi` of exactly `0.500000000000`, so the
remixing costs nothing in conservation.

### 5.3 How much the answer depends on `Pe`

At the reference dump's segregation number (`Sr = 1.8278`, section 6.1), the on-face index against the
Peclet number:

| `Pe` | 4.0 | 8.0 | 12.0 | 20.0 | 40.0 | infinite |
|---|---:|---:|---:|---:|---:|---:|
| index | 0.303216 | 0.382816 | 0.416573 | 0.449244 | 0.480694 | 0.514352 |

Halving `Pe` from 12 to 4 costs 27 percent of the sorting; raising it to 40 adds 15 percent. The
answer is genuinely sensitive to a constant nobody has measured on this material. Say so when
reporting a result.

One implementation fact that is easy to miss: **`segregate_face` never passes `pe`.** It constructs
`FlowingLayer(phi0=split.fine, sr=av.sr, nz=NZ_DEFAULT)`, so the shipped path always runs at
`PECLET_DEFAULT`. To vary it you have to drive `FlowingLayer` yourself.

---

## 6. Where `Sr` comes from, and the two regimes

`bedblend/facesegregation.py` is the coupling. It is the module that turns a truck tipping over a
crest into the four physical quantities `segregation_number` needs.

### 6.1 `avalanche_state(drop_m, face_angle_deg, mat) -> Avalanche`

Four steps, in this order.

**Does it flow at all.** Granular material starts moving at a steeper angle than it stops at, so the
angle that governs an avalanche already in motion sits below the static angle of repose.
`FLOW_HYSTERESIS_DEG = 4.0` is subtracted from the material's own repose angle, giving a dynamic
friction angle of 33.0 degrees for the default material (`repose_dry_deg = 37.0`), and
`mu = tan(33 deg) = 0.649408`. The depth-averaged momentum balance on a slope is

```
    a  =  g * (sin(t) - mu * cos(t))
```

with `t` the face angle and `g = GRAVITY_M_S2 = 9.81`. If `a <= 0` the face holds, and the function
returns `Avalanche(0.0, h_min, 0.0, 0.0, 0.0, flows=False)`. A face that does not avalanche cannot
sieve, so the honest output is no sorting at all. The gate is `accel > 0`, so it sits exactly at the
dynamic friction angle and not a fraction above it. Measured for the default material at a 20 m drop:
`flows` is False at 20, 28, 31, 32 and 33.0 degrees, and True at 33.0001 degrees and everything above
it, including the 33.05 degree row in the sweep in section 6.2. The older fitted
curve gave such a face a segregation gradient anyway, because its angle term was a ramp starting at 28
degrees with nothing physical underneath it.

**Speed, from rest at the crest.**

```
    L  =  drop / sin(t)              path_m
    U  =  sqrt(2 * a * L)            u_ms
```

**Thickness, from flux conservation with a grain floor.**

```
    H  =  max( Q / U , h_min ),      Q = CASCADE_FLUX_M2_S = 1.0 m2/s
    h_min  =  LAYER_MIN_DIAMETERS * d,    LAYER_MIN_DIAMETERS = 5.0
```

`Q` is the volumetric flux per unit width of a load cascading over the crest. A haul truck body empties
in about ten seconds across about ten metres of crest, which for a hundred cubic metre load is of order
one. The floor exists because a layer thinner than a few of its own grains is not a layer and the
continuum description stops meaning anything. For the default material (`d50_mm = 120.0`, so
`d = 0.12 m`), `h_min = 5.0 * 0.12 = 0.60 m`.

**Percolation velocity, on the shear rate.**

```
    q  =  kappa * (U / H) * d,        kappa = PERCOLATION_COEFFICIENT = 0.30
```

and then `Sr = segregation_number(q, L, H, U)`.

Substituting `q` into (3.19):

```
    Sr  =  q L / (H U)  =  kappa * d * L / H^2
```

**`U` has cancelled.** How fast the layer runs does not change how much it sieves per metre of slope: a
slower layer takes longer over the same path and sorts by the same amount. This is a genuine
prediction of the scaling and it is the opposite of what most operational intuition expects.

The reference dump, an 11 m face at 37 degrees in the default material, measured:

```
    L = 18.2780 m    U = 5.4615 m/s    H = 0.6000 m (grain-limited)
    q = 0.327689 m/s     Sr = 1.8278
```

### 6.2 The two regimes, and the reversal (the subtle part)

`H` is a max of two expressions, so `Sr` has two branches:

```
    flux-limited    H = Q/U       Sr = kappa d L U^2 / Q^2    rises steeply with drop AND with angle
    grain-limited   H = h_min     Sr = kappa d L / h_min^2    rises with drop, FALLS with angle
```

Both closed forms were checked against `avalanche_state` and agree to a relative error of about
`1e-16` in every case tried.

In the grain-limited regime the thickness has stopped responding to anything, so all that is left of
the face angle is the path length `L = drop / sin(t)`, and a steeper face **shortens** it. The
face-angle dependence therefore **reverses** between the regimes. This is not a numerical artifact and
it is not a modelling choice; it is what the scaling says once the layer bottoms out on its own grains.

The crossover is where `Q/U` falls to `h_min`. Measured for the default material:

| face angle | crossover drop |
|---:|---:|
| 35 deg | 1.9515 m |
| 37 deg | 1.0244 m |
| 40 deg | 0.6263 m |
| 45 deg | 0.4038 m |

(30 and 33 degrees do not appear because the default material does not flow below 33.0 degrees.) The
1.02 m figure at 37 degrees is the number recorded in the module docstring and it reproduces exactly.

Now the reversal, measured with `avalanche_state` on the default material. Regime in brackets:

| drop | 35 deg | 37 deg | 40 deg | 45 deg |
|---:|---|---|---|---|
| 0.5 m | 0.0223 (flux) | 0.0406 (flux) | 0.0621 (flux) | 0.0707 (grain) |
| 1.0 m | 0.0893 (flux) | 0.1622 (flux) | 0.1556 (grain) | 0.1414 (grain) |
| 2.0 m | 0.3487 (grain) | 0.3323 (grain) | 0.3111 (grain) | 0.2828 (grain) |
| 11.0 m | 1.9178 (grain) | 1.8278 (grain) | 1.7113 (grain) | 1.5556 (grain) |
| 20.0 m | 3.4869 (grain) | 3.3233 (grain) | 3.1114 (grain) | 2.8284 (grain) |

At a half-metre drop `Sr` rises with angle by a factor of three across the row. At eleven metres it
falls monotonically. The published operational statement, that steeper faces at 35 to 40 degrees
"create faster material flow down the face, increasing trajectory segregation", is the **flux-limited**
direction, and it is the regime a truck tipping over a modest crest is in. A tall face reverses it.

The reversal also shows up in angle at a fixed drop, which is worth seeing because it makes the
mechanism unmistakable. At a 20 m drop, sweeping the angle upward from the flow threshold:

| angle | `U` | `Q/U` | `H` | `L` | `Sr` | regime |
|---:|---:|---:|---:|---:|---:|---|
| 33.05 | 0.8653 | 1.1557 | 1.1557 | 36.672 | 0.9884 | flux |
| 33.10 | 1.2228 | 0.8178 | 0.8178 | 36.623 | 1.9715 | flux |
| 33.25 | 1.9296 | 0.5182 | 0.6000 | 36.477 | 3.6477 | grain |
| 34.00 | 3.8213 | 0.2617 | 0.6000 | 35.766 | 3.5766 | grain |
| 37.00 | 7.3643 | 0.1358 | 0.6000 | 33.233 | 3.3233 | grain |
| 45.00 | 11.7291 | 0.0853 | 0.6000 | 28.284 | 2.8284 | grain |

`Sr` rises almost four-fold over the first fifth of a degree above the flow threshold, peaks at
`3.6539` at `33.1862` degrees, and falls thereafter. The peak is not a fitted feature: it sits exactly
at the crossover angle where `Q/U` falls to `h_min`, found by bisecting on that condition and
confirmed by a sweep at a ten-thousandth of a degree. Near the threshold the layer is slow, so `Q/U` is
thick, so flux conservation binds and `Sr` climbs with angle. Past the crossover the grain floor binds
and only the shortening path is left.

The upshot for anyone reading a result: **`Sr` is not monotone in the face angle**, and which way it
goes depends on where the load sits relative to the crossover. A sweep that samples only tall faces
will conclude that segregation falls with angle, and a sweep that samples only shallow tips will
conclude the opposite. Both are right about their own regime.

The module docstring records that across the 16762 loads that formed a face in the consuming product's
shipped scenarios, with a median drop of 1.38 m, 42 percent were flux-limited and 58 percent
grain-limited. **That measurement is not reproducible from this repository**, because those scenarios
live in the consuming product. What is reproducible here is the crossover that makes the split
plausible: 1.02 m at 37 degrees against a median drop of 1.38 m puts the population squarely across the
boundary rather than on one side of it.

### 6.3 The march down the face

`segregate_face(*, drop_m, face_angle_deg, mat, n_bins=12) -> FaceSegregation` runs the coupling.

1. `g = intensity(drop_m, face_angle_deg, mat)` and `av = avalanche_state(...)`.
2. A `FlowingLayer` is started at the crest holding the load's own fine fraction uniformly through its
   depth, at `sr = av.sr`.
3. Bin centres run from the crest at index 0 to the toe at index `n - 1`. The deposition weights are
   `w[k] = 0.35 + 0.65 * s[k]`, normalised to sum to one. For 12 bins that is
   `0.0466 0.0532 0.0599 0.0666 0.0733 0.0800 0.0867 0.0934 0.1001 0.1067 0.1134 0.1201`, so the toe
   bin receives 2.58 times the mass of the crest bin. This is the published observation that a cascade
   "typically aggregates more at the bottom of the dumping area under normal conditions and less near
   the top crest of the dump" (Young and Rogers, Minerals 2021, 11, 636, section 3.3). **It is imposed,
   not solved**, and it is kept separate from the sieving on purpose so each claim can be checked on
   its own.
4. At each bin the layer is marched `dx_nd = 1/n` and then `split_base(deposit / remaining)` deposits
   the bottom slice. Because the fines have drained to the base, what is laid down is fine-rich and
   what keeps travelling is coarse-rich. **Coarse at the toe is an output of the flux
   `F(phi) = -Sr phi (1 - phi)`, not a rule written anywhere in the code.**
5. Whatever is still travelling at the last bin is the overrun. Its composition is
   `1 - layer.mean_phi`, guarded by `av.flows`: a face that did not avalanche falls back to
   `1 - split.fine`. The two agree anyway, because a layer at `sr = 0` is never advanced and its
   `mean_phi` is still `split.fine`, which is why the drop-zero row of the table in section 6.4 reads
   `0.3500`.

`split_base(base_frac)` returns `(phi_deposited, phi_remaining)`, replaces the layer with its top
portion regridded conservatively back to `nz` cells, and satisfies
`base_frac * phi_dep + (1 - base_frac) * phi_rest == mean_phi` exactly. It short-circuits on a uniform
layer (`max - min <= 1e-15`) rather than integrating, so `Sr = 0` gives exact equality rather than
equality to `1e-16`. The requested fractions grow down the face as the travelling mass shrinks:

```
    bin  0: deposit 0.04418 of the load, split_base(0.04418) of the layer
    bin  5: deposit 0.07592 of the load, split_base(0.10608) of the layer
    bin 11: deposit 0.11400 of the load, split_base(0.69121) of the layer
    mass still travelling at the toe: 0.05092543213437646, against an overrun of
                                      0.05092543213437649, so equal to 3e-17
```

### 6.4 What comes out

`FaceSegregation` carries, per bin from crest (0) to toe:

* `coarse_profile[k]`, `fine_profile[k]`: the share of THAT SPECIES in the load which came to rest in
  bin `k`. Each sums to the share of its species that stayed on the face, so the two sums differ, and
  the difference is itself a result.
* `overrun_fraction`, `overrun_coarse_fraction`, `intensity`, `drop_m`, `face_angle_deg`, and the
  `avalanche` that was actually marched. `FaceSegregation.sr` reads through to `avalanche.sr`.
* `coarse_fraction_at(split, k)`: the local coarse fraction of the material sitting in bin `k`. This is
  the number that reaches the ledger.

The reference face, 11 m at 37 degrees, `Sr = 1.8278`, overrun `0.0509` at `0.9984` coarse:

| bin | `coarse_profile` | `fine_profile` | local coarse fraction |
|---:|---:|---:|---:|
| 0 | 0.015907 | 0.059408 | 0.126008 |
| 1 | 0.011575 | 0.071505 | 0.080173 |
| 2 | 0.009352 | 0.082466 | 0.057547 |
| 3 | 0.008483 | 0.092698 | 0.046964 |
| 4 | 0.008168 | 0.102632 | 0.041095 |
| 5 | 0.008954 | 0.111973 | 0.041283 |
| 6 | 0.011449 | 0.120393 | 0.048711 |
| 7 | 0.018975 | 0.126105 | 0.074950 |
| 8 | 0.044693 | 0.122021 | 0.164734 |
| 9 | 0.134321 | 0.083524 | 0.464077 |
| 10 | 0.263147 | 0.023920 | 0.855566 |
| 11 | 0.319714 | 0.003225 | 0.981611 |

Sums: coarse `0.854738`, fine `0.999871`. Mass closes exactly:
`0.35 * 0.854738 + 0.65 * 0.999871 = 0.949074567866 = 1 - overrun`.

Two things in that table are worth pausing on. First, the load was 35 percent coarse and the toe bin
comes out at 98 percent coarse while the middle of the face sits near 4 percent: the sorting is severe,
not marginal. Second, **bin 0 is not the finest bin.** It reads `0.126` coarse against `0.041` at bin
4. The first deposit is taken after only one marching step, so the layer has barely sieved when the
crest slice is laid down. Where the minimum sits is itself a function of the drop: swept at 37
degrees, it is bin 1 at 2 m, bin 3 at 5 m, bin 4 from 8 through 20 m, and back to bin 3 at 25 and
30 m. It is never at the crest and never deeper than a third of the way down. That is a real
prediction of the march and it is not something a monotone fitted curve could produce.

Two reported indices:

* `segregation_index(seg, split)`: coarse fraction of the toe half minus the crest half. Measures the
  slope you can see.
* `total_segregation_index(seg, split)`: the same, mass-weighted, counting the overrun as toe material,
  because it lands on the floor in front of the pile.

They diverge, and the divergence is the point. Measured at 37 degrees:

| drop | `Sr` | on-face index | total index | overrun | overrun coarse | `intensity` |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.3500 | 0.0000 |
| 1 | 0.1622 | 0.0630 | 0.0674 | 0.0008 | 0.7851 | 0.0593 |
| 2 | 0.3323 | 0.1247 | 0.1363 | 0.0030 | 0.9081 | 0.1135 |
| 5 | 0.8308 | 0.2606 | 0.3002 | 0.0152 | 0.9832 | 0.2493 |
| 8 | 1.3293 | 0.3336 | 0.3993 | 0.0323 | 0.9955 | 0.3527 |
| 11 | 1.8278 | 0.3661 | 0.4523 | 0.0509 | 0.9984 | 0.4314 |
| 15 | 2.4925 | 0.3763 | 0.4846 | 0.0753 | 0.9993 | 0.5080 |
| 20 | 3.3233 | 0.3667 | 0.4988 | 0.1024 | 0.9995 | 0.5717 |
| 25 | 4.1541 | 0.3500 | 0.5028 | 0.1247 | 0.9995 | 0.6122 |
| 30 | 4.9849 | 0.3333 | 0.5033 | 0.1424 | 0.9994 | 0.6379 |

The on-face index peaks near 15 m and then **falls**, while the total index keeps rising and flattens
near `0.503`. Above about fifteen metres the extra drop throws more coarse clear of the face than it
sorts onto it. Reporting only the on-face number would make a taller bench look like it sorted less,
which is why both exist. Note also that `Sr` itself is strictly increasing in the drop across the whole
sweep and does not saturate; the saturation in the indices is the overrun and the Peclet-limited
equilibrium, not the segregation number.

`apparent_repose_deg(seg, split, mat)` returns `(crest third, toe third)` blended repose angles. On the
reference face: `34.4660` degrees at the crest and `37.6990` at the toe. Note that this **disagrees**
with the source statement that "a segregated pile often has a slightly larger angle of repose at the
top compared to the base of the pile". It has to, for this material: `repose_coarse_deg = 40.0` exceeds
`repose_fine_deg = 34.0`, the coarse ends up at the toe, so the toe stands steeper. The function
therefore reports both ends and lets the caller compare, rather than asserting a direction the material
may not have. If a material's fines stood steeper than its coarse, the same code would reproduce the
source's direction.

---

## 7. The picture

```
                     THE FLOWING LAYER OVER THE STATIC BED
                    (one downslope station, depth section)

     free surface, z = 1, phi[31]                     shear profile
     ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~        u(z)
       O     O    o     O      O     o    O          |------------>
          O     O    O     o      O     O            |--------->
     - - - - - - - - - - - - - - - - - - - - -       |------>
        o . O . o  .  O . o  .  O .  o . O           |---->        du/dz > 0
       . : . : . :  . : . : .  : . : . : .           |-->          opens and
     :::::::::::::::::::::::::::::::::::::::         |->           closes voids
     base of the layer, z = 0, phi[0]                |
     ///////////////////////////////////////  STATIC BED  ///////////

       LARGE grains are levered up:   w_l - w = + q phi_s      (3.10)
       SMALL grains drain down:       w_s - w = - q phi_l      (3.10)
       net flux in depth:             F(phi) = - Sr phi (1 - phi)


                  THE DEPOSITION SPLIT, MARCHING DOWN THE FACE

   crest
     |\
     | \   layer starts UNIFORM at phi = fine fraction of the load
     |  \  . . . . . . . . . . . . . . . . . . . . . .  free surface
     |   \ ooooooooooooooooooooooooooooooooooooo         coarse rides on top,
     |    \ ...................................          KEEPS TRAVELLING
     |     \ :::::::::::::::::::::::::::::::::
     |      \ ::::::::::::::::::::::::::::::::          fines at the BASE
     |       \ ------------------------------           split_base(f) deposits
     |        \  |     |     |     |     |              the bottom f here
     |         \ v     v     v     v     v
     |          \##  ###  ####  #####  ######
     |    bin:   0     4  ...   9    10    11    |  beyond the toe
     |          fine-rich ------------> coarse-rich   |
     |          0.126 0.041 ... 0.464 0.856 0.982     v  overrun 0.0509
     |                (local coarse fraction)            at 0.9984 coarse
     |          bin 0 is NOT the finest: the minimum is bin 4
     |
     +--------------------------------------------------------------
      pad                                          toe        floor

   Numbers are the measured reference face: 11 m drop, 37 deg, default material.
```

---

## 8. What is anchored rather than measured

Two constants, both from the literature, neither fitted to any material this engine has seen. The
README discloses both by name and a test asserts that the disclosure and the constants stay in step
(`tests/test_readme.py::test_the_readme_names_the_anchored_constants_and_they_are_real`).

**`PERCOLATION_COEFFICIENT = 0.30`** in `bedblend/facesegregation.py`. This is `kappa` in
`q = kappa * (U/H) * d`, the ratio of the percolation velocity to the shear rate times the particle
diameter. The comment above it says the value is set so that `Sr` for the reference dump (11 m at 37
degrees, default material) "comes out around 1.8, inside the range of the worked examples in the
source"; the measured value is `1.8278`. Which source is not stated, and this document will not put a
paper's name where the code carries none, so treat the anchor as unattributed and see item 6 of
section 13. Because `Sr` is exactly linear
in `kappa`, every segregation number this engine reports scales one-for-one with it: doubling `kappa`
doubles `Sr` everywhere. **What would replace it:** a DEM run of a sheared bidisperse layer, measuring
the percolation velocity against the shear rate directly, or a laboratory characterisation test on the
real material. Neither has been run for this release. That is recorded, not assumed.

**`PECLET_DEFAULT = 12.0`** in `bedblend/segregation.py`. Gray and Chugunov fit the Peclet number
against chute experiments and report values of order ten; this sits mid-range. Section 5.3 quantifies
what it is worth: the on-face index at the reference `Sr` moves from `0.303` at `Pe = 4` to `0.481` at
`Pe = 40`. **What would replace it:** a fit of the measured shock thickness in a chute or DEM
experiment on the same material, which is the quantity `Pe` controls.

Everything else in the two modules is either derived (`L`, `U`, `H`, `q`, `Sr`), a physical constant
(`GRAVITY_M_S2 = 9.81`), a numerical parameter of the discretisation rather than of the material
(`NZ_DEFAULT = 32` depth cells and `CFL = 0.4`, both in `segregation.py`; section 4.2 says what each
buys), or an explicitly labelled operational observation (`REFERENCE_DROP_M = 11.0`,
`FAST_FLOW_ANGLE_DEG = 35.0`, `CASCADE_FLUX_M2_S = 1.0`, `LAYER_MIN_DIAMETERS = 5.0`,
`FLOW_HYSTERESIS_DEG = 4.0`, and the `0.35 + 0.65 s` deposition weights).

---

## 9. Where it fails

**Trajectory segregation is not modelled.** Coarse rock leaving the crest with enough momentum to fly,
bounce and roll past the toe is ballistic. Gray and Thornton's equation does not contain it, and this
engine does not add it. What the code does instead is split the claim in two: the **magnitude** of the
overrun stays an operational term,

```
    overrun = min(0.25, 0.30 * intensity * (1 - exp(-drop_m / (2 * REFERENCE_DROP_M))))
```

gated on `av.flows`, while its **composition** comes from the solver, because what overruns is whatever
is still travelling in the layer when it reaches the toe. That composition is a real output: `0.9984`
coarse at 11 m, `0.9995` at 20 m. Anyone reading an overrun tonnage should treat the tonnage as an
operational estimate and the assay of it as a solved quantity. The `0.25` cap is an operational
judgement; measured, it does not bind until about a 56 m drop at 45 degrees, so it is inactive
everywhere a real bench operates (`0.1899` at 30 m and 45 degrees).

**`intensity()` is a fitted curve and it still runs, but only for the overrun.** Its three terms are a
height saturation `1 - exp(-drop / 11)`, an angle ramp `(angle - 28) / 12` clipped to `[0, 1]`, and a
size-spread term `4c(1-c)` that is `0.9100` for the default material. The angle ramp **saturates at 40
degrees**, so the overrun at 40 and 45 degrees from the same drop is identical (`0.1366` at 20 m for
both), and it starts at 28 degrees, which is below the dynamic friction angle the solver actually
gates on. `intensity` no longer scales the size distribution at all. Do not read the
`FaceSegregation.intensity` field as a result; it is an input driver, and the `LoadRecord` field that
used to carry it now carries `segregation_index` for exactly this reason.

**The result depends on `n_bins`, which is not purely a reporting choice.** `n_bins` sets both the
output resolution and the number of deposition events, and more, smaller deposits sample the layer
differently. Measured on the reference face: on-face index `0.3859` at 6 bins, `0.3661` at 12,
`0.3534` at 24, `0.3421` at 48. That is an 11 percent drift and it is not converged. The shipped path
uses the default 12. Comparing indices computed at different `n_bins` is not valid.

**Plug flow, and one dimension.** The reduction assumes `u` uniform through the depth. The real layer
is sheared, which is what drives the sieving in the first place, and Gray and Thornton show that shear
in the downslope velocity advects the concentration shock into an inclined structure. That structure
is not represented here. There is no cross-slope (`y`) dependence either: a load spreading laterally as
it cascades is not modelled.

**Two species only.** `phi` is the fine fraction of a `SizeSplit`. There is no third size class, no
continuous distribution, and no dependence on the size ratio between the species, which in the real
mechanism controls how easily a fine grain fits through the coarse matrix.

**`Sr` is not monotone in the face angle near the flow threshold** (section 6.2), and the transition
between regimes is a kink, not a smooth blend, because `H = max(Q/U, h_min)` is not differentiable
there. A parameter sweep crossing the crossover will show a corner. It is physical in origin but it is
sharper in the model than it would be in a real layer.

**The flow gate is a hard threshold.** At or below the dynamic friction angle, `flows` is False and
everything, sorting and overrun both, is exactly zero. Real material near the threshold creeps. For
the default material the switch is at 33.0 degrees exactly: `flows` is False at 33.0 and True at
33.0001, with no blend between them.

**The apparent repose angles can contradict the source** (section 6.4), because their direction is set
by `repose_coarse_deg` against `repose_fine_deg` in the material rather than by the segregation model.

---

## 10. The API a caller actually touches

```python
from bedblend.segregation import (
    CFL, NZ_DEFAULT, PECLET_DEFAULT, FlowingLayer, segregation_number,
)
from bedblend.facesegregation import (
    PERCOLATION_COEFFICIENT, Avalanche, FaceSegregation,
    apparent_repose_deg, avalanche_state, intensity, segregate_face,
    segregation_index, total_segregation_index,
)
```

| name | signature | what it does |
|---|---|---|
| `FlowingLayer` | `(phi0, sr, nz=32, pe=12.0)` | the avalanching layer; index 0 is the BASE |
| `FlowingLayer.advance` | `(dx_nd) -> None` | march `dx_nd` downslope, CFL sub-stepped |
| `FlowingLayer.split_base` | `(base_frac) -> (phi_dep, phi_rest)` | deposit the bottom slice, regrid the rest |
| `FlowingLayer.mean_phi` | property | depth-averaged fine fraction, conserved by `advance` |
| `FlowingLayer.diffusivity` | property | `Dr = Sr / Pe`, zero when `Pe <= 0` or infinite |
| `segregation_number` | `(q_ms, path_m, layer_h_m, u_ms) -> float` | equation (3.19) |
| `avalanche_state` | `(drop_m, face_angle_deg, mat) -> Avalanche` | `L`, `U`, `H`, `q`, `Sr`, `flows` |
| `segregate_face` | `(*, drop_m, face_angle_deg, mat, n_bins=12) -> FaceSegregation` | the whole coupling |
| `FaceSegregation.coarse_fraction_at` | `(split, k) -> float` | local coarse fraction in bin `k` |
| `segregation_index` | `(seg, split) -> float` | toe half minus crest half, on the face only |
| `total_segregation_index` | `(seg, split) -> float` | the same, counting the overrun as toe material |
| `apparent_repose_deg` | `(seg, split, mat) -> (crest, toe)` | blended repose at the two ends |
| `intensity` | `(drop_m, face_angle_deg, mat) -> float` | the fitted driver; overrun magnitude only |

### 10.1 How it reaches the pile

`bedblend/build.py` is the only caller in the shipped path. The function is `_run_one_load`, defined
at line 393, and the segregation block runs at lines 466 to 486. `build.py` imports exactly two names,
`segregate_face` and `segregation_index`, and it is the only module in the package that imports either
for use: `__init__.py` imports from both modules purely to re-export, and `facesegregation` imports
`NZ_DEFAULT`, `FlowingLayer` and `segregation_number` from `segregation`. That is the whole call
graph. For a load that is at a face and has a down-face parameterisation (`at_face and pl.s_frac`):

```python
seg = segregate_face(drop_m=max(drop, 0.0), face_angle_deg=face_deg, mat=material)
nb = seg.n_bins
coarse = [seg.coarse_fraction_at(split, min(int(sv * nb), nb - 1)) for sv in pl.s_frac]
```

and `coarse` is handed to `model.record(..., coarse_fraction=coarse)`, which is a **per-cell list**.
`BlockModel.record` writes one value per cell into `Parcel.coarse_fraction`.

The load record also picks up `segregation_index(seg, split)`, `seg.sr`, `seg.overrun_fraction`,
`seg.overrun_coarse_fraction` and the drop. A paddock heap, or an edge load with no down-face
parameterisation, gets `[split.coarse] * len(pl.cells)`: the material's own split, because a load
tipped on flat ground has no face to sort along.

**This is the composition of the NEW parcel, not a shift applied to material already in the column.**
Nothing existing is modified. A parcel is appended to the top of each column carrying its own
`coarse_fraction`, and `BlockModel.column_coarse` reads a thickness-weighted average back out over the
whole stack. Segregation is therefore recorded as **stratigraphy**: a column near the toe of a face
accumulates coarse-rich parcels lift after lift, and the visible coarse field is the accumulation of
many independent per-load solves, not a field anyone smoothed.

One historical note that belongs here because it is the failure mode this coupling is exposed to.
`BlockModel.take_from_top` used to rebuild a split parcel by listing nine of `Parcel`'s ten fields
positionally; `coarse_fraction` is the tenth and defaults to zero, so every slice that moved was
stamped with a coarse fraction of nothing. Thickness was conserved, so the ledger-versus-terrain
assertion passed, and grade and provenance were inside the nine, so those survived. The only field
that died was the one no invariant covered, and it is the observable this entire method is measured
on: the shipped reference pile read `0.2093` against the `0.35` that was placed, with 43 cells at
exactly zero. The fix is `dataclasses.replace`, which copies every declared field. Anything that
transports a `Parcel` must do the same.

---

## 11. Tests that pin this

`tests/test_segregation.py` (7 tests) and `tests/test_material_segregation.py` (18 tests), all 25
passing at the time of writing. The ones that carry real weight:

* `test_species_mass_is_conserved_by_the_march` and `test_split_base_conserves_species_mass`: the two
  conservation identities, at `1e-9`.
* `test_concentration_stays_physical`: `phi` in `[0, 1]` under 80 steps at `Sr = 6`.
* `test_fines_drain_to_the_base`: the direction of the whole mechanism, asserted with a margin of 0.4.
* `test_zero_segregation_number_is_a_passive_tracer`: exact equality, not approximate. The negative
  control depends on it.
* `test_a_face_below_the_dynamic_friction_angle_does_not_sort_at_all`: the prediction the fitted curve
  could not make.
* `test_the_solver_is_the_thing_that_runs`: pins that the face reports the layer it marched, and that
  setting `PERCOLATION_COEFFICIENT` to zero flattens the profile. This is the test whose absence let a
  documented solver sit uncalled for several releases.
* `test_a_taller_face_segregates_more`: asserted metre by metre on the total index, not at two
  endpoints, with the on-face fall above 15 m explicitly allowed and explained.
* `test_coarse_ends_up_at_the_toe_and_fines_near_the_crest`: one of its assertions once read
  `... < ... or True`, so it asserted nothing while the comparison it hid was written backwards.

---

## 12. References

Cited by the source code:

* Gray, J.M.N.T. and Thornton, A.R. (2005), *A theory for particle size segregation in shallow granular
  free-surface flows*, Proceedings of the Royal Society A 461(2057), 1447-1473.
  doi:10.1098/rspa.2004.1420
* Gray, J.M.N.T. and Chugunov, V.A. (2006), *Particle-size segregation and diffusive remixing in
  shallow granular avalanches*, Journal of Fluid Mechanics 569, 365-398.
  doi:10.1017/S0022112006002977
* Young, A. and Rogers, W.P. (2021), *Modelling Large Heaped Fill Stockpiles Using FMS Data*,
  Minerals 11(6), 636. doi:10.3390/min11060636. The operational statements quoted in
  `facesegregation`: the cascade aggregating at the bottom of the dumping area, the overrun past the
  bench floor, the 10 to 12 m height guidance, and the 35 to 40 degree fast-flow band. The title
  above is the registered one; most of this repository calls this paper *Modelling of pre-crusher
  stockpiles*, which is wrong. See item 7 of section 13.

Background, **not cited anywhere in this engine's source**, given here because a reader coming to the
method will want them:

* Savage, S.B. and Lun, C.K.K. (1988), *Particle size segregation in inclined chute flow of dry
  cohesionless granular solids*, Journal of Fluid Mechanics 189, 311-335.
  doi:10.1017/S002211208800103X. The first quantitative theory of kinetic sieving, section 2.1.
* Gray, J.M.N.T. (2018), *Particle Segregation in Dense Granular Flows*, Annual Review of Fluid
  Mechanics 50, 407-433. doi:10.1146/annurev-fluid-122316-045201. The review of the field.

All five DOIs above were resolved against Crossref while writing this document, and the titles,
volumes and page ranges are the registered metadata rather than a recollection.

---

## 13. Disagreements found while writing this, and not silently fixed

This document did not modify any source file. Seven claims recorded in comments, docstrings and
neighbouring documents did not reproduce as written, and a maintainer should know which.

1. **The 2006 paper is given the 2005 paper's title in the source.** The comment above
   `PECLET_DEFAULT` in `bedblend/segregation.py` reads: Gray and Chugunov 2006, "A theory for particle
   size segregation in shallow granular free-surface flows". The registered title of
   doi:10.1017/S0022112006002977 is *Particle-size segregation and diffusive remixing in shallow
   granular avalanches*; the string quoted is the title of the 2005 Proc. R. Soc. A paper. The DOI in
   the comment is correct, and the README already has the right title, so this is a stale string in one
   comment rather than a wrong citation.

2. **The saturation pair.** The same comment states the on-face sorting index was "0.5162 at
   `Sr = 1.5` and 0.5162 at `Sr = 15`" with remixing off. Reproducing that measurement here gives
   `0.512605` at `Sr = 1.5` and `0.516195` at `Sr = 15`. The second figure matches to four decimals;
   the first is `0.5126`, not `0.5162`. The claim the pair exists to support is unaffected and if
   anything is understated: the operational band `Sr = 1.8` to `4.0` spans `0.0019` with remixing off
   against `0.0764` with it on. Protocols tried that do not recover `0.5162` at `Sr = 1.5`:
   `nz = 16` (`0.4858`), `nz = 64` (`0.5207`), 24 bins (`0.5051`), with the 11 m overrun applied
   (`0.4577`).

3. **The tall-face `Sr` row.** The docstring of `bedblend/facesegregation.py` records, at an 11 m drop,
   "1.928, 1.838, 1.721, 1.564" for 35, 37, 40 and 45 degrees. The code now returns `1.9178`, `1.8278`,
   `1.7113`, `1.5556`, uniformly 0.53 to 0.56 percent lower. The ratio of new to recorded is near
   constant across all four angles (`0.9947`, `0.9945`, `0.9944`, `0.9947`), which points at a slightly
   different constant at the time of measurement rather than at a changed model. The 0.5 m row
   ("0.022, 0.041, 0.062, 0.071") reproduces exactly to the quoted precision
   (`0.0223`, `0.0406`, `0.0621`, `0.0707`), and the reversal between the rows, which is the whole
   point, is unchanged.

4. **The 42 / 58 percent regime split.** The docstring cites 16762 loads with a median drop of 1.38 m
   from the consuming product's shipped scenarios. Those scenarios are not in this repository and the
   figure could not be checked here. The crossover it rests on, 1.02 m at 37 degrees, reproduces to
   `1.0244 m`.

5. **The cost of the march.** The module docstring of `bedblend/segregation.py` says the solver is "a
   few hundred floating-point operations per avalanche generation" and that the continuum model is
   "therefore cheaper than the fitted parametric curve it might have been replaced with". Counted on
   the reference face by wrapping `_godunov_flux` and `FlowingLayer.advance`: 780 sub-steps, 24180
   flux evaluations, 24960 cell updates, about 9 ms per face in CPython. That is hundreds of thousands
   of operations, not hundreds, and it is far more than `intensity()`, which is three closed-form
   terms. The conclusion the paragraph draws, that nothing about the cost argues against running the
   real solver per load, survives untouched; only its arithmetic does not. Section 4.2 carries the
   measured figures.

6. **The percolation anchor names no source.** The comment above `PERCOLATION_COEFFICIENT` says the
   value is chosen so `Sr` for the reference dump lands "inside the range of the worked examples in
   the source", without saying which source. The docstring of `facesegregation` quotes only Young and
   Rogers, who report no segregation numbers at all, so the intended reference is presumably Gray and
   Thornton, but the code does not say so and this document does not supply the citation on its
   behalf. Naming the paper, the table and the example range in that comment would close it.

7. **The Young and Rogers title is wrong throughout the repository, and this is the widest of the
   seven.** Resolved against Crossref, doi:10.3390/min11060636 is *Modelling Large Heaped Fill
   Stockpiles Using FMS Data*, Minerals 11(6), 636, 2021, by Aaron Young and William Pratt Rogers.
   Nine bibliography entries here give it instead as *Modelling of pre-crusher stockpiles*:
   `README.md`, `docs/README.md`, the three guides under `docs/guides/`,
   `docs/methods/01_terrain-and-trafficability.md`, `docs/methods/02_dump-plan-and-tips.md`,
   `docs/methods/08_reclaim.md`, and the first version of this page. Nothing in the code is affected.
   The DOI, journal, volume, issue and article number are right in every one of the nine;
   `docs/architecture/01_overview.md` cites the paper without a title; and the module docstrings that
   cite it as "Young and Rogers, Minerals 2021, 11, 636" plus a section or figure number never quote a
   title either. Section 12 of this page is now corrected; the other eight are not, because this
   document does not edit other files.
