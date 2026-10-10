# GitHooks (Limnoria)

This plugin announces events GitHub repositories to IRC.

**This plugin requires Limnoria.**

## Webhook Setup

To use this plugin you must forward/open the port which is specified by 
the configuration variable `supybot.servers.http.port` (8080 is the 
default value). For more information, see 
[Using the HTTP server in Limnoria's documentation](https://docs.limnoria.net/use/httpserver.html).

To add announces use the command `githooks announce add <owner> <repo>` 
`Owner` means the owner of the repository (GitHub username) 
and repo what git repository the bot should announce. When you want to 
remove announce, use the command `githooks announce remove <owner> <repo>`.

Please note that the names are case-sensitive. If you use mis-spelled 
repository names, the bot will not announce commits to that repository. Globs are
also supported in the `<owner>` and `<repo>` fields.

To get the bot notified about events, you must tell GitHub to post to your 
bot. [GitHub explanation](http://help.github.com/post-receive-hooks/)
In order to do that, you must go admin page of repo, tab webhooks 
(direct link: ` https://github.com/<owner>/<repo>/settings/hooks ` ) and 
click `Add webhook` and add the URL of your bot there. The URL is 
` http://<IP or dynamicdns-service>:<port>/githooks `.
Let the `Content type` be `application/json`!

**NOTE:** Previous versions of this plugin used `application/x-www-form-urlencoded`!

Fill the other fields of the form according to what you want.

## Other forges

Gitea, Forgejo and Gogs webhooks are supported: add a webhook of type
Gitea/Gogs (or "Forgejo") pointing at the same URL, with content type
`application/json`. The event name is read from `X-GitHub-Event` (sent by
Gitea and Forgejo), else `X-Gitea-Event`, `X-Forgejo-Event` or `X-Gogs-Event`.
If you set `supybot.plugins.GitHooks.announces.secret`, the signature is
checked from `X-Hub-Signature(-256)`, `X-Gitea-Signature`,
`X-Forgejo-Signature` or `X-Gogs-Signature` (old Gogs: the `secret` field).
GitLab is not supported yet.

`format.global` works unchanged on these forges (missing issue/PR URLs, which
Gogs does not send, are rebuilt). If you keep the per-event `echo` formats,
replace `$pusher__name` with `$pusher__login` and `$compare` with
`$compare_url` in `format.push`.

### Variable names

Every payload variable can be written with single underscores:
`$issue__html_url` is also `$issue_html_url`, and each name also exists
prefixed with the event: `$issues_issue_html_url`, `$push_repository_name`.
The `__` forms keep working.

## Announce format

This plugin has a default configuration to announce events most people want to
see announced on IRC, using bold formatting and no colors; but this can be tweaked.

### Simple global format

Out of the box, GitHooks announces in the style of the GitBot IRC bot, with
colours:

```
[GitHub] (bob/proj) alice pushed 3154423 to main: Fix the thing - https://github.com/.../commit/3154423
[GitHub] (bob/proj) [issue] carol opened #7: It broke - https://github.com/.../issues/7
[Gitea] (bob/proj) [PR] carol merged #9: Add x - https://git.example/bob/proj/pulls/9
[GitHub] (bob/proj) (+3 hidden commits)
```

That is `format.global` (every event but pushes), `format.global.push` (each
commit of a push) and `format.global.hidden` (the "more commits" line). To change
the look, set them to your own plain-text template:

```
@config supybot.plugins.GitHooks.format.global "<your template>"
```

Keep the double quotes: Limnoria runs anything in `[...]` as a nested command.
If you change `format.global` and leave `format.global.push` alone, pushes use
your `format.global` too. Set `format.global` to empty to go back to the older
per-event `echo` formats described below.

Type the colour codes straight from your IRC client (Ctrl+K, Ctrl+B, Ctrl+O in
mIRC and most others) and paste the result in.

| Variable | Meaning |
|---|---|
| `$forge` | GitHub, Gitea, Forgejo or Gogs |
| `$repo` `$owner` `$name` | `owner/name`, owner, name |
| `$user` | who did it (the commit author, for pushes) |
| `$what` | ready phrase, e.g. "opened issue #3", "committed" |
| `$kind` `$verb` | `issue`/`PR`/`commit`... and `opened`/`commented on`/`merged`... |
| `$action` | the raw action (opened, closed, labeled...) |
| `$ref` | `#3`, short commit id, tag or branch name |
| `$number` `$title` `$body` | issue/PR number, title, first line of the text |
| `$url` `$branch` | link to the thing, branch |
| `$label` `$assignee` `$tag` | for labeled/assigned events and releases |
| `$hidden` | number of hidden commits (hidden-commits line only) |

The raw payload variables (`$issue__title`, `$issue_title`) also work.
Empty variables don't leave double spaces.

More settings:
* `format.global.push`: template for each commit of a push (falls back to
  `format.global` when empty).
* `format.global.hidden`: the "(+N hidden commits)" line (has a default).
* `format.global.events`: which events use the global format. By default
  push, issues, issue comments, pull requests, reviews and commit comments;
  add `create delete release fork watch star` to announce those too.
* Per-action formats (`format.issues.closed` ...) still take priority, and
  setting one to `ignore` silences that action.
* `@githooks vars [<event>] [<pattern>]` lists the variables (with values) of
  the last event of that type the bot received, optionally filtered by name.

See [VARIABLES.md](VARIABLES.md) for how every `$variable` works and how to
find the one you need.

### Syntax description

To announce other events type, you have to set config variables 
`supybot.plugins.GitHooks.format.<type>` (where `type` is a type referenced 
at http://developer.github.com/webhooks/#events ) to a template.
A template is a command, where you can use @echo to print variable content.
Variable names are prefixed with a $.
Replacements will be made using the data sent by GitHub. As this data 
contains lists and dictionnaries, it is “flattened”, ie. 
`data['foo']['bar']['baz']` can be accessed with `$foo__bar__baz` (or `$foo_bar_baz`; note the double underscores).
There are also special variables:
* if `$foo` is a git ref, `$foo__branch` will be the matching branch
* if `$foo` is a string, `$foo__firstline` will contain the first line of 
`$foo`

Concerning push events, one line is formatted per commit; it is given extra
 variables: `$__commit__foo` for each `data['commits'][X]['foo']`.

Format of 'issues' and 'pull_request' events can be overridden on a per-action
basis, with the `supybot.plugins.GitHooks.format.<type>.<action>` config variable.
Note that setting `supybot.plugins.GitHooks.format.<type>.<action>` globally overrides
channel-specific values of `supybot.plugins.GitHooks.format.<type>`.
For example, in order to ignore label-related actions, you can use:

```
@config supybot.plugins.GitHooks.format.issues.labeled ignore
@config supybot.plugins.GitHooks.format.issues.unlabeled ignore
@config supybot.plugins.GitHooks.format.pull_request.labeled ignore
@config supybot.plugins.GitHooks.format.pull_request.unlabeled ignore
```

The plugin can validate if the payload was sent by GitHub with a proper secret if `supybot.plugins.GitHooks.announces.secret`
is set.

The Utilities plugin is required to be active for this plugin to work.

### Default configuration

Here are the default templates:

```
supybot.plugins.GitHooks.format.issue_comment: echo $repository__owner__login/\x02$repository__name\x02: \x02$sender__login\x02 $action comment on issue #$issue__number: \x02$issue__title\x02 $comment__html_url
supybot.plugins.GitHooks.format.issues: echo $repository__owner__login/\x02$repository__name\x02: \x02$sender__login\x02 $action issue #$issue__number: \x02$issue__title\x02 $issue__html_url
supybot.plugins.GitHooks.format.pull_request: echo $repository__owner__login/\x02$repository__name\x02: \x02$sender__login\x02 $action pull request #$number (to \x02$pull_request__base__ref\x02): \x02$pull_request__title\x02 $pull_request__html_url
supybot.plugins.GitHooks.format.pull_request_review: echo $repository__owner__login/\x02$repository__name\x02: \x02$review__user__login\x02 reviewed pull request #$pull_request__number (to \x02$pull_request__base__ref\x02): \x02$pull_request__title\x02 $pull_request__html_url
supybot.plugins.GitHooks.format.pull_request_review_comment: echo $repository__owner__login/\x02$repository__name\x02: \x02$comment__user__login\x02 reviewed pull request #$pull_request__number (to \x02$pull_request__base__ref\x02): \x02$pull_request__title\x02 $pull_request__html_url
supybot.plugins.GitHooks.format.pull_request_review_thread:
supybot.plugins.GitHooks.format.push: echo $repository__owner__name/\x02$repository__name\x02 (in \x02$ref__branch\x02): $__commit__author__name committed \x02$__commit__message__firstline\x02 $__commit__url
supybot.plugins.GitHooks.format.push.hidden: echo (+$__hidden_commits hidden commits)
supybot.plugins.GitHooks.format.status: echo $repository__owner__login/\x02$repository__name\x02: Status for commit "\x02$commit__commit__message__firstline\x02" by \x02$commit__commit__committer__name\x02: \x02$description\x02 $target_url
```

everything else, and therefore is not announce

### Notifico-style configuration

Here is an alternative set of configuration values, which are more verbose, use colors and no bold,
[inspired by Notifico](https://github.com/TkTech/notifico/blob/85a84b28625d36733a2037960970d9443fd8cabc/notifico/contrib/services/github.py#L340).
They expect the Conditional plugin to be loaded.

```
supybot.plugins.GitHooks.format.ping: echo "\x0F[\x0302GitHub\x0F]" $zen
supybot.plugins.GitHooks.format.issues: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" \x0307$sender__login\x0F $action issue \x0303#$issue__number\x0F: $issue__title - \x0313$issue__html_url\x0F
supybot.plugins.GitHooks.format.issue_comment: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" \x0307$sender__login\x0F $action a comment on issue \x0303#$issue__number\x0F: $issue__title - \x0313$comment__html_url\x0F
supybot.plugins.GitHooks.format.commit_comment: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" \x0307$comment__user__login\x0F $action a comment on commit \x0303$comment__commit_id\x0F - \x0313$comment__html_url\x0F
supybot.plugins.GitHooks.format.create: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" \x0307$sender__login\x0F created $ref_type \x0303$ref\x0F - \x0313$repository__html_url\x0F
supybot.plugins.GitHooks.format.delete: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" \x0307$sender__login\x0F deleted $ref_type \x0303$ref\x0F - \x0313$repository__html_url\x0F
supybot.plugins.GitHooks.format.pull_request: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" \x0307$sender__login\x0F $action pull request \x0303#$number\x0F: $pull_request__title - \x0313$pull_request__html_url\x0F
supybot.plugins.GitHooks.format.pull_request_review_comment: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" \x0307$comment__user__login\x0F reviewed pull request \x0303#$pull_request__number\x0F commit - \x0313$comment__html_url\x0F
supybot.plugins.GitHooks.format.watch: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" \x0307$sender__login\x0F starred \x0303$repository__owner__login/$repository__name\x0F - \x0313$sender__html_url\x0F
supybot.plugins.GitHooks.format.release: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" \x0307$sender__login\x0F $action \x0303$release__tag_name "|" $release__name\x0F - \x0313$release__html_url\x0F
supybot.plugins.GitHooks.format.fork: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" \x0307$forkee__owner__login\x0F forked the repository - \x0313$forkee__owner__html_url\x0F
supybot.plugins.GitHooks.format.member: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" \x0307$sender__login\x0F $action user \x0303$member__login\x0F - \x0313$member__html_url\x0F
supybot.plugins.GitHooks.format.public: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" \x0307$sender__login\x0F made the repository public!
supybot.plugins.GitHooks.format.team_add: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" \x0307$sender__login\x0F added the team \x0303$team__name\x0F to the repository!
supybot.plugins.GitHooks.format.status: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" [cif [ceq [echo $state] success] \"echo \x0303$state\x0F." \"echo \x0304$state\x0F.\"] $description - \x0313$target_url\x0F
supybot.plugins.GitHooks.format.before.push: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" [cif [ceq [echo $pusher__name] none] \"echo \x0307A deploy key\x0F\" \"echo \x0307$pusher__name\x0F\"] pushed [echo $__num_commits] [cif [ceq [echo $__num_commits] 1] \"echo commit\" \"echo commits\"] to \x0303$ref__branch\x0F "[+$__files__added__len/-$__files__removed__len/\u00B1$__files__modified__len]" \x0313$compare\x0F
supybot.plugins.GitHooks.format.push: echo "\x0F[\x0302$repository__owner__login/$repository__name\x0F]" [cif [ceq [echo $__commit__author__username] $__commit__author__username] "echo \x0307$__commit__author__name\x0F" "echo \x0307$__commit__author__username\x0F"] \x0303$__commit__id__short\x0F - $__commit__message__firstline
supybot.plugins.GitHooks.format.push.hidden: echo (+$__hidden_commits hidden commits)
supybot.plugins.GitHooks.format.workflow_run: echo "\x0f[\x0302$repository__owner__login/$repository__name\x0f]" Workflow Run for \x0307$workflow_run__name\x0f [cif [ceq [echo $workflow_run__conclusion] success] "echo \x0303$workflow_run__status\x0f" "cif [ceq [echo $workflow_run__conclusion] None] \\"echo $workflow_run__status\\" \\"echo \x0304$workflow_run__status\x0f\\""] on branch \x0303$workflow_run__head_branch\x0F. [cif [ceq [echo $workflow_run__conclusion] None] "echo \\"\\"" "echo $workflow_run__conclusion."] \x0313$workflow_run__html_url\x0f
```

If you use Continuous Integration external to GitHub (or if you like very noisy CI notifications from GitHub Workflows), use this instead of `check_run`:

```
supybot.plugins.GitHooks.format.check_run: echo "\x0f[\x0302$repository__owner__login/$repository__name\x0f]" Check Run for \x0307$check_run__name\x0f [cif [ceq [echo $check_run__conclusion] success] "echo \x0303$check_run__status\x0f." "cif [ceq [echo $check_run__conclusion] None] \\"echo $check_run__status.\\" \\"echo \x0304$check_run__status\x0f.\\""] [cif [ceq [echo $check_run__conclusion] None] "echo \\"\\"" "echo $check_run__conclusion."] \x0313$check_run__details_url\x0f
```

To apply it, either use the Config plugin, or add them to your main `.conf` file.
