# Installation and integration

Each directory under `skills/` is an independently discoverable skill. Install
only the capabilities a consumer needs, or install all four for the complete
GitHub Delivery adapter.

## Supported skill roots

For Codex, install beneath `${CODEX_HOME}/skills` when `CODEX_HOME` is set, or
`~/.codex/skills` otherwise. For a repository-local or another compatible
consumer, supply the exact skills root that consumer is configured to scan;
each installed directory must contain its own `SKILL.md`.

The installer deliberately requires an explicit destination and refuses to
replace an existing skill directory.

Install the full ecosystem by copy:

```bash
python3 scripts/install.py --destination /exact/path/to/skills
```

Install one independently:

```bash
python3 scripts/install.py \
  --destination /exact/path/to/skills \
  --skill gh-work-planning
```

Repeat `--skill` to select several. For a development checkout, use
`--mode symlink`. Preview either mode with `--dry-run`.

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
