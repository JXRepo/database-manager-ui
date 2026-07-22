# Blue Microstructure Homepage Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the public homepage with the authenticated workspace's blue palette and replace the concentric hero graphic with a materials-specific polycrystalline RVE map.

**Architecture:** Preserve the existing Django view, routes, content structure, and responsive editorial layout. Refine the scoped homepage tokens and inline SVG in `templates/pages/index.html`, synchronize the public document background in `templates/layouts/base-public.html`, and lock the visual contract in the existing homepage response test.

**Tech Stack:** Django templates, scoped CSS, inline SVG, Django `TestCase`

## Global Constraints

- Keep `index`, `search`, `upload_json`, `login`, and `register` route behavior unchanged.
- Use workspace canvas `#F4F7FA`, workspace navy `#3F4D67`, active blue `#04A9F5`, sidebar mist `#A9B7D0`, paper white `#FFFFFF`, and slate ink `#334155`.
- Do not add packages, images, JavaScript, backend queries, models, or migrations.
- Keep all existing synthetic preview data and privacy assertions.
- The hero graphic must not contain circles or concentric contour paths.
- Preserve a useful layout from 320px upward and respect `prefers-reduced-motion`.
- Use English for interface copy, comments, and docstrings.

## File Map

- `apps/pages/tests.py`: homepage response contract for palette tokens, hero class, and removal of the old fingerprint.
- `templates/pages/index.html`: scoped color system, decorative microstructure SVG, specimen label, and responsive motion.
- `templates/layouts/base-public.html`: public document theme color and body fallback background.

---

### Task 1: Lock the Blue Microstructure Contract

**Files:**
- Modify: `apps/pages/tests.py`, `JSONDataSharingTests.test_public_home_page_is_available_without_login`
- Test: `apps/pages/tests.py`

**Interfaces:**
- Consumes: the public response returned by `reverse("index")`.
- Produces: assertions for `.microstructure-map`, the three shared application colors, and removal of `.material-fingerprint`.

- [ ] **Step 1: Replace the old hero assertion and add palette assertions**

Replace:

```python
self.assertContains(response, 'class="material-fingerprint"')
```

with:

```python
self.assertContains(response, 'class="microstructure-map"')
self.assertContains(response, "Polycrystal map")
self.assertContains(response, "--atlas-canvas: #f4f7fa;")
self.assertContains(response, "--atlas-navy: #3f4d67;")
self.assertContains(response, "--atlas-blue: #04a9f5;")
self.assertNotContains(response, 'class="material-fingerprint"')
```

- [ ] **Step 2: Run the focused test and verify the contract fails**

Run:

```powershell
.\.venv\Scripts\python.exe manage.py test apps.pages.tests.JSONDataSharingTests.test_public_home_page_is_available_without_login --verbosity 1
```

Expected: `FAIL` because the current response still contains `.material-fingerprint` and does not contain `.microstructure-map`.

### Task 2: Apply the Authenticated Workspace Palette

**Files:**
- Modify: `templates/pages/index.html`
- Modify: `templates/layouts/base-public.html`
- Test: `apps/pages/tests.py`

**Interfaces:**
- Consumes: the existing `.landing-shell` scoped stylesheet.
- Produces: shared color tokens consumed by every homepage section and the public page chrome.

- [ ] **Step 1: Replace the homepage color tokens**

Use these exact declarations at the start of `.landing-shell`:

```css
--atlas-canvas: #f4f7fa;
--atlas-paper: #ffffff;
--atlas-navy: #3f4d67;
--atlas-slate: #596a82;
--atlas-blue: #04a9f5;
--atlas-blue-soft: #a9b7d0;
--atlas-ink: #334155;
--atlas-muted: #6d7b8a;
--atlas-line: rgba(63, 77, 103, 0.16);
```

Map old token usage as follows:

```text
--atlas-mist -> --atlas-canvas
--atlas-mineral -> --atlas-navy
--atlas-mineral-soft -> --atlas-slate
--atlas-copper -> --atlas-blue
--atlas-patina -> --atlas-blue-soft
```

- [ ] **Step 2: Synchronize the public document background**

In `templates/layouts/base-public.html`, use:

```html
<meta name="theme-color" content="#f4f7fa">
```

and:

```css
body {
  background: #f4f7fa;
}
```

- [ ] **Step 3: Run the focused test**

Run the focused command from Task 1. Expected: still `FAIL` only for the new hero class and label while the palette assertions now pass.

### Task 3: Replace the Circular Fingerprint with a Polycrystalline RVE Map

**Files:**
- Modify: `templates/pages/index.html`
- Test: `apps/pages/tests.py`

**Interfaces:**
- Consumes: `.atlas-specimen`, the new palette tokens, and the existing specimen details.
- Produces: decorative `.microstructure-map` markup with polygonal `.grain` cells and no `<circle>` elements.

- [ ] **Step 1: Replace the fingerprint CSS**

Define `.microstructure-map`, `.grain`, `.grain-load-path`, `.grain-outline`, `.grain-axis`, and `.grain-arrow`. Use navy boundaries, pale blue fills, one active-blue load path, a subtle cool shadow, and `atlas-microstructure-drift` with no rotation or pulsing.

