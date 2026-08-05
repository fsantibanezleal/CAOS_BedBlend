# 02. Determinism: one 32-bit xorshift, one stochastic choice

A `bedblend` run is a pure function of its parameters and its seed. This document says exactly what that
means, what it costs, what it does not cover, and demonstrates it with output from runs made while
writing the document.

---

## 1. The generator

There are two copies of the same generator in the package, and they are byte-identical in behaviour.

`Xorshift` in `bedblend/stream.py` is the public one, exported from the package root. It adds a
Box-Muller `normal()` on top of the uniform draw:

```python
class Xorshift:
    """A seeded xorshift32, reproducible bit for bit against a browser implementation.

    Deliberately not ``random``: the live engine has to produce the identical sequence, and a
    language's built-in generator is not a portable contract.
    """

    __slots__ = ("_spare", "state")

    def __init__(self, seed: int) -> None:
        self.state = (seed | 1) & 0xFFFFFFFF
        self._spare: float | None = None

    def uniform(self) -> float:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF
        return self.state / 0x100000000
```

`_Rand` in `bedblend/build.py` is the private one the build loop uses. It is `Xorshift` without the
normal deviate and with `next()` in place of `uniform()`. Its docstring repeats the reason: "Deliberately
not `random`: the browser mirror of this engine has to produce the identical sequence, and a language's
built-in generator is not a portable contract."

The two are the same stream. Measured, on seed 20260801:

```
first 100000 draws identical, _Rand vs Xorshift: True
```

That duplication is a real, if small, maintenance hazard: a change to one must be mirrored in the other,
and nothing in the package asserts that they agree. The check above is three lines and is not currently
in the test suite.

### The recurrence

```
    x_0     = (seed OR 1)  AND  0xFFFFFFFF

    x_{n+1} = T3(T2(T1(x_n)))                        all arithmetic modulo 2^32

      T1(x) = (x XOR (x << 13)) AND 0xFFFFFFFF        left shift, truncated to 32 bits
      T2(x) =  x XOR (x >> 17)                        logical right shift, no truncation needed
      T3(x) = (x XOR (x <<  5)) AND 0xFFFFFFFF        left shift, truncated to 32 bits

    draw_n  = x_n / 2^32                              a double in [0, 1)

    seed              the caller's integer seed; build() defaults to 20260801
    x_n               the 32-bit generator state after n draws
    0xFFFFFFFF        4294967295, the 32-bit mask
    2^32              4294967296, written 0x100000000 in the source
```

This is Marsaglia's xorshift with the shift triple (13, 17, 5). The shift triple is not cited to a paper
anywhere in the source, and this document does not invent a citation for it.

### What each piece of the recurrence buys

**`seed | 1` guarantees a non-zero state.** Zero is the fixed point of every xorshift: all three
operations map 0 to 0, so a zero state produces an endless run of zeros. Forcing the low bit removes it.
The cost is that seeds come in pairs. Measured:

```
seed 0 first 4: [6.295e-05, 0.015747428, 0.616404102, 0.071618635]
seed 1 first 4: [6.295e-05, 0.015747428, 0.616404102, 0.071618635]
seed 2 first 4: [0.000188851, 0.047005296, 0.704413431, 0.444536226]
seed 3 first 4: [0.000188851, 0.047005296, 0.704413431, 0.444536226]
```

An even seed and the odd seed above it are the same run. If a caller sweeps seeds `0..N` expecting `N+1`
distinct runs, they get `(N+1)/2`. Nothing warns about this.

**The two `& 0xFFFFFFFF` masks are the portability contract, not an optimisation.** Python integers are
unbounded, so `x << 13` grows without limit; JavaScript's `<<` is defined on 32-bit signed integers and
truncates on its own. Masking after each left shift is what makes the Python and the JavaScript
implementations agree. The right shift needs no mask because `>>` on a value already inside 32 bits
cannot leave it. Measured over 200000 consecutive draws from seed 20260801:

```
min state 7530   max state 4294959696   bound 4294967295
all in [0, 2**32): True
state ever zero:  False
```

**`state / 0x100000000` is an exact division.** `2^32` is a power of two, so the quotient is exactly
representable as a double and every draw is an exact multiple of `2^-32`. Verified: over the first draw
of seeds 1 through 4999, `(x * 0x100000000).is_integer()` holds for every value. Any language whose
doubles are IEEE-754 binary64 reproduces this mapping bit for bit; it is the one arithmetic step in the
generator with no rounding at all.

### The reference sequence, seed 20260801

Useful as a fixture when checking a port. States and draws, in order:

```
state:  476574151  2847112680  130925327  1243867129  3980873335  2512136787  238946088  364341477
draw :  0.11096106632612646
        0.6628950778394938
        0.030483428156003356
        0.2896103842649609
        0.9268693008925766
        0.584902425063774
        0.055633971467614174
        0.08482986059971154
```

