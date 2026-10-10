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

import supybot.conf as conf
import supybot.registry as registry
try:
    from supybot.i18n import PluginInternationalization
    from supybot.i18n import internationalizeDocstring
    _ = PluginInternationalization('GitHooks')
except:
    # This are useless functions that's allow to run the plugin on a bot
    # without the i18n plugin
    _ = lambda x:x
    internationalizeDocstring = lambda x:x

def configure(advanced):
    # This will be called by supybot to configure this module.  advanced is
    # a bool that specifies whether the user identified himself as an advanced
    # user or not.  You should effect your configuration by manipulating the
    # registry as appropriate.
    from supybot.questions import expect, anything, something, yn
    conf.registerPlugin('GitHooks', True)


GitHooks = conf.registerPlugin('GitHooks')
# This is where your configuration variables (if any) should go.  For example:
# conf.registerGlobalValue(GitHooks, 'someConfigVariableName',
#     registry.Boolean(False, _("""Help for someConfigVariableName.""")))
conf.registerGroup(GitHooks, 'api')
conf.registerGlobalValue(GitHooks.api, 'url',
        registry.String('https://api.github.com', _("""The URL of the
        GitHub API to use. You probably don't need to edit it, but I let it
        there, just in case.""")))
conf.registerGlobalValue(GitHooks, 'announces',
        registry.String('', _("""You shouldn't edit this configuration
        variable yourself, unless you know what you do. Use '@GitHooks announce
        add' or '@GitHooks announce remove' instead.""")))
conf.registerGlobalValue(GitHooks.announces, 'secret',
        registry.SpaceSeparatedSetOfStrings(set(), _("""Set of space-separated
        secret payloads used to authenticate the forge."""), private=True))
conf.registerChannelValue(GitHooks, 'max_announce_commits',
        registry.Integer(3, _("""Determines the maximum number of commits that
        will be announced for a single push. The rest are summarized by
        format.push.hidden.""")))
conf.registerChannelValue(GitHooks, 'ignoreBots',
        registry.Boolean(False, _("""Whether to ignore webhook events that were
        triggered by bots like dependabot""")))

conf.registerGroup(GitHooks, 'format')
# The defaults reproduce the style of the GitBot IRC bot:
# [GitHub] (owner/repo) [issue] user opened #7: title - url
DEFAULT_GLOBAL = ('\x0303[$forge]\x03 \x0314($repo)\x03 [$kind] '
                  '\x02$user\x02 $verb \x0313$ref\x03: $title - $url')
DEFAULT_GLOBAL_PUSH = ('\x0303[$forge]\x03 \x0314($repo)\x03 '
                       '\x02$user\x02 pushed \x0313$ref\x03 to '
                       '\x0307$branch\x03: $title - $url')
DEFAULT_PUSH_SUMMARY = ('\x0303[$forge]\x03 \x0314($repo)\x03 \x02$user\x02 '
                        'pushed $count commits to \x0307$branch\x03 - $url')
DEFAULT_PUSH_COMMIT = ('\x0303[$forge]\x03 \x0314($repo)\x03 '
                       '\x0313$ref\x03 - $title - $url')
conf.registerChannelValue(GitHooks.format, 'global',
        registry.String(DEFAULT_GLOBAL,
        _("""Plain-text template used for push, issue, pull request and
        comment events instead of the per-event formats below (a per-action
        format such as format.issues.closed still wins, and "ignore" there
        silences it). No commands: colour codes (Ctrl+K, Ctrl+B, Ctrl+O) can
        be pasted directly from your IRC client. Variables: $repo $owner $name
        $user $what $kind $verb $action $ref $title $url $branch $forge
        (GitHub, Gitea, Forgejo or Gogs); the raw payload
        variables like $issue__title also work. Empty disables it.""")))
