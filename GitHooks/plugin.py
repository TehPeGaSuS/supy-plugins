###
# Copyright (c) 2011-2014, Valentin Lorentz
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

import re
import string
import sys
import json
import time
import hmac
import urllib
import socket
import hashlib
import fnmatch
import threading
from string import Template
import supybot.log as log
import supybot.utils as utils
import supybot.world as world
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircmsgs as ircmsgs
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
import supybot.httpserver as httpserver

if sys.version_info[0] < 3:
    from cStringIO import StringIO
    from urlparse import urlparse
    quote_plus = urllib.quote_plus
else:
    from io import StringIO
    from urllib.parse import urlparse
    quote_plus = urllib.parse.quote_plus
    basestring = str
try:
    from supybot.i18n import PluginInternationalization
    from supybot.i18n import internationalizeDocstring
    _ = PluginInternationalization('GitHooks')
except:
    # This are useless functions that's allow to run the plugin on a bot
    # without the i18n plugin
    _ = lambda x:x
    internationalizeDocstring = lambda x:x

if sys.version_info[0] >= 3:
    def b(s):
        return s.encode('utf-8')
    def u(s):
        return s
    urlencode = urllib.parse.urlencode
else:
    def u(s):
        return s.decode('utf-8')
    def b(s):
        return s
    urlencode = urllib.urlencode

def flatten_subdicts(dicts, flat=None):
    """Change dict of dicts into a dict of strings/integers. Useful for
    using in string formatting."""
    if flat is None:
        # Instanciate the dictionnary when the function is run and now when it
        # is declared; otherwise the same dictionnary instance will be kept and
        # it will have side effects (memory exhaustion, ...)
        flat = {}
    if isinstance(dicts, list):
        return flatten_subdicts(dict(enumerate(dicts)))
    elif isinstance(dicts, dict):
        for key, value in dicts.items():
            if isinstance(value, dict):
                value = dict(flatten_subdicts(value))
                for subkey, subvalue in value.items():
                    flat['%s__%s' % (key, subkey)] = subvalue
            else:
                flat[key] = value
        return flat
    else:
        return dicts

#####################
# Server stuff
#####################

# Header carrying the event name, per forge. Gitea and Forgejo also send
# X-GitHub-Event with GitHub-compatible names, which is tried first.
EVENT_HEADERS = ('x-github-event', 'x-gitea-event', 'x-forgejo-event',
                 'x-gogs-event')
# Headers holding a bare hex HMAC-SHA256 of the body.
HEX_SIGNATURE_HEADERS = ('x-gitea-signature', 'x-forgejo-signature',
                         'x-gogs-signature')

def _event_name(headers):
    for name in EVENT_HEADERS:
        if headers.get(name):
            return headers[name]
    return ''

def _signature_ok(secrets, headers, body, payload):
    """Without any configured secret everything is accepted. Otherwise one
    of the secrets must match the signature sent by GitHub, Gitea, Forgejo
    or Gogs (or, for old Gogs, the 'secret' field of the payload)."""
    if not secrets:
        return True
    if payload.get('secret') in secrets:
        return True
    for secret in secrets:
        key = secret.encode()
        sha1 = 'sha1=' + hmac.new(key, body, hashlib.sha1).hexdigest()
        sha256 = hmac.new(key, body, hashlib.sha256).hexdigest()
        candidates = [('x-hub-signature', sha1),
                      ('x-hub-signature-256', 'sha256=' + sha256)]
        candidates += [(h, sha256) for h in HEX_SIGNATURE_HEADERS]
        for (header, expected) in candidates:
            if hmac.compare_digest(headers.get(header, ''), expected):
                return True
    return False

