# Template variables

Everything starting with `$` in a GitHooks format, like `$sender__login` or
`$user`, is replaced with a value from the webhook the forge sent. There are
two kinds:

* **Payload variables**, one for every value in the webhook's JSON, named after
  where the value sits in it: `$issue__title`, `$sender__login`. These are the
  names progval's GitHub plugin used, and they work for every event.
* **Shorthand**, a few short names the plugin fills in for the common events,
  with the same meaning everywhere: `$user`, `$repo`, `$title`, `$url`.

> **Tip: use the long form when you can.** A payload variable is exactly what
> the forge sent, so you always know what you get. Shorthand is a convenience:
> it picks a value for you (the commit author for a push, the reviewer for a
> review...), which is handy for one template that covers every event, but
> it's one more step between the webhook and your line. When a shorthand
> doesn't give what you expected, look up the payload variable with
> `@githooks vars` and use that.

* [Quick start](#quick-start)
* [Payload variables](#payload-variables)
* [Worked example](#worked-example)
* [Who is who](#who-is-who)
* [Variables the plugin adds](#variables-the-plugin-adds)
* [Worked example: a push](#worked-example-a-push)
* [Shorthand](#shorthand)
* [Differences between forges](#differences-between-forges)
* [Finding a name](#finding-a-name)
* [Template rules](#template-rules)
* [Ready-made templates](#ready-made-templates)

## Quick start

The defaults already give GitBot-style lines. They are:

```
format.global       ^C03[$forge]^C ^C14($repo)^C [$kind] ^B$user^B $verb ^C13$id^C: $title - $url
format.global.push  ^C03[$forge]^C ^C14($repo)^C ^B$user^B pushed ^C13$id^C to ^C07$branch^C: $title - $url
format.global.push.summary  ^C03[$forge]^C ^C14($repo)^C ^B$user^B pushed $count commits to ^C07$branch^C - $url
format.global.push.commit   ^C03[$forge]^C ^C14($repo)^C ^C13$id^C - $title - $url
format.global.hidden        ^C03[$forge]^C ^C14($repo)^C (+$hidden hidden commits)
```

The `push` template is used for pushes up to `max_announce_commits`; bigger
pushes get `push.summary`, then shortened `push.commit` lines, then `hidden`.
(`^C` is the colour code, Ctrl+K, and `^B` is bold, Ctrl+B.) To make your own:

```
@config supybot.plugins.GitHooks.format.global "[$forge] ($repo) $user $action $id - $title - $url"
```

**Put the template in double quotes.** Spaces are fine without them, but
Limnoria treats `[...]` as a nested command, so an unquoted `[$forge]` fails
with `"$forge" is not a valid command`. Quoting always works, colour codes
included.

Colour and bold codes are typed straight from your IRC client (Ctrl+K, Ctrl+B,
Ctrl+O in mIRC and most others), so you can set the format from your client
and see the result straight away.

## Payload variables

A webhook is a JSON document. Part of the one GitHub sends when an issue is
opened:

```json
{
  "action": "opened",
  "issue": {
    "number": 1347,
    "title": "Found a bug",
    "html_url": "https://github.com/octocat/Hello-World/issues/1347",
    "user": { "login": "octocat" }
  },
  "repository": {
    "name": "Hello-World",
    "full_name": "octocat/Hello-World",
    "owner": { "login": "octocat" }
  },
  "sender": { "login": "octocat" }
}
```

Every value in it is a variable. Start from the top of the JSON and write the
names on the way down, with **two underscores** between the levels:

| Position in the JSON | Variable |
|---|---|
| `action` | `$action` |
| `issue` → `number` | `$issue__number` |
| `issue` → `title` | `$issue__title` |
| `issue` → `user` → `login` | `$issue__user__login` |
| `repository` → `full_name` | `$repository__full_name` |
| `repository` → `owner` → `login` | `$repository__owner__login` |
| `sender` → `login` | `$sender__login` |

The event name (`issues`) is not part of the name: the JSON above *is* the
whole webhook, so the path starts at `action`, `issue`, `repository`...

Two underscores because JSON names often contain one: in `$issue__html_url`,
`__` means "go into `issue`" and the `_` belongs to the name `html_url`.

Lists inside the payload (like the `labels` of an issue) aren't turned into
variables. The commits of a push and the pages of a wiki edit are the
exception, see [below](#variables-the-plugin-adds).

**Single underscores also work:** `$issue__user__login` can be written
`$issue_user_login`. If two payload fields end up with the same
single-underscore name, the first one wins, so the `__` form is the one to
use when in doubt.

## Worked example

Take the issue webhook above, and announce new issues with a per-action
format built only from payload variables:

```
@config supybot.plugins.GitHooks.format.issues.opened "echo $sender__login opened issue #$issue__number on $repository__full_name: $issue__title - $issue__html_url"
```

When GitHub sends the webhook, each variable is looked up in the JSON:

| In the template | Path in the JSON | Becomes |
|---|---|---|
| `$sender__login` | `sender` → `login` | `octocat` |
| `$issue__number` | `issue` → `number` | `1347` |
| `$repository__full_name` | `repository` → `full_name` | `octocat/Hello-World` |
| `$issue__title` | `issue` → `title` | `Found a bug` |
| `$issue__html_url` | `issue` → `html_url` | `https://github.com/octocat/Hello-World/issues/1347` |

and the bot says:

```
octocat opened issue #1347 on octocat/Hello-World: Found a bug - https://github.com/octocat/Hello-World/issues/1347
```

The `#` before `$issue__number` and the words `opened issue`, `on` are plain
text, copied as they are. `echo` is there because per-action formats are
Limnoria commands (see [Template rules](#template-rules)).

**The same with shorthand.** [Shorthand](#shorthand) names do the lookups for
you, and work for issues, pull requests, pushes and the other common events
alike. In `format.global`, which is plain text and needs no `echo`:

```
@config supybot.plugins.GitHooks.format.global "[$forge] ($repo) $user $what: $title - $url"
```

```
[GitHub] (octocat/Hello-World) octocat opened issue #1347: Found a bug - https://github.com/octocat/Hello-World/issues/1347
```

Here `$repo` is `$repository__full_name`, `$user` is `$sender__login`,
`$what` is the ready phrase `opened issue #1347`, `$title` is `$issue__title`
and `$url` is `$issue__html_url`.

**When it's someone else.** If hubot later closes that issue, GitHub sends the
same JSON with `"action": "closed"` and `"sender": { "login": "hubot" }`, but
`issue` → `user` is still octocat:

```
@config supybot.plugins.GitHooks.format.global "$sender__login $action #$issue__number (opened by $issue__user__login)"
```

```
hubot closed #1347 (opened by octocat)
```

## Who is who

Most payloads have several people in them, and they're not always the same:

* `$sender__login` is who **did the thing** this webhook is about: opened,
  closed, labeled, commented, pushed...
* `$issue__user__login`, `$pull_request__user__login`, `$comment__user__login`
  are who **created** that issue, pull request or comment.

| Event | `$sender__login` | `$issue__user__login` |
|---|---|---|
| alice opens #1 | alice | alice |
| bob closes #1 | bob | alice |
| carol labels #1 | carol | alice |
| bob comments on #1 | bob | alice |

So `$sender__login` is usually the one you want. The shorthand `$user` picks
the right person for you (see [Shorthand](#shorthand)).

## Variables the plugin adds

These aren't in the JSON; the plugin makes them. Names starting with `__` are
the plugin's own, so they can never clash with a field the forge sends.

**Pushes.** A push carries a *list* of commits, and lists don't become
variables. So the plugin announces one commit per line and puts the commit
being announced under `__commit`:

| Variable | Value |
|---|---|
| `$__commit__id` | full commit id |
| `$__commit__id__short` | short commit id |
| `$__commit__message__firstline` | first line of the commit message |
| `$__commit__author__name` | author's git name |
| `$__commit__author__username` | author's login, when the forge knows it |
| `$__commit__url` | link to the commit |
| `$__num_commits` | number of commits in the whole push |
| `$__files__added__len` | files added in the whole push (also `removed`, `modified`) |
| `$__hidden_commits` | commits left out of a big push (on the `push.hidden` line) |

Any other field of a commit works the same way: `commits` → (one commit) →
`timestamp` is `$__commit__timestamp`.

**Wiki edits** (GitHub's `gollum` event) work the same: one line per edited
page, as `$__page__title`, `$__page__action`, `$__page__html_url`...

**Endings** added to existing variables:

| Ending | Added to | Value |
|---|---|---|
| `__short` | any 40-character commit id, e.g. `$after__short` | the first 7 characters |
| `__branch` | any full ref, e.g. `$ref__branch` | `refs/heads/main` becomes `main` (a ref that is already a short name gets no `__branch`) |
| `__firstline` | any text, e.g. `$comment__body__firstline` | the first non-empty line, at most 300 characters, skipping quoted `> ` lines |

## Worked example: a push

Part of the webhook GitHub sends when octocat pushes one commit to `main`:

```json
{
  "ref": "refs/heads/main",
  "before": "16c0988f7a2c3a6c52b1b5a3b2a6c5e6f1e7d8c9",
  "after": "3154423facdc7041d731fad3b5b57ac887a2ad66",
  "compare": "https://github.com/octocat/Hello-World/compare/16c0988f7a2c...3154423facdc",
  "commits": [
    {
      "id": "3154423facdc7041d731fad3b5b57ac887a2ad66",
      "message": "Fix crash on empty config\n\nThe parser assumed at least one section.",
      "timestamp": "2026-10-26T14:02:11+01:00",
      "url": "https://github.com/octocat/Hello-World/commit/3154423facdc7041d731fad3b5b57ac887a2ad66",
      "author": { "name": "The Octocat", "email": "octocat@github.com", "username": "octocat" },
      "added": [],
      "removed": [],
      "modified": ["config.py"]
    }
  ],
  "repository": { "name": "Hello-World", "full_name": "octocat/Hello-World" },
  "pusher": { "name": "octocat", "email": "octocat@github.com" },
  "sender": { "login": "octocat" }
}
```

`commits` is a list, so the plugin sends one line per commit and puts the
commit of that line under `__commit` (see
[Variables the plugin adds](#variables-the-plugin-adds)). A per-event format
for pushes:

```
@config supybot.plugins.GitHooks.format.push "echo $repository__full_name ($ref__branch): $__commit__author__username committed $__commit__id__short: $__commit__message__firstline - $__commit__url"
```

gives:

```
octocat/Hello-World (main): octocat committed 3154423: Fix crash on empty config - https://github.com/octocat/Hello-World/commit/3154423facdc7041d731fad3b5b57ac887a2ad66
```

**The commit of this line:**

| Variable | Path in the JSON | Value |
|---|---|---|
| `$__commit__id` | `commits` → (this commit) → `id` | `3154423facdc7041d731fad3b5b57ac887a2ad66` |
| `$__commit__id__short` | the same, first 7 characters | `3154423` |
| `$__commit__message` | → `message` | the whole message, all lines |
| `$__commit__message__firstline` | the same, first line | `Fix crash on empty config` |
| `$__commit__timestamp` | → `timestamp` | `2026-10-26T14:02:11+01:00` |
| `$__commit__url` | → `url` | `https://github.com/octocat/Hello-World/commit/3154423…` |
| `$__commit__author__name` | → `author` → `name` | `The Octocat` |
| `$__commit__author__email` | → `author` → `email` | `octocat@github.com` |
| `$__commit__author__username` | → `author` → `username` | `octocat` (missing when the forge doesn't know the author's account, so it's left as typed; the shorthand `$user` falls back to the git name) |

**The whole push** (the same on every line of it):

| Variable | Path in the JSON | Value |
|---|---|---|
| `$ref` | `ref` | `refs/heads/main` |
| `$ref__branch` | the same, without `refs/heads/` | `main` |
| `$before__short` | `before`, first 7 characters | `16c0988` (the branch before the push) |
| `$after__short` | `after`, first 7 characters | `3154423` (the branch after the push) |
| `$compare` | `compare` | `https://github.com/octocat/Hello-World/compare/16c0988f7a2c...3154423facdc` (`$compare_url` on Gitea, Forgejo and Gogs) |
| `$pusher__name` | `pusher` → `name` | `octocat` (`$pusher__login` on Gitea, Forgejo and Gogs) |
| `$sender__login` | `sender` → `login` | `octocat` |
| `$__num_commits` | made by the plugin | `1` |
| `$__files__added__len` `$__files__removed__len` `$__files__modified__len` | made by the plugin | `0`, `0`, `1` |

The author and the pusher aren't always the same person: if octocat pushes
commits written by someone else, `$__commit__author__name` is that person and
`$pusher__name` is still octocat.

`$__commit__message` keeps the line breaks of the message, which IRC can't
show, so use `$__commit__message__firstline` in announces.

**The same with shorthand.** The default `format.global.push` uses only
shorthand, and gives (colours left out):

```
[GitHub] (octocat/Hello-World) octocat pushed 3154423 to main: Fix crash on empty config - https://github.com/octocat/Hello-World/commit/3154423facdc7041d731fad3b5b57ac887a2ad66
```

On a push, each shorthand stands for:

| Shorthand | Long form | Value here |
|---|---|---|
| `$user` | `$__commit__author__username` (the git name if missing) | `octocat` |
| `$id` | `$__commit__id__short` | `3154423` |
| `$title` | `$__commit__message__firstline` | `Fix crash on empty config` |
| `$url` | `$__commit__url` | `https://github.com/octocat/Hello-World/commit/3154423…` |
| `$branch` | `$ref__branch` | `main` |
| `$count` | `$__num_commits` | `1` |

`$ref` is not shorthand: it's the payload's `ref`, `refs/heads/main`, in every
kind of format.

## Shorthand

Writing `$repository__full_name` every time is long, so the plugin also fills
in these short names, with the same meaning for every supported event:

| Shorthand | Meaning |
|---|---|
| `$forge` | `GitHub`, `Gitea`, `Forgejo` or `Gogs` |
| `$repo` | `owner/name` |
| `$owner` `$name` | the two halves of `$repo` |
| `$user` | who did it (see below) |
| `$event` | the event type: `push`, `issues`, `pull_request`... |
| `$action` | the raw action: `opened`, `closed`, `labeled`... (empty for pushes) |
| `$what` | a ready phrase such as `opened issue #3` or `committed` |
| `$kind` | `issue`, `PR`, `commit`, `push`, `release`, `branch`... |
| `$verb` | `opened`, `closed`, `merged`, `commented on`, `reviewed`, `pushed`... (`synchronize` becomes `updated`) |
| `$id` | what the event is about: `#3`, a short commit id, a tag or a branch |
| `$number` | issue or pull request number |
| `$title` | title of the issue, pull request or release, or the commit message |
| `$body` | first line of the text (issue, comment, review, release notes) |
| `$url` | link to the thing |
| `$branch` | branch of a push, or of a created/deleted branch |
| `$label` `$assignee` | for labeled and assigned events |
| `$tag` | tag of a release |
| `$count` | number of commits in the push |
| `$hidden` | number of hidden commits (only on the hidden-commits line) |

What they contain depends on the event:

| Event | `$what` | `$id` | `$title` | `$url` |
|---|---|---|---|---|
| `push` (once per commit) | `committed` | short commit id | first line of the message | the commit |
| `issues` | `opened issue #3` | `#3` | issue title | the issue |
| `issue_comment` | `commented on issue #3` | `#3` | issue title | the comment |
| `pull_request` | `opened pull request #3` | `#3` | PR title | the PR |
| pull request reviews | `reviewed pull request #3` | `#3` | PR title | the PR or comment |
| `commit_comment` (GitHub only) | `commented on commit` | short commit id | first line of the comment | the comment |
| `create` / `delete` | `created branch` | name of the branch/tag | | the repository |
| `release` | `published release` | tag | release name | the release |
| `fork` | `forked` | | name of the new fork | the fork |
| `watch` / `star` (GitHub only) | `starred` | | the repository | the repository |

`$user` is `$sender__login`, except for pushes, where it is the commit author's
login (or git name if the forge sends no login), and for reviews, where it is
the reviewer. A merged pull request has the action `merged` instead of
`closed`. When the forge doesn't send a link (Gogs has none for issues and
releases), the plugin builds one from the repository URL. See
[Differences between forges](#differences-between-forges).

For other events the shorthand only has the common parts (`$repo`, `$user`,
`$forge`, `$action`...); use the payload variables for the rest.

**Shorthand never hides a payload variable.** If the payload has a top-level
field with the same name, the payload's value is used, in every kind of
format. That only happens with `$action` and `$number`, which have the same
value either way, and with `$name` on `status` events (the payload's
`owner/name` there).

Before October 2026 the shorthand `$id` was called `$ref`, which hid the
payload's `ref`. Templates still equal to the old defaults are upgraded
automatically; if you wrote your own template with the shorthand `$ref`,
replace it with `$id`.

## Differences between forges

Gitea and Forgejo copy GitHub's payloads closely, Gogs less so. The shorthand
already deals with everything below; it only matters when you write payload
variables yourself. (Checked against GitHub's example payloads, and the
webhook code of Gitea, Forgejo and Gogs 0.14.3, in October 2026. Support for
forges other than GitHub is best effort, see the
[README](README.md#other-forges).)

**Links.** A field called `url` is the API address on GitHub, Gitea and
Forgejo; the web page is `html_url`.

| Link to | GitHub | Gitea / Forgejo | Gogs |
|---|---|---|---|
| issue | `$issue__html_url` | `$issue__html_url` | not sent: `$repository__html_url/issues/$issue__number`, or the shorthand `$url` |
| pull request | `$pull_request__html_url` | `$pull_request__html_url` | `$pull_request__html_url` |
| comment | `$comment__html_url` | `$comment__html_url` | `$comment__html_url` |
| release | `$release__html_url` | `$release__html_url` | not sent, and Gogs has no page per release: the shorthand `$url` links `$repository__html_url/releases` |
| user | `$sender__html_url` | `$sender__html_url` | not sent |
| commit (push) | `$__commit__url` | `$__commit__url` | `$__commit__url` |
| compare (push) | `$compare` | `$compare_url` | `$compare_url` |

**Other fields.**

| What | GitHub | Gitea / Forgejo | Gogs |
|---|---|---|---|
| who pushed | `$pusher__name` | `$pusher__login` | `$pusher__login` |
| PR target branch | `$pull_request__base__ref` | `$pull_request__base__ref` | `$pull_request__base_branch` |
| PR source branch | `$pull_request__head__ref` | `$pull_request__head__ref` | `$pull_request__head_branch` |
| created/deleted branch or tag (`$ref` of `create`/`delete`) | `feature` | `feature`, but `refs/heads/feature` on Forgejo webhooks of type *Forgejo* | `feature` |
| the label just added or removed | `$label__name` | `$label__name` on Forgejo; Gitea doesn't say which one | not sent |
| the assignee of an assigned event | `$assignee__login` | `$issue__assignee__login` | `$issue__assignee__login` |

The shorthand `$id` and `$branch` are always the short name, and `$assignee`
looks in both places.

**Events.** `commit_comment`, `watch`/`star` and `gollum` are GitHub only.
Gitea and Forgejo name pull request reviews `pull_request_approved`,
`pull_request_rejected` and `pull_request_comment`, and have no `review` →
`user`: there `$user` is the sender. Gogs has no review events.

## Finding a name

* **`@githooks vars`** lists the event types the bot has received since it
  started.
* **`@githooks vars <event>`** shows the variables and their current values for
  the last event of that type, shorthand first, then the payload variables.
* **`@githooks vars <event> <pattern>`** keeps only the names containing the
  pattern, e.g. `@githooks vars issues user__`. At most 40 names are shown, so
  use a pattern on big payloads.
* If the bot hasn't received that event yet, trigger one, or use *Redeliver* in
  the webhook settings of your forge.
* **Your forge keeps the JSON it sent:** on GitHub, open the repository's
  *Settings → Webhooks →* (your webhook) *→ Recent Deliveries* and click a
  delivery. Gitea, Forgejo and Gogs have the same list on the webhook's page.
* **Example payloads for every GitHub event**, one file per action, are in
  [octokit/webhooks](https://github.com/octokit/webhooks/tree/main/payload-examples/api.github.com)
  (e.g. `issues/opened.payload.json`). GitHub's own *Webhook events and
  payloads* page lists the fields too.

`@githooks vars` only knows events for repositories announced somewhere, and
only since the bot last started.

## Template rules

* There are two kinds of formats:
  * `format.global` and its `push`, `push.summary`, `push.commit` and `hidden`
    templates are **plain text**: what you write is what is sent.
  * The per-event and per-action formats (`format.issues`,
    `format.issues.opened`, `format.push`...) are **Limnoria commands**, so
    they start with `echo`: `echo $sender__login opened issue #$issue__number`.
    They can use other commands too, like `cif` from the Conditional plugin.
* Per-action formats such as `format.issues.closed` win over `format.global`
  (and `ignore` silences that action). Both kinds can use every variable on
  this page.
* A variable is `$` followed by letters, digits and underscores. To put text
  right after one, use braces: `${user}s`. For a literal dollar sign use `$$`.
* An unknown name (a typo, or a field this event doesn't have) is left in the
  message as typed, e.g. `$titel`. A known name with no value gives an empty
  string, and in `format.global` spaces left doubled by an empty variable are
  collapsed.
* Colour and formatting codes can be pasted into the template. If you type
  them in a config file, they are `\x02` (bold), `\x03` (colour) and `\x0f`
  (reset).

## Ready-made templates

Set them with `@config supybot.plugins.GitHooks.<setting> "<template>"`.

Minimal:

```
format.global  $user $what: $title - $url
```

The defaults (GitBot style) give, for example:

```
[GitHub] (bob/proj) alice pushed 3154423 to main: Fix crash on empty config - https://github.com/bob/proj/commit/3154423facdc7041d731fad3b5b57ac887a2ad66
[GitHub] (bob/proj) [issue] carol opened #7: It broke - https://github.com/bob/proj/issues/7
[GitHub] (bob/proj) alice pushed 6 commits to main - https://github.com/bob/proj/compare/16c0988...098dbc7
[GitHub] (bob/proj) 3154423 - Fix crash on empty config - https://github.com/bob/proj/commit/3154423
[GitHub] (bob/proj) (+3 hidden commits)
```

Only issue openings, as a per-action format, with payload variables:

```
format.issues.opened  echo $sender__login opened issue #$issue__number: $issue__title - $issue__html_url
```

The same with shorthand:

```
format.issues.opened  echo $user opened issue $id: $title - $url
```

Announcing releases and new branches as well:

```
format.global.events  push issues issue_comment pull_request create release
```
