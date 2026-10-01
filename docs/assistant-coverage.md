# Assistant help coverage

The initial catalogue has 82 topics: 76 prepared guides across nine general
categories, plus six summaries of the current accessible object. Questions may
be typed in English or Chinese; answers and navigation remain in English.
The local embedding model selects prepared answers. It does not generate answers
or train on questions or uploaded data.

## Task coverage and sources

| Category | Topics | Covered tasks | Maintained sources |
| --- | ---: | --- | --- |
| Getting started | 4 | Platform workflow, reopening the tour, backups, support availability | `README.md`, `apps/pages/getting_started.py`, `templates/includes/navigation.html` |
| Prepare data | 9 | JSON structure and templates, required fields, identifiers, field names, wrappers, nested requirements, units, phase names | `apps/dyn_api/metadata_compat.py`, `apps/dyn_api/required_schema.py`, `apps/dyn_api/helpers.py`, upload services, bundled schemas, README validation rules |
| Upload help | 11 | Submitting files, corrections, allowances, interruptions, atomic files, progress, JSON syntax, sharing errors, storage, rate limits, navigation | `apps/pages/views.py`, `apps/pages/upload_services.py`, `apps/pages/upload_jobs.py`, `config/settings.py`, upload template |
| Search help | 8 | Keywords and advanced filters, empty results, Kelvin ranges, booleans, bookmarks, public activity, Creator versus Owner | `apps/pages/views.py`, search field presets and tests, README search rules |
| Access and sharing | 8 | Public/private access, adding and removing recipients, received objects, history, visibility changes, reuse rights, unavailable links | `apps/pages/views.py`, `apps/pages/models.py`, detail and Share templates |
| My Data | 10 | Own uploads, filters, selection, downloads, deletion, editing limits, export formats, choosing CSV columns, CSV failures, recovery limits | `apps/pages/views.py`, `apps/pages/mechanical_csv.py`, My Data/detail templates |
| Reading data and plots | 6 | Metadata display, tensor arrows, strain illustration, missing curves, units, analysis limits | Detail template, metadata compatibility and mechanical curve helpers, README detail rules |
| Charts | 7 | Dataset coverage, counting, combined filters, temperature coverage, quality notes, opening detail curves and their image/data exports | `apps/charts/analytics.py`, `apps/charts/plots.py`, `apps/charts/views.py`, Charts and detail templates |
| Account | 13 | Registration, password change/recovery, ORCID connection/setup/profile/disconnection/failure, sessions, settings, notifications, deletion limits, login failures | `apps/pages/forms.py`, `apps/pages/auth_views.py`, `apps/pages/orcid_auth.py`, `apps/pages/orcid_profile.py`, `apps/pages/session_policy.py`, account views/templates |
| Current object | 6 | Summary, phase, software, mechanical boundaries, available curves, access | Authorized assistant branches in `apps/pages/views.py` and shared metadata helpers |

Object topics are shown in the menu only on an authorized detail page. Asking an
object question elsewhere explains how to open an object. Every request with an
object reference checks its current permissions again, including after sharing
is revoked.

## Navigation and conversations

**Browse help topics** opens the categories and clears the previous topic.
Each category shows at most six questions, with adjacent page buttons. Page
buttons contain their category and page, so they still work after context
expires or semantic matching becomes unavailable. Within a category menu,
`more`/`next` and `back`/`previous` navigate pages; English and Chinese numbered
choices select one of the six visible questions. Page navigation buttons are
not counted as question choices.

Answers suggest related questions and use read-only page links. Following a link
does not upload, delete, share, sign out or connect an identity. A complete new
question can change the topic. Specific short follow-ups include upload fields,
size and formats, deletion recovery, and sharing instructions. Revocation and
visibility follow-ups retain their original direction instead of becoming
instructions to add a share.

An ambiguous phrase such as `data form`, `password` or `ORCID` offers relevant
choices. Similar meanings may need a clarification even when the general intent
is recognized. Unknown or unrelated questions return platform help. Menu buttons
work without the model; natural-language coverage is not guaranteed.

## Boundaries that answers must preserve

