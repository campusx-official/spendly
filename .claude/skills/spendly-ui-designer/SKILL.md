---
name: spendly-ui-designer
description: Designs and generates modern, production-ready UI for Spendly, a personal expense tracker built on Flask + Jinja2 + vanilla CSS (repo - https://github.com/campusx-official/spendly). Produces clean fintech-style pages and components - cards, forms, tables, dashboards, modals - with consistent spacing, soft shadows, rounded corners, and Lucide icons. Use this skill whenever the user asks to design, build, create, redesign, improve, or style any Spendly page, screen, section, or component - including phrasings like "design the X page", "create UI for X", "build a component for X", "make the X look better", "redesign X", or any request about Spendly's frontend, layout, CSS, or visual polish - even when Spendly isn't named explicitly if the conversation context is clearly about it.
disable-model-invocation: true
---

# Spendly UI Designer

You are designing frontend UI for **Spendly**, a personal expense tracker. Spendly is a Flask app with server-rendered Jinja2 templates, vanilla CSS, and a sprinkle of vanilla JS. The goal of this skill is to help you generate UI that feels like it belongs in a polished, modern fintech product - not generic bootstrap-era output, and not React/Tailwind output that doesn't match the stack.

## What Spendly's stack looks like

- **Backend:** Flask (`app.py`), SQLite (`database/db.py` + `database/queries.py`)
- **Templates:** Jinja2 in `templates/` — `base.html` (layout every page extends),
  `landing.html`, `login.html`, `register.html`, `profile.html` (the dashboard —
  there is no `dashboard.html`), `add_expense.html`, `edit_expense.html`,
  `analytics.html` (coming-soon placeholder), `terms.html`, `privacy.html`
- **Styles:** vanilla CSS in `static/css/` — `style.css` is global and owns the
  design tokens; `landing.css`, `profile.css`, `add_expense.css`, `analytics.css`
  are page-scoped. No Tailwind, no CSS-in-JS, no preprocessors.
- **Scripts:** `static/js/main.js` — currently **empty**. There is no JS
  infrastructure yet, so anything interactive you add is the first of its kind.
- **Icons:** currently **none**. The app uses text glyphs (`◈` for the brand mark).

Generate output that fits this stack. Do not introduce React, Vue, Tailwind, shadcn, Bootstrap, or styled-components unless the user explicitly asks for a migration.

### Icons: read this before emitting `data-lucide`

**Lucide is not loaded anywhere in this project.** `base.html` loads Google Fonts,
`style.css`, and `main.js` — nothing else. Emitting `<i data-lucide="wallet">`
without adding the library produces an empty, invisible element.

If a design genuinely needs icons, you must either:

1. Add the CDN script to `base.html` and call `lucide.createIcons()` — and say so
   explicitly in your integration note, because it is a new external dependency on
   every page; or
2. Inline the SVG you need directly in the template. `analytics.html` already does
   this with a hand-written `<svg>` — follow that precedent for one or two icons.

Prefer inline SVG for small counts. Reach for the CDN only when a page needs many
icons, and flag it as a decision for the user rather than making it silently.

## Before you design: check what already exists

If the user's project files are available (e.g. they've shared the repo, uploaded files, or you're inside the codebase), open `base.html`, the main CSS file, and one or two existing templates before generating anything new. The goal is *consistency* - Spendly should feel like one coherent product, not a collage.

Specifically, look for and reuse:

- **Color tokens** (CSS custom properties like `--color-primary`, `--color-bg`, `--color-surface`, etc.)
- **Spacing scale** (if there's a `--space-1`, `--space-2` pattern, use it)
- **Font family and type scale**
- **Existing component classes** - `.card`, `.btn`, `.input`, `.badge`, `.table`, etc.
- **The base layout** - sidebar? topbar? container width? Follow it.

If you can't see the existing files and the request is non-trivial, ask the user to share a screenshot or paste a relevant template before you generate. One screenshot of the existing dashboard saves three rounds of revision.

## The Spendly design language

Spendly already has a design language, and it is **not** the generic indigo-on-white
fintech look. It is warm, editorial, print-leaning: cream paper, forest green, a
serif display face. Match it. Anything that arrives looking like default Tailwind is
wrong for this product.

**Use the tokens — never hardcode a hex value.** These are defined on `:root` in
`static/css/style.css` and are the single source of truth:

```css
/* Ink — text */
--ink: #0f0f0f;          --ink-soft: #2d2d2d;
--ink-muted: #6b6b6b;    --ink-faint: #a0a0a0;

/* Paper — backgrounds */
--paper: #f7f6f3;        /* page background, warm off-white */
--paper-warm: #f0ede6;   /* subtle raised/alternate fill */
--paper-card: #ffffff;   /* card surfaces */

/* Accent — forest green primary, ochre secondary */
--accent: #1a472a;       --accent-light: #e8f0eb;
--accent-2: #c17f24;     --accent-2-light: #fdf3e3;

/* Semantic */
--danger: #c0392b;       --danger-light: #fdecea;

/* Structure */
--border: #e4e1da;       --border-soft: #eeebe4;

/* Type */
--font-display: 'DM Serif Display', Georgia, serif;
--font-body: 'DM Sans', system-ui, sans-serif;

/* Layout */
--max-width: 1200px;     --auth-width: 440px;
--radius-sm: 6px;        --radius-md: 12px;  --radius-lg: 20px;
```

**Typography:** `--font-display` (DM Serif Display) for headings and page titles —
this serif is what gives Spendly its character, so do not replace it with a sans
heading. `--font-body` (DM Sans) for everything else. Both are already loaded in
`base.html` via Google Fonts; do not add another font link. Amounts should use
`font-variant-numeric: tabular-nums` so columns of rupee figures align.

**Currency is the rupee (`₹`).** Amounts are pre-formatted as strings by
`database/queries.py` (`"{:,.2f}"`), so templates render `₹{{ tx.amount }}` — do not
apply number formatting in Jinja or JS.

**Radius:** use `--radius-sm` for inputs and badges, `--radius-md` for cards,
`--radius-lg` for large panels and modals.

**Spacing:** 8px grid. Multiples of 4px or 8px for padding, gap, margin. No
arbitrary 13px or 27px values. There is no spacing token scale — use literal
multiples and stay consistent within a page.

**Shadows:** subtle only. This design leans on `--border` and `--border-soft` far
more than on shadow. If a border will do, use the border. No glows.

**If you add a new colour**, add it as a token on `:root` in `style.css` first, then
reference it. A raw hex in a page stylesheet is a review finding.

**Layout patterns:**
- Card-based composition - group related info in surfaces, don't sprawl
- Generous whitespace - tight layouts read as cluttered in finance apps
- Left-aligned content with clear hierarchy; centered layouts only for empty states and auth
- Tables: zebra stripes optional, but always have row hover, right-align numeric columns
- Forms: label above input, helper text below, error state in red with icon

## Icons: Lucide

Load Lucide once in `base.html`:

```html
<script src="https://unpkg.com/lucide@latest"></script>
```

And call `lucide.createIcons()` after the DOM is ready (and after any dynamic DOM insert). In templates, use:

```html
<i data-lucide="wallet"></i>
<i data-lucide="trending-up"></i>
<i data-lucide="plus"></i>
```

Size icons via CSS with `width` and `height` on the `<svg>` (after Lucide replaces the `<i>`) or wrap in a span with the size you want. Prefer 16px for inline with text, 20px for buttons, 24px for section headers.

Pick icons that carry meaning. A few Spendly-appropriate defaults:
- Expense/spend: `arrow-down-right`, `shopping-bag`, `credit-card`
- Income: `arrow-up-right`, `wallet`, `trending-up`
- Budget: `target`, `pie-chart`
- Category: `tag`, `folder`
- Add/new: `plus`, `plus-circle`
- Settings: `settings`, `sliders-horizontal`
- Date/time: `calendar`, `clock`
- Search: `search`, Filter: `filter`

Don't sprinkle icons everywhere. One icon per button, one per section heading, one per table row action - that's usually the right density.

## Output structure

When fulfilling a design request, structure your response like this:

### 1. Short UI plan (2-5 bullets)
Name the key sections of the page/component and any notable UX decisions. Keep it tight - this is orientation, not a spec document. Example: "Dashboard has 4 summary cards on top (balance, income, expenses, savings), a 'recent transactions' table, and a category breakdown donut. Summary cards show trend vs last month as a small delta pill."

### 2. The code
- **Template file(s)** - full Jinja2 with `{% extends "base.html" %}` and a `{% block content %}` unless building `base.html` itself. Use Jinja control flow (`{% for %}`, `{% if %}`) with sensible placeholder variable names the user can wire to their Flask route.
- **CSS** - either a new page file (e.g. `static/css/reports.css`) or additions to an existing stylesheet. Scope with a page/component class prefix (`.profile-...`, `.tx-table-...`, matching what `profile.css` already does) so styles don't leak.
- **JS** (only if needed) - vanilla, no frameworks. Small and readable.

Put each file in its own fenced code block with a clear header comment or path annotation like `{# templates/profile.html #}` or `/* static/css/profile.css */`.

### 3. Integration note (1-3 lines)
How to wire it up - which Flask route renders it, what variables the template expects, any new dependency (almost always none). If the user needs to add a link in the sidebar or a route in `app.py`, call that out.

## What to avoid

- **Generic/dated looks** - no `<h1>Welcome to My App</h1>` with default browser styles, no sharp-cornered bordered boxes, no 2012-era bootstrap cards.
- **Code dumps without structure** - always separate template, CSS, and JS into labeled blocks.
- **Over-styling** - if something can be solid color instead of a gradient, use solid. If it can be a border instead of a shadow, use border. Restraint reads as quality.
- **Inconsistent spacing** - if you used 16px for card padding in one place, use 16px in the next place too. No 14px here, 18px there.
- **Random color accents** - one primary accent, semantic colors for meaning, everything else neutral.
- **Clever-but-unclear UX** - a clearly-labeled button beats a mystery icon. In finance, trust matters more than cuteness.
- **Mobile afterthought** - use CSS that works at narrow widths. At minimum, stack cards vertically and make tables horizontally scrollable below ~768px.

## Handling ambiguity

If the user asks for something under-specified ("design the reports page"), make reasonable assumptions and *state them up front* in the UI plan - one line each, no long preamble. For example: "Assuming reports page shows: monthly spend trend, top categories, and a downloadable CSV. Let me know if you want different widgets."

Don't pepper the user with clarifying questions for things you can reasonably decide. Do ask when the answer genuinely changes the output - e.g. "Is this a standalone page or a modal on top of the dashboard?"

## A worked example of the right vibe

**Request:** "Design the add expense form"

**UI plan:**
- Modal dialog (not a full page) - users add expenses inline from the dashboard
- Fields: amount (large, prominent), category (pill selector), date (defaults to today), note (optional)
- Primary action "Add expense" anchors bottom-right; cancel is a subtle text button
- Amount field gets a currency symbol prefix and tabular-nums

**Template:** `templates/add_expense.html` — already exists and extends `base.html`.
Modify it rather than creating a partial; Spendly has no `templates/partials/`
directory and no `{% include %}` usage yet, so introducing one is a structural
decision to raise, not to assume.

**CSS:** additions to the existing `static/css/add_expense.css`, loaded through
`{% block head %}`. Reuse `.btn-primary`, which `profile.html` already uses. There is
no `components.css` and no `.modal` class anywhere — check before referencing a class
as existing.

**JS:** `static/js/main.js` is empty, so any interaction is the first script in the
project. Keep it small, module-free, and guard for the element being absent
(`main.js` loads on every page, including ones without your component).

That's the shape - concrete, consistent with the stack, visually restrained, and immediately usable.

---

## Where this skill sits in the workflow

- `spendly-quality-reviewer` reads this file before commenting on templates or CSS,
  so its review and your output agree on what "correct" means.
- Backend wiring is out of scope here. If a design needs new data, name the template
  variables you expect and say which route must supply them — do not edit `app.py`
  or `database/` yourself.
- Deployment concerns (static file serving, CDN, cache headers) belong to the
  `spendly-devops` skill, not here.

## Verify before you hand off

- [ ] Every colour is a `var(--token)`, no raw hex
- [ ] Headings use `--font-display`; body uses `--font-body`
- [ ] Template extends `base.html` and uses `{% block head %}` for its stylesheet
- [ ] Every internal link is `url_for(...)`, never a literal path
- [ ] Amounts render as `₹{{ value }}` with no Jinja number formatting
- [ ] No `data-lucide` unless you also added the library and said so
- [ ] Referenced CSS classes actually exist — grep before claiming reuse
- [ ] Layout stacks and tables scroll below ~768px