---

## 2. Why not `random`, and why not numpy

Three separate reasons, all of them structural.

**A language's built-in generator is not a portable contract.** CPython's `random` is a Mersenne
Twister with a specific seeding routine and a specific way of consuming words to build a double.
JavaScript's `Math.random` has no specified algorithm at all. Neither can be relied on to produce the
same stream in a browser mirror of this engine, and reproducing the browser is the stated requirement:
the package docstring says the core "has to be reproducible bit for bit against a browser implementation
of the same equations".

**numpy would give away the dependency-free core.** The package docstring states it as a design
constraint: "The core is dependency-free by design, plain Python floats and lists rather than numpy,
because it has to be reproducible bit for bit against a browser implementation of the same equations and
a core with no dependencies installs anywhere in seconds." A numpy `Generator` also has its own
versioning contract to track across releases; a nine-line recurrence has none.

**A generator that is only ever asked for one draw per load does not need to be fast.** The reference
200-load build consumes 125 draws in total. There is nothing to optimise.

The trade is real and should be stated: xorshift32 has a period of `2^32 - 1` and is a weak generator by
any modern statistical standard. It would be the wrong choice for Monte Carlo. It is used here for a
single categorical draw with three outcomes, sampled at most once per truck load, which is a load it
carries comfortably.

---

## 3. What "reproducible bit for bit against a browser implementation" actually requires

The generator is the easy half. Five conditions have to hold together, and only the first three are
about the generator at all.

1. **The state transition must be identical.** Both left shifts masked to 32 bits, the right shift
   logical rather than arithmetic, and the shift triple `(13, 17, 5)` in that order. In JavaScript the
   `>>>` operator is required, not `>>`; `>>` is arithmetic and sign-extends.
2. **The seeding must be identical.** `(seed | 1) & 0xFFFFFFFF`, applied before the first draw.
3. **The scaling must be identical.** `state / 2^32`, with `state` interpreted as unsigned. In
   JavaScript the masked value must be read through `>>> 0` before dividing, or a state above `2^31`
   comes out negative.
4. **The number of draws must match, and so must their order.** This is where a port usually diverges.
   `_Rand.next()` is called at exactly one site in the whole build loop, and it is called
   unconditionally at that site (see section 4). Any port that skips the draw when the answer turns out
   not to need it desynchronises the stream from that load onward, and every subsequent profile is
   wrong even though the generator is correct.
5. **Everything else must be IEEE-754 binary64 with the same operation order.** The generator is exact,
   but the terrain, the relaxation, the segregation solver and the route costs are all floating point.
   Two implementations agree only if they perform the same operations in the same order. Python and
   JavaScript both use binary64 for `float` and `Number`, so this is achievable, but it is a constraint
   on the whole engine and not on the generator.

Condition 5 has a corollary worth writing down: **no part of the engine may depend on the iteration order
of a set.** Reading the code, sets are used for membership testing (`queued`, `dug`, `crest_set`,
`seen`) and as seed collections that are immediately pushed onto a heap of `(-z, cell)` tuples, where the
unique cell index makes the ordering total and the pop sequence therefore fixed. Dictionaries whose
iteration order matters (`weights` in `bedblend/dump.py`, `prov` in `bedblend/reclaim.py`) are keyed by
integers and populated in a deterministic order, and CPython dictionaries iterate in insertion order.

That reading was checked empirically across separate processes with different hash seeds, which is the
condition that would expose any accidental dependence. The configuration, stated in full so the block
can be re-run: a 48 by 48 pad at 2.5 m cells, one 60 m by 60 m area with one 8 m bench,
`row_spacing_m` 10, `tip_spacing_m` 8, `loads_per_dozer_pass` 40, access at `(60, 60)`, four CAT 793F
trucks with the shovel at `(110, 110)`, 120 payloads, `repose_deg` 37, the default seed.

```
PYTHONHASHSEED=0          placed=120 surface=a92529c18bf8274e profiles=[('comet', 20), ('oval', 54), ('paddock', 29), ('rectangular', 17)]
PYTHONHASHSEED=1          placed=120 surface=a92529c18bf8274e profiles=[('comet', 20), ('oval', 54), ('paddock', 29), ('rectangular', 17)]
PYTHONHASHSEED=12345      placed=120 surface=a92529c18bf8274e profiles=[('comet', 20), ('oval', 54), ('paddock', 29), ('rectangular', 17)]
PYTHONHASHSEED=987654321  placed=120 surface=a92529c18bf8274e profiles=[('comet', 20), ('oval', 54), ('paddock', 29), ('rectangular', 17)]
```

