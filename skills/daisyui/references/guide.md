# DaisyUI v5 — Component Library for Tailwind CSS

## Contents

- Documentation
- Installation
- Core Concepts
- ⚠️ CRITICAL GOTCHAS
- Component Quick Reference

DaisyUI is a Tailwind CSS plugin that adds semantic component classes (e.g. `btn`, `card`, `drawer`) so you write less utility soup. **Version 5** targets **Tailwind CSS v4**, uses zero JS, and relies purely on CSS.

## Documentation

For full docs on any component, fetch the raw markdown from GitHub:

```
https://raw.githubusercontent.com/saadeghi/daisyui/refs/heads/master/packages/docs/src/routes/(routes)/components/{COMPONENT}/+page.md
```

Replace `{COMPONENT}` with: `drawer`, `navbar`, `button`, `menu`, `modal`, `card`, `table`, `badge`, `alert`, `dropdown`, `indicator`, `toggle`, `tooltip`, `tab`, `collapse`, etc.

Full list: https://daisyui.com/components/

## Installation

```css
/* app.css — Tailwind v4 */
@import "tailwindcss";
@plugin "daisyui";
```

Install via npm: `npm i -D daisyui@5`

## Core Concepts

### Semantic Classes

DaisyUI provides component-level classes instead of raw Tailwind utilities:

```html
<button class="btn btn-primary">Click me</button>
```

### Theming

- Set via `data-theme="themename"` on any element (typically `<html>`)
- Built-in themes: `light`, `dark`, `cupcake`, `dracula`, `nord`, `corporate`, `business`, etc.
- Semantic color names: `primary`, `secondary`, `accent`, `neutral`, `base-100/200/300`, `info`, `success`, `warning`, `error`
- Each color has a `-content` variant for text on that background (e.g. `primary-content`)

### Modifiers

- **Size**: `-xs`, `-sm`, `-md`, `-lg`, `-xl`
- **Style**: `-outline`, `-ghost`, `-soft`, `-dash`

---

## ⚠️ CRITICAL GOTCHAS

### 1. Drawer positioning

Inspect the rendered DOM and computed styles before diagnosing a positioning issue. Grid alignment is not a universal override of absolute positioning. Prefer a flex/grid layout for a close button when it fits, or position it inside a deliberately positioned sidebar container. `.btn` is not inherently incompatible with drawers.

```html
<aside class="relative min-h-full w-64 bg-base-200">
  <button type="button" class="btn btn-ghost btn-sm absolute right-2 top-2" aria-label="Close menu">×</button>
  <ul class="menu pt-12"><!-- navigation --></ul>
</aside>
```

Wire the button to the drawer's actual control state. Do not nest buttons or claim positioning is broken without inspecting its containing block. [Drawer component](https://daisyui.com/components/drawer/).

### 3. Drawer structure is strict

The drawer has a mandatory element order. It will break if elements are rearranged:

```
.drawer                          // Root grid container
├── .drawer-toggle               // Hidden checkbox (controls open/close)
├── .drawer-content              // Main page content
│   └── (navbar, content, etc.)
└── .drawer-side                 // Sidebar container
    ├── .drawer-overlay           // Click-to-close overlay
    └── (sidebar content)         // Your menu/aside
```

### 4. Responsive drawer

- `lg:drawer-open` — sidebar always visible at `lg`+ breakpoint, overlay on smaller screens

### 5. Collapsible sidebar (v5)

DaisyUI v5 provides state-aware modifiers:

```html
<div class="drawer-side is-drawer-close:overflow-visible">
  <div class="is-drawer-close:w-14 is-drawer-open:w-64">
    <span class="is-drawer-close:hidden">Label Text</span>
  </div>
</div>
```

---

## Component Quick Reference

### Navbar

```html
<div class="navbar bg-base-200">
  <div class="navbar-start"><!-- left --></div>
  <div class="navbar-center"><!-- center --></div>
  <div class="navbar-end"><!-- right --></div>
</div>
```

### Button

```html
<button class="btn">Default</button>
<button class="btn btn-primary">Primary</button>
<button class="btn btn-ghost btn-sm">Small Ghost</button>
<button class="btn btn-outline btn-error">Error Outline</button>
<button class="btn btn-square btn-sm">□</button>
<button class="btn btn-circle btn-sm">○</button>
```

### Menu (sidebar nav)

```html
<ul class="menu bg-base-200 w-56">
  <li><a>Item 1</a></li>
  <li class="menu-title">Section Title</li>
  <li><a>Item 2</a></li>
  <li><a class="menu-active">Active Item</a></li>
</ul>
```

### Card

```html
<div class="card bg-base-100 card-border">
  <div class="card-body">
    <h2 class="card-title">Title</h2>
    <p>Content</p>
    <div class="card-actions justify-end">
      <button class="btn btn-primary">Action</button>
    </div>
  </div>
</div>
```

### Modal

```html
<button class="btn" onclick="my_modal.showModal()">Open</button>
<dialog id="my_modal" class="modal">
  <div class="modal-box">
    <h3 class="text-lg font-bold">Title</h3>
    <p>Content</p>
    <div class="modal-action">
      <form method="dialog"><button class="btn">Close</button></form>
    </div>
  </div>
  <form method="dialog" class="modal-backdrop"><button>close</button></form>
</dialog>
```

### Dropdown

```html
<details class="dropdown">
  <summary class="btn m-1">Click</summary>
  <ul
    class="dropdown-content menu bg-base-100 rounded-box z-50 w-52 p-2 shadow"
  >
    <li><a>Item 1</a></li>
    <li><a>Item 2</a></li>
  </ul>
</details>
```

### Table

```html
<div class="overflow-x-auto">
  <table class="table">
    <thead>
      <tr>
        <th>Name</th>
        <th>Value</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Row 1</td>
        <td>Data</td>
      </tr>
      <tr class="row-hover">
        <td>Hoverable</td>
        <td>Row</td>
      </tr>
    </tbody>
  </table>
</div>
```

Modifiers: `table-zebra`, `table-xs`/`sm`/`md`/`lg`, `table-pin-rows`, `table-pin-cols`

### Badge / Indicator

```html
<span class="badge badge-primary">label</span>
<span class="badge badge-error badge-xs">3</span>

<div class="indicator">
  <span class="indicator-item badge badge-error badge-xs">9+</span>
  <button class="btn">Inbox</button>
</div>
```

### Alert

```html
<div class="alert alert-info"><span>Info message</span></div>
<div class="alert alert-error alert-soft"><span>Soft error</span></div>
```
