from supybot import utils, plugins, ircutils, callbacks, conf
from supybot.commands import *
from supybot.i18n import PluginInternationalization
import re
import requests
import random
import time
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import threading
from supybot import ircmsgs

_ = PluginInternationalization("Pollinations")

class Pollinations(callbacks.Plugin):
    """Use the Pollinations.ai API for text and image generation"""
    threaded = True

    def __init__(self, irc):
        self.__parent = super(Pollinations, self)
        self.__parent.__init__(irc)
        self.session = requests.Session()
        retry_strategy = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=None, raise_on_status=False)
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        # Dedicated session for image requests: image gen often returns transient
        # 500/429 errors, so we retry those too with a longer backoff.
        self.image_session = requests.Session()
        image_retry = Retry(
            total=1,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            # Return the last response (with the error status) instead of
            # raising RetryError when retries are exhausted, so the caller can
            # inspect the status and fall back to another model.
            raise_on_status=False,
        )
        image_adapter = HTTPAdapter(max_retries=image_retry, pool_connections=10, pool_maxsize=10)
        self.image_session.mount("http://", image_adapter)
        self.image_session.mount("https://", image_adapter)
        self.max_workers = 10
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self.pending = 0
        self.pending_lock = threading.Lock()
        self.dict_lock = threading.Lock()
        self.max_pending = 10  
        self.last_reply_time = {}
        self.cleanup_interval = 3600
        self.last_cleanup = time.time()
        self.context_cache = {}
        self.context_cache_ttl = 90
        self.active_requests = threading.Semaphore(5)
        self._last_drop_notice = {}
        self._drop_notice_interval = 30
        self._text_models_cache = None  # (timestamp, set_of_names) or None
        self._text_models_cache_ttl = 600  # 10 minutes
        
        
    def doPrivmsg(self, irc, msg):
        if not irc.isChannel(msg.channel):
            return
        if not self.registryValue("auto_reply", msg.channel):
            return
        if msg.nick == irc.nick:
            return
        trigger_words = self.registryValue("trigger_words", msg.channel)
        if not trigger_words:
            return
        message = msg.args[1]
        min_interval = self.registryValue("min_reply_interval", msg.channel)
        now = time.time()
        
        with self.dict_lock:
            last = self.last_reply_time.get(msg.channel, 0)
            
        if now - last < min_interval:
            return
            
        with self.dict_lock:
            if now - self.last_cleanup > self.cleanup_interval:
                cutoff = now - self.cleanup_interval
                self.last_reply_time = {k: v for k, v in self.last_reply_time.items() if v > cutoff}
                self.last_cleanup = now
                
        for word in trigger_words:
            processed_word = word.replace("_", " ").replace("$botnick", irc.nick)
            if word.startswith('*') and word.endswith('*'):
                pattern = re.escape(processed_word.strip('*'))
            elif word.endswith('*'):
                pattern = r'^' + re.escape(processed_word.rstrip('*'))
            elif word.startswith('*'):
                pattern = re.escape(processed_word.lstrip('*')) + r'$'
            else:
                pattern = r'^' + re.escape(processed_word) + r'$'
            if re.search(pattern, message, re.IGNORECASE):
                probability = self.registryValue("trigger_probability", msg.channel)
                if random.random() <= probability:
                    with self.pending_lock:
                        if self.pending >= self.max_pending:
                            now_drop = time.time()
                            last_drop = self._last_drop_notice.get(msg.channel, 0)
                            if now_drop - last_drop >= self._drop_notice_interval:
                                self._last_drop_notice[msg.channel] = now_drop
                                irc.reply("Queue is full, request dropped. Please try again shortly.", prefixNick=False, to=msg.channel)
                            return
                        self.pending += 1
                    def _run():
                        try:
                            text = message
                            prefix = irc.nick + " "
                            if text.lower().startswith(prefix.lower()):
                                text = text[len(prefix):].strip()
                            self._chat(irc, msg, text)
                        finally:
                            with self.pending_lock:
                                self.pending -= 1
                    self.executor.submit(_run)
                    break
    
    @staticmethod
    def tail_lines(path, n):
        try:
            with open(path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()

                block_size = n * 150
                max_size = 524288

                if size > max_size:
                    size = max_size
                
                if size < block_size:
                    f.seek(0)
                else:
                    f.seek(size - block_size)
                    f.readline()  
                
                lines = [line.decode("utf-8", errors="ignore").rstrip() for line in f]
                return lines[-n:] if len(lines) > n else lines
        except Exception:
            return []
    
    def _read_context(self, irc, channel, context_lines):
        try:
            start_time = time.time()
            timeout = 3.5
            log_dir = conf.supybot.directories.log()
            network = irc.network
            channel_lower = channel.lower()
            log_path = os.path.join(log_dir, "ChannelLogger", network, channel_lower, f"{channel_lower}.log")
            
            if not os.path.exists(log_path):
                return ""
            
            recent = self.tail_lines(log_path, context_lines)
            # Bail out if file reading already took too long (bounded by the
            # 512KB seek cap in tail_lines, but check just in case).
            if time.time() - start_time > timeout:
                return ""
            chat_lines = []
            for line in recent:
                if "<" in line and ">" in line:
                    parts = line.split(">", 1)
                    if len(parts) == 2:
                        nick_part = parts[0].split("<")[-1]
                        message_part = parts[1].strip()
                        if nick_part and message_part:
                            chat_lines.append(f"{nick_part}: {message_part}")
            return "\n".join(chat_lines[-context_lines:])
        except Exception:
            return ""

    def _get_valid_text_models(self):
        """Return a set of valid text model names, cached for 10 minutes.

        Fetches GET https://gen.pollinations.ai/text/models on cache miss.
        Returns None on any failure (failures are NOT cached).
        """
        now = time.time()
        if self._text_models_cache is not None:
            cached_ts, cached_set = self._text_models_cache
            if now - cached_ts < self._text_models_cache_ttl:
                return cached_set

        try:
            response = self.session.get(
                "https://gen.pollinations.ai/text/models", timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    names = set()
                    for m in data:
                        if isinstance(m, dict):
                            if m.get("name"):
                                names.add(m["name"])
                            if m.get("id"):
                                names.add(m["id"])
                            names.update(m.get("aliases") or [])
                        elif isinstance(m, str):
                            names.add(m)
                    if names:
                        self._text_models_cache = (now, names)
                        return names
        except Exception:
            pass
        return None

    def _chat_request(self, model, messages, timeout, api_token):
        """Send a chat completion API request for the given model.

        Returns (content_string, None) on success with usable content,
        or (None, error_string) on failure.  Raises on network/timeout
        errors so the caller can surface them to IRC.
        """
        payload = {
            "messages": messages,
            "model": model,
            "jsonMode": False
        }
        headers = {"Content-Type": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        _attempt_start = time.time()
        response = self.session.post(
            "https://gen.pollinations.ai/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=timeout
        )
        _elapsed = time.time() - _attempt_start

        if response.status_code != 200:
            self.log.info("Text attempt on model %s took %.1fs (status=%s)", model, _elapsed, response.status_code)
            self.log.warning(f"Chat API error {response.status_code} (model={model})")
            return (None, "HTTP %d" % response.status_code)

        try:
            data = response.json()
            choice = data.get("choices", [{}])[0]
            finish_reason = choice.get("finish_reason", "")

            if finish_reason == "content_filter":
                self.log.info("Text attempt on model %s took %.1fs (status=%s)", model, _elapsed, "content_filter")
                filter_results = choice.get("content_filter_results", {})
                filtered_categories = [
                    k for k, v in filter_results.items()
                    if isinstance(v, dict) and v.get("filtered")
                ]
                details = ", ".join(filtered_categories) if filtered_categories else "content policy"
                return (None, "content_filter:" + details)

            content = choice.get("message", {}).get("content", "").strip()
            if content and len(content) >= 3:
                self.log.info("Text attempt on model %s took %.1fs (status=%s)", model, _elapsed, "ok")
                return (content, None)
            self.log.info("Text attempt on model %s took %.1fs (status=%s)", model, _elapsed, "empty")
            return (None, "empty")
        except (ValueError, KeyError, IndexError) as e:
            self.log.info("Text attempt on model %s took %.1fs (status=%s)", model, _elapsed, "parse_error")
            self.log.error(f"Parse error (model={model}): {e}")
            return (None, "parse_error")

    @staticmethod
    def _clean_markdown(content):
        """Turn model markdown into IRC-friendly text.

        Search models cite sources as '([site](url))' after every claim; on
        IRC that is noise that also eats the line-length budget, so citations
        are dropped. Remaining links keep their label, bold becomes IRC bold.
        """
        # Parenthesised citations: ([label](url)) or ([a](u1), [b](u2))
        content = re.sub(r"\s*\(\s*\[[^\]]*\]\([^)]*\)(?:\s*[,;]\s*\[[^\]]*\]\([^)]*\))*\s*\)", "", content)
        # Bare citations: [label](url) -> label (keeps legit named links readable)
        content = re.sub(r"\[([^\]]+)\]\((?:https?://)[^)]*\)", r"\1", content)
        content = re.sub(r"\*\*(.+?)\*\*", "\x02\\1\x02", content)
        content = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", "\x1d\\1\x1d", content)
        content = re.sub(r"`([^`\n]+)`", r"\1", content)
        content = re.sub(r"^#{1,6}\s+", "", content, flags=re.M)
        content = re.sub(r"[ \t]{2,}", " ", content)
        return content.strip()

    def _chat(self, irc, msg, text, model_setting="text_model", fallback_setting="text_fallback_model", extra_prompt_setting=None):
        channel = msg.channel if irc.isChannel(msg.channel) else msg.nick
        
        if not self.active_requests.acquire(blocking=False):
            irc.reply("I am processing too many requests right now. Please try again in a moment.", prefixNick=False)
            return
            
        try:
            if self.registryValue("nick_include", msg.channel):
                text = "%s: %s" % (msg.nick, text)
            
            prompt = self.registryValue("prompt", msg.channel).replace("$botnick", irc.nick)
            if extra_prompt_setting:
                extra = self.registryValue(extra_prompt_setting, msg.channel).strip()
                if extra:
                    prompt = "%s %s" % (prompt, extra.replace("$botnick", irc.nick))
            context_lines = self.registryValue("context_lines", msg.channel)
            context = ""
            
            if context_lines > 0:
                cache_key = msg.channel
                now = time.time()
                
                with self.dict_lock:
                    if cache_key in self.context_cache:
                        cached_time, cached_context = self.context_cache[cache_key]
                        if now - cached_time < self.context_cache_ttl:
                            context = cached_context
                        else:
                            context = self._read_context(irc, channel, context_lines)
                            self.context_cache[cache_key] = (now, context)
                    else:
                        context = self._read_context(irc, channel, context_lines)
                        self.context_cache[cache_key] = (now, context)
            
            timeout = self.registryValue("text_timeout", msg.channel) 
            text_model = self.registryValue(model_setting, msg.channel)
            api_token = self.registryValue("api_token", msg.channel)

            messages = [
                {"role": "system", "content": prompt}
            ]

            if context:
                messages.append({"role": "system", "content": f"Recent conversation:\n{context}"})

            messages.append({"role": "user", "content": text})

            # --- primary attempt ---
            content, error = self._chat_request(text_model, messages, timeout, api_token)

            # Content filter is not retryable — reply immediately
            if error is not None and isinstance(error, str) and error.startswith("content_filter:"):
                details = error.split(":", 1)[1]
                if details != "content policy":
                    irc.reply("Response filtered by content policy (%s)" % details, prefixNick=False)
                else:
                    irc.reply("Response filtered by content policy", prefixNick=False)
                return

            # --- fallback attempts on failure ---
            if content is None:
                valid_models = self._get_valid_text_models()
                # Skip primary model early if it's known to be invalid
                if valid_models is not None and text_model not in valid_models:
                    self.log.info("Primary text model '%s' is not in the valid models list", text_model)

                fallback_models_str = self.registryValue(fallback_setting, msg.channel)
                fallback_models = fallback_models_str.split() if fallback_models_str else []
                for fb_model in fallback_models:
                    if fb_model.lower() != text_model.lower():
                        # Fast-fail: skip fallback models not in the valid list
                        if valid_models is not None and fb_model not in valid_models:
                            self.log.info("Skipping unknown text fallback model: %s", fb_model)
                            continue
                        self.log.info(
                            "Primary model '%s' failed (%s), trying fallback '%s'"
                            % (text_model, error, fb_model)
                        )
                        content, fb_error = self._chat_request(fb_model, messages, timeout, api_token)
                        if content is not None:
                            break
                        # Content filter on fallback — reply and stop
                        if fb_error is not None and isinstance(fb_error, str) and fb_error.startswith("content_filter:"):
                            details = fb_error.split(":", 1)[1]
                            if details != "content policy":
                                irc.reply("Response filtered by content policy (%s)" % details, prefixNick=False)
                            else:
                                irc.reply("Response filtered by content policy", prefixNick=False)
                            return
                        error = fb_error  # track last error for logging

            if content is None:
                self.log.warning("All text models failed. Last error: %s" % (error,))
                irc.reply("The AI service is currently unavailable, please try again in a moment.", prefixNick=False)
                return

            # --- format and send reply ---
            content = self._clean_markdown(content)
            if self.registryValue("nick_strip", msg.channel):
                content = re.sub(r"^%s: " % (irc.nick), "", content)

            prefix = self.registryValue("nick_prefix", msg.channel)
            if self.registryValue("reply_intact", msg.channel):
                for line in content.splitlines():
                    if line:
                        text = "%s: %s" % (msg.nick, line) if prefix else line
                        irc.queueMsg(ircmsgs.privmsg(channel, text))
            else:
                response_text = " ".join(content.splitlines())
                text = "%s: %s" % (msg.nick, response_text) if prefix else response_text
                irc.reply(text, prefixNick=False, to=channel)

            with self.dict_lock:
                self.last_reply_time[msg.channel] = time.time()
        
        except requests.exceptions.Timeout:
            irc.reply("Request timed out.", prefixNick=False)
            return
        except requests.exceptions.RetryError:
            irc.reply("The AI service is overloaded right now, please try again in a moment.", prefixNick=False)
            return
        except requests.exceptions.RequestException as e:
            self.log.warning(f"Network error: {repr(e)}")
            irc.reply("Network error.", prefixNick=False)
            return
        except Exception as e:
            self.log.error(f"Unexpected error in _chat: {repr(e)}")
            irc.reply("Unexpected error.", prefixNick=False)
            return
        finally:
            self.active_requests.release()

    def chat(self, irc, msg, args, text):
        """Public command wrapper for _chat"""
        self._chat(irc, msg, text)

    chat = wrap(chat, ["text"])

    def search(self, irc, msg, args, text):
        """<query>
        Answer a question using live web search (needs a search-capable
        model, see 'models search'). Example: search who won the match today
        """
        self._chat(irc, msg, text, "search_model", "search_fallback_model", "search_prompt")

    search = wrap(search, ["text"])

    def image(self, irc, msg, args, text):
        """Generate image from text prompt using Pollinations.ai"""
        if not text.strip():
            irc.reply("Please provide a prompt", prefixNick=False)
            return
            
        if not self.active_requests.acquire(blocking=False):
            irc.reply("The image server is currently busy. Please try again shortly.", prefixNick=False)
            return
        
        try:
            width = self.registryValue("image_width", msg.channel)
            height = self.registryValue("image_height", msg.channel)
            model = self.registryValue("image_model", msg.channel)
            enhance = self.registryValue("image_enhance", msg.channel)
            nologo = self.registryValue("image_nologo", msg.channel)
            private = self.registryValue("image_private", msg.channel)
            safe = self.registryValue("image_safe", msg.channel)
            negative_prompt = self.registryValue("negative_prompt", msg.channel)
            shorten_urls = self.registryValue("shorten_urls", msg.channel)
            timeout = self.registryValue("image_timeout", msg.channel)
            fallback_model = self.registryValue("image_fallback_model", msg.channel)
            api_token = self.registryValue("api_token", msg.channel)
            
            # nologo and private require an authenticated account; without a token
            # they are ignored by the API and can contribute to errors, so only
            # send them when we actually have a token.
            if not api_token:
                nologo = False
                private = False
            
            seed = random.randint(1, 1000000)
            
            params = {
                "width": width,
                "height": height,
                "seed": seed,
                "model": model,
                "enhance": str(enhance).lower(),
                "nologo": str(nologo).lower(),
                "private": str(private).lower(),
                "safe": str(safe).lower(),
                "referrer": "limnoria-pollinations-plugin",
            }
            
            if negative_prompt.strip():
                params["negative_prompt"] = negative_prompt
            
            final_url = self._generate_image(text, params, timeout, model, fallback_model, api_token)
            
            if final_url is None:
                return  # error already replied
            
            if not final_url.startswith("image://"):
                # final_url is the image URL
                display_url = final_url
                if shorten_urls:
                    try:
                        shorten_response = self.session.post(
                            "https://is.gd/create.php",
                            data={"format": "simple", "url": display_url},
                            timeout=5,
                        )
                        if shorten_response.status_code == 200:
                            candidate = shorten_response.text.strip()
                            # is.gd returns the short URL on success, but on
                            # failure it returns 200 with an error message like
                            # "Error, database insert failed". Only use the
                            # candidate if it actually looks like a URL.
                            if candidate.lower().startswith("http"):
                                display_url = candidate
                            else:
                                self.log.warning(
                                    f"URL shortener returned non-URL body: {candidate[:120]}"
                                )
                        else:
                            self.log.warning(
                                f"URL shortener returned status {shorten_response.status_code}"
                            )
                    except Exception as e:
                        self.log.warning(f"URL shortener failed: {e}")
                irc.reply(display_url, prefixNick=False)
            else:
                # error sentinel
                irc.reply(final_url[len("image://"):], prefixNick=False)
        except requests.exceptions.Timeout:
            irc.reply("Request timed out (image generation can take up to 60s, try again)", prefixNick=False)
        except requests.exceptions.RequestException as e:
            self.log.warning(f"Network error in image(): {repr(e)}")
            irc.reply("Network error", prefixNick=False)
        except Exception as e:
            self.log.error(f"Error in image(): {repr(e)}")
            irc.reply("Error generating image", prefixNick=False)
        finally:
            self.active_requests.release()

    def _generate_image(self, text, params, timeout, model, fallback_model, api_token):
        """Build the image URL, request it, and return either the final image
        URL string, or an 'image://<error message>' sentinel, or None if an
        error was already replied. Tries the configured model first, then the
        fallback model if the first attempt fails with a non-transient error."""
        def _build_url(m):
            p = dict(params)
            p["model"] = m
            param_string = "&".join(
                [f"{k}={requests.utils.quote(str(v))}" for k, v in p.items()]
            )
            return f"https://image.pollinations.ai/prompt/{requests.utils.quote(text)}?{param_string}"

        def _attempt(m):
            image_url = _build_url(m)
            self.log.info(f"Requesting image URL: {image_url[:200]}...")
            headers = {}
            if api_token:
                headers["Authorization"] = f"Bearer {api_token}"
            try:
                response = self.image_session.get(
                    image_url, timeout=timeout, allow_redirects=True, headers=headers
                )
            except requests.exceptions.RequestException as e:
                # Network/timeout/SSL error — log and fall back to the next model
                # instead of letting the exception propagate (which would skip
                # the fallback and surface as a generic "Network error").
                self.log.warning(f"Image request failed (model={m}): {repr(e)}")
                return None
            self.log.info(
                f"Response status: {response.status_code}, "
                f"Content-Type: {response.headers.get('Content-Type', 'unknown')}"
            )
            if response.status_code == 200:
                content_type = response.headers.get("Content-Type", "")
                if content_type.startswith("image/"):
                    return response.url
                # 200 but not an image — log body for diagnosis
                body = response.text[:300] if response.text else ""
                self.log.warning(f"Non-image 200 response (model={m}): {body}")
                return f"image://Generated invalid image, try different prompt"
            else:
                body = response.text[:300] if response.text else ""
                self.log.warning(
                    f"Image API error {response.status_code} (model={m}): {body}"
                )
                return None

        result = _attempt(model)
        if result is not None:
            return result

        # First attempt failed; try the fallback model if it's different
        if fallback_model and fallback_model.lower() != model.lower():
            self.log.info(f"Primary model '{model}' failed, trying fallback '{fallback_model}'")
            result = _attempt(fallback_model)
            if result is not None:
                return result
            return f"image://Error: image generation failed for both '{model}' and '{fallback_model}'"

        return f"image://Error: image generation failed for model '{model}'"

    image = wrap(image, ["text"])

    def models(self, irc, msg, args, model_type, category):
        """[text|image] [low|med|high]
        Lists API models organized by price. Example: models text low
        """
        model_type = (model_type or "").lower().strip()
        category = (category or "").lower().strip()

        if model_type not in ["text", "image", "search"]:
            irc.reply("Please specify the model type. Usage: models text [low|med|high] OR models image [low|med|high] OR models search", prefixNick=False)
            return

        try:
            if model_type == "search":
                response = self.session.get(
                    "https://gen.pollinations.ai/text/models",
                    params={"capabilities": "web_search"}, timeout=5)
                if response.status_code != 200:
                    irc.reply("Error contacting the text API.", prefixNick=False)
                    return
                data = response.json()
                names = []
                for m in data if isinstance(data, list) else []:
                    if not isinstance(m, dict) or str(m.get("name", "")).startswith("community/"):
                        continue
                    aliases = m.get("aliases") or []
                    # Prefer the shortest alias: it is the one people type.
                    names.append(min(aliases, key=len) if aliases else m.get("name"))
                irc.reply("Web search models: %s" % (", ".join(names) if names else "none found"), prefixNick=False)
                return

            url = f"https://gen.pollinations.ai/{model_type}/models"
            response = self.session.get(url, timeout=5)
            
            if response.status_code != 200:
                irc.reply(f"Error contacting the {model_type} API.", prefixNick=False)
                return

            data = response.json()
            if not isinstance(data, list):
                irc.reply("Unknown data format received.", prefixNick=False)
                return
            
            # Se a API de imagens devolver apenas nomes sem preços
            if len(data) > 0 and isinstance(data[0], str):
                if category:
                    irc.reply(f"All {model_type.capitalize()} models (no price tiers available): {', '.join(data)}", prefixNick=False)
                else:
                    irc.reply(f"Available {model_type.capitalize()} Models: {', '.join(data)}", prefixNick=False)
                return

            low, med, high = [], [], []

            for m in data:
                if not isinstance(m, dict): continue
                name = m.get("name") or m.get("id")
                if not name: continue
                
                pricing = m.get("pricing", {})
                price_val = 0.0
                
                if pricing:
                    val = pricing.get("promptTextTokens") or pricing.get("price") or 0.0
                    try:
                        price_val = float(val) * 1000000
                    except ValueError:
                        price_val = 0.0

                if price_val <= 0.50:
                    low.append(name)
                elif price_val <= 1.50:
                    med.append(name)
                else:
                    high.append(name)

            if category in ["low", "cheap", "free"]:
                irc.reply(f"Low Cost {model_type.capitalize()} Models: {', '.join(low)}" if low else f"No low cost {model_type} models found.", prefixNick=False)
            elif category in ["med", "medium"]:
                irc.reply(f"Med Cost {model_type.capitalize()} Models: {', '.join(med)}" if med else f"No medium cost {model_type} models found.", prefixNick=False)
            elif category in ["high", "premium"]:
                irc.reply(f"High Cost {model_type.capitalize()} Models: {', '.join(high)}" if high else f"No high cost {model_type} models found.", prefixNick=False)
            else:
                irc.reply(f"{model_type.capitalize()} API Summary: {len(low)} low, {len(med)} med, and {len(high)} high models.", prefixNick=False)
                irc.reply(f"Usage: models {model_type} low | med | high", prefixNick=False)

        except Exception as e:
            self.log.error(f"Error in models command: {e}")
            irc.reply("Internal error while fetching models.", prefixNick=False)

    # CORREÇÃO: "somethingWithoutSpaces" garante que o Limnoria apanha apenas uma palavra (text/image) e deixa o resto para a category
    models = wrap(models, [optional("somethingWithoutSpaces"), optional("text")])
    
    def die(self):
        try:
            # wait=False so reload/shutdown is not blocked by in-flight
            # image requests (which can take up to 60s). Pending workers will
            # be abandoned and cleaned up by the interpreter on exit.
            self.executor.shutdown(wait=False)
        except Exception:
            pass
        self.__parent.die()

Class = Pollinations
