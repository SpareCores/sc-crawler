# Overview

<!-- brief description of what the PR does if it's not clear from the PR title -->

# Required checks before merge

Mark all tasks that were completed with a checkmark. Unrelated tasks can be left unchecked.

PR status:

- [ ] Branch is based on and up-to-date with `main`
- [ ] PR has a clear title and/or brief description
- [ ] PR builders passed
- [ ] No red flags from coderabbit.ai
- [ ] Pinged code owners for human review after all other major items in this list are completed
- [ ] Human approval

Versioning, changelog, and documentation:

- [ ] New features, bugfixes etc are tracked in `CHANGELOG.md`
- [ ] Package version bumped in `pyproject.toml`
- [ ] `add_vendor.md` is up-to-date (after schema changes or new learnings that generalizes well to future vendors)
- [ ] `mkdocs` renders correctly in local preview and has been manually checked on new or updated functions/methods


Database:

- [ ] Alembic migrations are provided for database schema changes
    - [ ] Tested on SQLite
    - [ ] Tested on PostgreSQL
- [ ] `sc-crawler pull` was tested on all vendors and records
- [ ] Data changes were manually cross-checked with the vendor homepages or other trusted sources
- [ ] The output (e.g. SQLite file) of an example run is included in the PR to demonstrate major data changes
