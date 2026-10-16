import logging
import hashlib
from django.db import models
from django.utils.translation import gettext_lazy as _
from config import settings
from openai import OpenAI
from django.utils import timezone
from encrypted_model_fields.fields import EncryptedCharField
import time
import datetime
from django.core.cache import cache
from utils.text_handler import get_token_count, adaptive_chunking
import os
import re
import deepl
import json
from urllib import request, parse
from core.tasks.task_manager import task_manager
from utils.translation_integrity import translation_error, MEDIA_INSTRUCTIONS

logger = logging.getLogger(__name__)


_OPENROUTER_FREE_DENY_TERMS = (
    "content-safety",
    "guard",
    "moderation",
    "embed",
    "rerank",
    "audio",
    "music",
    "coder",
    "code",
)


def _filter_openrouter_free_models(
    rows: list,
    current_model: str,
    allowed_authors: list,
    deny_terms: list,
    min_context_tokens: int,
    min_completion_tokens: int,
    max_models: int,
    require_unmoderated: bool,
) -> list:
    """Build an ordered free-model allowlist from OpenRouter catalog rows."""
    author_rank = {
        author.strip().lower(): index
        for index, author in enumerate(allowed_authors)
        if author.strip()
    }
    denied = tuple(term.strip().lower() for term in deny_terms if term.strip())
    candidates = []

    for catalog_index, row in enumerate(rows):
        model_id = str(row.get("id") or "")
        normalized_id = model_id.lower()
        if not model_id.endswith(":free") or model_id == current_model:
            continue

        author = normalized_id.split("/", 1)[0]
        if author not in author_rank or any(term in normalized_id for term in denied):
            continue

        pricing = row.get("pricing") or {}
        try:
            is_free = (
                pricing.get("prompt") is not None
                and pricing.get("completion") is not None
                and float(pricing["prompt"]) == 0
                and float(pricing["completion"]) == 0
            )
        except (TypeError, ValueError):
            is_free = False
        if not is_free:
            continue

        architecture = row.get("architecture") or {}
        if "text" not in (architecture.get("output_modalities") or []):
            continue

        top_provider = row.get("top_provider") or {}
        if require_unmoderated and top_provider.get("is_moderated") is not False:
            continue

        try:
            context_tokens = int(row.get("context_length") or 0)
            completion_tokens = int(
                top_provider.get("max_completion_tokens") or 0
            )
        except (TypeError, ValueError):
            continue
        if (
            context_tokens < min_context_tokens
            or completion_tokens < min_completion_tokens
        ):
            continue

        candidates.append(
            (
                author_rank[author],
                -completion_tokens,
                -context_tokens,
                catalog_index,
                model_id,
            )
        )

    candidates.sort()
    return [candidate[-1] for candidate in candidates[:max_models]]


# ── 本地补丁：按 HTML 块边界切分长正文 ────────────────────────────────
# 上游的 adaptive_chunking 以英文句号切分，用在 HTML 上会把标签和属性
# （`https://x.com/a.html`、`<a href="...">`）从中间劈开，模型拿到半截标签
# 会译出坏结构。这里改成只在块级标签的闭合处切，切完拼回去仍是合法 HTML。
_BLOCK_BOUNDARY = re.compile(
    r"(?<=</p>)|(?<=</blockquote>)|(?<=</div>)|(?<=</ul>)|(?<=</ol>)"
    r"|(?<=</li>)|(?<=</h1>)|(?<=</h2>)|(?<=</h3>)|(?<=</h4>)"
    r"|(?<=</figure>)|(?<=</table>)|(?<=</pre>)|(?<=<hr>)|(?<=<hr/>)"
)


