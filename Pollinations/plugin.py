from supybot import utils, plugins, ircutils, callbacks, conf
from supybot.commands import *
from supybot.i18n import PluginInternationalization
import re
import requests
import random
import time
import os
import json
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
        # Daily search count and the Tavily credits the bot spent this month,
        # kept on disk so a restart does not reset them.
        self._search_stats = self._load_search_stats()
        self._search_last = {}  # hostmask -> time of last search

        
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

    def _chat_request(self, model, messages, timeout, api_token, options=None):
        """Send a chat completion API request for the given model.

        options are extra payload fields (e.g. reasoning_effort); a model
        that rejects them with HTTP 400 is asked once more without them.
        Returns (content_string, None) on success with usable content,
        or (None, error_string) on failure.  Raises on network/timeout
        errors so the caller can surface them to IRC.
        """
        payload = {
            "messages": messages,
            "model": model,
            "jsonMode": False
        }
        payload.update(options or {})
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
            if response.status_code == 400 and options:
                self.log.info("Retrying model %s without %s", model, ", ".join(options))
                return self._chat_request(model, messages, timeout, api_token)
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
        # Bare citations whose label is just a domain: [yr.no](url) -> dropped
        content = re.sub(r"\s*\[(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:/[^\]\s]*)?\]\((?:https?://)[^)]*\)", "", content)
        # Other links keep their label so named links stay readable
        content = re.sub(r"\[([^\]]+)\]\((?:https?://)[^)]*\)", r"\1", content)
        # Plain-text citations the model appends at the end: bare domains or
        # URLs left on their own after the last sentence
        content = re.sub(r"(?:[ \t]+(?:https?://\S+|(?:www\.)?[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|io|gov|edu|fr|uk|de|es|pt|br|no|eu|info)(?:/\S*)?))+[ \t]*$", "", content, flags=re.M)
        content = re.sub(r"(?im)^\s*(?:sources?|references?)\s*:.*$", "", content)
        content = re.sub(r"\*\*(.+?)\*\*", "\x02\\1\x02", content)
        content = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", "\x1d\\1\x1d", content)
        content = re.sub(r"`([^`\n]+)`", r"\1", content)
        content = re.sub(r"^#{1,6}\s+", "", content, flags=re.M)
        content = re.sub(r"[ \t]{2,}", " ", content)
        return content.strip()

    def _send_reply(self, irc, msg, channel, content, suffix="", tag=""):
        content = self._clean_markdown(content)
        if self.registryValue("nick_strip", msg.channel):
            content = re.sub(r"^%s: " % (irc.nick), "", content)
        content = tag + content.rstrip() + suffix

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

    def _chat(self, irc, msg, text, model_setting="text_model", fallback_setting="text_fallback_model", extra_prompt_setting=None, persona_setting=None, thinking_setting=None, extra_system=None, suffix="", tag="", reasoning_setting=None):
        channel = msg.channel if irc.isChannel(msg.channel) else msg.nick
        
        if not self.active_requests.acquire(blocking=False):
            irc.reply("I am processing too many requests right now. Please try again in a moment.", prefixNick=False)
            return
            
        try:
            if self.registryValue("nick_include", msg.channel):
                text = "%s: %s" % (msg.nick, text)
            
            prompt = self.registryValue("prompt", msg.channel).replace("$botnick", irc.nick)
            if extra_prompt_setting:
                extra = self.registryValue(extra_prompt_setting, msg.channel).strip().replace("$botnick", irc.nick)
                # Without the persona toggle the extra prompt replaces the
                # main one entirely, so a personality does not leak in.
                if persona_setting and not self.registryValue(persona_setting, msg.channel):
                    prompt = extra
                elif extra:
                    prompt = "%s %s" % (prompt, extra)

            if thinking_setting:
                thinking = self.registryValue(thinking_setting, msg.channel).strip()
                if thinking:
                    irc.queueMsg(ircmsgs.privmsg(channel, thinking))
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

            # Models do not know today's date; search answers in particular
            # need it to tell live facts from stale page snapshots.
            now = time.strftime("%A, %Y-%m-%d %H:%M UTC", time.gmtime())
            messages = [
                {"role": "system", "content": "%s\nCurrent date and time: %s." % (prompt, now)}
            ]

            if context:
                messages.append({"role": "system", "content": f"Recent conversation:\n{context}"})

            if extra_system:
                messages.append({"role": "system", "content": extra_system})

            messages.append({"role": "user", "content": text})

            options = {}
            if reasoning_setting:
                effort = self.registryValue(reasoning_setting, msg.channel).strip()
                if effort:
                    options["reasoning_effort"] = effort

            # --- primary attempt ---
            content, error = self._chat_request(text_model, messages, timeout, api_token, options)

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
                        content, fb_error = self._chat_request(fb_model, messages, timeout, api_token, options)
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

            self._send_reply(irc, msg, channel, content, suffix, tag)

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

    def _shorten_url(self, url):
        """Return the is.gd short URL, or the original URL if that fails."""
        try:
            shorten_response = self.session.post(
                "https://is.gd/create.php",
                data={"format": "simple", "url": url},
                timeout=5,
            )
            if shorten_response.status_code == 200:
                candidate = shorten_response.text.strip()
                # is.gd returns the short URL on success, but on
                # failure it returns 200 with an error message like
                # "Error, database insert failed". Only use the
                # candidate if it actually looks like a URL.
                if candidate.lower().startswith("http"):
                    return candidate
                self.log.warning(
                    f"URL shortener returned non-URL body: {candidate[:120]}"
                )
            else:
                self.log.warning(
                    f"URL shortener returned status {shorten_response.status_code}"
                )
        except Exception as e:
            self.log.warning(f"URL shortener failed: {e}")
        return url

    @staticmethod
    def _search_results(items, limit, length):
        """Keep (title, url, snippet) for results that have a URL, snippets
        cut to length characters."""
        results = []
        for item in items or []:
            if isinstance(item, dict) and item.get("url"):
                results.append((
                    (item.get("title") or "").strip(),
                    item["url"],
                    " ".join((item.get("content") or "").split())[:length],
                ))
        return results[:limit]

    @staticmethod
    def _search_stats_path():
        return conf.supybot.directories.data.dirize("Pollinations-search.json")

    def _load_search_stats(self):
        # capped: today's searches on the backends search_daily_limit covers
        stats = {"day": None, "searches": 0, "capped": 0, "month": None,
                 "tavily_credits": 0, "tavily_searches": 0}
        try:
            with open(self._search_stats_path()) as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                # The file may be edited by hand: take counts written as
                # "5" or 5.0, drop anything that is not a number.
                for k in stats:
                    if k not in saved:
                        continue
                    if k in ("day", "month"):
                        stats[k] = str(saved[k]) if saved[k] else None
                        continue
                    try:
                        stats[k] = max(0, int(float(saved[k])))
                    except (TypeError, ValueError):
                        self.log.warning("Ignoring bad %s in search stats: %r", k, saved[k])
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            self.log.warning("Could not read search stats: %r", e)
        return stats

    def _save_search_stats(self):
        """Write the stats; the caller holds dict_lock."""
        try:
            f = utils.file.AtomicFile(self._search_stats_path())
            f.write(json.dumps(self._search_stats))
            f.close()
        except OSError as e:
            self.log.warning("Could not save search stats: %r", e)

    def _roll_search_stats(self, now=None):
        """Start a new day or month in the stats; the caller holds dict_lock."""
        now = time.gmtime(now)
        today, month = time.strftime("%Y-%m-%d", now), time.strftime("%Y-%m", now)
        stats = self._search_stats
        if stats["day"] != today:
            stats["day"], stats["searches"], stats["capped"] = today, 0, 0
        if stats["month"] != month:
            stats["month"], stats["tavily_credits"], stats["tavily_searches"] = month, 0, 0

    def _record_tavily(self, data, depth):
        """Add the credits a Tavily search used to this month's count."""
        credits = None
        usage = data.get("usage") if isinstance(data, dict) else None
        if isinstance(usage, dict):
            credits = usage.get("credits")
        if not isinstance(credits, (int, float)):
            credits = 2 if depth == "advanced" else 1
        with self.dict_lock:
            self._roll_search_stats()
            self._search_stats["tavily_credits"] += credits
            self._search_stats["tavily_searches"] += 1
            self._search_stats["capped"] += 1
            self._save_search_stats()

    def _search_tavily(self, query, channel):
        """Return (answer, results) from Tavily, or None if it is unusable."""
        key = self.registryValue("tavily_api_key")
        if not key:
            return None
        want_answer = not self.registryValue("tavily_rewrite", channel)
        depth = self.registryValue("tavily_depth", channel)
        payload = {
            "query": query,
            "search_depth": depth,
            "max_results": self.registryValue("search_results", channel),
            "include_answer": self.registryValue("tavily_answer", channel) if want_answer else False,
            # Reports the credits this request used, so the bot can count them
            # instead of waiting for Tavily's /usage, which lags behind.
            "include_usage": True,
        }
        try:
            response = self.session.post(
                "https://api.tavily.com/search",
                json=payload,
                headers={"Authorization": "Bearer %s" % key},
                timeout=self.registryValue("search_timeout", channel),
            )
            if response.status_code != 200:
                # 432/433 mean the monthly plan or pay-as-you-go limit is used up
                self.log.warning("Tavily search error %s: %s", response.status_code, response.text[:200])
                return None
            data = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            self.log.warning("Tavily search failed: %r", e)
            return None
        self._record_tavily(data, depth)
        answer = ""
        if want_answer and isinstance(data, dict):
            answer = (data.get("answer") or "").strip()
        results = self._search_results(data.get("results") if isinstance(data, dict) else None,
                                       self.registryValue("search_results", channel),
                                       self.registryValue("search_snippet_length", channel))
        return (answer, results)

    def _search_searxng(self, query, channel):
        """Return ("", results) from SearXNG, or None if it is unusable."""
        base = self.registryValue("searxng_url").strip().rstrip("/")
        if not base:
            return None
        limit = self.registryValue("search_results", channel)
        params = {"q": query, "format": "json", "categories": "general"}
        # "who won the last race": search engines do not know what "last"
        # means, so ask for recent pages first and widen if that is too thin.
        time_range = self.registryValue("searxng_recent_range", channel).strip()
        words = set(re.findall(r"\w+", query.lower()))
        recent_words = {w.lower() for w in self.registryValue("searxng_recent_words", channel)}
        attempts = [params]
        if time_range and words & recent_words:
            attempts.insert(0, dict(params, time_range=time_range))
        results = None
        for attempt in attempts:
            try:
                response = self.session.get(
                    base + "/search",
                    params=attempt,
                    timeout=self.registryValue("search_timeout", channel),
                )
                if response.status_code != 200:
                    # 403 here usually means the json format is not enabled in settings.yml
                    self.log.warning("SearXNG search error %s", response.status_code)
                    return None
                data = response.json()
            except (requests.exceptions.RequestException, ValueError) as e:
                self.log.warning("SearXNG search failed: %r", e)
                return None
            results = self._search_results(data.get("results") if isinstance(data, dict) else None,
                                           limit, self.registryValue("search_snippet_length", channel))
            self.log.info("SearXNG search (time_range=%s): %d results",
                          attempt.get("time_range", "any"), len(results))
            if len(results) >= min(3, limit):
                break
        return ("", results)

    def _search_allowed(self, irc, msg):
        """Apply the per-user cooldown; reply and return False when the
        search may not run. Counts the search when allowed."""
        now = time.time()
        cooldown = self.registryValue("search_cooldown", msg.channel)
        with self.dict_lock:
            last = self._search_last.get(msg.prefix, 0)
            if cooldown and now - last < cooldown:
                wait = int(cooldown - (now - last)) + 1
                irc.reply("Please wait %ds before searching again." % wait, prefixNick=False)
                return False
            self._roll_search_stats(now)
            self._search_stats["searches"] += 1
            self._save_search_stats()
            self._search_last = {k: v for k, v in self._search_last.items() if now - v < cooldown}
            self._search_last[msg.prefix] = now
        return True

    def _search_capped(self):
        """True when today's tavily/pollinations searches hit search_daily_limit."""
        limit = self.registryValue("search_daily_limit")
        with self.dict_lock:
            self._roll_search_stats()
            return bool(limit) and self._search_stats["capped"] >= limit

    def _search_refund(self):
        with self.dict_lock:
            self._search_stats["searches"] = max(0, self._search_stats["searches"] - 1)
            self._save_search_stats()

    def search(self, irc, msg, args, text):
        """<query>
        Answer a question using live web search (see the search_backend
        setting). Example: search who won the match today
        """
        channel = msg.channel if irc.isChannel(msg.channel) else msg.nick
        if not self.registryValue("search_enabled", msg.channel):
            irc.reply("Search is disabled.", prefixNick=False)
            return
        backends = [b.lower() for b in self.registryValue("search_backend", msg.channel)]
        if not backends:
            irc.reply("No search backend is configured.", prefixNick=False)
            return
        if not self._search_allowed(irc, msg):
            return

        thinking = self.registryValue("search_thinking", msg.channel).strip()
        if thinking:
            irc.queueMsg(ircmsgs.privmsg(channel, thinking))

        capped = False
        for backend in backends:
            # Tavily credits and paid search models count against the daily
            # limit; SearXNG is free and only skipped when it fails.
            if backend in ("tavily", "pollinations") and self._search_capped():
                capped = True
                continue
            if backend == "pollinations":
                with self.dict_lock:
                    self._search_stats["capped"] += 1
                    self._save_search_stats()
                self._chat(irc, msg, text, "search_model", "search_fallback_model", "search_prompt", "search_use_prompt", tag="[P] ", reasoning_setting="search_reasoning_effort")
                return
            if backend == "tavily":
                found = self._search_tavily(text, msg.channel)
            elif backend == "searxng":
                found = self._search_searxng(text, msg.channel)
            else:
                self.log.warning("Unknown search backend: %s", backend)
                continue
            if not found or not (found[0] or found[1]):
                continue
            answer, results = found
            # What the model is given, so a bad answer can be traced to bad results
            self.log.info("Search %s for %r: %s", backend, text,
                          " | ".join(title[:60] or url for title, url, _snippet in results) or "(answer only)")
            # Short marker of which backend answered: [T]avily, [S]earXNG
            tag = "[%s] " % backend[0].upper()
            urls = [url for _title, url, _snippet in results[:self.registryValue("search_sources", msg.channel)]]
            if self.registryValue("search_shorten_urls", msg.channel):
                urls = [self._shorten_url(url) for url in urls]
            suffix = (" | " + " ".join(urls)) if urls else ""
            if answer:
                self._send_reply(irc, msg, channel, answer, suffix, tag)
                return
            sources = "\n\n".join(
                "[%d] %s (%s)\n%s" % (i, title, url, snippet)
                for i, (title, url, snippet) in enumerate(results, 1))
            extra = ("Web search results for the user's question. They are saved copies of "
                     "pages and may be days old:\n\n%s\n\n"
                     "For anything live, such as the current time or date somewhere, never "
                     "use clocks or dates from these results: work it out from the current "
                     "date and time given above (convert UTC to the place's time zone). "
                     "Otherwise answer only from these results. If they point to an answer, "
                     "for example a headline saying who won, give it (with its date if the "
                     "date matters) rather than refusing; only if nothing in them answers the "
                     "question, say briefly that you could not find it. Answer as if you knew "
                     "it yourself: never mention the results, the sources or what is 'listed "
                     "here', do not write the [n] numbers, and never ask the user questions or "
                     "offer to look anything up." % sources)
            self._chat(irc, msg, text, "search_text_model", "search_text_fallback_model",
                       "search_prompt", "search_use_prompt", extra_system=extra, suffix=suffix, tag=tag,
                       reasoning_setting="search_reasoning_effort")
            return

        self._search_refund()
        if capped:
            irc.reply("Daily search limit reached (%d). It resets at 00:00 UTC."
                      % self.registryValue("search_daily_limit"), prefixNick=False)
        else:
            irc.reply("Web search is unavailable right now, please try again later.", prefixNick=False)

    search = wrap(search, ["text"])

    def searchusage(self, irc, msg, args):
        """takes no arguments

        Shows today's search count, the Tavily credits the bot spent this
        month and the Tavily account usage.
        """
        with self.dict_lock:
            self._roll_search_stats()
            stats = dict(self._search_stats)
        limit = self.registryValue("search_daily_limit")
        capped_names = [b.capitalize() for b in self.registryValue("search_backend", msg.channel)
                        if b.lower() in ("tavily", "pollinations")] or ["Tavily"]
        parts = ["Today: %d searches, %d/%s %s" % (
            stats["searches"], stats["capped"], limit or "unlimited", "+".join(capped_names))]
        key = self.registryValue("tavily_api_key")
        if key:
            parts.append("Tavily this month (bot): %s credits in %d searches" % (
                stats["tavily_credits"], stats["tavily_searches"]))
            try:
                response = self.session.get(
                    "https://api.tavily.com/usage",
                    headers={"Authorization": "Bearer %s" % key}, timeout=10)
                account = None
                if response.status_code == 200:
                    account = response.json().get("account")
            except (requests.exceptions.RequestException, ValueError, AttributeError) as e:
                self.log.warning("Tavily usage failed: %r", e)
                account = None
            if isinstance(account, dict) and account.get("plan_limit") is not None:
                used, total = account.get("plan_usage") or 0, account["plan_limit"]
                parts.append("Tavily account: %s/%s credits used (%s left, plan %s; may lag)" % (
                    used, total, total - used, account.get("current_plan") or "?"))
            else:
                parts.append("Tavily account: usage unavailable")
        irc.reply(" | ".join(parts), prefixNick=False)

    searchusage = wrap(searchusage, ["owner"])

    def polliusage(self, irc, msg, args):
        """takes no arguments

        Shows the Pollinations pollen balance and what this bot's API key
        spent in the last 24 hours.
        """
        api_token = self.registryValue("api_token", msg.channel)
        if not api_token:
            irc.reply("No Pollinations api_token is set.", prefixNick=False)
            return
        headers = {"Authorization": "Bearer %s" % api_token}
        parts = []

        try:
            response = self.session.get(
                "https://gen.pollinations.ai/account/balance", headers=headers, timeout=10)
            data = response.json() if response.status_code == 200 else None
        except (requests.exceptions.RequestException, ValueError) as e:
            self.log.warning("Pollinations balance failed: %r", e)
            response, data = None, None
        if isinstance(data, dict) and isinstance(data.get("balance"), (int, float)):
            text = "Pollen: %.4f left" % data["balance"]
            account = data.get("accountBalance")
            if isinstance(account, dict):
                text += " (Quest %.4f, paid %.4f)" % (account.get("tier") or 0, account.get("paid") or 0)
            parts.append(text)
        elif response is not None and response.status_code == 403:
            # Unbudgeted keys need account:usage to read the account balance
            parts.append("Pollen: balance needs the account:usage permission on the key "
                         "(enter.pollinations.ai/keys)")
        else:
            parts.append("Pollen: balance unavailable")

        try:
            response = self.session.get(
                "https://gen.pollinations.ai/account/key/usage",
                params={"days": 1, "limit": 50000}, headers=headers, timeout=15)
            data = response.json() if response.status_code == 200 else None
        except (requests.exceptions.RequestException, ValueError) as e:
            self.log.warning("Pollinations key usage failed: %r", e)
            data = None
        records = data.get("usage") if isinstance(data, dict) else None
        if isinstance(records, list):
            records = [r for r in records if isinstance(r, dict)]
            cost = sum(r.get("cost_usd") or 0 for r in records)
            models = {}
            for r in records:
                name = r.get("model") or "?"
                models[name] = models.get(name, 0) + 1
            top = sorted(models.items(), key=lambda item: -item[1])[:3]
            text = "Last 24h (this key): %d requests, $%.4f" % (len(records), cost)
            if top:
                text += " (%s)" % ", ".join("%s %d" % item for item in top)
            parts.append(text)
        else:
            parts.append("Last 24h: usage unavailable")

        irc.reply(" | ".join(parts), prefixNick=False)

    polliusage = wrap(polliusage, ["owner"])

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
                display_url = self._shorten_url(final_url) if shorten_urls else final_url
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
