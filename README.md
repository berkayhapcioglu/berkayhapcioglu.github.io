# King Legends: Survivor web pages

Privacy policy (EN/TR), support page and app-ads.txt for the King Legends: Survivor iOS game, served by GitHub Pages at https://berkayhapcioglu.github.io/kinglegends/.

## Remote config (kinglegends/rc.json)

Every build of the game, 1.0 included, reads `kinglegends/rc.json` at launch. A wrong value reaches every player on their next launch, so check the file before every write:

```
python3 tools/rc_check.py            # exits 1 on errors: do not publish
```

- `tools/rc_check.py`: the checker (types, ranges, `targets`, `news`, store links). Errors block, warnings are for review.
- `tools/rc-schema.json`: field names, types, defaults and ranges taken from the game code. Regenerate it from the game repo after new remote keys are added: `python3 Tools/rc_schema.py <path to>/tools/rc-schema.json`. A stale schema only turns new keys into warnings.
- `.github/workflows/rc-check.yml`: runs the checker and its tests on every change. It reports, it never blocks Pages.
- Top-level keys reach every build. `targets` (per version, platform, channel, date) and `news` are read only by game code 25 and later. Details: `Docs/remote-config-safety.md` in the game repo.
