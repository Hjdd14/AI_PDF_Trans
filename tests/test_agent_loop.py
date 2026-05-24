"""Tests for the ReAct agent loop with mocked LiteLLM responses."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from src.agent_runtime import AgentRuntime
from src.models.config import LLMConfig, AppConfig
from tests.conftest import DATA_DIR


# ─── Helper: build mock LiteLLM responses ────────────────────────────────────

def _make_mock_response(tool_calls=None, content=None):
    """Create a mock LiteLLM completion response."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls

    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"

    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    usage.total_tokens = 15

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_tool_call(name, arguments, id_suffix="1"):
    """Create a mock LiteLLM tool call."""
    tc = MagicMock()
    tc.id = f"call_{id_suffix}"
    tc.type = "function"
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments) if isinstance(arguments, dict) else arguments
    return tc


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestAgentInit:
    def test_creates_instance(self):
        llm = LLMConfig(model_name="test-model", api_key="test-key")
        app = AppConfig()
        agent = AgentRuntime(llm, app, DATA_DIR)
        assert agent.llm_config is llm
        assert agent.app_config is app
        assert agent.data_dir == DATA_DIR
        assert agent._cancelled is False
        assert agent._tool_call_count == 0
        assert agent._max_tool_calls == 500

    def test_cancel_flag(self):
        agent = AgentRuntime(LLMConfig(), AppConfig(), DATA_DIR)
        assert agent._cancelled is False
        agent.cancel()
        assert agent._cancelled is True


class TestAgentLoop:
    def test_translation_complete_immediately(self, temp_dir, fake_pdf):
        """LLM returns translation_complete → loop ends successfully."""
        llm = LLMConfig(model_name="test-model", api_key="test-key")
        app = AppConfig()
        agent = AgentRuntime(llm, app, DATA_DIR)
        agent._max_tool_calls = 5

        # Create the PDF that translation_complete will find
        working_pdf = os.path.join(temp_dir, "work_dir", "output.pdf")
        os.makedirs(os.path.dirname(working_pdf), exist_ok=True)
        with open(working_pdf, "w") as f:
            f.write("fake pdf content")

        final_output = os.path.join(temp_dir, "final_output.pdf")

        mock_tc = _make_tool_call("translation_complete", {
            "output_pdf_path": working_pdf,
            "summary": "Completed test translation.",
        }, id_suffix="complete")

        with patch("litellm.completion", return_value=_make_mock_response(tool_calls=[mock_tc])):
            result = agent.run(fake_pdf, final_output)

        assert result == final_output
        assert os.path.isfile(final_output), "Output PDF should have been copied"

    def test_tool_then_complete(self, temp_dir, fake_pdf):
        """LLM calls a regular tool, then translation_complete on second turn."""
        llm = LLMConfig(model_name="test-model", api_key="test-key")
        app = AppConfig(target_lang="Chinese")
        agent = AgentRuntime(llm, app, DATA_DIR)
        agent._max_tool_calls = 10

        working_pdf = os.path.join(temp_dir, "work", "output.pdf")
        os.makedirs(os.path.dirname(working_pdf), exist_ok=True)
        with open(working_pdf, "w") as f:
            f.write("fake pdf content")

        final_output = os.path.join(temp_dir, "final.pdf")

        # First call: get_font_info
        tc1 = _make_tool_call("get_font_info", {"target_lang": "chinese"}, id_suffix="1")
        # Second call: translation_complete
        tc2 = _make_tool_call("translation_complete", {
            "output_pdf_path": working_pdf,
            "summary": "Done",
        }, id_suffix="2")

        mock = MagicMock()
        mock.side_effect = [
            _make_mock_response(tool_calls=[tc1]),
            _make_mock_response(tool_calls=[tc2]),
        ]

        with patch("litellm.completion", mock):
            result = agent.run(fake_pdf, final_output)

        assert result == final_output
        assert agent._tool_call_count == 2

    def test_text_only_response_then_complete(self, temp_dir, fake_pdf):
        """LLM returns text-only, then translation_complete."""
        llm = LLMConfig(model_name="test-model", api_key="test-key")
        app = AppConfig()
        agent = AgentRuntime(llm, app, DATA_DIR)
        agent._max_tool_calls = 10

        working_pdf = os.path.join(temp_dir, "work", "output.pdf")
        os.makedirs(os.path.dirname(working_pdf), exist_ok=True)
        with open(working_pdf, "w") as f:
            f.write("fake pdf")

        final_output = os.path.join(temp_dir, "final.pdf")

        # First call: text-only (LLM thinking)
        text_resp = _make_mock_response(content="I will start by analyzing the PDF structure.")
        # Second call: translation_complete
        tc = _make_tool_call("translation_complete", {
            "output_pdf_path": working_pdf,
            "summary": "Done",
        }, id_suffix="2")

        mock = MagicMock()
        mock.side_effect = [text_resp, _make_mock_response(tool_calls=[tc])]

        with patch("litellm.completion", mock):
            result = agent.run(fake_pdf, final_output)

        assert result == final_output
        assert agent._tool_call_count == 1