def chunk_html_on_blocks(text: str, max_tokens: int) -> list:
    """把 HTML 按块级边界贪心地攒进不超过 max_tokens 的块里。"""
    pieces = [p for p in _BLOCK_BOUNDARY.split(text) if p]
    chunks, cur, cur_tokens = [], [], 0
    for piece in pieces:
        n = get_token_count(piece)
        if n > max_tokens:
            # 单个块自己就超预算（超长表格/整篇没有段落标签），退回句子级切分
            if cur:
                chunks.append("".join(cur))
                cur, cur_tokens = [], 0
            chunks.extend(
                adaptive_chunking(
                    piece,
                    target_chunks=max(1, n // max_tokens + 1),
                    min_chunk_size=500,
                    max_chunk_size=max_tokens,
                )
            )
            continue
        if cur_tokens + n > max_tokens and cur:
            chunks.append("".join(cur))
            cur, cur_tokens = [], 0
        cur.append(piece)
        cur_tokens += n
    if cur:
        chunks.append("".join(cur))
    return chunks or [text]


class Agent(models.Model):
    name = models.CharField(_("Name"), max_length=100, unique=True)
    valid = models.BooleanField(_("Valid"), null=True)
    is_ai = models.BooleanField(default=False, editable=False)
    log = models.TextField(
        _("Log"),
        default="",
        blank=True,
        null=True,
    )

    def translate(self, text: str, target_language: str, **kwargs) -> dict:
        raise NotImplementedError(
            "subclasses of TranslatorEngine must provide a translate() method"
        )

    def min_size(self) -> int:
        if hasattr(self, "max_characters"):
            return self.max_characters * 0.7
        if hasattr(self, "max_tokens"):
            return self.max_tokens * 0.7
        return 0

    def max_size(self) -> int:
        if hasattr(self, "max_characters"):
            return self.max_characters * 0.9
        if hasattr(self, "max_tokens"):
            return self.max_tokens * 0.9
        return 0

    def validate(self) -> bool:
        raise NotImplementedError(
            "subclasses of TranslatorEngine must provide a validate() method"
        )

    class Meta:
        abstract = True

    def __str__(self):
        return self.name


def openai_advanced_default():
    return {"temperature": 0.2,"reasoning_effort":"minimal"}


class OpenAIAgent(Agent):
    # https://platform.openai.com/docs/api-reference/chat
    is_ai = models.BooleanField(default=True, editable=False)
    api_key = EncryptedCharField(_("API Key"), max_length=255)
    base_url = models.URLField(_("API URL"), default="https://api.openai.com/v1")
    model = models.CharField(
        max_length=100,
        default="gpt-3.5-turbo",
        help_text="e.g. gpt-3.5-turbo, gpt-4-turbo",
    )
    title_translate_prompt = models.TextField(
        _("Title Translate Prompt"), default=settings.default_title_translate_prompt
    )
    content_translate_prompt = models.TextField(
        _("Content Translate Prompt"), default=settings.default_content_translate_prompt
    )
    summary_prompt = models.TextField(default=settings.default_summary_prompt)

    advanced_params = models.JSONField(
        default=openai_advanced_default,
        help_text=("Advanced OpenAI chat params as JSON."),
    )
    max_tokens = models.IntegerField(
        default=0, help_text="0 means detect automatically"
    )
    rate_limit_rpm = models.IntegerField(
        _("Rate Limit (RPM)"),
        default=0,
        help_text=_("Maximum requests per minute (0 = no limit)"),
    )
    merge_system_prompt = models.BooleanField(
        _("Merge System Prompt to User Message"),
        default=False,
        help_text=_("Enable for models that don't support system system instructions (e.g., Gemma 3)")
    )
    EXTRA_HEADERS = {
        "HTTP-Referer": "https://www.rssbox.app",
        "X-Title": "RSSBox",
    }

    class Meta:
        verbose_name = "OpenAI"
        verbose_name_plural = "OpenAI"

    def _init(self):
        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=settings.OPENAI_API_TIMEOUT,
            max_retries=settings.OPENAI_API_MAX_RETRIES,
        )

    def validate(self) -> bool:
        if self.api_key:
            try:
                client = self._init()
                # 应用速率限制
                self._wait_for_rate_limit()

                system_prompt = "You must only reply with exactly one character: 1"
                user_content = "1"

                # 根据 merge_system_prompt 的值决定消息格式
                if self.merge_system_prompt:
                    merged_content = f"{system_prompt}\n\n{user_content}"
                    messages = [
                        {"role": "user", "content": merged_content}
                    ]
                else:
                    messages = [
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {"role": "user", "content": user_content},
                    ]

                res = client.with_options(
                    max_retries=settings.OPENAI_API_MAX_RETRIES
                ).chat.completions.create(
                    extra_headers=self.EXTRA_HEADERS,
                    model=self.model,
                    messages=messages,
                    # max_tokens=50,
                    max_completion_tokens=50,
                )
                # 有些第三方源在key或url错误的情况下，并不会抛出异常代码，而是返回html广告，因此添加该行。
                fr = res.choices[0].finish_reason
                # 提交后台任务检测模型限制
                if self.max_tokens == 0:
                    task_manager.submit_task(
                        f"detect_model_limit_{self.model}_{self.id}",
                        self.detect_model_limit,
                        force=True,
                    )
                    logger.info(
                        f"Submitted background task to detect model limit for {self.model}"
                    )
                self.log = ""
                self.valid = True
                return True
            except Exception as e:
                logger.error("OpenAIAgent validate ->%s", e)
                self.log = f"{timezone.now()}: {str(e)}"
                self.valid = False
                return False
            finally:
                self.save(update_fields=["log", "valid"])

    def detect_model_limit(self, force=False) -> int:
        """通过二分搜索来高效检测模型实际限制"""
        if not force and self.max_tokens != 0:
            return self.max_tokens

        initial_model = self.model
        initial_max_tokens = self.max_tokens

        # 二分搜索找到确切限制
        def binary_search_limit(low, high):
            """使用二分搜索找到确切的token限制"""
            if high - low <= 256:  # 当范围足够小时，返回低值作为安全限制
                return low

            mid = (low + high) // 2

            try:
                # 应用速率限制
                self._wait_for_rate_limit()
                # 使用最小的测试内容减少token消耗
                response = self._init().chat.completions.create(
                    extra_headers=self.EXTRA_HEADERS,
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You must only reply with exactly one character: 1",
                        },
                        {"role": "user", "content": "1"},
                    ],
                    # max_tokens=mid,
                    max_completion_tokens=mid,
                    temperature=0,  # 确保结果一致性
                    stop=[",", "\n", " ", ".", "1"],
                )
                if response.choices[0].finish_reason == "stop":
                    # 成功调用，尝试更高的限制
                    return binary_search_limit(mid, high)

            except Exception as e:
                error_str = str(e).lower()
                if any(
                    keyword in error_str
                    for keyword in ["maximum", "limit", "tokens", "context", "length"]
                ):
                    # 遇到限制错误，降低上限
                    return binary_search_limit(low, mid)
                else:
                    # 其他错误（如API错误），使用保守值
                    logger.warning(
                        f"Detect model limit when non-limit error occurs: {e}"
                    )
                    return low

        # 直接使用二分搜索
        final_limit = binary_search_limit(4096, 1000000)
        self.max_tokens = final_limit

        if self.pk is None:
            return final_limit

        updated = type(self).objects.filter(
            pk=self.pk,
            model=initial_model,
            max_tokens=initial_max_tokens,
        ).update(max_tokens=final_limit)
        if updated:
            return final_limit

        current_max_tokens = (
            type(self).objects.filter(pk=self.pk).values_list("max_tokens", flat=True).first()
        )
        if current_max_tokens is not None:
            self.max_tokens = current_max_tokens
            return current_max_tokens

        return final_limit

    def _wait_for_rate_limit(self):
        """等待直到满足速率限制条件"""
        if self.rate_limit_rpm <= 0:
            return  # 无速率限制

        # 生成基于当前分钟的缓存键
        current_minute = datetime.datetime.now().strftime("%Y%m%d%H%M")
        cache_key = f"openai_rate_limit_{self.id}_{current_minute}"

        # 获取当前计数或初始化为0
        request_count = cache.get(cache_key, 0)

        # 计算等待时间（如果超过限制）
        if request_count >= self.rate_limit_rpm:
            # 计算到下一分钟开始的时间
            now = datetime.datetime.now()
            next_minute = now.replace(second=0, microsecond=0) + datetime.timedelta(
                minutes=1
            )
            wait_seconds = (next_minute - now).total_seconds()

            # 添加一点缓冲确保时间窗口切换
            wait_seconds += 0.1
            logger.info(f"Rate limit reached. Waiting {wait_seconds:.2f} seconds...")
            time.sleep(wait_seconds)

            # 重置计数（新分钟开始）
            cache.delete(cache_key)
            return

        # 增加计数并设置过期时间（确保在下一分钟开始时过期）
        cache.set(cache_key, request_count + 1, timeout=60)

    def _fallback_agent(self):
        """Return the configured OpenAI-compatible fallback without recursing."""
        fallback_id = os.environ.get(
            "TRANSLATION_FALLBACK_OPENAI_AGENT_ID", ""
        ).strip()
        if not fallback_id:
            return None

        try:
            fallback_id = int(fallback_id)
        except ValueError:
            logger.error(
                "Invalid TRANSLATION_FALLBACK_OPENAI_AGENT_ID: %r", fallback_id
            )
            return None

        if self.pk == fallback_id:
            return None

        fallback = type(self).objects.filter(pk=fallback_id, valid=True).first()
        if not fallback:
            logger.error("Translation fallback agent %s is unavailable", fallback_id)
        return fallback

    def _openrouter_free_model_fallbacks(self):
        """Discover allowed free models without weakening the fixed primary model."""
        if parse.urlparse(self.base_url).hostname != "openrouter.ai":
            return []

        allowed_authors = [
            author.strip().lower()
            for author in os.environ.get(
                "OPENROUTER_ALLOWED_MODEL_AUTHORS", ""
            ).split(",")
            if author.strip()
        ]
        if not allowed_authors:
            return []

        deny_terms = [
            term.strip().lower()
            for term in os.environ.get(
                "OPENROUTER_FREE_DENY_TERMS",
                ",".join(_OPENROUTER_FREE_DENY_TERMS),
            ).split(",")
            if term.strip()
        ]

        def env_int(name, default):
            try:
                return max(1, int(os.environ.get(name, str(default))))
            except (TypeError, ValueError):
                logger.error("Invalid %s; using %s", name, default)
                return default

        min_context_tokens = env_int(
            "OPENROUTER_FREE_MIN_CONTEXT_TOKENS", 65536
        )
        min_completion_tokens = env_int(
            "OPENROUTER_FREE_MIN_COMPLETION_TOKENS", 65536
        )
        requested_max_models = env_int("OPENROUTER_FREE_MODEL_MAX_FALLBACKS", 3)
        # OpenRouter rejects a `models` fallback array with more than 3 items.
        max_models = min(requested_max_models, 3)
        if requested_max_models > max_models:
            logger.warning(
                "OPENROUTER_FREE_MODEL_MAX_FALLBACKS capped at %s", max_models
            )
        cache_seconds = env_int("OPENROUTER_FREE_MODEL_CACHE_SECONDS", 21600)
        require_unmoderated = os.environ.get(
            "OPENROUTER_FREE_REQUIRE_UNMODERATED", "1"
        ).lower() not in ("0", "false", "no")

        signature = "|".join(
            [
                self.model,
                ",".join(allowed_authors),
                ",".join(deny_terms),
                str(min_context_tokens),
                str(min_completion_tokens),
                str(max_models),
                str(require_unmoderated),
            ]
        )
        cache_suffix = hashlib.sha256(signature.encode()).hexdigest()[:16]
        cache_key = f"openrouter_free_models_{cache_suffix}"
        stale_key = f"{cache_key}_stale"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        query = parse.urlencode(
            {
                "model_authors": ",".join(allowed_authors),
                "max_price": 0,
                "max_output_price": 0,
                "output_modalities": "text",
                "sort": "throughput-high-to-low",
                "limit": 1000,
            }
        )
        catalog_url = f"{self.base_url.rstrip('/')}/models?{query}"

        try:
            catalog_request = request.Request(
                catalog_url,
                headers={"User-Agent": "RSSBox controlled free-model router"},
            )
            with request.urlopen(catalog_request, timeout=10) as response:
                payload = json.loads(response.read())
            models = _filter_openrouter_free_models(
                rows=payload.get("data") or [],
                current_model=self.model,
                allowed_authors=allowed_authors,
                deny_terms=deny_terms,
                min_context_tokens=min_context_tokens,
                min_completion_tokens=min_completion_tokens,
                max_models=max_models,
                require_unmoderated=require_unmoderated,
            )
            if not models:
                raise ValueError("OpenRouter catalog returned no allowed free fallbacks")
            cache.set(cache_key, models, timeout=cache_seconds)
            cache.set(stale_key, models, timeout=604800)
            logger.info("OpenRouter free-model fallbacks: %s", models)
            return models
        except Exception as e:
            stale_models = cache.get(stale_key) or []
            logger.error(
                "Could not refresh OpenRouter free-model fallbacks: %s; using %s",
                e,
                stale_models,
            )
            return stale_models

    def completions(
        self,
        text: str,
        system_prompt: str = None,
        user_prompt: str = None,
        _is_chunk: bool = False,  # 内部参数，用于标记是否为分块调用
        _translation_guard: bool = False,
        **kwargs,
    ) -> dict:
        client = self._init()
        tokens = 0
        result_text = ""
        log_updated = False

        try:
            if user_prompt:
                system_prompt += f"\n\n{user_prompt}"

            # 应用速率限制
            self._wait_for_rate_limit()

            if self.merge_system_prompt:
                merged_content = f"{system_prompt}\n\n{text}"
                messages = [
                    {"role": "user", "content": merged_content}
                ]
                # 当合并 system prompt 时，system_prompt_tokens 为 0（因为已包含在 merged_content 中）
                system_prompt_tokens = 0
                input_tokens = get_token_count(merged_content)
            else:
                messages = [
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ]
                # 计算系统提示的token占用
                system_prompt_tokens = get_token_count(system_prompt)
                input_tokens = get_token_count(system_prompt) + get_token_count(text)

            # 获取最大可用token数（保留buffer）
            if self.max_tokens == 0:
                task_manager.submit_task(
                    f"detect_model_limit_{self.model}_{self.id}",
                    self.detect_model_limit,
                    force=True,
                )
                raise ValueError(
                    "max_tokens is not set, Please wait for the model limit detection to complete"
                )

            # 计算最大可用token数
            # 当 merge_system_prompt=True 时，system_prompt 已包含在 merged_content 中，所以只需要考虑 text 的 token
            if self.merge_system_prompt:
                # 合并模式下，需要从总限制中减去 system_prompt 的 token（因为它会占用输入空间）
                system_prompt_token_cost = get_token_count(system_prompt)
                max_usable_tokens = (
                    self.max_tokens - system_prompt_token_cost - 100
                )  # 100 token buffer
            else:
                max_usable_tokens = (
                    self.max_tokens - system_prompt_tokens - 100
                )  # 100 token buffer

            # ── 本地补丁：分块判据必须同时受"输出上限"约束 ──────────────
            # max_tokens 存的是模型的**上下文**上限（Gemini 3.5 Flash Lite
            # 实测 999,756），但翻译的输出长度≈输入长度，而单次**输出**上限
            # 只有 65,536 token。于是一篇七万 token 的长文永远进不了分块分支，
            # 一次性发出去、输出撞上限被截 —— 下面那个补丁把半截译文留了下来，
            # 但读者看到的仍然只有半篇。这里按输出预算再压一道每块输入上限。
            _out_cap = int(os.environ.get("TRANSLATE_OUTPUT_TOKEN_CAP", "65536"))
            max_usable_tokens = max(2000, min(max_usable_tokens, int(_out_cap * 0.45)))

            # 检查文本长度是否需要分块
            if get_token_count(text) > max_usable_tokens:
                logger.info(
                    f"Text too large ({get_token_count(text)} tokens), chunking..."
                )

                # 本地补丁：正文是 HTML，按块级边界切（见 chunk_html_on_blocks）
                chunks = chunk_html_on_blocks(text, max_usable_tokens)
                logger.info(f"chunked into {len(chunks)} pieces")

                # 分块翻译
                translated_chunks = []
                for chunk in chunks:
                    result = self.completions(
                        text=chunk,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        _is_chunk=True,  # 标记为分块调用
                        _translation_guard=_translation_guard,
                        **kwargs,
                    )
                    if not result.get("text"):
                        raise ValueError("A translation chunk failed; refusing partial article")
                    translated_chunks.append(result["text"])
                    tokens += result["tokens"]

                # 按块边界切的，拼回去不加空格
                result_text = "".join(translated_chunks)
                if _translation_guard:
                    error = translation_error(text, result_text)
                    if error:
                        result_text = ""
                        raise ValueError(error)
                return {"text": result_text, "tokens": tokens}

            # 计算合理的输出token限制
            # input_tokens 已经在上面根据 merge_system_prompt 的情况正确计算了，直接使用
            # 输出token限制 = 模型总限制 - 输入token - 安全缓冲
            output_token_limit = int(max(4096, (self.max_tokens - input_tokens) * 0.8))
            # 本地补丁：别把上下文窗口当输出预算报给 API
            output_token_limit = min(output_token_limit, _out_cap)

            # 正常流程
            adv_params = self.advanced_params or {}
            if not isinstance(adv_params, dict):
                adv_params = {}

            call_kwargs = {**adv_params}
            extra_body = call_kwargs.get("extra_body")
            if extra_body is None:
                extra_body = {}
            # Only the free primary participates in the vetted free pool.
            # A dedicated paid model (for example The Diff's GPT-6 Luna)
            # must not silently route to a different free model.
            if (
                self.model.endswith(":free")
                and isinstance(extra_body, dict)
                and "models" not in extra_body
            ):
                model_fallbacks = self._openrouter_free_model_fallbacks()
                if model_fallbacks:
                    extra_body = {**extra_body, "models": model_fallbacks}
                    call_kwargs["extra_body"] = extra_body
            # 仅在未显式提供时设置安全的默认/限制
            if (
                "max_completion_tokens" not in call_kwargs
                and "max_tokens" not in call_kwargs
            ):
                call_kwargs["max_completion_tokens"] = output_token_limit

            res = client.with_options(
                max_retries=settings.OPENAI_API_MAX_RETRIES
            ).chat.completions.create(
                extra_headers=self.EXTRA_HEADERS,
                model=self.model,
                messages=messages,
                **call_kwargs,
            )
            # Truncated or invalid output must enter fallback, never the saved feed.
            choice = res.choices[0] if res.choices else None
            finish_reason = getattr(choice, "finish_reason", None) if choice else None
            content = (
                getattr(getattr(choice, "message", None), "content", None)
                if choice
                else None
            )
            if content and finish_reason == "stop":
                result_text = content
                if _translation_guard:
                    error = translation_error(text, result_text)
                    if error:
                        logger.warning("[%s]: rejected translation: %s", self.name, error)
                        result_text = ""
                logger.debug(f"[{self.name}]: {result_text[:50]}...")
            else:
                logger.warning(
                    f"[{self.name}]: Failed to complete request:[{finish_reason or 'unknown'}]"
                )

            tokens = res.usage.total_tokens if getattr(res, "usage", None) else 0
        except Exception as e:
            self.log = f"{timezone.now()}: {str(e)}"
            log_updated = True
            logger.error(f"{self.name}: {e}")

        if not str(result_text or "").strip():
            fallback = self._fallback_agent()
            if fallback:
                logger.warning(
                    "Primary translator %s returned no text; falling back to %s",
                    self.name,
                    fallback.name,
                )
                fallback_result = fallback.completions(
                    text=text,
                    system_prompt=system_prompt,
                    # user_prompt was already merged into system_prompt above.
                    user_prompt=None,
                    _is_chunk=_is_chunk,
                    _translation_guard=_translation_guard,
                    **kwargs,
                )
                if str(fallback_result.get("text") or "").strip():
                    result_text = fallback_result["text"]
                    tokens += fallback_result.get("tokens", 0)

        if not _is_chunk and log_updated:
            self.save(update_fields=["log"])

        return {"text": result_text, "tokens": tokens}

    def translate(
        self,
        text: str,
        target_language: str,
        user_prompt: str = None,
        text_type: str = "title",
        **kwargs,
    ) -> dict:
        logger.info(f">>>Start Translate [{target_language}]: {text[:50]}...")
        system_prompt = (
            self.title_translate_prompt
            if text_type == "title"
            else self.content_translate_prompt
        ).replace("{target_language}", target_language)

        return self.completions(
            text, system_prompt=system_prompt + MEDIA_INSTRUCTIONS,
            user_prompt=user_prompt, _translation_guard=True, **kwargs
        )

    def summarize(self, text: str, target_language: str, **kwargs) -> dict:
        logger.info(f">>> Start Summarize [{target_language}]: {text[:50]}...")
        system_prompt = self.summary_prompt.replace(
            "{target_language}", target_language
        )
        return self.completions(text, system_prompt=system_prompt, **kwargs)

    def digester(
        self,
        text: str,
        system_prompt: str,
        digest_name: str,
        date: str,
        **kwargs,
    ) -> dict:
        logger.info(f">>> Start Digesting [{digest_name}]-{date}")
        # prompt = system_prompt + settings.output_format_for_digest_prompt
        return self.completions(text, system_prompt=system_prompt, **kwargs)

    def filter(self, text: str, system_prompt: str, **kwargs) -> dict:
        logger.info(f">>> Start Filter: {text[:50]}...")
        passed = False
        tokens = 0
        results = self.completions(
            text,
            system_prompt=system_prompt + settings.output_format_for_filter_prompt,
            **kwargs,
        )

        if results["text"] and "Passed" in results["text"]:
            logger.info(">>> Filter Passed")
            passed = True
            tokens = results["tokens"]
        else:
            logger.info(">>> Filter Blocked")
            passed = False

        return {"passed": passed, "tokens": tokens}


