# Changelog

All notable changes to `bedblend` are recorded here. The format follows Keep a Changelog, newest on
top, and the versions follow `X.XX.XXX` (the manifest carries the semver form with the padding
dropped).

## [0.01.000] - 2026-08-01

First release. The engine was extracted from the StockTwin product repository, where it had been
written as an internal package. An internal package advertises a library nobody can install, so the
engine now lives in its own repository and StockTwin consumes it as a pinned dependency, which is the
same shape as `milldem` for ChargeCascade and `minehaulsim` for DispatchLab.

### Added

- `heightfield`: mass-conserving relaxation to an imposed angle of repose. A priority cascade with a
  water-filling toppling rule, so a cell sheds to several downslope neighbours at once and the
  ordered transfers are the avalanche path the segregation solver then marches along.
- `segregation`: the Gray-Thornton kinetic sieving equation in the flowing layer, solved with a
  Godunov flux on a convex flux function so the concentration shocks are preserved rather than
  smeared. `Sr = 0` degenerates exactly to a passive tracer through the same code path, which is what
  makes it usable as a negative control.
- `pile`: the pad, the per-cell lot stacks, and the four reclaim geometries (full face, bucket wheel,
  end, loader) parameterised by the two numbers that decide the layer count, engaged width and reach.
  Provenance fractions on every cut sum to one.
- `stacking`: chevron, windrow, cone shell, chevcon and strata.
- `blending`: tonnage-weighted variance, the variance reduction ratio, the `1/N` independent-layer
  bound, the mixing effect, and experimental variograms with a spherical fit.
- `rtd`: residence-time distribution, its dimensionless variance, and its FIFO/LIFO character.
- `stream`: a correlated truck stream from an exact one-step recursion, with a 32-bit xorshift and
  Box-Muller generator written out explicitly so another language can reproduce it bit for bit.
- 30 tests covering mass conservation, the repose bound, cascade ordering, species-mass conservation,
  the exact `Sr = 0` tracer identity, provenance summing to one across all four reclaim geometries,
  the VRR direction pinned against Loubser and de Korte's published table, and determinism.

### Notes

- The core has no dependencies on purpose. It is plain Python floats and lists, which keeps it
  installable anywhere in seconds and reproducible against a browser implementation.
- `RunConfig.case_id` carries the consumer's label through to the result. The engine never interprets
  it.
