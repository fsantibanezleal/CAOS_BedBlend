# bedblend

[![CI](https://img.shields.io/github/actions/workflow/status/fsantibanezleal/CAOS_BedBlend/ci.yml?branch=main&label=CI)](https://github.com/fsantibanezleal/CAOS_BedBlend/actions)
[![License](https://img.shields.io/github/license/fsantibanezleal/CAOS_BedBlend)](LICENSE)
[![Version](https://img.shields.io/github/v/tag/fsantibanezleal/CAOS_BedBlend?label=version&sort=semver)](https://github.com/fsantibanezleal/CAOS_BedBlend/tags)

A bed-blending stockpile engine: repose-angle deposition, Gray-Thornton kinetic size segregation, a
per-cell lot ledger with provenance, and the blending metrics.

```bash
pip install bedblend
```

## The problem it answers

A blending bed is the cheapest variance reduction available in a mineral processing plant. Material is
stacked in many thin layers and reclaimed across all of them at once, so the cut delivered to the mill
is an average over the layers the reclaimer crosses rather than over whichever truck arrived last.

The question a planner actually has is how much variance a given pile removes, and the honest answer
is often "less than you think". The layer count is the dominant term, and it is set by the reclaim
geometry rather than by the stacking geometry: a bridge reclaimer rakes the whole cross-section and
crosses every layer at a station, a front-end loader takes a shallow bite and crosses a handful. This
engine computes that, on a real pile, with the provenance kept.

```python
import bedblend as bb

pad = bb.PadSpec(nx=24, ny=16, cell_m=3.0)
dumps = bb.generate_stream(n_dumps=120, seed=7)          # a correlated grade stream, not white noise
cfg = bb.RunConfig(pad=pad, stacking="chevron", reclaim="fullface",
                   n_passes=12, sr=1.0, cut_tonnes=600.0)

result = bb.simulate(cfg, dumps)
m = result.metrics
print(f"{len(result.cuts)} cuts, VRR {m.vrr:.3f} against the 1/N ideal {m.vrr_ideal:.3f}")
print(f"{m.n_layers_mean:.1f} layers per cut")
```

```
43 cuts, VRR 0.093 against the 1/N ideal 0.046
21.9 layers per cut
```

The ratio is variance OUT over variance IN, on a tonnage base, so **lower is better** and `1.0` means
the bed did nothing. It is reported next to the `1/N` bound because the gap between them is the
interesting quantity: it is what the pile fails to recover, and it is driven by the autocorrelation of
the incoming stream. Layers only average if they are independent.

## What is in it

| Module | What it computes |
|---|---|
| `heightfield` | Mass-conserving relaxation to an imposed angle of repose. A priority cascade with a water-filling toppling rule; the ordered transfers ARE the avalanche path. |
| `segregation` | Gray-Thornton kinetic sieving in the flowing layer, `dphi/dt + ... - Sr d/dz[phi(1-phi)] = 0`, solved with a Godunov flux so the concentration shocks survive. `Sr = 0` degenerates to a passive tracer, which is the negative control. |
| `pile` | The pad, the per-cell lot stacks, and four reclaim geometries (full face, bucket wheel, end, loader). Every reclaimed tonne carries provenance fractions back to the truck loads that made it. |
| `stacking` | Five build geometries: chevron, windrow, cone shell, chevcon, strata. |
| `blending` | Tonnage-weighted variance, VRR, the `1/N` bound, mixing effect, experimental variograms with a spherical fit. |
| `rtd` | Residence-time distribution and its FIFO/LIFO character. |
| `stream` | A geostatistically correlated truck stream, generated exactly from a one-step recursion. |

## What it does NOT claim

* **The angle of repose is imposed, not emergent.** This is a continuum height-field model, not DEM. It
  reproduces the geometry a given repose angle produces; it does not predict that angle from particle
  properties.
* **The segregation number `Sr` is a parameter, not a measurement.** Gray and Thornton's non-dimensional
  group is supplied, and the honest use is to sweep it and report the sensitivity.
* **It is not a blending optimizer.** It evaluates a pile; it does not choose one.
* **It is not plant metal accounting.** It stops at the reclaimed stream.

## Determinism

A run is a pure function of `(parameters, seed)`. The stream generator is a 32-bit xorshift feeding
Box-Muller, written out explicitly rather than using `random` or numpy, so the same stream can be
reproduced bit for bit by an implementation in another language. That is what makes an in-browser
mirror of this engine checkable against it.

## References

The equations and their provenance:

* Gray, J.M.N.T. and Thornton, A.R. (2005), *A theory for particle size segregation in shallow granular
  free-surface flows*, Proc. R. Soc. A 461, 1447-1473. [doi:10.1098/rspa.2004.1420](https://doi.org/10.1098/rspa.2004.1420)
* Bak, P., Tang, C. and Wiesenfeld, K. (1987), *Self-organized criticality: an explanation of 1/f noise*,
  Phys. Rev. Lett. 59, 381. [doi:10.1103/PhysRevLett.59.381](https://doi.org/10.1103/PhysRevLett.59.381)
* Gerstner, W. and Schramm, G. — see `docs/` for the blending-bed literature and the measured mixing
  effects the `1/N` comparison is calibrated against.
* Kumral, M. (2006), *Bed blending design incorporating multiple regression modelling and genetic
  algorithms*, J. S. Afr. Inst. Min. Metall. 106, 229-236.

## Licence

MIT. See [LICENSE](LICENSE).