class TestAgentErrorHandling:
    def test_invalid_tool_name(self, temp_dir, fake_pdf):
        """LLM calls an undefined tool → error message added to messages."""
        llm = LLMConfig(model_name="test-model", api_key="test-key")
        app = AppConfig()
        agent = AgentRuntime(llm, app, DATA_DIR)
        agent._max_tool_calls = 10

        working_pdf = os.path.join(temp_dir, "work", "output.pdf")
        os.makedirs(os.path.dirname(working_pdf), exist_ok=True)
        with open(working_pdf, "w") as f:
            f.write("fake pdf")
        final_output = os.path.join(temp_dir, "final.pdf")

        # First call: unknown tool
        tc1 = _make_tool_call("nonexistent_tool", {}, id_suffix="1")
        # Second call: translation_complete
        tc2 = _make_tool_call("translation_complete", {
            "output_pdf_path": working_pdf,
            "summary": "Done",
        }, id_suffix="2")

        mock = MagicMock()
        mock.side_effect = [
            _make_mock_response(tool_calls=[tc1]),
            _make_mock_response(tool_calls=[tc2]),
        ]

        with patch("litellm.completion", mock):
            result = agent.run(fake_pdf, final_output)

        assert result == final_output
        error_msgs = [m for m in agent._messages if "unknown tool" in m.get("content", "").lower()]
        assert len(error_msgs) >= 1

    def test_invalid_json_args(self, temp_dir, fake_pdf):
        """LLM sends invalid JSON → error message added to messages."""
        llm = LLMConfig(model_name="test-model", api_key="test-key")
        app = AppConfig()
        agent = AgentRuntime(llm, app, DATA_DIR)
        agent._max_tool_calls = 10

        working_pdf = os.path.join(temp_dir, "work", "output.pdf")
        os.makedirs(os.path.dirname(working_pdf), exist_ok=True)
        with open(working_pdf, "w") as f:
            f.write("fake pdf")
        final_output = os.path.join(temp_dir, "final.pdf")

        # Tool call with INVALID json arguments
        tc_bad = _make_tool_call("get_font_info", "not valid json{{{", id_suffix="1")
        tc_good = _make_tool_call("translation_complete", {
            "output_pdf_path": working_pdf,
            "summary": "Done",
        }, id_suffix="2")

        mock = MagicMock()
        mock.side_effect = [
            _make_mock_response(tool_calls=[tc_bad]),
            _make_mock_response(tool_calls=[tc_good]),
        ]

        with patch("litellm.completion", mock):
            result = agent.run(fake_pdf, final_output)

        assert result == final_output
        error_msgs = [m for m in agent._messages if "invalid json" in m.get("content", "").lower()]
        assert len(error_msgs) >= 1


class TestAgentCancellation:
    def test_cancel_during_loop(self, temp_dir, fake_pdf):
        """Calling cancel() while loop is running should raise InterruptedError."""
        llm = LLMConfig(model_name="test-model", api_key="test-key")
        app = AppConfig()
        agent = AgentRuntime(llm, app, DATA_DIR)

        final_output = os.path.join(temp_dir, "final.pdf")

        tc = _make_tool_call("get_font_info", {"target_lang": "chinese"}, id_suffix="1")

        with patch("litellm.completion", return_value=_make_mock_response(tool_calls=[tc])):
            agent.cancel()
            with pytest.raises(InterruptedError):
                agent.run(fake_pdf, final_output)

    def test_cancel_before_run(self, temp_dir, fake_pdf):
        """Cancel before run starts should immediately raise."""
        llm = LLMConfig(model_name="test-model", api_key="test-key")
        app = AppConfig()
        agent = AgentRuntime(llm, app, DATA_DIR)
        agent.cancel()

        with pytest.raises(InterruptedError):
            agent.run(fake_pdf, os.path.join(temp_dir, "final.pdf"))


