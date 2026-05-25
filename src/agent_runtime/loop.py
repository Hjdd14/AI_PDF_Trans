"""ReAct agent loop for LLM-orchestrated PDF translation."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from src.utils.logger import get_logger
from src.utils.font_utils import get_cjk_font_filename_for_lang, needs_cjk_package

from .tool_defs import TOOL_DEFINITIONS, TOOL_NAME_MAP
from .tools import TOOL_FUNCTIONS, clear_pdf_cache
from .prompts import format_system_prompt, format_initial_message


class AgentRuntime:
    """ReAct agent loop that orchestrates PDF translation via LLM tool calling."""

    def __init__(
        self,
        llm_config,  # LLMConfig object
        app_config,  # AppConfig object
        data_dir: str,
    ):
        self.llm_config = llm_config
        self.app_config = app_config
        self.data_dir = data_dir
        self.log = get_logger()
        self._cancelled = False

        # State
        self._messages: list[dict] = []
        self._tool_call_count = 0
        self._max_tool_calls = 500
        self._start_time: float = 0.0

    def cancel(self):
        self._cancelled = True

    def _check_cancelled(self):
        if self._cancelled:
            raise InterruptedError("Translation cancelled by user")

    def run(
        self,
        pdf_path: str,
        output_path: str,
        progress_callback: Optional[Callable] = None,
    ) -> str:
        """Run the agent loop to translate a PDF.

        Args:
            pdf_path: Path to the input PDF file.
            output_path: Path where the output PDF should be saved.
            progress_callback: Optional callback for UI progress updates.

        Returns:
            Path to the translated PDF file.

        Raises:
            InterruptedError: If translation is cancelled.
            RuntimeError: If translation fails.
        """
        self.log.info(f"Starting agent translation: {pdf_path} -> {output_path}")
        self._start_time = time.time()

        # Create working directory
        working_dir = str(Path(output_path).parent / f".agent_work_{Path(output_path).stem}")
        os.makedirs(working_dir, exist_ok=True)
        tex_path = os.path.join(working_dir, "output.tex")

        # Set up subdirectories
        figures_dir = os.path.join(working_dir, "figures")
        renders_dir = os.path.join(working_dir, "page_renders")
        os.makedirs(figures_dir, exist_ok=True)
        os.makedirs(renders_dir, exist_ok=True)

        # Get font info for the system prompt
        cjk_font = ""
        if needs_cjk_package(self.app_config.target_lang):
            cjk_font = get_cjk_font_filename_for_lang(self.app_config.target_lang)

        # Build system prompt
        system_content = format_system_prompt(
            pdf_path=pdf_path,
            source_lang=self.app_config.source_lang,
            target_lang=self.app_config.target_lang,
            working_dir=working_dir,
            tex_path=tex_path,
            output_path=output_path,
            cjk_font_filename=cjk_font,
        )

        # Initialize message history
        self._messages = [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": format_initial_message(
                    pdf_path, self.app_config.source_lang,
                    self.app_config.target_lang, output_path,
                ),
            },
        ]

        if progress_callback:
            progress_callback("agent_started", 5, "Starting translation agent...")

        # ── Agent Loop ────────────────────────────────────────────────────
        try:
            while self._tool_call_count < self._max_tool_calls:
                self._check_cancelled()

                if progress_callback:
                    pct = min(15 + int(70 * self._tool_call_count / self._max_tool_calls), 85)
                    progress_callback("agent_running", pct, f"Agent: {self._tool_call_count} tool calls...")

                # ── Call LLM ──────────────────────────────────────────────
                response = self._call_llm()

                if response is None:
                    raise RuntimeError("LLM API call returned no response")

                msg = response.choices[0].message

                # ── Handle text-only response ─────────────────────────────
                if not msg.tool_calls and msg.content:
                    self._messages.append({"role": "assistant", "content": msg.content})
                    self.log.info(f"LLM: {msg.content[:200]}...")

                    if msg.content.strip().endswith("translation_complete"):
                        # Heuristic: LLM might indicate completion in text
                        pass
                    continue

                # ── Handle tool calls ─────────────────────────────────────
                if msg.tool_calls:
                    # Add assistant message with tool calls
                    assistant_msg = {"role": "assistant", "content": msg.content or ""}
                    # Preserve reasoning_content — required by Xiaomi MiMo and DeepSeek
                    # when tool_calls appear in message history.  Both APIs reject follow-up
                    # requests if assistant.tool_calls lacks this field.  OpenAI silently
                    # ignores it; LiteLLM strips it during Anthropic conversion — safe to
                    # always include an empty string fallback when tool_calls exist.
                    rc = getattr(msg, "reasoning_content", None)
                    assistant_msg["reasoning_content"] = rc if rc is not None else ""
                    tool_call_list = []
                    for tc in msg.tool_calls:
                        tool_call_list.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        })
                    assistant_msg["tool_calls"] = tool_call_list
                    self._messages.append(assistant_msg)

                    # ── Batch-process tool calls (parallel for independent tools) ───
                    # Parse all args first
                    parsed = []  # (tool_name, tool_id, args_dict_or_error_str)
                    for tc in msg.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError as e:
                            parsed.append((tc.function.name, tc.id, f"Error: invalid JSON: {e}"))
                            continue
                        parsed.append((tc.function.name, tc.id, args))

                    # Fast path: single translation_complete call
                    if (len(parsed) == 1 and parsed[0][0] == "translation_complete"):
                        self._tool_call_count += 1
                        if progress_callback:
                            progress_callback("tool_call", 0, "Calling translation_complete...")
                        tname, tid, args = parsed[0]
                        try:
                            result = TOOL_FUNCTIONS["translation_complete"](**args)
                        except Exception as e:
                            result = {"error": str(e), "completed": False}
                        if isinstance(result, dict) and result.get("completed"):
                            output_pdf = result.get("output_pdf_path", output_path)
                            self.log.info(f"Agent completed: {result.get('summary', '')}")
                            import shutil
                            if os.path.isfile(output_pdf):
                                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                                if os.path.abspath(output_pdf) != os.path.abspath(output_path):
                                    shutil.copy2(output_pdf, output_path)
                            elif not os.path.isfile(output_path):
                                raise RuntimeError(f"Output PDF not found: {output_pdf}")
                            self._cleanup(working_dir)
                            if progress_callback:
                                progress_callback("done", 100, "Translation complete!")
                            return output_path
                        else:
                            error = result.get("error", "Unknown error")
                            self._messages.append({
                                "role": "tool", "tool_call_id": tid,
                                "content": f"Error: {error}",
                            })
                            continue

                    # Pre-process: inject data_dir for compile, prepare for execution
                    pending = []
                    for tname, tid, args in parsed:
                        if isinstance(args, str):  # parse error
                            self._tool_call_count += 1
                            self._messages.append({
                                "role": "tool", "tool_call_id": tid,
                                "content": args,
                            })
                            continue
                        if tname == "compile_tex_to_pdf":
                            args["data_dir"] = self.data_dir
                        pending.append((tname, tid, args))

                    if not pending:
                        continue

                    # Execute all pending tools serially
                    self._tool_call_count += len(pending)
                    for tname, tid, args in pending:
                        self.log.info(f"[{self._tool_call_count - len(pending) + 1}] Tool: {tname}({_summarize_args(args)})")
                    if progress_callback:
                        progress_callback("tool_call", 0, f"Executing {len(pending)} tools...")

                    def _run_one(name, a):
                        fn = TOOL_FUNCTIONS.get(name)
                        if not fn:
                            return f"Error: unknown tool '{name}'"
                        try:
                            raw = fn(**a)
                            if isinstance(raw, (dict, list)):
                                r = json.dumps(raw, ensure_ascii=False, indent=2)
                            else:
                                r = str(raw)
                        except Exception as ex:
                            self.log.error(f"Tool {name} failed: {ex}")
                            r = f"Error executing {name}: {ex}"
                        if len(r) > 100000:
                            r = r[:100000] + "\n...(truncated)"
                        return r

                    results = [None] * len(pending)
                    with ThreadPoolExecutor(max_workers=min(8, len(pending))) as executor:
                        futures = {
                            executor.submit(_run_one, name, args): idx
                            for idx, (name, _, args) in enumerate(pending)
                        }
                        for future in futures:
                            self._check_cancelled()
                        for future in futures:
                            idx = futures[future]
                            results[idx] = future.result()

                    # Append results in original order
                    for (tname, tid, args), result_str in zip(pending, results):
                        self._messages.append({
                            "role": "tool",
                            "tool_call_id": tid,
                            "content": result_str,
                        })

                    # Check for translation_complete in batch (LLM shouldn't mix it)
                    for tname, _, _ in pending:
                        if tname == "translation_complete":
                            self.log.warning(
                                "translation_complete mixed with other tools — "
                                "agent will process it on next iteration"
                            )

                    continue

                # ── No tool calls, no content: stop ───────────────────────
                self.log.warning("LLM returned empty response with no tool calls")
                break

            # ── Loop ended without completion ─────────────────────────────
            raise RuntimeError(
                f"Agent loop ended without completing translation "
                f"({self._tool_call_count} tool calls, {time.time() - self._start_time:.0f}s)"
            )

        except InterruptedError:
            if progress_callback:
                progress_callback("cancelled", 0, "Translation cancelled.")
            self._cleanup(working_dir)
            raise
        except Exception as e:
            self.log.exception("Agent loop failed")
            if progress_callback:
                progress_callback("error", 0, f"Error: {e}")
            self._cleanup(working_dir)
            raise

    def _build_completion_params(self) -> dict:
        """Build the completion parameters dict."""
        params = {
            "model": self.llm_config.get_litellm_model(),
            "messages": self._messages,
            "tools": TOOL_DEFINITIONS,
            "max_tokens": 16384,
            "temperature": 0,
            "timeout": 600,  # 10 min — agent accumulates many messages
        }
        if self.llm_config.api_key:
            params["api_key"] = self.llm_config.api_key
        if self.llm_config.api_url:
            params["api_base"] = self.llm_config.api_url
        return params

    def _call_llm(self):
        """Make a LiteLLM completion call, retrying with stripped params on BadRequest."""
        import litellm
        litellm.drop_params = True
        litellm.modify_params = True  # auto-fix orphaned tool_calls / empty content
        litellm.num_retries = 2

        params, used_fallbacks = self._build_completion_params(), set()
        model_name = params["model"]
        timeout_retries = 2
        tools_was_stripped = False

        while True:
            self.log.info(
                f"LLM call: model={model_name}, messages={len(self._messages)}, "
                f"tools={len(TOOL_DEFINITIONS)}, fallbacks={used_fallbacks or 'none'}, "
                f"timeout_retries_left={timeout_retries}"
            )
            try:
                response = litellm.completion(**params)
                # If tools were stripped to get this response, the API doesn't
                # support function calling — agent can't make progress.
                if tools_was_stripped:
                    raise RuntimeError(
                        f"API 不支持 function calling (tool_use)。\n"
                        f"当前模型 {model_name} 不兼容本程序所需的 function calling 协议。\n"
                        f"可能原因：\n"
                        f"  1. 该 API 确实不支持 tool_use（需换用 OpenAI/Anthropic/DeepSeek 等）\n"
                        f"  2. 该 API 需要特殊的消息格式（如小米 MiMo 要求 tool_calls 消息\n"
                        f"     必须包含 reasoning_content 字段）\n"
                        f"请检查 API 文档，或在设置中更换支持 function calling 的模型。"
                    )
                self._log_token_usage(response)
                return response
            except litellm.BadRequestError as e:
                error_str = str(e)
                self.log.warning(f"BadRequest for {model_name}: {error_str[:300]}")

                # Try fallback strategies in order
                fallback = self._next_fallback(params, used_fallbacks)
                if fallback:
                    params, stripped_key = fallback
                    used_fallbacks.add(stripped_key)
                    if stripped_key == "max_tokens":
                        self.log.warning(f"Retrying with 'max_completion_tokens' instead of 'max_tokens'...")
                    elif stripped_key == "tools":
                        self.log.warning(f"Retrying without 'tools' (stripping tool-related messages)...")
                        tools_was_stripped = True
                    else:
                        self.log.warning(f"Retrying without '{stripped_key}'...")
                    continue

                # No more fallbacks — the API likely doesn't support function calling
                self.log.error(
                    f"All param fallbacks exhausted for {model_name}. "
                    f"Sent params: {list(params.keys())}"
                )
                raise RuntimeError(
                    f"API 不支持 function calling (tool_use)。\n"
                    f"当前模型 {model_name} 的接口不兼容 OpenAI 的 function calling 协议。\n"
                    f"请使用支持 function calling 的 API（如 OpenAI、Anthropic、DeepSeek 等），\n"
                    f"或在设置中将 '服务商类型' 切换为 'compatible' 并确保模型支持 tool_use。"
                ) from e
            except litellm.Timeout as e:
                if timeout_retries > 0:
                    timeout_retries -= 1
                    self.log.warning(
                        f"Timeout for {model_name}, retrying ({timeout_retries+1} left): {e}"
                    )
                    continue
                self.log.error(f"Timeout for {model_name}, all retries exhausted")
                raise

    @staticmethod
    def _next_fallback(params: dict, used: set) -> tuple[dict, str] | None:
        """Try progressively stripping problematic params when BadRequest occurs.

        Order: temperature → max_tokens → tools.
        api_base is never stripped — it's user-configured and removing it would
        redirect to OpenAI's default servers, causing ConnectTimeout.
        """
        if "temperature" not in used and "temperature" in params:
            new = dict(params)
            del new["temperature"]
            return new, "temperature"

        if "max_tokens" not in used and "max_tokens" in params:
            new = dict(params)
            new["max_completion_tokens"] = new.pop("max_tokens")
            return new, "max_tokens"

        if "tools" not in used and "tools" in params:
            new = dict(params)
            del new["tools"]
            # Also strip tool-related messages — APIs that reject tools
            # will also reject assistant.tool_calls and role=tool messages
            new["messages"] = [
                m for m in new.get("messages", [])
                if m.get("role") != "tool" and "tool_calls" not in m
            ]
            return new, "tools"

        return None

    def _log_token_usage(self, response):
        """Log token usage from a LiteLLM response."""
        try:
            usage = response.usage
            if usage:
                self.log.info(
                    f"Tokens: {usage.prompt_tokens}↑ + {usage.completion_tokens}↓ "
                    f"= {usage.total_tokens} total"
                )
        except Exception:
            pass

    def _cleanup(self, working_dir: str):
        """Remove the working directory if it exists."""
        import shutil
        clear_pdf_cache()
        try:
            if os.path.isdir(working_dir):
                shutil.rmtree(working_dir, ignore_errors=True)
                self.log.info(f"Cleaned up working directory: {working_dir}")
        except Exception as e:
            self.log.warning(f"Failed to clean up {working_dir}: {e}")


def _summarize_args(args: dict, max_len: int = 120) -> str:
    """Summarize tool arguments for logging (truncate long strings)."""
    parts = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 100:
            s = s[:100] + "..."
        parts.append(f"{k}={s}")
    result = ", ".join(parts)
    if len(result) > max_len:
        result = result[:max_len] + "..."
    return result
