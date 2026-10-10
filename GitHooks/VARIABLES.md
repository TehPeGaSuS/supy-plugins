# Template variables

Everything between two `$` signs in a GitHooks format, like `$user` or
`$issue_title`, is replaced with a value taken from the webhook the forge sent.
This page explains where those names come from and how to find the one you
need.

* [Quick start](#quick-start)
* [Friendly variables](#friendly-variables)
* [Raw payload variables](#raw-payload-variables)
* [Aliases](#aliases)
* [Special suffixes](#special-suffixes)
* [Pushes](#pushes)
* [Finding a name](#finding-a-name)
* [Template rules](#template-rules)
* [Ready-made templates](#ready-made-templates)

## Quick start

The defaults already give GitBot-style lines. They are:

```
format.global       ^C03[$forge]^C ^C14($repo)^C [$kind] ^B$user^B $verb ^C13$ref^C: $title - $url
format.global.push  ^C03[$forge]^C ^C14($repo)^C ^B$user^B pushed ^C13$ref^C to ^C07$branch^C: $title - $url
format.global.push.summary  ^C03[$forge]^C ^C14($repo)^C ^B$user^B pushed $count commits to ^C07$branch^C - $url
format.global.push.commit   ^C03[$forge]^C ^C14($repo)^C ^C13$ref^C - $title - $url
format.global.hidden        ^C03[$forge]^C ^C14($repo)^C (+$hidden hidden commits)
```

The `push` template is used for pushes up to `max_announce_commits`; bigger
pushes get `push.summary`, then shortened `push.commit` lines, then `hidden`.
(`^C` is the colour code, Ctrl+K, and `^B` is bold, Ctrl+B.) To make your own:

```
@config supybot.plugins.GitHooks.format.global "[$forge] ($repo) $user $action $ref - $title - $url"
```

**Put the template in double quotes.** Spaces are fine without them, but
Limnoria treats `[...]` as a nested command, so an unquoted `[$forge]` fails
with `"$forge" is not a valid command`. Quoting always works, colour codes
included.

Colour and bold codes are typed straight from your IRC client (Ctrl+K, Ctrl+B,
Ctrl+O in mIRC and most others), so you can set the format from your client
and see the result straight away.

## Friendly variables

These exist for every event handled by `format.global`, with the same meaning
everywhere:

| Variable | Meaning |
|---|---|
| `$forge` | `GitHub`, `Gitea`, `Forgejo` or `Gogs` |
| `$repo` | `owner/name` |
| `$owner` `$name` | the two halves of `$repo` |
| `$user` | who did it (see the table below) |
| `$event` | the event type: `push`, `issues`, `pull_request`... |
| `$action` | the raw action: `opened`, `closed`, `labeled`... (empty for pushes) |
| `$what` | a ready phrase such as `opened issue #3` or `committed` |
| `$kind` | `issue`, `PR`, `commit`, `push`, `release`, `branch`... |
| `$verb` | `opened`, `closed`, `merged`, `commented on`, `reviewed`, `pushed`... (`synchronize` becomes `updated`) |
| `$ref` | what the event is about: `#3`, a short commit id, a tag or a branch |
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

| Event | `$what` | `$ref` | `$title` | `$url` |
|---|---|---|---|---|
| `push` (once per commit) | `committed` | short commit id | first line of the message | the commit |
| `issues` | `opened issue #3` | `#3` | issue title | the issue |
| `issue_comment` | `commented on issue #3` | `#3` | issue title | the comment |
| `pull_request` | `opened pull request #3` | `#3` | PR title | the PR |
| pull request reviews | `reviewed pull request #3` | `#3` | PR title | the PR or comment |
| `commit_comment` | `commented on commit` | short commit id | first line of the comment | the comment |
| `create` / `delete` | `created branch` | name of the branch/tag | | the repository |
| `release` | `published release` | tag | release name | the release |
| `fork` | `forked` | | name of the new fork | the fork |
| `watch` / `star` | `starred` | | the repository | the repository |

`$user` is the person who triggered the event. The exceptions are pushes,
where it is the commit author's login (the git name if the forge sends no login), and reviews, where it is the reviewer.
A merged pull request has the action `merged` instead of `closed`. When the
forge doesn't send a link (Gogs has no issue or pull request URLs), the plugin
builds it from the repository URL.

Events other than the ones above, or events not listed in
`format.global.events`, don't use the friendly variables or `format.global`.

## Raw payload variables

A webhook is a nested JSON document. Part of an "issue opened" webhook:

```json
{
  "action": "opened",
  "issue": { "number": 7, "title": "It broke", "user": { "login": "alice" } },
  "repository": { "name": "proj", "owner": { "login": "bob" } }
}
```

GitHooks turns every value in it into a variable, joining the levels with
**two underscores**:

| Position in the JSON | Variable |
|---|---|
| `action` | `$action` |
| `issue` → `title` | `$issue__title` |
| `issue` → `user` → `login` | `$issue__user__login` |
| `repository` → `owner` → `login` | `$repository__owner__login` |

The double underscore is needed because JSON names often contain a single one
(`html_url`). In `$issue__html_url` the double underscore means "go into
`issue`" and the single one belongs to the name `html_url`.

Lists inside the payload aren't expanded, so you can't pick the third label out
of `labels`. The exception is the commits of a push, see [Pushes](#pushes).

## Aliases

Typing two underscores is awkward, so every raw variable also has two other
names:

| Spelling | Example |
|---|---|
| raw | `$issue__user__login` |
| single underscores | `$issue_user_login` |
| prefixed with the event | `$issues_issue_user_login` |

They all give the same value, and the double-underscore form always works. The
first two spellings are enough in practice. The prefixed one is there if you
like to see which event a variable belongs to. An alias never replaces an
existing variable.

## Special suffixes

Besides the payload fields, the plugin makes a few derived variables:

| Suffix | Added to | Value |
|---|---|---|
| `__short` | any 40-character commit id, e.g. `$after__short` | the first 7 characters |
| `__branch` | any field called `ref`, e.g. `$ref__branch` | `refs/heads/main` becomes `main` |
| `__firstline` | any text, e.g. `$comment__body__firstline` | the first non-empty line, at most 300 characters, skipping quoted `> ` lines |

These have aliases too: `$comment_body_firstline`, `$ref_branch`.

## Pushes

A push is announced one commit at a time (up to `max_announce_commits`), and
the commit being announced is available as `$__commit__...`, also written
`$commit_...`:

| Variable | Value |
|---|---|
| `$__commit__id` / `$commit_id` | full commit id |
| `$__commit__id__short` / `$commit_id_short` | short commit id |
| `$__commit__message__firstline` / `$commit_message_firstline` | first line of the message |
| `$__commit__author__name` / `$commit_author_name` | author |
| `$__commit__url` / `$commit_url` | link to the commit |
| `$__num_commits` / `$num_commits` | commits in the whole push |
| `$__files__added__len` / `$files_added_len` | files added in the whole push (also `removed`, `modified`) |

With `format.global` you rarely need these, since `$user`, `$ref`, `$title` and
`$url` already describe the commit. When a push has more commits than the
limit, one more line is sent with `format.global.hidden`, where `$hidden` is the
number left out.

## Finding a name

* **`@githooks vars`** lists the event types the bot has received since it
  started.
* **`@githooks vars <event>`** shows the variables and their current values for
  the last event of that type, friendly names first.
* **`@githooks vars <event> <pattern>`** keeps only the names containing the
  pattern, e.g. `@githooks vars issues user`. At most 40 names are shown, so use
  a pattern on big payloads.
* If the bot hasn't received that event yet, trigger one, or use *Redeliver* in
  the webhook settings of your forge (the *Recent deliveries* page also shows
  the exact JSON that was sent).
* The forges document their payloads: GitHub's *Webhook events and payloads*,
  and the webhook pages of Gitea, Forgejo and Gogs. Take the path to the value
  you want and put `__` between the levels.

`@githooks vars` only knows events for repositories announced somewhere, and
only since the bot last started.

## Template rules

* A variable is `$` followed by letters, digits and underscores. To put text
  right after one, use braces: `${user}s`. For a literal dollar sign use `$$`.
* An unknown name (a typo, or a field this event doesn't have) is left in the
  message as typed, e.g. `$titel`. A known name with no value gives an empty
  string, and spaces left doubled by an empty variable are collapsed.
* Colour and formatting codes can be pasted into the template. If you type
  them in a config file, they are `\x02` (bold), `\x03` (colour) and `\x0f`
  (reset).
* Per-action formats such as `format.issues.closed` win over `format.global`
  (and `ignore` silences that action). Those older formats are written as
  `echo ...` commands, see the README, and use the same variable names.

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

Announcing releases and new branches as well:

```
format.global.events  push issues issue_comment pull_request create release
```
