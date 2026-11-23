---
name: mapleset-design
description: Mapleset's rules for web UI across its brands (Mapleset, Breakdown Analytics, RO Search, Applesauce Labs) — DaisyUI and Lucide everywhere, where each brand package lives and how it is installed, and where UI picks go. Use when designing, building, restyling or reviewing any web UI, page, packet or mockup in a Mapleset project, or when choosing a theme, icons or brand colours.
---

# Mapleset design

Mapleset builds web UI for several brands. These are the house rules; the method lives in the generic skills this one points to.

## Standard in every project

- **DaisyUI.** 5.8.2 for new work. Where a project vendors DaisyUI (for example `assets/vendor/daisyui.js`), read its version first and stay on it unless the task is the upgrade. Classes and gotchas: the `oh-phoenix:daisyui` skill where it's loaded (it switches on in Elixir repos); elsewhere, the official docs at https://daisyui.com/components/.
- **Lucide icons**, nothing else:
  - Phoenix: the `lucide_icons` dependency. The package's own components are `<Lucideicons.arrow_right />`, or `<Lucideicons.render name="arrow-right" />` for dynamic names. The Breakdown apps add a project wrapper, `<.icon name="lucide-…">` (its `icon/1` clause in `core_components.ex` strips the prefix). Use the wrapper only where the project defines it; check the locked package version before using `render`.
  - Go apps: Lucide SVGs embedded in the binary.
  - React: `lucide-react`.

## Brands

Each brand is one repository built with brandkit (`mise use github:shermanhuman/brandkit`):

| Brand | Repository | Base |
|---|---|---|
| Mapleset | `shermanhuman/mapleset-brand` (branch `brand/base`) | itself |
| Breakdown Analytics | `Applesauce-Labs/breakdown-brand` | itself |
| RO Search | `Applesauce-Labs/rosearch-brand` | extends breakdown |

Applesauce Labs has no package of its own yet; ask which to use. That is a taste call, so wait for the answer rather than picking a default. A project installs its brand with `brandkit install <repo>@<tag>`. If the repository or tag doesn't exist yet, say so on the work's issue; don't invent tokens.

The package is the only source of colours, fonts, radius and themes. Use brandkit's `brandkit:brand` skill to define or change a brand and its `brandkit:design` skill for UI work on top of one.

## Picks

UI options for the user to choose between go in a Sugarhouse decision item (`sugar post`, with a mockup on each option) when `sugar` is installed, and otherwise on a packet page on the factory-packets server, as the always-on rules describe.

## Data

Charts follow the `dataviz` skill (bundled with Claude Code; in a host without it, follow the always-on packet rule on charts and tables).
