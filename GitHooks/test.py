###
# Copyright (c) 2011, Valentin Lorentz
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

from supybot.test import *

LEGACY_ISSUE_ANNOUNCE = '''progval/\x02Supybot-plugins\x02: \x02progval\x02
opened issue #350: \x02GitHub: Add config var for each issue/PR action\x02
https://github.com/progval/Supybot-plugins/issues/350'''.replace('\n', ' ')
DEFAULT_ISSUE_ANNOUNCE = (
    '\x0303[GitHub]\x03 \x0314(progval/Supybot-plugins)\x03 [issue] '
    '\x02progval\x02 opened \x0313#350\x03: '
    'GitHub: Add config var for each issue/PR action - '
    'https://github.com/progval/Supybot-plugins/issues/350')
ISSUE_EVENT = {
  "action": "opened",
  "issue": {
    "url": "https://api.github.com/repos/progval/Supybot-plugins/issues/350",
    "repository_url": "https://api.github.com/repos/progval/Supybot-plugins",
    "labels_url": "https://api.github.com/repos/progval/Supybot-plugins/issues/350/labels{/name}",
    "comments_url": "https://api.github.com/repos/progval/Supybot-plugins/issues/350/comments",
    "events_url": "https://api.github.com/repos/progval/Supybot-plugins/issues/350/events",
    "html_url": "https://github.com/progval/Supybot-plugins/issues/350",
    "id": 1601910470,
    "node_id": "I_kwDOAA_IP85fezbG",
    "number": 350,
    "title": "GitHub: Add config var for each issue/PR action",
    "user": {
      "login": "progval",
      "id": 406946,
      "node_id": "MDQ6VXNlcjQwNjk0Ng==",
      "avatar_url": "https://avatars.githubusercontent.com/u/406946?v=4",
      "gravatar_id": "",
      "url": "https://api.github.com/users/progval",
      "html_url": "https://github.com/progval",
      "followers_url": "https://api.github.com/users/progval/followers",
      "following_url": "https://api.github.com/users/progval/following{/other_user}",
      "gists_url": "https://api.github.com/users/progval/gists{/gist_id}",
      "starred_url": "https://api.github.com/users/progval/starred{/owner}{/repo}",
      "subscriptions_url": "https://api.github.com/users/progval/subscriptions",
      "organizations_url": "https://api.github.com/users/progval/orgs",
      "repos_url": "https://api.github.com/users/progval/repos",
      "events_url": "https://api.github.com/users/progval/events{/privacy}",
      "received_events_url": "https://api.github.com/users/progval/received_events",
      "type": "User",
      "site_admin": False
    },
    "labels": [

    ],
    "state": "open",
    "locked": False,
    "assignee": None,
    "assignees": [

    ],
    "milestone": None,
    "comments": 0,
    "created_at": "2023-02-27T20:37:29Z",
    "updated_at": "2023-02-27T20:37:29Z",
    "closed_at": None,
    "author_association": "OWNER",
    "active_lock_reason": None,
    "body": "currently we need to mess with Conditional in order to do simple stuff like hide label/unlabel, and that's just awful",
    "reactions": {
      "url": "https://api.github.com/repos/progval/Supybot-plugins/issues/350/reactions",
      "total_count": 0,
      "+1": 0,
      "-1": 0,
      "laugh": 0,
      "hooray": 0,
      "confused": 0,
      "heart": 0,
      "rocket": 0,
      "eyes": 0
    },
    "timeline_url": "https://api.github.com/repos/progval/Supybot-plugins/issues/350/timeline",
    "performed_via_github_app": None,
    "state_reason": None
  },
  "repository": {
    "id": 1034303,
    "node_id": "MDEwOlJlcG9zaXRvcnkxMDM0MzAz",
    "name": "Supybot-plugins",
    "full_name": "progval/Supybot-plugins",
    "private": False,
    "owner": {
      "login": "progval",
      "id": 406946,
      "node_id": "MDQ6VXNlcjQwNjk0Ng==",
      "avatar_url": "https://avatars.githubusercontent.com/u/406946?v=4",
      "gravatar_id": "",
      "url": "https://api.github.com/users/progval",
      "html_url": "https://github.com/progval",
      "followers_url": "https://api.github.com/users/progval/followers",
      "following_url": "https://api.github.com/users/progval/following{/other_user}",
      "gists_url": "https://api.github.com/users/progval/gists{/gist_id}",
      "starred_url": "https://api.github.com/users/progval/starred{/owner}{/repo}",
      "subscriptions_url": "https://api.github.com/users/progval/subscriptions",
      "organizations_url": "https://api.github.com/users/progval/orgs",
      "repos_url": "https://api.github.com/users/progval/repos",
      "events_url": "https://api.github.com/users/progval/events{/privacy}",
      "received_events_url": "https://api.github.com/users/progval/received_events",
      "type": "User",
      "site_admin": False
    },
    "html_url": "https://github.com/progval/Supybot-plugins",
    "description": "Collection of plugins for Supybot/Limnoria I wrote or forked.",
    "fork": False,
    "url": "https://api.github.com/repos/progval/Supybot-plugins",
    "forks_url": "https://api.github.com/repos/progval/Supybot-plugins/forks",
    "keys_url": "https://api.github.com/repos/progval/Supybot-plugins/keys{/key_id}",
    "collaborators_url": "https://api.github.com/repos/progval/Supybot-plugins/collaborators{/collaborator}",
    "teams_url": "https://api.github.com/repos/progval/Supybot-plugins/teams",
    "hooks_url": "https://api.github.com/repos/progval/Supybot-plugins/hooks",
    "issue_events_url": "https://api.github.com/repos/progval/Supybot-plugins/issues/events{/number}",
    "events_url": "https://api.github.com/repos/progval/Supybot-plugins/events",
    "assignees_url": "https://api.github.com/repos/progval/Supybot-plugins/assignees{/user}",
    "branches_url": "https://api.github.com/repos/progval/Supybot-plugins/branches{/branch}",
    "tags_url": "https://api.github.com/repos/progval/Supybot-plugins/tags",
    "blobs_url": "https://api.github.com/repos/progval/Supybot-plugins/git/blobs{/sha}",
    "git_tags_url": "https://api.github.com/repos/progval/Supybot-plugins/git/tags{/sha}",
    "git_refs_url": "https://api.github.com/repos/progval/Supybot-plugins/git/refs{/sha}",
    "trees_url": "https://api.github.com/repos/progval/Supybot-plugins/git/trees{/sha}",
    "statuses_url": "https://api.github.com/repos/progval/Supybot-plugins/statuses/{sha}",
    "languages_url": "https://api.github.com/repos/progval/Supybot-plugins/languages",
    "stargazers_url": "https://api.github.com/repos/progval/Supybot-plugins/stargazers",
    "contributors_url": "https://api.github.com/repos/progval/Supybot-plugins/contributors",
    "subscribers_url": "https://api.github.com/repos/progval/Supybot-plugins/subscribers",
    "subscription_url": "https://api.github.com/repos/progval/Supybot-plugins/subscription",
    "commits_url": "https://api.github.com/repos/progval/Supybot-plugins/commits{/sha}",
    "git_commits_url": "https://api.github.com/repos/progval/Supybot-plugins/git/commits{/sha}",
    "comments_url": "https://api.github.com/repos/progval/Supybot-plugins/comments{/number}",
    "issue_comment_url": "https://api.github.com/repos/progval/Supybot-plugins/issues/comments{/number}",
    "contents_url": "https://api.github.com/repos/progval/Supybot-plugins/contents/{+path}",
    "compare_url": "https://api.github.com/repos/progval/Supybot-plugins/compare/{base}...{head}",
    "merges_url": "https://api.github.com/repos/progval/Supybot-plugins/merges",
    "archive_url": "https://api.github.com/repos/progval/Supybot-plugins/{archive_format}{/ref}",
    "downloads_url": "https://api.github.com/repos/progval/Supybot-plugins/downloads",
    "issues_url": "https://api.github.com/repos/progval/Supybot-plugins/issues{/number}",
    "pulls_url": "https://api.github.com/repos/progval/Supybot-plugins/pulls{/number}",
    "milestones_url": "https://api.github.com/repos/progval/Supybot-plugins/milestones{/number}",
    "notifications_url": "https://api.github.com/repos/progval/Supybot-plugins/notifications{?since,all,participating}",
    "labels_url": "https://api.github.com/repos/progval/Supybot-plugins/labels{/name}",
    "releases_url": "https://api.github.com/repos/progval/Supybot-plugins/releases{/id}",
    "deployments_url": "https://api.github.com/repos/progval/Supybot-plugins/deployments",
    "created_at": "2010-10-29T07:41:23Z",
    "updated_at": "2023-02-05T11:26:05Z",
    "pushed_at": "2022-12-23T21:25:32Z",
    "git_url": "git://github.com/progval/Supybot-plugins.git",
    "ssh_url": "git@github.com:progval/Supybot-plugins.git",
    "clone_url": "https://github.com/progval/Supybot-plugins.git",
    "svn_url": "https://github.com/progval/Supybot-plugins",
    "homepage": "https://github.com/ProgVal/Limnoria/",
    "size": 4517,
    "stargazers_count": 106,
    "watchers_count": 106,
    "language": "Python",
    "has_issues": True,
    "has_projects": True,
    "has_downloads": True,
    "has_wiki": False,
    "has_pages": False,
    "has_discussions": False,
    "forks_count": 67,
    "mirror_url": None,
    "archived": False,
    "disabled": False,
    "open_issues_count": 59,
    "license": None,
    "allow_forking": True,
    "is_template": False,
    "web_commit_signoff_required": False,
    "topics": [
      "limnoria",
      "plugins",
      "python",
      "supybot"
    ],
    "visibility": "public",
    "forks": 67,
    "open_issues": 59,
    "watchers": 106,
    "default_branch": "master"
  },
  "sender": {
    "login": "progval",
    "id": 406946,
    "node_id": "MDQ6VXNlcjQwNjk0Ng==",
    "avatar_url": "https://avatars.githubusercontent.com/u/406946?v=4",
    "gravatar_id": "",
    "url": "https://api.github.com/users/progval",
    "html_url": "https://github.com/progval",
    "followers_url": "https://api.github.com/users/progval/followers",
    "following_url": "https://api.github.com/users/progval/following{/other_user}",
    "gists_url": "https://api.github.com/users/progval/gists{/gist_id}",
    "starred_url": "https://api.github.com/users/progval/starred{/owner}{/repo}",
    "subscriptions_url": "https://api.github.com/users/progval/subscriptions",
    "organizations_url": "https://api.github.com/users/progval/orgs",
    "repos_url": "https://api.github.com/users/progval/repos",
    "events_url": "https://api.github.com/users/progval/events{/privacy}",
    "received_events_url": "https://api.github.com/users/progval/received_events",
    "type": "User",
    "site_admin": False
  }
}