class DeepLAgent(Agent):
    # https://github.com/DeepLcom/deepl-python
    api_key = EncryptedCharField(_("API Key"), max_length=255)
    max_characters = models.IntegerField(default=5000)
    server_url = models.URLField(_("API URL(optional)"), null=True, blank=True)
    proxy = models.URLField(_("Proxy(optional)"), null=True, blank=True)
    language_code_map = {
        "English": "EN-US",
        "Chinese Simplified": "ZH",
        "Russian": "RU",
        "Japanese": "JA",
        "Korean": "KO",
        "Czech": "CS",
        "Danish": "DA",
        "German": "DE",
        "Spanish": "ES",
        "French": "FR",
        "Indonesian": "ID",
        "Italian": "IT",
        "Hungarian": "HU",
        "Norwegian Bokmål": "NB",
        "Dutch": "NL",
        "Polish": "PL",
        "Portuguese": "PT-PT",
        "Swedish": "SV",
        "Turkish": "TR",
    }

    class Meta:
        verbose_name = "DeepL"
        verbose_name_plural = "DeepL"

    def _init(self):
        return deepl.Translator(
            self.api_key, server_url=self.server_url, proxy=self.proxy
        )

    def validate(self) -> bool:
        is_valid = False
        try:
            translator = self._init()
            usage = translator.get_usage()
            if usage.character.valid:
                self.log = ""
                is_valid = True
        except Exception as e:
            logger.error("DeepLTranslator validate ->%s", e)
            self.log = f"{timezone.now()}: {str(e)}"
            is_valid = False
        finally:
            self.valid = is_valid
            self.save()
        return is_valid

    def translate(self, text: str, target_language: str, **kwargs) -> dict:
        logger.info(">>> DeepL Translate [%s]: %s", target_language, text)
        target_code = self.language_code_map.get(target_language, None)
        translated_text = ""
        try:
            if target_code is None:
                logger.error(
                    "DeepLTranslator->Not support target language:%s", target_language
                )
            translator = self._init()
            resp = translator.translate_text(
                text,
                target_lang=target_code,
                preserve_formatting=True,
                split_sentences="nonewlines",
                tag_handling="html",
            )
            translated_text = resp.text
        except Exception as e:
            logger.error("DeepLTranslator->%s: %s", e, text)
            self.log = f"{timezone.now()}: {str(e)}"
        finally:
            self.save()
        return {"text": translated_text, "characters": len(text)}


