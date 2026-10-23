## Summary

What does this PR change, and why?

## Scope check

- [ ] Domain rules remain separate from model/database adapters and frontend transport.
- [ ] The README "What it does not do" boundaries still hold (or the change is explicitly justified).
- [ ] No credentials, local databases, or generated evaluation artifacts are committed.
- [ ] `README.md` and `README.zh-CN.md` are updated together if API/configuration docs changed.
- [ ] Dependency changes go through `requirements*.txt` / `package-lock.json`.

## Tests

How was this verified? Include the commands run and their outcome.

- [ ] `python -X utf8 -m pytest -q -p no:cacheprovider` passes.
- [ ] New/changed behavior has failure-path test coverage.
- [ ] C++ parser touched: `ctest --test-dir build --output-on-failure` passes.
- [ ] Frontend touched: `npm test`, `npm run typecheck`, `npm run build` pass.
