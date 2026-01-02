# Overview

<!-- brief description of what the PR does if it's not clear from the PR title -->

# Required checks before merge

- [ ] Branch is based on and up-to-date with `main`
- [ ] PR has a clear title and/or brief description
- [ ] PR builders passed
- [ ] No red flags from coderabbit.ai
- [ ] New features, bugfixes etc are tracked in `CHANGELOG.md`
- [ ] Package version bumped in `pyproject.toml`
- [ ] `add_vendor.md` is up-to-date
- [ ] Alembic migrations are provided (or not needed)
    - [ ] Tested on SQLite
    - [ ] Tested on PostgreSQL
- [ ] `sc-crawler pull` was tested on all vendors and records
- [ ] `mkdocs` renders correctly and has been checked for new functions/methods
- [ ] Human approval