class LibreTranslateAgent(Agent):
    """
    An Agent that uses a LibreTranslate server for translation,
    with API communication logic integrated directly into the class.
    """

    api_key = EncryptedCharField(_("API Key (if required)"), max_length=255, blank=True)
    server_url = models.URLField(
        verbose_name="Server URL",
        default="https://libretranslate.com",
        help_text="Your self-hosted or public LibreTranslate server endpoint",
    )
    max_characters = models.IntegerField(
        default=5000,
        verbose_name="Max Characters",
        help_text="Maximum characters per translation request",
    )
    language_map = {
        "Chinese Simplified": "zh",
        "Chinese Traditional": "zh",
        "English": "en",
        "Spanish": "es",
        "French": "fr",
        "German": "de",
        "Italian": "it",
        "Portuguese": "pt",
        "Russian": "ru",
        "Japanese": "ja",
        "Dutch": "nl",
        "Korean": "ko",
        "Czech": "cs",
        "Danish": "da",
        "Indonesian": "id",
        "Polish": "pl",
        "Hungarian": "hu",
        "Norwegian Bokmål": "nb",
        "Swedish": "sv",
        "Turkish": "tr",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # --------------------------------
    # API Methods
    # --------------------------------
    def _api_request(
        self, endpoint: str, params: dict = None, method: str = "POST"
    ) -> any:
        """
        Handles sending requests to the configured LibreTranslate server endpoint.
        """
        try:
            url = self.server_url
            if not url.endswith("/"):
                url += "/"
            full_url = f"{url}{endpoint}"

            query_params = params or {}
            if self.api_key:
                query_params["api_key"] = self.api_key

            data = parse.urlencode(query_params).encode("utf-8")
            req = request.Request(full_url, data=data, method=method)
            req.add_header("accept", "application/json")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            req.add_header("User-Agent", "LibreTranslateAgent/1.0")

            with request.urlopen(req, timeout=settings.LT_TIMEOUT) as response:
                response_str = response.read().decode("utf-8")
                return json.loads(response_str)
        except Exception as e:
            raise ConnectionError(f"_api_request {str(e)}")  # e.reason

    def _api_translate(
        self, q: str, source: str, target: str, format: str = "html"
    ) -> str:
        """Calls the /translate endpoint."""
        params = {"q": q, "source": source, "target": target, "format": format}
        response_data = self._api_request("translate", params=params, method="POST")

        if "error" in response_data:
            raise Exception(f"_api_translate Error: {response_data['error']}")

        return response_data.get("translatedText", "")

    def _api_languages(self) -> list:
        """Calls the /languages endpoint."""
        # Languages endpoint requires a GET request
        return self._api_request("languages", method="GET")

    # --------------------------------
    # Agent Methods
    # --------------------------------
    def validate(self) -> bool:
        is_valid = False
        try:
            self._api_languages()
            self.log = ""
            is_valid = True
        except Exception as e:
            self.log = f"{timezone.now()}: {str(e)}"
            is_valid = False
        finally:
            self.valid = is_valid
            self.save()
        return is_valid

    def translate(self, text: str, target_language: str, **kwargs) -> dict:
        target_code = self.language_map.get(target_language)
        if not target_code:
            self.log += (
                f"{timezone.now()}: Not support target language: {target_language}"
            )
            logger.error(
                f"LibreTranslateAgent->Not support target language: {target_language}"
            )
            self.save()
            return {"text": "", "characters": 0}

        try:
            translated_text = self._api_translate(
                q=text, source="auto", target=target_code, format="html"
            )
            return {"text": translated_text, "characters": len(text)}
        except Exception as e:
            logger.error("LibreTranslateAgent->: %s", str(e))
            self.log = f"{timezone.now()}: {str(e)}"
            self.save()
            return {"text": "", "characters": 0}

    class Meta:
        verbose_name = "LibreTranslate"
        verbose_name_plural = "LibreTranslate"


class TestAgent(Agent):
    translated_text = models.TextField(default="@@Translated Text@@")
    max_characters = models.IntegerField(default=50000)
    max_tokens = models.IntegerField(default=50000)
    interval = models.IntegerField(_("Request Interval(s)"), default=3)
    is_ai = models.BooleanField(default=True, editable=False)

    class Meta:
        verbose_name = "Test"
        verbose_name_plural = "Test"

    def validate(self) -> bool:
        return True

    def translate(self, text: str, target_language: str, **kwargs) -> dict:
        logger.info(">>> Test Translate [%s]: %s", target_language, text)
        time.sleep(self.interval)
        return {"text": self.translated_text, "tokens": 10, "characters": len(text)}

    def summarize(self, text: str, target_language: str, **kwargs) -> dict:
        logger.info(">>> Test Summarize [%s]: %s", target_language, text)
        time.sleep(self.interval)
        return {"text": self.translated_text, "tokens": 10, "characters": len(text)}

    def filter(self, text: str, **kwargs):
        logger.info(">>> Test Filter")
        import random

        time.sleep(self.interval)
        return {"passed": random.choice([True, False]), "tokens": 10}