class GithubCallback(httpserver.SupyHTTPServerCallback):
    name = "GitHooks announce callback"
    defaultResponse = _("""
    You shouldn't be here, this subfolder is not for you. Go back to the
    index and try out other plugins (if any).""")
    def doPost(self, handler, path, form):
        headers = {k.lower(): v for (k, v) in self.headers.items()}
        if not isinstance(form, bytes):
            form = b(json.dumps(form)) if form else b('')
        secrets = self.plugin.registryValue('announces.secret')
        try:
            payload = json.loads(form.decode('utf8'))
        except ValueError:
            payload = None
        if not isinstance(payload, dict) or \
                not _signature_ok(secrets, headers, form, payload):
            log.warning("""'%s' tried to act as a web hook, but sent an
            invalid payload or no/invalid secret.""" %
            handler.address_string())
            self.send_response(403)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b('Error: invalid payload or secret.'))
            return
        try:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b('Thanks.'))
        except socket.error:
            pass
        event = _event_name(headers)
        if event == 'ping':
            log.info('Got ping event for repository %s',
                     payload.get('repository', {}).get('full_name'))
        self.plugin.announce.onPayload(headers, payload)

#####################
# API access stuff
#####################

def _first_line(text):
    for line in (text or '').split('\n'):
        line = line.strip('\r').strip()
        if line and not line.startswith('> '):
            return line[:300]
    return ''

def _add_aliases(repl, event, prefixed=True):
    """Add single-underscore names for the flattened payload variables, so
    that $issue__html_url can also be written $issue_html_url or, prefixed
    with the event, $issues_issue_html_url. Existing names are never
    replaced."""
    prefix = event.split('.')[0]
    for (key, value) in list(repl.items()):
        short = key.replace('__', '_').strip('_')
        for alias in ((short, '%s_%s' % (prefix, short)) if prefixed
                      else (short,)):
            repl.setdefault(alias, value)

def _forge_url(payload, kind, number):
    """Gogs does not send issue/PR URLs: build them from the repo's."""
    base = payload.get('repository', {}).get('html_url', '')
    return '%s/%s/%s' % (base, kind, number)

def _global_vars(event, payload):
    """Variables of the plain-text "format.global" template. Colour codes
    are pasted straight into the template, so there is no command layer."""
    repo = payload.get('repository', {})
    owner = repo.get('owner', {})
    v = {
        'repo': repo.get('full_name') or '%s/%s' % (
            owner.get('login') or owner.get('name'), repo.get('name')),
        'name': repo.get('name', ''),
        'owner': owner.get('login') or owner.get('name') or '',
        'user': payload.get('sender', {}).get('login') or
                payload.get('sender', {}).get('username') or '',
        'event': event, 'action': payload.get('action', ''),
        'what': event, 'ref': '', 'title': '', 'url': '', 'branch': '',
        'forge': payload.get('__forge', 'Git'), 'hidden': '',
        'number': '', 'body': '', 'label': '', 'assignee': '', 'tag': '',
    }
    for (key, path) in (('label', ('label', 'name')),
                        ('assignee', ('assignee', 'login'))):
        obj = payload.get(path[0])
        if isinstance(obj, dict):
            v[key] = obj.get(path[1]) or ''
    ref = payload.get('ref')
    if isinstance(ref, str) and ref.count('/') >= 2:
        v['branch'] = ref.split('/', 2)[2]
    if event == 'push':
        c = payload['__commit']
        v.update(user=c.get('author', {}).get('name', v['user']),
                 what='committed', ref=c['id'][:7],
                 title=c['message'].split('\n', 1)[0], url=c['url'])
    elif event == 'push.hidden':
        v.update(what='pushed more commits', hidden=payload['__hidden_commits'],
                 title='(+%s hidden commits)' % payload['__hidden_commits'],
                 url=payload.get('compare') or payload.get('compare_url', ''))
    elif event in ('issues', 'issue_comment'):
        i = payload['issue']
        is_pr = bool(i.get('pull_request') or payload.get('is_pull'))
        kind = 'pull request' if is_pr else 'issue'
        v.update(ref='#%s' % i['number'], number=i['number'],
                 title=i['title'], body=_first_line(i.get('body')),
                 url=i.get('html_url') or _forge_url(
                     payload, 'pulls' if is_pr else 'issues', i['number']))
        if event == 'issues':
            v['what'] = '%s %s #%s' % (v['action'], kind, i['number'])
        else:
            v['what'] = 'commented on %s #%s' % (kind, i['number'])
            v['url'] = payload['comment'].get('html_url') or v['url']
            v['body'] = _first_line(payload['comment'].get('body'))
    elif event.startswith('pull_request'):
        pr = payload['pull_request']
        v.update(ref='#%s' % pr['number'], number=pr['number'],
                 title=pr['title'], body=_first_line(pr.get('body')),
                 url=pr.get('html_url') or _forge_url(
                     payload, 'pulls', pr['number']))
        if event == 'pull_request':
            v['what'] = '%s pull request #%s' % (v['action'], pr['number'])
        else:
            v['what'] = 'reviewed pull request #%s' % pr['number']
            who = (payload.get('review') or payload.get('comment') or {})
            v['user'] = (who.get('user') or {}).get('login') or v['user']
            v['body'] = _first_line(who.get('body') or who.get('content'))
    elif event in ('create', 'delete'):
        kind = payload.get('ref_type', 'ref')
        v.update(what='%s %s' % (event + 'd', kind), ref=payload.get('ref', ''),
                 url=repo.get('html_url', ''))
        if kind == 'branch':
            v['branch'] = payload.get('ref', '')
    elif event == 'release':
        r = payload['release']
        v.update(what='%s release' % (v['action'] or 'published'),
                 ref=r.get('tag_name', ''), tag=r.get('tag_name', ''),
                 title=r.get('name') or r.get('tag_name', ''),
                 body=_first_line(r.get('body')), url=r.get('html_url', ''))
    elif event == 'fork':
        f = payload.get('forkee') or {}
        v.update(what='forked', title=f.get('full_name', ''),
                 url=f.get('html_url', ''))
    elif event in ('watch', 'star'):
        v.update(what='starred' if payload.get('action') != 'deleted'
                 else 'unstarred', title=v['repo'], url=repo.get('html_url', ''))
    elif event == 'commit_comment':
        c = payload['comment']
        v.update(what='commented on commit', body=_first_line(c.get('body')), ref=c['commit_id'][:7],
                 title=c['body'].split('\n', 1)[0][:300], url=c['html_url'])
    return v