conf.registerChannelValue(GitHooks.format.get('global'), 'events',
        registry.SpaceSeparatedSetOfStrings(
            'push issues issue_comment pull_request pull_request_review '
            'pull_request_review_comment pull_request_approved '
            'pull_request_rejected pull_request_comment commit_comment'.split(),
        _("""Events announced with format.global. Add create, delete, release,
        fork, watch or star to also announce those (they are not announced by
        default, to keep the channel quiet).""")))
conf.registerChannelValue(GitHooks.format.get('global'), 'push',
        registry.String(DEFAULT_GLOBAL_PUSH,
        _("""Plain-text template for each commit of a push. If empty, or if
        you changed format.global and left this one alone, format.global is
        used. Example: $user pushed $ref to $branch: $title
        - $url""")))
conf.registerChannelValue(GitHooks.format.get('global').get('push'), 'summary',
        registry.String(DEFAULT_PUSH_SUMMARY,
        _("""Plain-text template of the line announcing a push with more commits
        than max_announce_commits, sent before the commit lines. $count is the
        number of commits and $url the compare link. Empty disables it. Not
        used when you changed format.global and left this one alone.""")))
conf.registerChannelValue(GitHooks.format.get('global').get('push'), 'commit',
        registry.String(DEFAULT_PUSH_COMMIT,
        _("""Plain-text template of each commit line of a push with more commits
        than max_announce_commits (the commits are then shortened to
        "hash - message"). If empty, or if you changed format.global and left
        this one alone, format.global.push or format.global is used.""")))
conf.registerChannelValue(GitHooks.format.get('global'), 'hidden',
        registry.String('\x0303[$forge]\x03 \x0314($repo)\x03 '
        '(+$hidden hidden commits)',
        _("""Plain-text template of the "N more commits" line that follows a
        push too big for max_announce_commits. Only used when format.global
        is set. Takes the same variables, plus $hidden.""")))
conf.registerGroup(GitHooks.format, 'before')
conf.registerChannelValue(GitHooks.format.before, 'push',
        registry.String('',
        _("""Format for an optional summary line before the individual commits
        in the push event.""")))

conf.registerChannelValue(GitHooks.format, 'push',
        registry.String('echo ' +
        _('$repository__owner__login/\x02$repository__name\x02 '
        '(in \x02$ref__branch\x02): $__commit__author__name committed '
        '\x02$__commit__message__firstline\x02 $__commit__url') \
        .replace('\n        ', ' '),
        _("""Format for push events.""")))
conf.registerChannelValue(GitHooks.format.push, 'hidden',
        registry.String('echo (+$__hidden_commits hidden commits)',
        _("""Format for the hidden commits message for push events.""")))
conf.registerChannelValue(GitHooks.format, 'commit_comment',
        registry.String('echo ' +
        _('$repository__owner__login/\x02$repository__name\x02: '
        '$comment__user__login commented on '
        'commit \x02$comment__commit_id__short\x02 $comment__html_url') \
        .replace('\n        ', ' '),
        _("""Format for commit comment events.""")))
conf.registerChannelValue(GitHooks.format, 'issues',
        registry.String('echo ' +
        _('$repository__owner__login/\x02$repository__name\x02: '
        '\x02$sender__login\x02 $action issue #$issue__number: '
        '\x02$issue__title\x02 $issue__html_url') \
        .replace('\n        ', ' '),
        _("""Format for issue events.""")))

for action in '''assigned closed deleted demilestoned edited labeled locked
                 milestoned opened pinned reopened transferred
                 unassigned unlabeled unlocked unpinned'''.split():
    conf.registerChannelValue(GitHooks.format.issues, action,
            registry.String('',
            _("""Format for events of an issue being %s.
                 If empty, defaults to
                 supybot.plugins.GitHooks.format.issues""" % action)))