- There is no email verification or self-service email password reset. ORCID
  sign-in does not bypass the current-password requirement for changing an
  existing usable local password. Linking ORCID never merges accounts by email.
- There is no current interface for changing an existing object's public/private
  mode, editing stored JSON, restoring deleted records, or deleting an account.
  Re-uploading an existing identifier never overwrites that record.
- Public still requires sign-in. A copied URL, old notification or sharing-history
  event does not grant current access. Access and reuse rights are separate.
- JSON export preserves stored fields and values, not the byte-for-byte original
  source file. Selected JSON exports skip unavailable objects; selected CSV
  exports reject the whole selection if any object is inaccessible or has no
  exportable curves. CSV is not a native XLSX workbook.
- Upload success and Charts availability do not establish scientific correctness.
  Missing results, units and intermediate tensor steps are not invented.
- Charts summarizes the accessible dataset. Individual curves and PNG/CSV
  controls are on data detail pages; Charts does not offer Save SVG.
- The assistant does not inspect selected files, execute searches or data
  operations, run simulations, fit material properties, contact administrators
  or transfer to a human. Upload allowances and quota guidance read active settings.

## Maintaining coverage

Add a focused topic to `apps/pages/assistant_knowledge.py` only after checking
its answer against current code. Keep its stable ID, canonical question, a small
set of explicit aliases, varied representative questions, and a useful existing
page link. Use `category` when a stable ID belongs under a different heading;
optional `related` IDs should point to the next useful tasks. Do not invent
unimplemented controls or add external links that imply a supported service.

Run all assistant tests with a locally prepared model, `DEBUG=True`, SQLite,
Chromium and a Node runtime with global `WebSocket`:

```bash
python manage.py test apps.pages --pattern='test_assistant*.py' --noinput
node --test tests/js/*.test.cjs
```

Use the configured project interpreter as described in the main README. The
coverage tests traverse every general topic through actual category page buttons,
check signed ordinal/page follow-ups and verify unsupported-feature guidance.
Existing tests retain authorization, expired/forged context, model failure,
offline matching and data-preservation checks. The browser test checks menu
paging, natural questions, retry behavior and 18 desktop layouts at 1280, 1440
and 1920 pixels wide, including long content and an empty account.
Its HTTP server processes requests sequentially because the live-server fixture
shares one in-memory SQLite connection. This avoids concurrent statement-cache
errors from background page requests; it is a UI check, not a load test.

The original 52-turn corpus remains a regression set. A privacy question may now
offer both access and revocation guidance instead of forcing the old single
answer. `apps/pages/fixtures/assistant_expanded_questions.json` preserves another
40 scenarios / 43 turns written independently before the expansion was inspected.
Its first evaluation found 16 core direct answers, 11 useful clarifications and
16 misses or incomplete answers; these prompted improvements to notifications,
export formats, account guidance and short follow-ups. Once used for improvements,
those questions become regressions, not an unseen accuracy benchmark.

The later `apps/pages/fixtures/assistant_followup_questions.json` preserves ten
additional questions, fixed before their first evaluation. That first evaluation
found four core direct answers, two useful clarifications and four failures:
CSV column selection, recalling downloaded copies, and two external-service
questions. The fixes add column-selection guidance, revocation wording and
outside-platform examples. These are also now regression questions.

The automated regressions check direct answers or relevant choices, five
platform-scope responses and one access denial across 105 turns. Separate factual
review must still compare an answer with the fixture's required facts and
prohibited claims; a passing topic ID is insufficient.

Final independent HTTP review of the added 53 turns found 34 core direct answers,
17 useful clarifications and two appropriate platform-scope responses. All
requests returned HTTP 200 and preserved stored data. Strictly matching the
precommitted response form and details was 52/53: “Which download do I need?”
received a correct JSON/CSV overview instead of the expected clarification.
Those results describe these now-seen questions, not arbitrary future wording.

For future quality checks, write new questions before inspecting matching results,
and report direct answers, useful clarifications and misses separately. A topic
being reachable by a menu does not prove that arbitrary wording finds it.
