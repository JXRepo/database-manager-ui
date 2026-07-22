# Materials Atlas Homepage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the public homepage's IDE-like presentation with a distinctive, responsive Materials Atlas experience that guides researchers to search or upload simulation data.

**Architecture:** Keep the existing public `index` Django view and URL contract unchanged. Implement the redesign entirely in the existing standalone homepage template, using semantic HTML, scoped CSS, and an inline decorative SVG; update only the focused homepage assertions in the existing pages test module.

**Tech Stack:** Django templates, Bootstrap-compatible HTML, CSS, inline SVG, Django `TestCase`

## Global Constraints

- Do not change backend data models, permissions, URL names, or authenticated-user redirect behavior.
- Do not expose real dataset records on the public homepage; keep synthetic examples only.
- Introduce no new package, font, or image dependency.
- Preserve useful behavior from 320px mobile width upward.
- Use English for interface copy, comments, and docstrings.
- Respect `prefers-reduced-motion` and provide visible keyboard focus.

## File Map

- `apps/pages/tests.py`: owns the public homepage response contract and privacy regression assertions.
- `templates/pages/index.html`: owns all public homepage markup, scoped styles, inline decorative SVG, copy, and responsive behavior.

---

### Task 1: Lock the Materials Atlas Homepage Contract

**Files:**
- Modify: `apps/pages/tests.py`, method `test_public_home_page_is_available_without_login`
- Test: `apps/pages/tests.py`

**Interfaces:**
- Consumes: Django route name `index` and the existing `JSONData` model.
- Produces: A response-level contract for the Materials Atlas headline, signature SVG, actions, synthetic examples, and public-data privacy.

- [ ] **Step 1: Replace the brittle visual assertions with the new contract**

Keep the existing record setup and privacy assertions. Replace the assertions after `self.assertNotContains(response, "demo")` with:

```python
self.assertContains(response, "The material record behind every simulation")
self.assertContains(response, 'class="material-fingerprint"')
self.assertContains(response, "Search data")
self.assertContains(response, "Upload JSON")
self.assertContains(response, "Materials Atlas")
self.assertContains(response, "Example materials index")
self.assertContains(response, "rve-copper-001")
self.assertContains(response, "Synthetic example")
self.assertContains(response, "Sign in to inspect dataset records")
self.assertContains(response, "Create account")
self.assertContains(response, "prefers-reduced-motion: reduce")
self.assertContains(response, ":focus-visible")
self.assertNotContains(response, "data-console")
self.assertNotContains(response, "data-slab")
```

- [ ] **Step 2: Run the focused test and confirm the old homepage fails the new contract**

Run:

```powershell
.\.venv\Scripts\python.exe manage.py test apps.pages.tests.PagesTests.test_public_home_page_is_available_without_login
```

If the containing class is not `PagesTests`, obtain the exact dotted name with:

```powershell
.\.venv\Scripts\python.exe manage.py test apps.pages.tests -v 2
```

Expected: `FAIL` because the old template does not contain `The material record behind every simulation`.

- [ ] **Step 3: Review the test diff**

Run:

```powershell
git diff --check -- apps/pages/tests.py
git diff -- apps/pages/tests.py
```

Expected: no whitespace errors, and only the homepage test assertions added by this task differ within the method.

### Task 2: Build the Materials Atlas Homepage

**Files:**
- Modify: `templates/pages/index.html`
- Test: `apps/pages/tests.py`

**Interfaces:**
- Consumes: Django URL names `index`, `search`, `upload_json`, `login`, `register`, `json_data_list`, `share`, `charts`, and `account_settings`.
- Produces: Semantic sections with IDs `capabilities`, `workflow`, and `public-preview`; a decorative `.material-fingerprint` SVG; synthetic-only preview rows.

- [ ] **Step 1: Replace the existing scoped stylesheet with the Materials Atlas token system**

Define the tokens on `.landing-shell` and derive all page colors from them:

```css
.landing-shell {
  --atlas-mist: #edf3f4;
  --atlas-paper: #fbfdfd;
  --atlas-mineral: #163f40;
  --atlas-copper: #c9573d;
  --atlas-patina: #55a8a3;
  --atlas-ink: #334a4e;
  background: var(--atlas-mist);
  color: var(--atlas-ink);
  min-height: 100vh;
  overflow: hidden;
}
```

Use `Georgia, "Times New Roman", serif` only for display headings, the existing `"Open Sans"` for body text, and `ui-monospace, SFMono-Regular, Consolas, monospace` only for data labels. Add visible `:focus-visible` outlines and a `@media (prefers-reduced-motion: reduce)` block that disables transitions and animations.

- [ ] **Step 2: Replace the public navigation and hero markup**

Use this semantic structure and exact primary copy:

