---
name: mapleset-design
description: Mapleset's rules for web UI across its brands (Mapleset, Breakdown Analytics, RO Search, Applesauce Labs): DaisyUI and Lucide everywhere, which brand a project uses, where each brand package lives and how it's installed, and how UI picks are shown. Use when designing, building, restyling or reviewing web UI, pages or mockups in a Mapleset project, or when choosing a theme, icons or brand colours.
---

# Mapleset design

Mapleset builds web UI for several brands. These are the house rules; the method lives in the generic skills this one points to.

## Standard in every project

- **DaisyUI.** Where a project vendors DaisyUI (for example `assets/vendor/daisyui.js`, including a fresh `phx.new` app), read its version and stay on it unless the task is the upgrade. For a project with none yet, use the newest version brandkit's README says its themes are built against. Classes and gotchas: the `oh-phoenix:daisyui` skill where it's loaded (it switches on in Elixir repos); elsewhere, the official docs at https://daisyui.com/components/.
- **Lucide icons**, nothing else:
  - Phoenix: the `lucide_icons` dependency. The package's own components are `<Lucideicons.arrow_right />`, or `<Lucideicons.render name="arrow-right" />` for dynamic names. The Breakdown apps add a project wrapper, `<.icon name="lucide-…">` (its `icon/1` clause in `core_components.ex` strips the prefix); a fresh Phoenix app's `icon/1` only matches `hero-`. Use the wrapper only where the project defines it; check the locked package version before using `render`.
  - Go apps: Lucide SVGs embedded in the binary.
  - React: `lucide-react`.

## Brands

Each brand is one repository built with brandkit (`mise use github:shermanhuman/brandkit`):

| Brand | Repository | Extends |
|---|---|---|
| Mapleset | `shermanhuman/mapleset-brand` | |
| Breakdown Analytics | `Applesauce-Labs/breakdown-brand` | |
| RO Search | `Applesauce-Labs/rosearch-brand` | `breakdown-brand` |

- **Which brand** (for a project on a package, or moving onto one). A project's brand is the one in its `brandkit.lock`. With no lock, take it from the work's issue, and ask if it isn't there. Applesauce Labs has no package of its own yet: ask which to use. That is a taste call, so wait for the answer rather than picking a default.
- **Installing.** `brandkit install <owner/repo>@<tag>`, with the newest release tag. It vendors the built files under `vendor/brand/<repo>/ui/`. If the repository or a release doesn't exist yet, say so on the work's issue; the design work waits for the package (the `brandkit:design` skill won't start without one), and no one invents tokens.
- **Projects not on a package yet** (most Breakdown apps today) keep their hand-written theme until their own migration issue moves them. Edit it in place when a task needs it, and note the drift on that issue; don't migrate a project mid-task.
- **Brand rules are per brand.** What a brand bans (shadows, for example, in Mapleset's) is in its package and enforced by `brandkit lint`; don't apply one brand's rules to another.
- **Packets** use the factory-packets template and its theme as they are.

The package is the only source of colours, fonts, radius and themes for a project on one. Use brandkit's `brandkit:brand` skill to define or change a brand and its `brandkit:design` skill for UI work on top of one.

## Picks

UI options for the user to choose between go wherever the always-on *Questions* rule sends questions. Each option carries its own mockup, shown as captures (desktop and mobile) or in a frame with `sandbox="allow-scripts"` and never `allow-same-origin`, so the mockup runs in an opaque origin. Never show live mockup code with the packet page's own origin: a packet page accepts answer posts from that origin.

## Data

Charts follow the `dataviz` skill (bundled with Claude Code). In a host without it, use the brand's chart colours from its package and label every axis and series; in packets, follow the always-on rule on charts and tables.