conf.registerChannelValue(GitHooks.format, 'issue_comment',
        registry.String('echo ' +
        _('$repository__owner__login/\x02$repository__name\x02: '
        '\x02$sender__login\x02 $action comment on issue #$issue__number: '
        '\x02$issue__title\x02 $comment__html_url') \
        .replace('\n        ', ' '),
        _("""Format for issue comment events.""")))
conf.registerChannelValue(GitHooks.format, 'status',
        registry.String('echo ' +
        _('$repository__owner__login/\x02$repository__name\x02: Status '
        'for commit "\x02$commit__commit__message__firstline\x02" '
        'by \x02$commit__commit__committer__name\x02: \x02$description\x02 '
        '$target_url') \
        .replace('\n        ', ' '),
        _("""Format for status events.""")))

conf.registerChannelValue(GitHooks.format, 'pull_request',
        registry.String('echo ' +
        _('$repository__owner__login/\x02$repository__name\x02: '
        '\x02$sender__login\x02 $action pull request #$number (to '
        '\x02$pull_request__base__ref\x02): \x02$pull_request__title\x02 '
        '$pull_request__html_url') \
        .replace('\n        ', ' '),
        _("""Format for pull request events.""")))

# github's own list of actions, plus "merged" which we substitute ourselves
# to the "closed" action when the PR is merged, because it's just confusing
# to call a merged PR "closed"
for action in '''assigned auto_merge_disabled auto_merge_enabled closed
                 converted_to_draft demilestoned dequeued edited enqueued
                 labeled locked milestoned opened ready_for_review
                 reopened review_request_removed review_requested
                 synchronize unassigned unlabeled unlocked merged'''.split():
    conf.registerChannelValue(GitHooks.format.pull_request, action,
            registry.String('',
            _("""Format for events of a pull request being %s.
                 If empty, defaults to
                 supybot.plugins.GitHooks.format.pull_request""" % action)))

conf.registerChannelValue(GitHooks.format, 'pull_request_review',
        registry.String('echo ' +
            _('$repository__owner__login/\x02$repository__name\x02: '
            '\x02$review__user__login\x02 reviewed pull request #$pull_request__number '
            '(to \x02$pull_request__base__ref\x02): \x02$pull_request__title\x02 '
            '$pull_request__html_url'),
        _("""Format for pull request review events. This is triggered when
        a pull request review is finished. If you want to be notified about
        individual comments during a review, use the
        pull_request_review_comment event.""")))
conf.registerChannelValue(GitHooks.format, 'pull_request_review_comment',
        registry.String('echo ' +
            _('$repository__owner__login/\x02$repository__name\x02: '
            '\x02$comment__user__login\x02 reviewed pull request #$pull_request__number '
            '(to \x02$pull_request__base__ref\x02): \x02$pull_request__title\x02 '
            '$pull_request__html_url'),
        _("""Format for pull request review comment events. This is for
        individual review comments, you probably only want to use the
        pull_request_review event to avoid clutter.""")))

# Copy-paste this from the table of contents here:
# https://docs.github.com/en/developers/webhooks-and-events/webhooks/webhook-events-and-payloads
EVENT_TYPES = """
branch_protection_rule
check_run
check_suite
code_scanning_alert
commit_comment
create
delete
dependabot_alert
deploy_key
deployment
deployment_status
discussion
discussion_comment
fork
github_app_authorization
gollum
installation
installation_repositories
issue_comment
issues
label
marketplace_purchase
member
membership
merge_group
meta
milestone
organization
org_block
package
page_build
ping
project
project_card
project_column
projects_v2_item
public
pull_request
pull_request_review
pull_request_review_comment
pull_request_review_thread
push
release
repository_dispatch
repository
repository_import
repository_vulnerability_alert
security_advisory
sponsorship
star
status
team
team_add
watch
workflow_dispatch
workflow_job
workflow_run
""".strip().split()


for event_type in EVENT_TYPES:
    conf.registerChannelValue(GitHooks.format, event_type,
            registry.String('', _("""Format for %s events.""") % event_type))


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