class GitHooksTestCase(ChannelPluginTestCase):
    plugins = ('GitHooks', 'Config', 'Utilities')
    def testAnnounceAdd(self):
        self.assertNotError('config supybot.plugins.GitHooks.announces ""')
        self.assertNotError('githooks announce add #foo ProgVal Limnoria')
        self.assertResponse('config supybot.plugins.GitHooks.announces',
                            'ProgVal/Limnoria | test | #foo')
        self.assertNotError('githooks announce add #bar ProgVal Supybot-plugins')
        self.assertResponse('config supybot.plugins.GitHooks.announces',
                            'ProgVal/Limnoria | test | #foo || '
                            'ProgVal/Supybot-plugins | test | #bar')


    def testAnnounceRemove(self):
        self.assertNotError('config supybot.plugins.GitHooks.announces '
                            'ProgVal/Limnoria | test | #foo || '
                            'ProgVal/Supybot-plugins | #bar')
        self.assertNotError('githooks announce remove #foo ProgVal Limnoria')
        self.assertResponse('config supybot.plugins.GitHooks.announces',
                            'ProgVal/Supybot-plugins |  | #bar')
        self.assertNotError('githooks announce remove #bar '
                            'ProgVal Supybot-plugins')
        self.assertResponse('config supybot.plugins.GitHooks.announces', ' ')

    def testAnnounceList(self):
        self.assertNotError('config supybot.plugins.GitHooks.announces '
                            'abc/def | test | #foo || '
                            'abc/def | test | #bar || '
                            'def/ghi | test | #bar')
        self.assertRegexp('githooks announce list #foo', 'The following .*abc/def')
        self.assertRegexp('githooks announce list #bar', 'The following .*(abc/def.*def/ghi|def/ghi.*abc/def)')
        self.assertRegexp('githooks announce list #baz', 'No repositories')

    def testNoAnnounce(self):
        cb = self.irc.getCallback('GitHooks')
        cb.announce.onPayload({'X-GitHub-Event': 'issues'}, ISSUE_EVENT)
        self.assertNoResponse(' ')

    def testDefaultAnnounce(self):
        self.assertNotError(
                'githooks announce add %s progval Supybot-plugins' %
                self.channel)
        try:
            cb = self.irc.getCallback('GitHooks')
            cb.announce.onPayload(
                {'X-GitHub-Event': 'issues'},
                ISSUE_EVENT)
            self.assertResponse(' ', DEFAULT_ISSUE_ANNOUNCE)

            cb.announce.onPayload(
                {'X-GitHub-Event': 'issues'},
                {**ISSUE_EVENT, 'action': 'labeled'})
            self.assertResponse(
                ' ', DEFAULT_ISSUE_ANNOUNCE.replace('opened', 'labeled'))
        finally:
            self.assertNotError(
                    'githooks announce remove %s progval Supybot-plugins' %
                    self.channel)

    def testLegacyFormats(self):
        self.assertNotError(
                'githooks announce add %s progval Supybot-plugins' %
                self.channel)
        try:
            with conf.supybot.plugins.GitHooks.format.get('global').context(''):
                cb = self.irc.getCallback('GitHooks')
                cb.announce.onPayload({'X-GitHub-Event': 'issues'},
                                      ISSUE_EVENT)
                self.assertResponse(' ', LEGACY_ISSUE_ANNOUNCE)
        finally:
            self.assertNotError(
                    'githooks announce remove %s progval Supybot-plugins' %
                    self.channel)

    def testIgnoreIssueAction(self):
        self.assertNotError(
                'githooks announce add %s progval Supybot-plugins' %
                self.channel)
        try:
            with conf.supybot.plugins.GitHooks.format.issues.labeled.context('ignore'):
                cb = self.irc.getCallback('GitHooks')
                cb.announce.onPayload(
                    {'X-GitHub-Event': 'issues'},
                    ISSUE_EVENT)
                self.assertResponse(' ', DEFAULT_ISSUE_ANNOUNCE)

                cb.announce.onPayload(
                    {'X-GitHub-Event': 'issues'},
                    {**ISSUE_EVENT, 'action': 'labeled'})
                self.assertNoResponse(' ')
        finally:
            self.assertNotError(
                    'githooks announce remove %s progval Supybot-plugins' %
                    self.channel)

