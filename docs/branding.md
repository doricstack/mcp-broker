# Branding rules

Status: locked for the first public brand pass.

This file is the single source of truth for how `mcp-broker` brand assets are used in this repo and in the public export. The production assets live under `brand/assets/`. Do not treat local scratch files, generated concept folders, or old experiment folders as source material.

Brand direction: routing backbone.

Tagline: one ingress. many servers. safe by profile.

## Enforcement model

These rules are executable repo rules, not style suggestions. A brand rule with no named gate is a comment, not a standard. Every locked rule below must name the file, test, Make target, or release gate that fails when the rule drifts.

Local check:

```bash
LOCAL_CPU_BUDGET=4 PYTEST_WORKERS=4 make test-journey PYTEST_ARGS='tests/journey/test_public_adoption_contract.py::test_branding_rules_document_locked_assets_and_enforcement'
```

Public-export check:

```bash
LOCAL_CPU_BUDGET=4 PYTEST_WORKERS=4 make public-export-check PUBLIC_REPO=<public-checkout>
```

Release check:

```bash
LOCAL_CPU_BUDGET=4 PYTEST_WORKERS=4 RELEASE_VERSION=<version> make release-check
```

## Asset map

| Surface | Required asset | Rule |
|---|---|---|
| README header | `brand/assets/readme-header.svg` | Use at the top of `README.md`. This is the first public brand signal. |
| GitHub social preview | `brand/assets/github-social-preview.svg` | Use as the source image for social preview exports. If GitHub needs a raster upload, use the matching PNG export. |
| App icon or GitHub avatar | `brand/assets/app-icon-1024.png` | Use for square identity surfaces that need a PNG. |
| Browser favicon | `brand/assets/favicon-32.png` | Use for 32px favicon export. Use `brand/assets/mark-favicon.svg` when SVG favicon is accepted. |
| Primary mark | `brand/assets/mark.svg` | Use for scalable square mark placement. |
| Small mark | `brand/assets/mark-favicon.svg` | Use for small-size mark rendering. |
| Horizontal lockup | `brand/assets/horizontal.svg` | Use in docs, repo cards, and public directory submissions when a horizontal wordmark fits better than the header. |
| One-color mark | `brand/assets/mark-black.svg`, `brand/assets/mark-white.svg` | Use only when the surface controls color poorly. |
| Design tokens | `brand/assets/tokens.css`, `brand/assets/tokens.json` | Use these as the palette source. Do not scatter raw brand hex values in docs or generated surfaces. |
| Brand overview | `brand/brand-overview.png` | Use only as a visual reference board. It is not the README header, icon, or favicon. |

## Locked rules

| ID | Rule | Enforcement |
|---|---|---|
| BRAND-1 | The production brand folder is `brand/assets/`. No alternate concept folders are public assets. | `tests/journey/test_public_adoption_contract.py::test_branding_rules_document_locked_assets_and_enforcement` checks this doc and `brand/README.md`. |
| BRAND-2 | `README.md` must use `brand/assets/readme-header.svg` near the top. | `make test-journey` fails if the README stops referencing the approved header. |
| BRAND-3 | `public-export/allowlist.txt` must include `docs/branding.md` and `brand/**` so public users get the same brand rules and assets. | `make test-journey` checks the allowlist. |
| BRAND-4 | Do not create public folders named after generated sets, production-vector experiments, downloads, or concept batches. Use `brand/assets/` only. | The doc contract requires no alternate concept folders and no generated-set folder names. |
| BRAND-5 | SVG is required for repo-native docs, README, website references, and directory markdown. PNG is allowed only for registry, icon, favicon, and social surfaces that reject SVG. | `tests/journey/test_public_adoption_contract.py::test_branding_rules_document_locked_assets_and_enforcement` fails if locked SVG and PNG assets are missing from `brand/assets/`. |
| BRAND-6 | Token colors come from `brand/assets/tokens.css` and `brand/assets/tokens.json`. | `tests/journey/test_public_adoption_contract.py::test_branding_rules_document_locked_assets_and_enforcement` fails if token names or hex values drift between this doc, CSS, and JSON. |
| BRAND-7 | Public directory copy should describe the brand as local routing infrastructure, not as a hosted automation or workflow product. | Directory submission copy must use `docs/directory-submission-packet.md` and this branding doc. |

## Color tokens

| Token | Hex | Role |
|---|---|---|
| `--mcp-ink` | `#0D1117` | Primary text and deep mark contrast. |
| `--mcp-midnight` | `#111827` | Dark panel and header surface. |
| `--mcp-slate` | `#334155` | Secondary text and quiet structural lines. |
| `--mcp-steel` | `#64748B` | Muted labels and inactive UI. |
| `--mcp-fog` | `#F6F7F9` | Light surface. |
| `--mcp-primary` | `#0EA5A0` | Broker routing identity. |
| `--mcp-secondary` | `#2563EB` | Network and MCP-client connection accent. |
| `--mcp-accent` | `#F59E0B` | Controlled warning, highlight, and safety-gate accent. |

## File ownership

| Path | Owner intent |
|---|---|
| `brand/README.md` | Folder-level summary and public asset rules. |
| `brand/assets/USAGE.md` | Asset kit summary generated with the production vector set. |
| `docs/branding.md` | Repo-level rules and enforcement. This file wins when usage is unclear. |
| `README.md` | Public first-screen brand placement. |
| `public-export/allowlist.txt` | Public export inclusion rule. |

## Change process

1. Update or add the asset under `brand/assets/`.
2. Update this file if the asset is meant for a public surface.
3. Update `brand/README.md` or `brand/assets/USAGE.md` if the folder-level guidance changes.
4. Run `LOCAL_CPU_BUDGET=4 PYTEST_WORKERS=4 make test-journey PYTEST_ARGS='tests/journey/test_public_adoption_contract.py::test_branding_rules_document_locked_assets_and_enforcement'`.
5. Run `LOCAL_CPU_BUDGET=4 PYTEST_WORKERS=4 make public-export-check PUBLIC_REPO=<public-checkout>` before pushing a public sync.

## Forbidden

- no alternate concept folders in the public repo
- no generated-set folder names
- no copied assets from a local downloads folder
- no brand assets outside `brand/` unless the target platform requires a root-level copy
- no parallel color palette in docs, CSS, package metadata, or directory listings
- no "manual review" enforcement for locked brand rules; repo-owned brand rules must have a test, export check, or release gate