```css
.microstructure-map {
  display: block;
  width: 100%;
  height: auto;
  filter: drop-shadow(0 28px 32px rgba(63, 77, 103, 0.14));
  animation: atlas-microstructure-drift 8s ease-in-out infinite;
}

.grain {
  stroke: rgba(63, 77, 103, 0.58);
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}

.grain-field { fill: #edf8fe; }
.grain-a, .grain-h, .grain-k { fill: #d8effb; }
.grain-b, .grain-e, .grain-l { fill: #bfe4f7; }
.grain-c, .grain-f, .grain-i { fill: #eef7fc; }
.grain-d, .grain-g, .grain-j, .grain-m { fill: #8ed3f3; }

.grain-outline {
  fill: none;
  stroke: var(--atlas-navy);
  stroke-width: 4;
  vector-effect: non-scaling-stroke;
}

.grain-load-path {
  fill: none;
  stroke: var(--atlas-blue);
  stroke-dasharray: 10 9;
  stroke-width: 4;
  vector-effect: non-scaling-stroke;
}

.grain-axis {
  fill: none;
  stroke: var(--atlas-navy);
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
}

.grain-arrow { fill: var(--atlas-navy); }

@keyframes atlas-microstructure-drift {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}
```

- [ ] **Step 2: Replace the inline SVG and specimen coordinate**

Use a clipped angular specimen field containing adjoining `<polygon>` grains, an exterior outline, dashed load path, coordinate axes, and triangular arrowheads. The top label must read:

```html
<div class="specimen-coordinate">RVE slice 03 · 128 grains</div>
<svg class="microstructure-map" viewBox="0 0 620 560" aria-hidden="true">
  <defs>
    <clipPath id="grain-field-clip">
      <path d="M82 88 532 58 574 405 505 474 126 496 60 165Z"/>
    </clipPath>
  </defs>
  <g clip-path="url(#grain-field-clip)">
    <path class="grain-field" d="M40 30H600V525H40Z"/>
    <polygon class="grain grain-a" points="50,100 180,40 220,155 132,236 45,210"/>
    <polygon class="grain grain-b" points="180,40 330,34 350,144 220,155"/>
    <polygon class="grain grain-c" points="330,34 510,30 570,125 468,190 350,144"/>
    <polygon class="grain grain-d" points="510,30 610,80 600,250 468,190 570,125"/>
    <polygon class="grain grain-e" points="45,210 132,236 150,360 55,410"/>
    <polygon class="grain grain-f" points="132,236 220,155 310,245 260,360 150,360"/>
    <polygon class="grain grain-g" points="220,155 350,144 395,250 310,245"/>
    <polygon class="grain grain-h" points="350,144 468,190 455,320 395,250"/>
    <polygon class="grain grain-i" points="468,190 600,250 580,390 455,320"/>
    <polygon class="grain grain-j" points="55,410 150,360 230,480 80,520"/>
    <polygon class="grain grain-k" points="150,360 260,360 360,480 230,480"/>
    <polygon class="grain grain-l" points="260,360 395,250 455,320 430,450 360,480"/>
    <polygon class="grain grain-m" points="455,320 580,390 520,520 430,450"/>
    <path class="grain-load-path" d="M116 421 478 112"/>
  </g>
  <path class="grain-outline" d="M82 88 532 58 574 405 505 474 126 496 60 165Z"/>
  <path class="grain-axis" d="M74 514H242M74 514V346"/>
  <path class="grain-arrow" d="M242 514 226 505V523ZM74 346 65 362H83Z"/>
</svg>
```

Do not include `<circle>` or any class beginning with `fingerprint-`. Change the specimen overline from `Material fingerprint` to `Polycrystal map`; retain `Cu · FCC`, `RVE-0249`, `DAMASK`, and `Validated`.

- [ ] **Step 3: Update responsive and reduced-motion selectors**

Replace `.material-fingerprint` with `.microstructure-map` in the mobile rule and reduced-motion block. The SVG remains fully visible without horizontal overflow at 320px.

- [ ] **Step 4: Run the focused test**

Run the focused command from Task 1. Expected: `OK` with one test passing.

### Task 4: Verify Project and Visual Quality

**Files:**
- Modify only if a defect is found: `templates/pages/index.html`, `templates/layouts/base-public.html`
- Test: `apps/pages/tests.py`

**Interfaces:**
- Consumes: the completed homepage response and the running Django development server.
- Produces: verified desktop and mobile rendering with no regressions.

- [ ] **Step 1: Run static and regression checks**

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test apps.pages.tests --verbosity 1
git diff --check -- apps/pages/tests.py templates/pages/index.html templates/layouts/base-public.html
```

Expected: Django reports no issues, all page tests pass, and Git reports no whitespace errors.

- [ ] **Step 2: Inspect desktop and mobile renders**

At `1440x1000` and `390x844`, confirm that the hero shows polygonal grains rather than a circular motif, the workspace blue palette is visually consistent, no content clips, the mobile navigation remains usable, and the document has no horizontal overflow or console error.

- [ ] **Step 3: Run the complete test suite**

```powershell
.\.venv\Scripts\python.exe manage.py test --verbosity 1
```

Expected: all project tests pass.

- [ ] **Step 4: Review the final scoped diff**

```powershell
git diff --check
git diff -- apps/pages/tests.py templates/pages/index.html templates/layouts/base-public.html
```

Expected: only the homepage contract, palette, hero visual, and public document background differ within the scoped files; unrelated existing work remains untouched.