def query(caller, type_, uri_end, args):
    args = dict([(x,y) for x,y in args.items() if y is not None])
    url = '%s/%s/%s?%s' % (caller._url(), type_, uri_end,
                           urlencode(args))
    if sys.version_info[0] >= 3:
        return json.loads(utils.web.getUrl(url).decode('utf8'))
    else:
        return json.load(utils.web.getUrlFd(url))

#####################
# Plugin itself
#####################

instance = None

@internationalizeDocstring
class GitHooks(callbacks.Plugin):
    """Add the help for "@plugin help GitHooks" here
    This should describe *how* to use this plugin."""

    def __init__(self, irc):
        global instance
        self.__parent = super(GitHooks, self)
        callbacks.Plugin.__init__(self, irc)
        instance = self
        self.last_payloads = {}

        callback = GithubCallback()
        callback.plugin = self
        httpserver.hook('githooks', callback)
        for cb in self.cbs:
            cb.plugin = self

        if 'reply_env' not in ircmsgs.IrcMsg.__slots__:
            log.error("Your version of Supybot is not compatible with "
                      "reply environments. So, the GitHooks plugin won't "
                      "be able to announce events from GitHub.")



    class announce(callbacks.Commands):
        def _variables(self, payload, event, format_='', with_global=False,
                       prefixed=True):
            """All the variables a template can use for this payload."""
            repl = flatten_subdicts(payload)
            for (key, value) in dict(repl).items():
                if isinstance(value, basestring) and \
                        re.search(r'^[a-f0-9]{40}$', value):
                    # Check if it looks like a commit ID, because there are key
                    # names such as "before" and "after" containing commit IDs.
                    repl[key + '__short'] = value[0:7]
                elif key == 'commits':
                    repl['__num_commits'] = len(value)
                    for key in ("added", "removed", "modified"):
                        # 'or []' for Gitea, which sets them to null instead of
                        # [] when the list would be empty.
                        repl['__files__' + key + '__len'] = sum(
                            len(commit.get(key) or []) for commit in value)
                elif key.endswith('ref'):
                    try:
                        repl[key + '__branch'] = value.split('/', 2)[2] \
                                if value else None
                    except IndexError:
                        pass
                elif isinstance(value, str) or \
                        (sys.version_info[0] < 3 and isinstance(value, unicode)):

                    # Skip empty lines or replies at the beginning
                    for line in value.split('\n'):
                        line = line.strip('\r')  # sometimes added by Github
                        if line and not line.startswith('> '):
                            first_line = line
                            break
                    else:
                        # Could not find any, use the first even if it's a
                        # quote
                        first_line = value.split('\n', 1)[0].strip('\r')

                    repl[key + '__firstline'] = (
                        first_line[0:300]  # prevents "(XX more messages)"
                    )
            _add_aliases(repl, event, prefixed)
            if with_global:
                repl.update(_global_vars(event, payload))
            return repl

        def _createPrivmsg(self, irc, channel, payload, event):
            bold = ircutils.bold

            def conf_(name):
                try:
                    return self.plugin.registryValue(name, channel)
                except Exception:  # unknown event or action: not announced
                    return ''

            format_ = ''
            if event == 'pull_request' and payload.get('action') == \
                    'synchronized':
                payload['action'] = 'synchronize'  # Gitea/Forgejo spelling
            if event == 'pull_request' and payload.get('action') == 'closed' \
                    and payload['pull_request'].get('merged'):
                # it's just confusing to call a merged PR "closed", so we
                # manually change that action.
                payload['action'] = 'merged'
            if event in ('issues', 'pull_request'):
                format_ = conf_('format.%s.%s' % (event, payload.get('action')))
                if format_.strip() == 'ignore':
                    return
            self.plugin.last_payloads[event] = payload
            global_ = ''
            base = event.split('.')[0]
            if not format_.strip() and \
                    base in (conf_('format.global.events') or ()):
                global_ = conf_('format.global')
                if global_.strip() and event == 'push.hidden':
                    global_ = conf_('format.global.hidden') or global_
                elif global_.strip() and event == 'push':
                    global_ = conf_('format.global.push') or global_
                if global_.strip():
                    format_ = global_
            if not format_.strip():
                format_ = conf_('format.%s' % event)
            if not format_.strip():
                return
            repl = self._variables(payload, event, format_,
                                   with_global=bool(global_.strip()))
            if global_.strip():
                text = string.Template(global_).safe_substitute(repl)
                text = re.sub(r' {2,}', ' ', text)  # empty variables
                irc.queueMsg(ircmsgs.privmsg(channel, text))
                return
            tokens = callbacks.tokenize(format_)
            if not tokens:
                return
            fake_msg = ircmsgs.IrcMsg(command='PRIVMSG',
                    args=(channel, 'GITHUB'), prefix='github!github@github',
                    reply_env=repl)
            try:
                self.plugin.Proxy(irc, fake_msg, tokens)
            except Exception as  e:
                self.plugin.log.exception('Error occured while running triggered command:')

        def onPayload(self, headers, payload):
            if 'reply_env' not in ircmsgs.IrcMsg.__slots__:
                log.error("Got event payload from GitHub, but your version "
                          "of Supybot is not compatible with reply "
                          "environments, so, the GitHooks plugin can't "
                          "announce it.")
            if 'full_name' in payload['repository']:
                repo = payload['repository']['full_name']
            elif 'name' in payload['repository']['owner']:
                repo = '%s/%s' % (payload['repository']['owner']['name'],
                                  payload['repository']['name'])
            else:
                repo = '%s/%s' % (payload['repository']['owner']['login'],
                                  payload['repository']['name'])
            lheaders = {k.lower(): v for (k, v) in headers.items()}
            event = _event_name(lheaders)
            # Forgejo also sends the Gitea headers, so test it first
            forge = 'GitHub'
            for (header, name) in (('x-forgejo-event', 'Forgejo'),
                                   ('x-gitea-event', 'Gitea'),
                                   ('x-gogs-event', 'Gogs')):
                if header in lheaders:
                    forge = name
                    break
            payload = dict(payload, __forge=forge)
            announces = self._load()
            repoAnnounces = set()
            for (dbRepo, network, channel) in announces:
                if fnmatch.fnmatch(repo, dbRepo):
                    repoAnnounces.add((network, channel))
            if len(repoAnnounces) == 0:
                log.info('Commit for repo %s not announced anywhere' % repo)
                return
            for (network, channel) in repoAnnounces:
                # Compatability with DBs without a network
                if network == '':
                    for irc in world.ircs:
                        if channel in irc.state.channels:
                            break
                else:
                    irc = world.getIrc(network)
                    if not irc:
                        log.warning('Received GitHub payload with announcing '
                                    'enabled in %s on unloaded network %s.',
                                    channel, network)
                        continue
                if channel not in irc.state.channels:
                    log.info(('Cannot announce event for repo '
                             '%s in %s on %s because I\'m not in %s.') %
                             (repo, channel, irc.network, channel))

                if self.plugin.registryValue('ignoreBots', channel):
                    if payload.get("sender", {}).get("type") == "Bot":
                        continue

                if event == 'push':
                    commits = payload['commits']
                    hidden = None
                    if len(commits) == 0:
                        log.warning('GitHub push hook called without any commit.')
                    else:
                        last_commit = commits[-1]

                        max_comm = self.plugin.registryValue(
                                'max_announce_commits', channel)

                        if len(commits) > max_comm:
                            # Never announce more than the limit
                            hidden = len(commits) - max_comm
                            commits = commits[:max_comm]

                    payload2 = dict(payload)

                    self._createPrivmsg(irc, channel, payload2, 'before.push')

                    for commit in commits:
                        payload2['__commit'] = commit
                        self._createPrivmsg(irc, channel, payload2, 'push')

                    if hidden:
                        payload2['__hidden_commits'] = hidden
                        self._createPrivmsg(irc, channel, payload2,
                                'push.hidden')
                elif event == 'gollum':
                    pages = payload['pages']
                    if len(pages) == 0:
                        log.warning('GitHub gollum hook called without any page.')
                    else:
                        payload2 = dict(payload)
                        for page in pages:
                            payload2['__page'] = page
                            self._createPrivmsg(irc, channel, payload2, 'gollum')
                else:
                    self._createPrivmsg(irc, channel, payload, event)

        def _load(self):
            announces = instance.registryValue('announces').split(' || ')
            if announces == ['']:
                return []
            announces = [x.split(' | ') for x in announces]
            output = []
            for annc in announces:
                repo = annc[0]
                # Compatibility with old DBs without a network set
                if len(annc) < 3:
                    net = ''
                    chan = annc[1]
                else:
                    net = annc[1]
                    chan = annc[2]
                output.append((repo, net, chan))
            return output

        def _save(self, data):
            stringList = []
            for announcement in data:
                stringList.extend([' | '.join(announcement)])
            string = ' || '.join(stringList)
            instance.setRegistryValue('announces', value=string)

        @internationalizeDocstring
        def add(self, irc, msg, args, channel, owner, name):
            """[<channel>] <owner> <name>

            Announce the commits of the GitHub repository called
            <owner>/<name> in the <channel>. Globs are also supported for
            <owner> and <name>.
            <channel> defaults to the current channel."""
            repo = '%s/%s' % (owner, name)
            announces = self._load()
            for (dbRepo, net, chan) in announces:
                if dbRepo == repo and\
                        (net == '' or net == irc.network) and\
                        chan == channel:
                    irc.error(_('This repository is already announced to '
                                'this channel.'))
                    return
            announces.append((repo, irc.network, channel))
            self._save(announces)
            irc.replySuccess()
        add = wrap(add, ['channel', 'something', 'something'])

        @internationalizeDocstring
        def remove(self, irc, msg, args, channel, owner, name):
            """[<channel>] <owner> <name>

            Don't announce the commits of the GitHub repository called
            <owner>/<name> in the <channel> anymore.
            <channel> defaults to the current channel."""
            repo = '%s/%s' % (owner, name)
            announces = self._load()
            for annc in announces:
                if annc[0] == repo and\
                        (annc[1] == '' or annc[1] == irc.network) and\
                        annc[2] == channel:
                    announces.remove(annc)
                    self._save(announces)
                    irc.replySuccess()
                    return
            irc.error(_('This repository is not yet announced to this '
                        'channel.'))
        remove = wrap(remove, ['channel', 'something', 'something'])

        def list(self, irc, msg, args, channel):
            """[<channel>]

            Lists all GitHub repositories announced to the given channel.
            <channel> defaults to the current channel.
            """
            announces = self._load()
            results = []
            for annc in announces:
                if (annc[1] == '' or annc[1] == irc.network) and \
                        ircutils.strEqual(annc[2], channel):
                    results.append(annc[0])

            if results:
                irc.reply(format(_('The following repositories announce to %s: %L'),
                          channel, results))
            else:
                irc.reply('No repositories announce to %s.' % channel)
        list = wrap(list, ['channel'])

    class repo(callbacks.Commands):
        def _url(self):
            url = instance.registryValue('api.url')
            if url == 'http://github.com/api/v2/json': # old api
                url = 'https://api.github.com'
                instance.setRegistryValue('api.url', value=url)
            return url

        @internationalizeDocstring
        def search(self, irc, msg, args, search, optlist):
            """<searched string> [--page <id>] [--language <language>]

            Searches the string in the repository names database. You can
            specify the page <id> of the results, and restrict the search
            to a particular programming <language>."""
            args = {'page': None, 'language': None}
            for name, value in optlist:
                if name in args:
                    args[name] = value
            results = query(self, 'legacy/repos/search',
                    quote_plus(search), args)
            reply = ' & '.join('%s/%s' % (x['owner'], x['name'])
                               for x in results['repositories'])
            if reply == '':
                irc.error(_('No repositories matches your search.'))
            else:
                irc.reply(u(reply))
        search = wrap(search, ['something',
                               getopts({'page': 'id',
                                        'language': 'somethingWithoutSpaces'})])
        @internationalizeDocstring
        def info(self, irc, msg, args, owner, name, optlist):
            """<owner> <repository> [--enable <field1>[,<field2>[,...]]] \
            [--disable <field3>[,<field4>[,...]]]

            Displays informations about <owner>'s <repository>.
            Individual fields can be included or excluded using --enable and
            --disable."""
            enabled = ['watchers', 'forks', 'pushed_at', 'open_issues',
                       'description']
            for mode, features in optlist:
                features = features.split(',')
                for feature in features:
                    if mode == 'enable':
                        enabled.append(feature)
                    else:
                        try:
                            enabled.remove(feature)
                        except ValueError:
                            # No error is raised, because:
                            # 1. it wouldn't break anything
                            # 2. it enhances cross-compatiblity
                            pass
            results = query(self, 'repos', '%s/%s' % (owner, name), {})
            output = []
            for key, value in results.items():
                if key in enabled:
                    output.append('%s: %s' % (key, value))
            irc.reply(u(', '.join(output)))
        info = wrap(info, ['something', 'something',
                           getopts({'enable': 'anything',
                                    'disable': 'anything'})])
    @internationalizeDocstring
    def vars(self, irc, msg, args, event, pattern):
        """[<event>] [<pattern>]

        Lists the variables a format can use. Without <event>, lists the events
        seen since the bot started. With <event>, shows the variables (and
        their values) of the last such event received, keeping only the names
        containing <pattern> if given."""
        if not event:
            seen = sorted(self.last_payloads)
            irc.reply(_('Events seen since I started: %s. Use "vars <event> '
                        '[<pattern>]" to see their variables. Friendly names '
                        'available everywhere: $repo $owner $name $user '
                        '$what $action $ref $number $title $body $url '
                        '$branch $label $assignee $tag $forge.') %
                      (', '.join(seen) or _('none yet')))
            return
        payload = self.last_payloads.get(event)
        if payload is None:
            irc.error(_('No %s event received yet. Trigger one (or use '
                        '"Redeliver" in the webhook settings of your '
                        'forge).') % event)
            return
        repl = self.announce._variables(payload, event, with_global=True,
                                        prefixed=False)
        friendly = sorted(_global_vars(event, payload))
        names = sorted((k for (k, val) in repl.items()
                        if isinstance(val, (str, int, float, bool))
                        and '__' not in k.strip('_')
                        and (not pattern or pattern.lower() in k.lower())),
                       key=lambda k: (k not in friendly, k))
        limit = 40
        items = ['$%s=%s' % (k, str(repl[k]).replace('\n', ' ')[:40])
                 for k in names[:limit]]
        if len(names) > limit:
            items.append(_('... %d more, narrow down with a pattern') %
                         (len(names) - limit))
        irc.replies(items or [_('No variable matches.')], joiner=' | ')
    vars = wrap(vars, [optional('something'), optional('something')])

    def die(self):
        self.__parent.die()
        httpserver.unhook('githooks')


Class = GitHooks


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
