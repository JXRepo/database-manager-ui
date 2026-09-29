# Platform assistant understanding

The user approved a locally operated assistant that matches meaning to maintained
platform answers and asks short clarifying questions. The existing literal FAQ
misses ordinary expressions such as `data form`; a working menu is insufficient.

## Accepted scope

- Keep the current English widget and Django endpoint, with no model API service,
  generated factual answers, human handoff, data mutations, or model training.
- Match English and Chinese paraphrases to maintained platform topics using a
  pretrained sentence embedding model running on CPU. Exact menu selections
  remain deterministic. Explicit aliases and conservative typo correction may
  supplement semantic retrieval, but must not replace it.
- Clarify `data form` with JSON format and upload form choices. Short replies
  such as `format`, `the second one`, and topic follow-ups use the last response.
  A new complete question may change topics; unrelated questions do not inherit
  a previous data object answer.
- Store only a signed, expiring topic/choice token in page memory. Bind it to the
  signed-in user and current object. Recheck object access on every request.
- Keep answers grounded in current README, code, and bundled schema. Add useful
  format/template guidance and the actual required field list, not just a count.
- Keep existing permissions, original JSON, upload behavior, and exports intact.
- Use a pinned public model snapshot with SHA-256 verification, fetched during
  setup/build only. Do not commit weights. Runtime questions never leave Django.
- Keep model work bounded (128 tokens, one CPU thread, serialized inference),
  avoid retaining questions or object contents in a model cache, and retain
  explicit help choices if the model is unavailable.
- Verify natural questions, ambiguity, topic switches, unsupported requests,
  access revocation, request failures, and desktop layouts in a real browser.

## Model feasibility

The quantized `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
snapshot `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` has a 118,453,870-byte
ONNX file. Use its 5,069,051-byte SentencePiece vocabulary with XLM-R token ID
alignment and attention-mask mean pooling. A local throwaway probe using
ONNX Runtime 1.23.2 and SentencePiece 0.2.1 used about 248 MiB resident memory
including Django setup, with a 330 MiB initialization peak. These measurements
do not establish Render capacity under concurrent uploads.

Sources: [model card](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2),
[token ID alignment](https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/models/xlm_roberta/tokenization_xlm_roberta.py).

## Acceptance examples

- `data form` -> clarify; `format` -> JSON layout; `which fields?` -> required fields.
- `My file will not go through` -> upload corrections.
- `I want to erase my old simulations` -> deletion guidance, never deletion.
- `我不想让别人看到我的结果` -> privacy guidance.
- `weather tomorrow` -> platform scope, never temperature filtering.
- A data object shared then revoked is inaccessible even with an earlier token.

The evaluation corpus is separate from the retrieval examples. Exact matching
of known questions alone does not count as semantic verification.

## Completed evaluation

The independent initial corpus had 35 scenarios and 42 turns. Its questions were
not copied into retrieval examples. A further 10 questions were written after
the initial evaluation. Both sets are now preserved as regressions in
`apps/pages/fixtures/assistant_questions.json`; they have informed iteration and
are not an untouched measure of generalization.

The final real HTTP run used authenticated sessions, CSRF, signed follow-ups and
an isolated SQLite database. Of 52 turns, 33 gave correct direct answers, 15 offered
the correct topic for clarification, 3 handled unrelated questions and 1 rejected
revoked access. Against the originally specified response types and candidate
combinations, 42/52 passed (36/42 original and 6/10 later questions). Some expected
direct answers still require a choice, and some choices include unrelated topics.
The regression test explicitly checks usefulness, not a claim of perfect accuracy.

The full Python 3.10.12 HTTP test process used 279.453 MiB resident memory after
52 questions and peaked at 356.883 MiB, including setup. The first question took
1.0581 seconds; 50 later successful serial requests had a 6.55 ms median and
9.6 ms P95. These include both semantic and deterministic responses on local
loopback, with no concurrent upload workload. Each web worker loads its own
encoder; the existing single-worker deployment and separate upload process remain.

38 targeted Django tests and 117 JavaScript tests passed, with no skipped browser
checks. Chromium exercised follow-ups, topic changes, manual retries and 12 desktop
layouts. Download integrity, native inference failure, missing files, runtime
network isolation, context expiry/binding and access revocation are covered.
Natural-text token IDs were checked against the pinned reference tokenizer;
SentencePiece treats markup-like control strings as literal question text.
