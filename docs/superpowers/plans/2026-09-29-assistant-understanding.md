# Assistant Understanding Implementation Plan

> **For agentic workers:** Execute the approved tasks below and obtain an independent final code review. The user has authorized implementation and the usual verified commit/push workflow.

**Goal:** Make ordinary platform questions and short follow-ups useful without an external AI service.

**Architecture:** Maintain trusted answers separately from semantic retrieval examples. A pinned local ONNX encoder ranks topics; dialogue code resolves clear requests or offers choices. Django signs the minimal conversation state and independently checks data access.

**Tech Stack:** Existing Django, NumPy, ONNX Runtime 1.23.2, SentencePiece 0.2.1, existing Chromium test harness.

**Spec:** `docs/superpowers/specs/2026-09-29-assistant-understanding.md`

## Global constraints

- English UI, comments, and docstrings; docstring summary has no final period.
- No external question processing, model training, live support, or data writes.
- Original JSON and server-side permissions remain unchanged.
- Model assets are ignored locally and fetched only during setup/build.
- Browser verification is desktop only and must actually run.

## Task 1: Reproducible local sentence matching

Files: `apps/pages/assistant_semantics.py`, `apps/pages/management/commands/prepare_assistant_model.py`,
`apps/pages/test_assistant_semantics.py`, `requirements.txt`, `build.sh`, `.gitignore`.

- [x] Add failing tests for local asset integrity, real paraphrase ranking,
  unavailable-model behavior, token ID alignment and bounded encoding.
- [x] Implement `prepare_model()` with fixed URLs, sizes and hashes,
  temporary downloads and atomic replacement; cached valid files avoid network.
- [x] Implement `rank_topics(question, examples)` returning topic/score pairs,
  with lazy initialization under a lock, CPU-only execution and no runtime fetch.
- [x] Check the real encoder against reference tokenizer IDs and related versus
  unrelated phrases. Keep model readiness separate from answer correctness.
- [x] Add setup to the build, preserving collectstatic and migrations.

## Task 2: Grounded dialogue and real question coverage

Files: `apps/pages/assistant.py`, `apps/pages/assistant_knowledge.py`,
`apps/pages/views.py`, `apps/pages/test_assistant_dialogue.py`,
`apps/pages/test_assistant_acceptance.py`,
`apps/pages/fixtures/assistant_questions.json`.

Interfaces: `help_reply(question, has_object=False, context=None)` returns the
existing reply keys plus internal `conversation`; `_build_assistant_answer`
accepts the same optional context. The HTTP endpoint returns a signed `context`
string and consumes it on the next request.

- [x] Add failing HTTP tests for `data form`, clarification choices, short
  follow-ups, a changed topic, missing/expired/forged context, and revoked access.
- [x] Build semantic examples from supported topics; keep evaluation questions
  separate. Score only complete examples, not single broad words like temperature.
- [x] Add JSON format/template guidance and actual required fields.
- [x] Use confidence and candidate separation to answer, clarify, or state scope.
  Do not silently guess the user's meaning from an ambiguous short phrase.
- [x] Keep exact menus and current data summaries functional during model failure.
- [x] Bind signed context to user/object, expire after 30 minutes, and reset on
  Browse help topics. Never put questions or data values into context tokens.
- [x] Run real corpus evaluation and report direct/candidate/unsupported results.

## Task 3: Browser integration, resource checks and delivery

Files: `templates/includes/fair_assistant.html`, `tests/browser/assistant.cjs`,
`apps/pages/test_assistant_browser.py`, `README.md`, `HANDOFF.md`.

- [x] Send the latest context token with the next question; preserve it on a
  connection failure and replace it only after a successful response.
- [x] Verify typed clarification, numbered choices, topic switches, manual retry,
  safe text rendering, and 1280/1440/1920 desktop layouts against Django.
- [x] Run relevant Django suites and `node --test tests/js/*.test.cjs`.
- [x] Measure a fresh process with the model and authenticated help requests;
  document the measured limits without claiming production capacity.
- [x] Independently review implementation and realistic questions; resolve
  material findings, update setup/handoff, inspect diff, commit, and push.

Verification commands use the interpreter resolved by PyCharm immediately before
each Python invocation, with `DEBUG=True` and local SQLite only. Model setup:
`manage.py prepare_assistant_model`. Relevant tests include the assistant suites,
phase names, and the existing four assistant permission/input tests in pages.tests.

Verification completed: 38 targeted Django tests, 117 JavaScript tests, 12 real
desktop layouts, verified model setup and dependency consistency. Independent
HTTP evaluation: 33 direct answers, 15 useful clarifications, 3 scope replies and
1 access rejection across 52 turns; strict original expectations passed 42/52.
Resource measurements and remaining clarification limits are recorded in the spec.
