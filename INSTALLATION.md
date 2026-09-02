# Installation and integration

Each directory under `skills/` is an independently discoverable skill. Install
only the capabilities a consumer needs, or install all four for the complete
GitHub Delivery adapter.

## Pinned installer

`scripts/install.py` matches the pinned-installer contract used by
`omiologic/context-governance` and `omiologic/deliver-product`. It fetches the
requested ref directly from the configured remote, materializes package-only
content, drops all `.git` metadata, and records a manifest with the source
commit and a per-package content digest.

Install all four packages for Codex non-interactively:

```bash
python3 scripts/install.py --target /path/to/consumer --agent codex --yes
```

Claude Code uses `--agent claude`. Omit `--yes` for an interactive
confirmation. Install a subset by repeating `--package`:

```bash
python3 scripts/install.py \
  --target /path/to/consumer \
  --agent codex \
  --package deliver-with-gh \
  --package gh-work-planning \
  --yes
```

Packages install beneath `.agents/skills/` for Codex or `.claude/skills/` for
Claude Code. The manifest `.deliver-with-gh-install.json` is written at that
skill root, beside the package directories:

```json
{
  "commit": "<full source commit SHA>",
  "source": "<source repository URL>",
  "packages": {
    "<package-name>": "<content_sha256>"
  }
}
```

Rerunning the installer reports each selected package as `install`, `current`,
`behind`, `local-modifications`, or an unmanaged `migrate-*` state, and lists
the differing package-relative paths. Upstream changes are never installed
silently: a `behind`, locally modified, unmanaged, or source-changed package
requires `--migrate`. A commit-changing installation must include every
previously installed package. Package replacement is atomic with backup and
rollback.

`--source` accepts a local path for development checkouts; `--ref` selects a
branch, tag, or commit (default `main`).

## Validation

From the repository root, one command validates all four skill packages,
package-local links, Python scripts, JSON fixtures, architecture invariants,
public fixture safety, and all scenarios:

```bash
python3 scripts/validate.py
```

Validate one source package and its scenarios:

```bash
python3 scripts/validate.py --skill gh-change-delivery
```

Validate an installed ecosystem or one installed skill structurally:

```bash
python3 scripts/validate.py --skills-root /exact/path/to/skills --skip-tests
python3 scripts/validate.py \
  --skills-root /exact/path/to/skills \
  --skill gh-delivery-reconciliation \
  --skip-tests
```

Codex's standard skill validator may also validate each directory directly:

```bash
python3 /path/to/skill-creator/scripts/quick_validate.py \
  /exact/path/to/skills/gh-work-planning
```

## Integration boundary

`deliver-with-gh` depends conceptually on the platform-neutral contracts from
`omiologic/deliver-product`. The dependency direction is one-way:

```text
deliver-with-gh -> deliver-product
```

Installing this package never writes to or patches `deliver-product`.
`deliver-product` remains independently installable and usable without GitHub
knowledge. The router passes owner-produced Planning, Execution, and
Reconciliation payloads into GitHub-specific children; the children return
projections or evidence, not canonical state.

Branch strategy and repository policy remain consumer inputs. The complete
ecosystem provides deterministic resolution but no default branch strategy,
repository path, label, Project field, iteration, priority, or status mapping.

Context Governance is an optional policy source for `gh-change-delivery`, not
an installation dependency. When both are installed, resolve the applicable
bounded governance context first and pass that compact result to the change
workflow. Installing `gh-change-delivery` by itself preserves direct
`consumer_policy` behavior unchanged.
