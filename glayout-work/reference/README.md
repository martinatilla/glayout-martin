# Reference layouts

GDS kept on purpose because no current script reproduces them. Everything a script in
`glayout-work/` can regenerate goes to `glayout-work/out/<script>/` (gitignored) instead.
Add one row per file: what it is, how it was built, why it is kept.

| File | What | Built with | Why kept |
|------|------|------------|----------|
| `cmirror_1.gds` | `current_mirror(gf180, numcols=1)` (AB), shared gate rail | `generated_cmirror.py` at `9ec41c0` | "after" side of the shared-gate change ([shared-gate-changes.md](../../shared-gate-changes.md)) |
| `cmirror_1_old.gds` | The same cell before the shared-gate change (two gate rails shorted) | `generated_cmirror.py` at `c80acbf` | "before" side of that comparison |