```html
<nav class="atlas-nav" aria-label="Main navigation">
  <a class="atlas-brand" href="{% url 'index' %}"><span class="atlas-brand-mark" aria-hidden="true"></span><span>Materials Data Platform</span></a>
  <div class="atlas-nav-links"><a href="#capabilities">Capabilities</a><a href="#workflow">Workflow</a><a href="#public-preview">Example data</a></div>
  <div class="atlas-account-actions"><a href="{% url 'login' %}">Sign in</a><a href="{% url 'register' %}">Create account</a></div>
</nav>
<section class="atlas-hero">
  <div class="atlas-hero-copy">
    <div class="atlas-kicker">FAIR materials simulation data</div>
    <h1>The material record behind every simulation.</h1>
    <p>Preserve the context around simulation results, validate structured metadata, and make research objects easier to find, review, and reuse.</p>
    <div class="atlas-actions">
      <a href="{% url 'search' %}">Search data</a>
      <a href="{% url 'upload_json' %}">Upload JSON</a>
    </div>
  </div>
  <div class="atlas-specimen" aria-hidden="true">
    <svg class="material-fingerprint" viewBox="0 0 620 560">
      <path class="fingerprint-field" d="M72 294C54 169 151 64 291 46c146-19 260 65 274 187 15 128-88 241-232 266C191 524 91 431 72 294Z"/>
      <path d="M112 292C96 194 173 108 286 91c119-18 216 50 230 149 15 104-69 195-188 216-114 20-200-57-216-164Z"/>
      <path d="M158 288C145 216 199 154 282 141c87-14 158 34 171 107 13 77-48 144-136 160-84 15-146-42-159-120Z"/>
      <path class="fingerprint-core" d="M208 281C199 237 231 198 279 190c52-8 96 20 105 65 10 48-27 89-80 99-50 9-87-26-96-73Z"/>
    </svg>
    <div class="specimen-label"><strong>Cu · FCC</strong><span>RVE-0249</span><span>DAMASK</span><span>Validated</span></div>
  </div>
</section>
```

The SVG must use nested organic contour paths in patina teal, oxidized copper, and deep mineral. It must not use grid backgrounds, editor chrome, code windows, or syntax-colored JSON.

- [ ] **Step 3: Build the three editorial capability panels**

Under `id="capabilities"`, implement three uneven panels with these exact headings and concise supporting text:

```html
<h2>Context turns files into research objects.</h2>
<article><h3>Preserve the whole record</h3><p>Upload one JSON file or a collection. Each valid object becomes an individual record while its simulation context stays intact.</p></article>
<article><h3>Find what matters</h3><p>Search practical metadata such as phase, identifier, creator, software, and keywords without crossing access boundaries.</p></article>
<article><h3>Review with confidence</h3><p>Read structured metadata, boundary conditions, and mechanical responses without working through raw JSON by hand.</p></article>
```

Use specimen-like labels such as `01 / INGEST`, `02 / DISCOVER`, and `03 / REVIEW` only as meaningful capability identifiers.

- [ ] **Step 4: Build the ordered workflow strip**

Under `id="workflow"`, render the real sequence as four linked steps:

```html
<ol class="atlas-workflow-list">
  <li><span>01</span><strong>Upload JSON</strong><p>Submit one or many simulation objects.</p></li>
  <li><span>02</span><strong>Validate and unwrap</strong><p>Keep valid records and surface clear metadata errors.</p></li>
  <li><span>03</span><strong>Control access</strong><p>Choose private, shared, or public visibility.</p></li>
  <li><span>04</span><strong>Search and review</strong><p>Find records and inspect the details that support reuse.</p></li>
</ol>
```

Use CSS connecting rules only between adjacent steps. Stack the sequence vertically below 760px.

- [ ] **Step 5: Restyle the synthetic dataset preview and footer**

Keep all three existing synthetic identifiers and the required privacy message. Introduce the heading `Example materials index`, the label `Materials Atlas`, and explicit `Synthetic example` badges. Preserve the footer's accurate platform, account, workflow, copyright, `Django UI`, and `JSON validation` content.

- [ ] **Step 6: Run the focused homepage test**

Run:

```powershell
.\.venv\Scripts\python.exe manage.py test apps.pages.tests -k public_home_page
```

Expected: `OK` with one matching test.

- [ ] **Step 7: Check the template diff**

Run:

```powershell
git diff --check -- templates/pages/index.html apps/pages/tests.py
```

Expected: no whitespace errors.

### Task 3: Verify Rendering, Responsiveness, and Project Health

**Files:**
- Modify if verification finds a defect: `templates/pages/index.html`
- Test: `apps/pages/tests.py`

**Interfaces:**
- Consumes: the completed homepage template and public homepage test contract.
- Produces: a visually inspected desktop and mobile homepage with a passing Django check and pages test module.

- [ ] **Step 1: Run Django validation and the pages tests**

Run:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test apps.pages.tests
```

Expected: `System check identified no issues` and all tests pass.

- [ ] **Step 2: Start the local server for visual inspection**

Run:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001 --noreload
```

Expected: Django serves the homepage at `http://127.0.0.1:8001/` without template errors.

- [ ] **Step 3: Inspect desktop and mobile layouts**

Capture the homepage at approximately `1440x1000` and `390x844`. Confirm:

```text
Desktop: hero copy and fingerprint balance without clipping; capability panels have intentional unequal proportions.
Mobile: navigation remains usable; hero and panels stack; no horizontal overflow; workflow reads top to bottom.
Both: synthetic label is clear; focus styles are visible; no IDE-style grid, console, or code panel remains.
```

- [ ] **Step 4: Run final regression checks**

Run:

```powershell
.\.venv\Scripts\python.exe manage.py test apps.pages.tests
.\.venv\Scripts\python.exe manage.py check
git diff --check
```

Expected: tests pass, Django reports no issues, and Git reports no whitespace errors.

- [ ] **Step 5: Commit only the homepage redesign if the overlapping worktree is cleanly separable**

Run:

```powershell
git add -- templates/pages/index.html
git diff --cached --check
git commit -m "feat: redesign public homepage as materials atlas"
```

Because `apps/pages/tests.py` already contains unrelated uncommitted work, stage its focused homepage-test hunk only when it can be separated without including unrelated changes. Otherwise leave the implementation uncommitted and report that constraint clearly.
