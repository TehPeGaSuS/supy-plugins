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
        fmt = '$repo/$branch $user $ref $title $url'
        with conf.supybot.plugins.GitHooks.format.get('global').context(fmt):
            self.cb.announce.onPayload({'x-gogs-event': 'push'}, GITEA_PUSH)
            self.assertResponse(
                ' ', 'bob/proj/main alice aaaaaaa Fix it '
                'https://git.example/bob/proj/commit/aaa')

    def testAliases(self):
        fmt = '$issues_issue_title / $issue_title / $repository_full_name'
        with conf.supybot.plugins.GitHooks.format.get('global').context(fmt):
            self.cb.announce.onPayload({'X-Gitea-Event': 'issues'},
                                       GITEA_ISSUE)
            self.assertResponse(' ', 'It broke / It broke / bob/proj')

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
               '\x0313$ref\x03 - $title - $url')
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
                '$user pushed $ref to $branch: $title'):
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
        self.assertRegexp('githooks vars issues issue_number', r'\$issue_number=7')
        self.assertNotRegexp('githooks vars issues', r'_firstline|\$__')
        self.assertRegexp('githooks vars issues firstline', r'_firstline=')

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
