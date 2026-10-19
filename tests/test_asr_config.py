from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).parents[1]


class AsrConfigurationTests(unittest.TestCase):
    def test_pi_defaults_to_accurate_english_model(self) -> None:
        compose = (PROJECT_DIR / "docker-compose.asr.yml").read_text(encoding="utf-8")
        dockerfile = (PROJECT_DIR / "services/faster-whisper/Dockerfile").read_text(
            encoding="utf-8"
        )
        server = (PROJECT_DIR / "services/faster-whisper/server.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('${FASTER_WHISPER_MODEL:-small.en}', compose)
        self.assertIn("ARG MODEL_SIZE=small.en", dockerfile)
        self.assertIn('os.getenv("FASTER_WHISPER_MODEL", "small.en")', server)
        self.assertIn('os.getenv("FASTER_WHISPER_MODEL_PATH", f"/models/{MODEL}")', server)

    def test_decoder_uses_accuracy_and_aviation_hints(self) -> None:
        server = (PROJECT_DIR / "services/faster-whisper/server.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("beam_size=BEAM_SIZE", server)
        self.assertIn("condition_on_previous_text=False", server)
        self.assertIn("initial_prompt=INITIAL_PROMPT", server)
        self.assertIn("hotwords=HOTWORDS", server)
        self.assertIn('"min_silence_duration_ms": 350', server)
        self.assertIn('"speech_pad_ms": 250', server)

        downloader = (PROJECT_DIR / "services/faster-whisper/download_model.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("/api/models/", downloader)
        self.assertIn("SHA-256 checksum mismatch", downloader)
        self.assertIn("hf-mirror.net", downloader)
        self.assertIn("modelscope.cn/models/pengzhendong", downloader)
        self.assertIn("16 * 1024 * 1024", downloader)

    def test_asr_is_a_separate_tailscale_bound_service(self) -> None:
        pi_compose = (PROJECT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
        asr_compose = (PROJECT_DIR / "docker-compose.asr.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("DIALOGUE_ASR_URL: ${DIALOGUE_ASR_URL:?", pi_compose)
        self.assertNotIn("  faster-whisper:", pi_compose)
        self.assertIn('"${ASR_BIND_ADDRESS:-127.0.0.1}:${ASR_PORT:-8903}:8803"', asr_compose)

    def test_llm_is_a_separate_tailscale_bound_mac_service(self) -> None:
        pi_compose = (PROJECT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
        mac_compose = (PROJECT_DIR / "docker-compose.asr.yml").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("  ollama:\n", pi_compose)
        self.assertIn("DIALOGUE_OLLAMA_URL: ${DIALOGUE_OLLAMA_URL:-", pi_compose)
        self.assertIn('"${LLM_BIND_ADDRESS:-127.0.0.1}:${OLLAMA_PORT:-8904}:11434"', mac_compose)
        self.assertIn("OLLAMA_MODEL_URL", mac_compose)
        self.assertIn("modelscope.cn/models/unsloth/gemma-4-E2B-it-GGUF", mac_compose)
        self.assertIn("ollama create", mac_compose)

        downloader = (PROJECT_DIR / "services/ollama-model/download_model.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("CHUNK_SIZE = 16 * 1024 * 1024", downloader)
        self.assertIn("SHA-256 checksum mismatch", downloader)


if __name__ == "__main__":
    unittest.main()
