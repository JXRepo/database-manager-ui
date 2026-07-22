# Materials Atlas Homepage Design

## Purpose

Redesign the public homepage so it reads as a trusted materials simulation data platform, not an IDE, dashboard template, or generic software landing page.

The primary audience is materials simulation researchers encountering the platform for the first time. The page has one job: establish credibility quickly and direct visitors to search existing data or upload their own JSON records.

## Chosen Direction

Use the **Materials Atlas** direction.

The visual concept comes from material morphology maps, contour plots, specimen labels, and archive records. Its signature element is a large irregular "material fingerprint": nested contour lines with a small specimen label attached. This replaces the current layered grids, crystal badge, and code-like metadata console that make the page resemble a development tool.

The page should feel scientific and precise without looking clinical. The fingerprint is the one expressive element; surrounding layout, cards, and typography remain restrained.

## Visual System

### Color

- Mineral mist `#EDF3F4`: primary page background
- Paper white `#FBFDFD`: elevated surfaces
- Deep mineral `#163F40`: headings, primary buttons, footer
- Oxidized copper `#C9573D`: focal points and small status accents
- Patina teal `#55A8A3`: contour lines and supporting highlights
- Slate ink `#334A4E`: body text

Avoid dark editor surfaces, neon gradients, terminal green, and full-page graph paper. Fine rules may appear only where they organize real data.

### Typography

- Display: Georgia with a restrained editorial treatment for the hero and major section headings
- Body: the project's existing Open Sans webfont
- Data labels: a system monospace stack used only for identifiers, units, and specimen metadata

The type contrast should signal "research atlas" rather than "developer console." Headings use tight letter spacing; body text stays compact and readable.

### Shape and Motion

- Use soft rectangular surfaces with 12–18px corners, not a repeated grid of identical SaaS cards
- Keep shadows subtle and cool-toned
- Animate only the hero fingerprint and initial hero reveal
- Respect `prefers-reduced-motion`
- Hover states should shift position or color by a small, controlled amount

## Page Structure

### Navigation

Use a compact public navigation bar with the platform name, in-page links for capabilities, workflow, and example data, plus `Sign in` and `Create account` actions. Remove the crowded row of authenticated application routes from the public header.

### Hero

Use a two-column composition:

- Left: FAIR materials data label, a concise thesis headline, supporting copy, `Search data` primary action, and `Upload JSON` secondary action
- Right: the material fingerprint SVG and a small specimen label showing a realistic material phase, identifier, solver, and validation state

The proposed headline is: **The material record behind every simulation.**

Supporting copy should explain that the platform preserves simulation context, validates JSON metadata, controls access, and makes datasets discoverable without sounding like a feature checklist.

### Capabilities

Use three uneven editorial panels rather than four identical numbered cards:

- Preserve context: upload and unwrap one or many JSON objects
- Find useful records: search practical metadata while enforcing access rules
- Review with confidence: inspect metadata, boundary conditions, and mechanical responses

Use field labels and material vocabulary as quiet details, never as code snippets.

### Workflow

Keep the real ordered sequence because order carries meaning:

1. Upload JSON
2. Validate and unwrap
3. Control access
4. Search and review

Present it as a horizontal specimen-processing strip on desktop and a vertical sequence on mobile.

### Example Data

Keep the existing synthetic example dataset requirement and do not expose database records on the public page. Restyle examples as a compact materials index with visible phase, software, and synthetic status.

### Footer

Use the deep mineral color. Keep essential platform, account, and workflow links, but simplify the visual weight and retain existing footer wording required by tests where it remains accurate.

## Behavior and Data

No backend or data model changes are required. Existing Django URL names remain unchanged. The homepage remains public, authenticated visitors continue to be redirected by the existing view, and synthetic preview records remain hard-coded presentation content.

All secure routes continue to rely on Django view permissions. The homepage redesign must not imply that protected records are publicly accessible.

## Responsive and Accessibility Requirements

- Preserve a useful layout from 320px mobile width upward
- Collapse navigation cleanly without hiding account actions
- Convert hero and editorial grids to a single column on small screens
- Keep all text selectable; the fingerprint SVG is decorative and hidden from assistive technology
- Provide visible keyboard focus styles
- Maintain adequate text and control contrast
- Disable nonessential motion when reduced motion is requested

## Verification

- Update the public homepage test to assert the new headline, signature element, synthetic examples, and absence of real records
- Keep URL and authentication behavior unchanged
- Run the focused homepage test, the relevant pages test module, and `manage.py check`
- Render the page at desktop and mobile widths and inspect screenshots for layout overflow, hierarchy, and visual regressions

## Scope Boundaries

This change redesigns only the public homepage and its directly associated test expectations. It does not redesign authenticated search, upload, detail, login, or registration pages, and it introduces no new package or image dependency.
