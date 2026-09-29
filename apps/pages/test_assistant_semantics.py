import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings


class AssistantSemanticsTests(SimpleTestCase):
    """
    Exercise the real local encoder and its setup boundary
    """

    def test_real_model_matches_meaning_without_runtime_network(self):
        """
        Rank paraphrases using the installed model while all HTTP is blocked
        """
        from .assistant_semantics import rank_topics

        examples = (
            ("privacy", "Keep my research results confidential"),
            ("delete", "Delete a stored simulation object"),
            ("upload", "Submit a JSON file to the platform"),
        )
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Runtime network")):
            self.assertEqual(rank_topics("I want to erase my old simulations", examples)[0][0], "delete")
            self.assertEqual(rank_topics("我不想让别人看到我的研究数据", examples)[0][0], "privacy")

    def test_missing_model_never_downloads_during_a_question(self):
        """
        Fail locally so the caller can retain prepared help choices
        """
        from .assistant_semantics import ModelUnavailable, rank_topics

        with tempfile.TemporaryDirectory() as directory, override_settings(ASSISTANT_MODEL_DIR=directory):
            with patch("requests.sessions.Session.request", side_effect=AssertionError("Runtime network")):
                with self.assertRaises(ModelUnavailable):
                    rank_topics("Where are my results?", (("mine", "Find my uploaded data"),))

    def test_corrupt_assets_are_not_loaded(self):
        """
        Reject modified model bytes before passing them to the native runtime
        """
        from .assistant_semantics import assets_ready

        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "model.onnx").write_bytes(b"not a trusted model")
            Path(directory, "sentencepiece.bpe.model").write_bytes(b"not a vocabulary")
            self.assertFalse(assets_ready(Path(directory)))

    def test_setup_reuses_verified_files_without_network(self):
        """
        Make repeated setup safe when model assets are already present
        """
        from .assistant_semantics import model_directory, prepare_model

        with patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected download")):
            self.assertEqual(prepare_model(), model_directory())

    def test_setup_rejects_changed_bytes_and_cleans_partial_downloads(self):
        """
        Verify both download integrity and atomic replacement using a small asset
        """
        from .assistant_semantics import MODEL_REVISION, prepare_model

        content = b"verified public asset"
        assets = (("model.onnx", "onnx/model.onnx", len(content), hashlib.sha256(content).hexdigest()),)
        with tempfile.TemporaryDirectory() as directory, override_settings(ASSISTANT_MODEL_DIR=directory):
            target = Path(directory, "model.onnx")
            target.write_bytes(b"previous incomplete asset")
            with patch("apps.pages.assistant_semantics.MODEL_FILES", assets), patch("requests.get") as download:
                response = download.return_value.__enter__.return_value
                for chunks in ([b"x" * len(content)], [content, b"oversized"]):
                    response.iter_content.return_value = iter(chunks)
                    with self.assertRaises(ValueError):
                        prepare_model()
                    self.assertEqual(target.read_bytes(), b"previous incomplete asset")
                    self.assertEqual(list(Path(directory).iterdir()), [target])
                response.iter_content.return_value = iter([content])
                prepare_model()
                self.assertEqual(target.read_bytes(), content)
                self.assertIn("/resolve/" + MODEL_REVISION + "/", download.call_args.args[0])

    def test_reference_token_ids_and_token_limit(self):
        """
        Check fixed XLM-R reference IDs and truncation before native inference
        """
        import numpy as np
        from .assistant_semantics import _encoder, model_directory

        encoder = _encoder(model_directory())
        examples = (
            ("Hello world", [0, 35378, 8999, 2]),
            ("我想上传数据", [0, 6, 23638, 186907, 12833, 2]),
            ("café\n数据 — 🧪", [0, 26216, 6, 12833, 292, 6, 3, 2]),
            ("x " * 150, [0] + [1022] * 126 + [2]),
        )
        with patch.object(encoder, "session") as session:
            session.run.return_value = [np.ones((1, 128, 384), dtype=np.float32)]
            for text, expected in examples:
                session.run.return_value = [np.ones((1, len(expected), 384), dtype=np.float32)]
                vector = encoder.encode([text])
                inputs = session.run.call_args.args[1]
                self.assertEqual(inputs["input_ids"].tolist(), [expected])
                self.assertTrue((inputs["attention_mask"] == 1).all())
                self.assertTrue((inputs["token_type_ids"] == 0).all())
                self.assertAlmostEqual(float(np.linalg.norm(vector[0])), 1, places=6)

    def test_embedding_does_not_depend_on_other_index_entries(self):
        """
        Keep quantized sentence vectors consistent between indexing and queries
        """
        import numpy as np
        from .assistant_semantics import _encoder, model_directory

        encoder = _encoder(model_directory())
        query = "How do I share a private object with a colleague?"
        alone = encoder.encode([query])[0]
        together = encoder.encode(["数据格式是什么？", query, "Remove old simulation records"])[1]
        np.testing.assert_allclose(alone, together, atol=1e-6)