GITEA_REPO = {'full_name': 'bob/proj', 'name': 'proj',
              'owner': {'login': 'bob', 'username': 'bob'},
              'html_url': 'https://git.example/bob/proj'}
GITEA_ISSUE = {'action': 'opened', 'repository': GITEA_REPO,
               'sender': {'login': 'alice'},
               'issue': {'number': 7, 'title': 'It broke',
                         'pull_request': None}}  # no html_url, like Gogs
GITEA_PUSH = {'ref': 'refs/heads/main', 'repository': GITEA_REPO,
              'sender': {'login': 'alice'}, 'pusher': {'login': 'alice'},
              'compare_url': 'https://git.example/bob/proj/compare/a...b',
              'commits': [{'id': 'a' * 40, 'message': 'Fix it\n\nlong body',
                           'url': 'https://git.example/bob/proj/commit/aaa',
                           'author': {'name': 'Alice', 'username': 'alice'}}]}

class GitHooksForgeTestCase(ChannelPluginTestCase):
    plugins = ('GitHooks', 'Config', 'Utilities')

    def setUp(self):
        super().setUp()
        self.assertNotError('config supybot.plugins.GitHooks.announces ""')
        self.assertNotError('githooks announce add %s bob proj' % self.channel)
        self.cb = self.irc.getCallback('GitHooks')

    def testGlobalFormatIssueWithoutUrl(self):
        fmt = '\x0302[$repo]\x0f \x02$user\x02 $what: $title $url'
        with conf.supybot.plugins.GitHooks.format.get('global').context(fmt):
            self.cb.announce.onPayload({'X-Gitea-Event': 'issues'},
                                       GITEA_ISSUE)
            self.assertResponse(
                ' ', '\x0302[bob/proj]\x0f \x02alice\x02 opened issue #7: '
                'It broke https://git.example/bob/proj/issues/7')

    def testGlobalFormatPush(self):
        fmt = '$repo/$branch $user $id $title $url'
        with conf.supybot.plugins.GitHooks.format.get('global').context(fmt):
            self.cb.announce.onPayload({'x-gogs-event': 'push'}, GITEA_PUSH)
            self.assertResponse(
                ' ', 'bob/proj/main alice aaaaaaa Fix it '
                'https://git.example/bob/proj/commit/aaa')

    def testAliases(self):
        # the event-prefixed spelling ($issues_issue_title) is gone
        fmt = ('$issue__title / $issue_title / $repository_full_name / '
               '$issues_issue_title')
        with conf.supybot.plugins.GitHooks.format.get('global').context(fmt):
            self.cb.announce.onPayload({'X-Gitea-Event': 'issues'},
                                       GITEA_ISSUE)
            self.assertResponse(
                ' ', 'It broke / It broke / bob/proj / $issues_issue_title')

    def testVariablesDocExample(self):
        # the worked example in VARIABLES.md, kept here so the doc can't drift
        payload = {
            'action': 'opened',
            'issue': {'number': 1347, 'title': 'Found a bug',
                      'html_url': 'https://github.com/octocat/Hello-World/'
                                  'issues/1347',
                      'user': {'login': 'octocat'}},
            'repository': {'name': 'Hello-World',
                           'full_name': 'octocat/Hello-World',
                           'owner': {'login': 'octocat'}},
            'sender': {'login': 'octocat'}}
        url = 'https://github.com/octocat/Hello-World/issues/1347'
        self.assertNotError('githooks announce add %s octocat Hello-World'
                            % self.channel)
        with conf.supybot.plugins.GitHooks.format.get('global').context(''), \
             conf.supybot.plugins.GitHooks.format.issues.opened.context(
                 'echo $sender__login opened issue #$issue__number on '
                 '$repository__full_name: $issue__title - $issue__html_url'):
            self.cb.announce.onPayload({'X-GitHub-Event': 'issues'}, payload)
            self.assertResponse(
                ' ', 'octocat opened issue #1347 on octocat/Hello-World: '
                'Found a bug - ' + url)
        with conf.supybot.plugins.GitHooks.format.get('global').context(
                '[$forge] ($repo) $user $what: $title - $url'):
            self.cb.announce.onPayload({'X-GitHub-Event': 'issues'}, payload)
            self.assertResponse(
                ' ', '[GitHub] (octocat/Hello-World) octocat opened issue '
                '#1347: Found a bug - ' + url)
        closed = dict(payload, action='closed', sender={'login': 'hubot'})
        with conf.supybot.plugins.GitHooks.format.get('global').context(
                '$sender__login $action #$issue__number '
                '(opened by $issue__user__login)'):
            self.cb.announce.onPayload({'X-GitHub-Event': 'issues'}, closed)
            self.assertResponse(' ', 'hubot closed #1347 (opened by octocat)')

    def testVariablesDocPushExample(self):
        # the push example in VARIABLES.md, kept here so the doc can't drift
        sha = '3154423facdc7041d731fad3b5b57ac887a2ad66'
        commit_url = 'https://github.com/octocat/Hello-World/commit/' + sha
        payload = {
            'ref': 'refs/heads/main',
            'before': '16c0988f7a2c3a6c52b1b5a3b2a6c5e6f1e7d8c9',
            'after': sha,
            'compare': 'https://github.com/octocat/Hello-World/compare/'
                       '16c0988f7a2c...3154423facdc',
            'commits': [{
                'id': sha,
                'message': 'Fix crash on empty config\n\n'
                           'The parser assumed at least one section.',
                'timestamp': '2026-10-26T14:02:11+01:00',
                'url': commit_url,
                'author': {'name': 'The Octocat',
                           'email': 'octocat@github.com',
                           'username': 'octocat'},
                'committer': {'name': 'The Octocat',
                              'email': 'octocat@github.com',
                              'username': 'octocat'},
                'added': [], 'removed': [], 'modified': ['config.py']}],
            'repository': {'name': 'Hello-World',
                           'full_name': 'octocat/Hello-World',
                           'html_url': 'https://github.com/octocat/'
                                       'Hello-World',
                           'owner': {'name': 'octocat', 'login': 'octocat'}},
            'pusher': {'name': 'octocat', 'email': 'octocat@github.com'},
            'sender': {'login': 'octocat'}}
        self.assertNotError('githooks announce add %s octocat Hello-World'
                            % self.channel)
        with conf.supybot.plugins.GitHooks.format.get('global').context(''), \
             conf.supybot.plugins.GitHooks.format.push.context(
                 'echo $repository__full_name ($ref__branch): '
                 '$__commit__author__username committed '
                 '$__commit__id__short: $__commit__message__firstline - '
                 '$__commit__url'):
            self.cb.announce.onPayload({'X-GitHub-Event': 'push'}, payload)
            self.assertResponse(
                ' ', 'octocat/Hello-World (main): octocat committed '
                '3154423: Fix crash on empty config - ' + commit_url)
        with conf.supybot.plugins.GitHooks.format.get('global').context(''), \
             conf.supybot.plugins.GitHooks.format.push.context(
                 'echo $ref | $before__short..$after__short | '
                 '$pusher__name | $__num_commits | '
                 '$__files__added__len/$__files__removed__len/'
                 '$__files__modified__len | $__commit__timestamp | '
                 '$__commit__author__name | $__commit__author__email'):
            self.cb.announce.onPayload({'X-GitHub-Event': 'push'}, payload)
            self.assertResponse(
                ' ', 'refs/heads/main | 16c0988..3154423 | octocat | 1 | '
                '0/0/1 | 2026-10-26T14:02:11+01:00 | The Octocat | '
                'octocat@github.com')
        # the default GitBot-style line, colours stripped
        self.cb.announce.onPayload({'X-GitHub-Event': 'push'}, payload)
        m = self.getMsg(' ')
        self.assertEqual(
            ircutils.stripFormatting(m.args[1]),
            '[GitHub] (octocat/Hello-World) octocat pushed 3154423 to main: '
            'Fix crash on empty config - ' + commit_url)

    def testForgeDifferences(self):
        # checked against each forge's webhook source, see VARIABLES.md
        events = conf.supybot.plugins.GitHooks.format.get('global').events
        with events.context(set(events()) | {'create', 'release'}), \
             conf.supybot.plugins.GitHooks.format.get('global').context(
                 '$what $id $branch $url $assignee'):
            # Forgejo-type webhooks send the full ref on create/delete
            create = {'ref': 'refs/heads/feature', 'ref_type': 'branch',
                      'repository': GITEA_REPO, 'sender': {'login': 'alice'}}
            self.cb.announce.onPayload({'X-Forgejo-Event': 'create'}, create)
            self.assertResponse(' ', 'created branch feature feature '
                                'https://git.example/bob/proj')
            # Gogs releases have no link: point at the releases page
            release = {'action': 'published', 'repository': GITEA_REPO,
                       'sender': {'login': 'alice'},
                       'release': {'tag_name': 'v1', 'name': 'One'}}
            self.cb.announce.onPayload({'X-Gogs-Event': 'release'}, release)
            self.assertResponse(' ', 'published release v1 '
                                'https://git.example/bob/proj/releases')
            # Gitea/Forgejo/Gogs only have the assignee inside the issue
            assigned = dict(GITEA_ISSUE, action='assigned',
                            issue=dict(GITEA_ISSUE['issue'],
                                       assignee={'login': 'dave'}))
            self.cb.announce.onPayload({'X-Gitea-Event': 'issues'}, assigned)
            self.assertRegexp(' ', r'^assigned issue #7 #7 .* dave$')

    def testShorthandInEchoFormats(self):
        with conf.supybot.plugins.GitHooks.format.get('global').context(''), \
             conf.supybot.plugins.GitHooks.format.issues.opened.context(
                 'echo $user $action issue $number: $title'):
            self.cb.announce.onPayload({'X-Gitea-Event': 'issues'},
                                       GITEA_ISSUE)
            self.assertResponse(' ', 'alice opened issue 7: It broke')

    def testPayloadWinsInEchoFormats(self):
        # $ref is the payload's ref in both kinds of formats; the
        # shorthand for the commit is $id
        with conf.supybot.plugins.GitHooks.format.get('global').context(''), \
             conf.supybot.plugins.GitHooks.format.push.context(
                 'echo $ref $ref__branch $id $user'):
            self.cb.announce.onPayload({'X-Gitea-Event': 'push'}, GITEA_PUSH)
            self.assertResponse(' ', 'refs/heads/main main aaaaaaa alice')
        g = conf.supybot.plugins.GitHooks.format.get('global')
        with g.context('$ref $id'), g.get('push').context('$ref $id'):
            self.cb.announce.onPayload({'X-Gitea-Event': 'push'}, GITEA_PUSH)
            self.assertResponse(' ', 'refs/heads/main aaaaaaa')

    def testOldDefaultsUpgraded(self):
        # a bot that saved its config before $ref became $id
        from . import config as cfg
        from .plugin import _upgrade_old_defaults
        g = conf.supybot.plugins.GitHooks.format.get('global')
        chan = g.get('push').get(self.channel)
        try:
            g.setValue(cfg.OLD_DEFAULTS['global'])
            chan.setValue(cfg.OLD_DEFAULTS['global.push'])
            g.get('push').get('commit').setValue('my own $ref')
            _upgrade_old_defaults()
            self.assertEqual(g(), cfg.DEFAULT_GLOBAL)
            self.assertEqual(chan(), cfg.DEFAULT_GLOBAL_PUSH)
            self.assertEqual(g.get('push').get('commit')(), 'my own $ref')
        finally:
            g.setValue(cfg.DEFAULT_GLOBAL)
            g.get('push').unregister(self.channel)
            g.get('push').get('commit').setValue(cfg.DEFAULT_PUSH_COMMIT)

    def testMaxAnnounceCommits(self):
        commits = [dict(GITEA_PUSH['commits'][0], message='c%d' % i)
                   for i in range(4)]
        push = dict(GITEA_PUSH, commits=commits)
        with conf.supybot.plugins.GitHooks.format.get('global').context(
                '$title'), \
             conf.supybot.plugins.GitHooks.max_announce_commits.context(3):
            self.cb.announce.onPayload({'X-Gitea-Event': 'push'}, push)
            for title in ('c0', 'c1', 'c2'):
                self.assertResponse(' ', title)
            self.assertResponse(' ', '\x0303[Gitea]\x03 \x0314(bob/proj)\x03 '
                                '(+1 hidden commits)')
            self.cb.announce.onPayload(
                {'X-Gitea-Event': 'push'}, dict(push, commits=commits[:3]))
            for title in ('c0', 'c1', 'c2'):
                self.assertResponse(' ', title)
            self.assertNoResponse(' ')

    def testGitBotStyle(self):
        fmt = ('\x0303[$forge]\x03 \x0314($repo)\x03 \x02$user\x02 '
               '\x0313$id\x03 - $title - $url')
        commits = [dict(GITEA_PUSH['commits'][0], message='c%d' % i)
                   for i in range(5)]
        with conf.supybot.plugins.GitHooks.format.get('global').context(fmt), \
             conf.supybot.plugins.GitHooks.max_announce_commits.context(1):
            self.cb.announce.onPayload({'X-Gitea-Event': 'push'},
                                       dict(GITEA_PUSH, commits=commits))
            self.assertResponse(
                ' ', '\x0303[Gitea]\x03 \x0314(bob/proj)\x03 \x02alice\x02 '
                '\x0313aaaaaaa\x03 - c0 - https://git.example/bob/proj/commit/aaa')
            self.assertResponse(
                ' ', '\x0303[Gitea]\x03 \x0314(bob/proj)\x03 '
                '(+4 hidden commits)')
            self.cb.announce.onPayload({'X-Forgejo-Event': 'issues',
                                        'X-Gitea-Event': 'issues'},
                                       dict(GITEA_ISSUE, action='opened'))
            self.assertResponse(
                ' ', '\x0303[Forgejo]\x03 \x0314(bob/proj)\x03 \x02alice\x02 '
                '\x0313#7\x03 - It broke - https://git.example/bob/proj/issues/7')

    def testPushTemplate(self):
        g = conf.supybot.plugins.GitHooks.format.get('global')
        with g.context('GLOBAL $title'), g.get('push').context(
                '$user pushed $id to $branch: $title'):
            self.cb.announce.onPayload({'X-Gitea-Event': 'push'}, GITEA_PUSH)
            self.assertResponse(' ', 'alice pushed aaaaaaa to main: Fix it')
            self.cb.announce.onPayload({'X-Gitea-Event': 'issues'},
                                       GITEA_ISSUE)
            self.assertResponse(' ', 'GLOBAL It broke')

    def testEventsSetting(self):
        g = conf.supybot.plugins.GitHooks.format.get('global')
        release = {'action': 'published', 'repository': GITEA_REPO,
                   'sender': {'login': 'alice'},
                   'release': {'tag_name': 'v1.0', 'name': 'One',
                               'html_url': 'https://git.example/r',
                               'body': '\nFirst release\nmore'}}
        fork = {'repository': GITEA_REPO, 'sender': {'login': 'carol'},
                'forkee': {'full_name': 'carol/proj',
                           'html_url': 'https://git.example/carol/proj'}}
        with g.context('$user $what $tag $title $body $url'):
            self.cb.announce.onPayload({'X-Gitea-Event': 'release'}, release)
            self.assertNoResponse(' ')
            with g.get('events').context({'push', 'release', 'fork'}):
                self.cb.announce.onPayload({'X-Gitea-Event': 'release'},
                                           release)
                self.assertResponse(' ', 'alice published release v1.0 One '
                                    'First release https://git.example/r')
                self.cb.announce.onPayload({'X-Gitea-Event': 'fork'}, fork)
                self.assertResponse(' ', 'carol forked carol/proj '
                                    'https://git.example/carol/proj')

    def testNewFriendlyNames(self):
        pr = {'action': 'labeled', 'repository': GITEA_REPO,
              'sender': {'login': 'alice'}, 'label': {'name': 'bug'},
              'assignee': {'login': 'dave'},
              'pull_request': {'number': 9, 'title': 'T', 'body': 'Line one',
                               'html_url': 'u'}}
        fmt = '$number $label $assignee $body'
        with conf.supybot.plugins.GitHooks.format.get('global').context(fmt):
            self.cb.announce.onPayload({'X-Gitea-Event': 'pull_request'}, pr)
            self.assertResponse(' ', '9 bug dave Line one')

    def testVarsCommand(self):
        self.assertRegexp('githooks vars', 'none yet')
        self.assertError('githooks vars issues')
        with conf.supybot.plugins.GitHooks.format.get('global').context('x'):
            self.cb.announce.onPayload({'X-Gitea-Event': 'issues'},
                                       GITEA_ISSUE)
            self.assertResponse(' ', 'x')
        self.assertRegexp('githooks vars', 'issues')
        self.assertRegexp('githooks vars issues', r'\$repo=bob/proj.*\$title=It broke')
        self.assertRegexp('githooks vars issues issue__number',
                          r'\$issue__number=7')
        self.assertNotRegexp('githooks vars issues', r'\$issue_number=')
        self.assertNotRegexp('githooks vars issues', r'_firstline|__forge')
        self.assertRegexp('githooks vars issues firstline', r'__firstline=')

    def testVarsCommandPush(self):
        with conf.supybot.plugins.GitHooks.format.get('global').context('x'):
            self.cb.announce.onPayload({'X-Gitea-Event': 'push'}, GITEA_PUSH)
            self.assertResponse(' ', 'x')
        self.assertRegexp('githooks vars push commit__',
                          r'\$__commit__id__short=aaaaaaa')
        self.assertRegexp('githooks vars push num', r'\$__num_commits=1')

    def testDocumentedPushVariables(self):
        fmt = ('$commit_id_short|$commit_message_firstline|$commit_author_name|'
               '$num_commits|$files_added_len|$ref_branch|$commit_url')
        with conf.supybot.plugins.GitHooks.format.get('global').context(fmt):
            self.cb.announce.onPayload({'X-Gitea-Event': 'push'}, GITEA_PUSH)
            self.assertResponse(
                ' ', 'aaaaaaa|Fix it|Alice|1|0|main|'
                'https://git.example/bob/proj/commit/aaa')

    def testDefaultsLikeGitBot(self):
        # nothing configured: GitBot-style lines
        pr = {'action': 'opened', 'repository': GITEA_REPO,
              'sender': {'login': 'alice'},
              'pull_request': {'number': 9, 'title': 'Add x',
                               'html_url': 'https://git.example/pr/9'}}
        self.cb.announce.onPayload({'X-Gitea-Event': 'pull_request'}, pr)
        self.assertResponse(
            ' ', '\x0303[Gitea]\x03 \x0314(bob/proj)\x03 [PR] '
            '\x02alice\x02 opened \x0313#9\x03: Add x - '
            'https://git.example/pr/9')
        self.cb.announce.onPayload({'X-Gitea-Event': 'push'}, GITEA_PUSH)
        self.assertResponse(
            ' ', '\x0303[Gitea]\x03 \x0314(bob/proj)\x03 \x02alice\x02 '
            'pushed \x0313aaaaaaa\x03 to \x0307main\x03: Fix it - '
            'https://git.example/bob/proj/commit/aaa')
        comment = dict(GITEA_ISSUE, action='created',
                       comment={'html_url': 'https://git.example/c'})
        self.cb.announce.onPayload({'X-Gitea-Event': 'issue_comment'}, comment)
        self.assertResponse(
            ' ', '\x0303[Gitea]\x03 \x0314(bob/proj)\x03 [issue] '
            '\x02alice\x02 commented on \x0313#7\x03: It broke - '
            'https://git.example/c')

    def testBigPushLikeGitBot(self):
        commits = [dict(GITEA_PUSH['commits'][0], id=ch * 40, message='c%d' % i,
                        url='https://git.example/c/%d' % i)
                   for (i, ch) in enumerate('abcde')]
        push = dict(GITEA_PUSH, commits=commits,
                    pusher={'login': 'alice'},
                    compare_url='https://git.example/compare/x...y')
        pre = '\x0303[Gitea]\x03 \x0314(bob/proj)\x03 '
        self.cb.announce.onPayload({'X-Gitea-Event': 'push'}, push)
        self.assertResponse(
            ' ', pre + '\x02alice\x02 pushed 5 commits to \x0307main\x03 - '
            'https://git.example/compare/x...y')
        for i, ch in enumerate('abc'):
            self.assertResponse(
                ' ', pre + '\x0313%s\x03 - c%d - https://git.example/c/%d' %
                (ch * 7, i, i))
        self.assertResponse(' ', pre + '(+2 hidden commits)')
        self.assertNoResponse(' ')
        # a small push: one full line per commit, no summary
        self.cb.announce.onPayload({'X-Gitea-Event': 'push'},
                                   dict(push, commits=commits[:2]))
        for i in range(2):
            self.assertRegexp(' ', r'pushed .* to .*main.*: c%d - ' % i)
        self.assertNoResponse(' ')

    def testPushUserFallsBackToAuthorName(self):
        commit = dict(GITEA_PUSH['commits'][0], author={'name': 'Al Ice'})
        push = dict(GITEA_PUSH, commits=[commit])
        with conf.supybot.plugins.GitHooks.format.get('global').context('$user'):
            self.cb.announce.onPayload({'X-Gitea-Event': 'push'}, push)
            self.assertResponse(' ', 'Al Ice')
            commit['author'] = {}
            self.cb.announce.onPayload({'X-Gitea-Event': 'push'}, push)
            self.assertResponse(' ', 'alice')  # the sender's login

    def testUnknownEventIgnored(self):
        self.cb.announce.onPayload({'X-Gitea-Event': 'whatever'}, GITEA_ISSUE)
        self.assertNoResponse(' ')

    def testSignatures(self):
        import hashlib, hmac
        import sys
        plugin = sys.modules[type(self.cb).__module__]
        body = b'{"a": 1}'
        ok = plugin._signature_ok
        h = hmac.new(b's3', body, hashlib.sha256).hexdigest()
        self.assertTrue(ok(set(), {}, body, {}))
        self.assertTrue(ok({'s3'}, {'x-gitea-signature': h}, body, {}))
        self.assertTrue(ok({'s3'}, {'x-hub-signature-256': 'sha256=' + h},
                           body, {}))
        self.assertTrue(ok({'s3'}, {}, body, {'secret': 's3'}))
        self.assertFalse(ok({'s3'}, {'x-gogs-signature': 'bad'}, body, {}))
        self.assertFalse(ok({'s3'}, {}, body, {}))

# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