class TestAgentMaxToolCalls:
    def test_max_tool_calls_exceeded(self, temp_dir, fake_pdf):
        """LLM keeps calling tools without completing → RuntimeError."""
        llm = LLMConfig(model_name="test-model", api_key="test-key")
        app = AppConfig()
        agent = AgentRuntime(llm, app, DATA_DIR)
        agent._max_tool_calls = 3  # Small limit for test speed

        tc = _make_tool_call("get_pdf_info", {"pdf_path": "/fake/test.pdf"}, id_suffix="loop")

        with patch("litellm.completion", return_value=_make_mock_response(tool_calls=[tc])):
            with pytest.raises(RuntimeError, match="Agent loop ended without completing"):
                agent.run(fake_pdf, os.path.join(temp_dir, "final.pdf"))

        assert agent._tool_call_count == 3


class TestAgentProgressCallback:
    def test_progress_callback_invoked(self, temp_dir, fake_pdf):
        """Progress callback should be called during the agent loop."""
        llm = LLMConfig(model_name="test-model", api_key="test-key")
        app = AppConfig(target_lang="Chinese")
        agent = AgentRuntime(llm, app, DATA_DIR)
        agent._max_tool_calls = 5

        working_pdf = os.path.join(temp_dir, "work", "output.pdf")
        os.makedirs(os.path.dirname(working_pdf), exist_ok=True)
        with open(working_pdf, "w") as f:
            f.write("fake pdf")
        final_output = os.path.join(temp_dir, "final.pdf")

        tc_complete = _make_tool_call("translation_complete", {
            "output_pdf_path": working_pdf,
            "summary": "Done",
        }, id_suffix="complete")

        calls = []

        def progress(stage, pct, msg):
            calls.append((stage, pct, msg))

        with patch("litellm.completion", return_value=_make_mock_response(tool_calls=[tc_complete])):
            agent.run(fake_pdf, final_output, progress_callback=progress)

        assert len(calls) > 0
        stages = [c[0] for c in calls]
        assert "agent_started" in stages
        assert "tool_call" in stages
        assert "done" in stages


class TestAgentWorkingDirectory:
    def test_working_dir_cleaned_up_on_success(self, temp_dir, fake_pdf):
        """Working directory should be cleaned up after successful completion."""
        llm = LLMConfig(model_name="test-model", api_key="test-key")
        app = AppConfig()
        agent = AgentRuntime(llm, app, DATA_DIR)
        agent._max_tool_calls = 5

        working_pdf = os.path.join(temp_dir, "work", "output.pdf")
        os.makedirs(os.path.dirname(working_pdf), exist_ok=True)
        with open(working_pdf, "w") as f:
            f.write("fake pdf")
        final_output = os.path.join(temp_dir, "final.pdf")

        tc = _make_tool_call("translation_complete", {
            "output_pdf_path": working_pdf,
            "summary": "Done",
        }, id_suffix="c")

        with patch("litellm.completion", return_value=_make_mock_response(tool_calls=[tc])):
            agent.run(fake_pdf, final_output)

        work_dirs = [d for d in os.listdir(temp_dir) if d.startswith(".agent_work_")]
        assert len(work_dirs) == 0, "Working directory should be cleaned up"

    def test_working_dir_cleaned_up_on_error(self, temp_dir, fake_pdf):
        """Working directory should be cleaned up even on error."""
        llm = LLMConfig(model_name="test-model", api_key="test-key")
        app = AppConfig()
        agent = AgentRuntime(llm, app, DATA_DIR)
        agent._max_tool_calls = 2

        tc = _make_tool_call("get_font_info", {"target_lang": "chinese"}, id_suffix="1")

        with patch("litellm.completion", return_value=_make_mock_response(tool_calls=[tc])):
            with pytest.raises(RuntimeError):
                agent.run(fake_pdf, os.path.join(temp_dir, "final.pdf"))

        work_dirs = [d for d in os.listdir(temp_dir) if d.startswith(".agent_work_")]
        assert len(work_dirs) == 0, "Working directory should be cleaned up"