The surface hash is SHA-256 over `repr()` of every cell elevation, truncated to 16 hex characters.
Four hash seeds, one hash.

No browser implementation was available to test against while writing this document, so the claim that
the two agree is **not** verified here. What is verified is that the Python side satisfies conditions 1
through 4 and shows no hash-order dependence.

---

## 4. The one stochastic choice

`rng.next()` appears once in `bedblend/build.py`:

```python
profile = classify(d_crest, truck.spec, rand=rng.next())
```

That is the whole of it. Nothing else in the build consumes randomness: not the tip lattice, not the
routing, not the dozer cadence, not the relaxation, not the segregation solver, not the payload stream
(which the caller supplies).

### What the draw decides

`classify` in `bedblend/dump.py` maps the draw onto the three at-crest profiles by their measured
counts from the 28 UAV-surveyed dumps:

```
    profile        count   cumulative threshold
    oval              12   0.545455
    comet              6   0.818182
    rectangular        4   1.000000

    the first profile whose cumulative threshold exceeds `rand` is returned
```

Verified against the function:

```
draw 0.00 at the crest: oval
draw 0.60 at the crest: comet
draw 0.90 at the crest: rectangular
far from the crest (20 m > 12.9 m): sloughed_heap
```

And over 200000 draws from seed 20260801:

```
oval        109256  (0.5463)
comet        54508  (0.2725)
rectangular  36236  (0.1812)
```

against the design frequencies 0.545455, 0.272727, 0.181818.

### Why it is stochastic at all

Because the source says the mechanism is unknown. From the `bedblend/dump.py` module docstring:

> "The paper is explicit that it could not say which of comet, oval or rectangular forms from position
> alone, and that its hypothesis about uneven tray loading was never tested: 'the exact interplay between
> how the trucks were loaded and the resulting dump profiles remains unclear, and no information on truck
> loading was gathered during this study'. So the choice among the three is drawn from their measured
> frequencies, seeded, rather than being predicted from a mechanism this model does not have. The
> frequencies are real; the selection is admittedly stochastic."

This is the correct shape for the uncertainty. The distribution is measured; the per-load draw from it is
not a model of anything and is labelled as such.

### The draw is consumed even when it is unused

`rand` is evaluated before the call, so the state advances on every at-face load. But `classify` returns
`SLOUGHED_HEAP` without reading `rand` at all when the truck is further than one body length from the
crest:

```python
if distance_to_crest_m > slough_truck_lengths * truck.body_length_m:
    return DumpProfile.SLOUGHED_HEAP
```

So on the reference run there were 125 at-face loads, 125 draws, and one of those draws was thrown away.
Measured:

```
placed by phase: paddock 75, edge 125
placed with a cascade profile (at_face was True): 125
rng draws consumed: 125
profile census: {'paddock': 75, 'oval': 77, 'comet': 25, 'rectangular': 22, 'sloughed_heap': 1}
```

A port that moves the draw inside the `if` branch will produce the same first sloughed heap and then
diverge on everything after it. This is condition 4 of section 3, made concrete.

### The stream generator's own draws

`bedblend/stream.py` uses the same `Xorshift` for `dig_sequence(seed=...)` and
`payloads_from(seed=...)`. `dig_sequence` seeds the generator directly; `payloads_from` mixes the seed
first, so passing one seed to both does not run the two functions off the same stream:

```python
rng = Xorshift(seed)               # dig_sequence
rng = Xorshift(seed ^ 0x5EED)      # payloads_from; 0x5EED is 24301
```

The source states no reason for the mix, so the intent above is inferred from what it does, not quoted.

`normal()` is Box-Muller with the second deviate cached, so the number of `uniform()` calls per
`normal()` alternates. Measured over six consecutive calls:

```
uniform() calls per normal(), 6 in a row: [2, 0, 2, 0, 2, 0]
```

That cache is stream state. A port must carry `_spare` across calls, and a caller that interleaves
`normal()` and `uniform()` on the same instance gets a different sequence than one that does not. Nothing
in the package does interleave them, but nothing prevents it either.

---

## 5. The demonstration

Configuration: a 64 by 64 pad at 2.5 m cells, one 90 m by 90 m area with one 8 m bench,
`row_spacing_m` 10, `tip_spacing_m` 8, `loads_per_dozer_pass` 40, access at `(90, 90)`, four CAT 793F
trucks with the shovel at `(140, 140)`, 200 payloads, `repose_deg` 37. Only the seed changes between
runs. `surface_sha256_16` is SHA-256 over `repr()` of every one of the 4096 cell elevations, truncated
to 16 hex characters.

```
build wall time: 7.4, 9.8, 9.8 s over three consecutive runs on the development machine

run A  seed=20260801  {'placed': 200, 'refused': 0, 'volume_m3': 24315.78947368421,
                       'peak_m': 4.596534773551165,
                       'profiles': {'paddock': 75, 'oval': 77, 'comet': 25,
                                    'rectangular': 22, 'sloughed_heap': 1},
                       'surface_sha256_16': 'f5bd205344835ac9'}
run B  seed=20260801  {'placed': 200, 'refused': 0, 'volume_m3': 24315.78947368421,
                       'peak_m': 4.596534773551165,
                       'profiles': {'paddock': 75, 'oval': 77, 'comet': 25,
                                    'rectangular': 22, 'sloughed_heap': 1},
                       'surface_sha256_16': 'f5bd205344835ac9'}
run C  seed=7         {'placed': 200, 'refused': 0, 'volume_m3': 24315.78947368421,
                       'peak_m': 6.164119010416274,
                       'profiles': {'paddock': 75, 'oval': 67, 'rectangular': 16, 'comet': 42},
                       'surface_sha256_16': '309cedb5734e51dd'}

A == B  surface identical:            True
A == B  profile sequence identical:   True
A == B  placed/refused identical:     True
A == B  grade field identical:        True
A == B  coarse field identical:       True

A == C  surface identical:            False
A == C  profile sequence identical:   False
A == C  placed/refused identical:     True
first profile that differs, index:    76
profiles differing over 200 common placed loads: 78
max |dz| A vs C: 3.332264 m over 4096 cells; cells differing: 1828
volume A 24315.789474  C 24315.789474  difference 0.000000000 m3
```

Read the three lines that matter.

**Same seed, identical everything.** Not "close": the elevation list compares equal element by element,
and so do the per-column grade field and the per-column coarse fraction field, which are the two outputs
downstream analysis consumes. The comparison is `==` on `list[float]`, not a tolerance.

**Different seed, first divergence at placed load 76.** Placed loads 0 through 74 are the paddock
campaign, which consumes no draws, so those 75 entries are identical by construction. Placed load 75 is
the first at-face load, and it came out the same profile in both runs by chance; index 76 is the first
that actually differs. Over the 125 at-face loads, 78 differ, a disagreement rate of 62.4 percent
against the 59.5 percent that two independent draws from these frequencies would give
(`1 - sum(p_i^2)` with `p = (0.545455, 0.272727, 0.181818)`).

**Different seed, identical mass.** `24315.789474 m3` for both, to the last printed digit, and both equal
`200 x 121.578947 m3`. The seed changes the shape and not the quantity: the peak moves from 4.60 m to
6.16 m and 1828 of 4096 cells differ by up to 3.33 m, while the total volume difference is exactly zero.

That last result is the cleanest statement of what the seed does. It selects among three deposit shapes
of equal volume. It does not create or destroy material, it does not change which loads are placed or
refused, and it does not touch the incoming stream.

The wall time is the one number in this block that is a property of the machine rather than of the
engine, and it moved by a third across three consecutive runs of the identical build. Treat it as an
order of magnitude, not a measurement. Everything else here is exact and reproduces run to run.

### Reproducing it

The script that produced the block above is not kept in the repository. It is short enough to restate:
build twice with the same seed and once with a different one using the configuration named at the top of
this section, then compare `terrain.z`, `model.grade_field()`, `model.coarse_field()` and
`[r.placed for r in res.loads]` with `==`, and hash `terrain.z` for a one-line summary. A build of this
size took between seven and ten seconds on the machine this was written on.

---

## 6. What is not covered by the seed

* **The incoming stream.** `payloads` is a caller argument. Two builds with the same seed and different
  payload lists differ.
* **Floating-point reproducibility across platforms.** Not tested here. Nothing in the engine uses
  `math.fsum`, extended precision, or fused multiply-add, and no operation order depends on data, but no
  cross-platform comparison was run for this document.
* **`bedblend.__version__`.** It is read from installed packaging metadata, so it can disagree with the
  source tree. See `docs/architecture/01_overview.md`, section 8.
* **The browser mirror.** No such implementation was run while writing this document, so the bit-for-bit
  agreement is a design property that is satisfied on the Python side and unverified across the two.

---

## 7. References

* Xorshift generators are due to Marsaglia. **The specific shift triple (13, 17, 5) is not attributed to
  any source in this package**, and no citation is invented for it here.
* Box, G.E.P. and Muller, M.E. The polar-form transform used in `Xorshift.normal` is named in the
  docstring as "Box-Muller" without a citation. **No reference for it appears in the source**, and none
  is added here.
* Young, A. and Rogers, W.P. (2022). *Mining* 2(1). doi:10.3390/mining2010006. The source of the profile
  counts (12 oval, 6 comet, 4 rectangular, 6 sloughed heap across 28 dumps) that the single stochastic
  draw samples, and the source of the statement that the choice among the first three could not be
  predicted from position.
