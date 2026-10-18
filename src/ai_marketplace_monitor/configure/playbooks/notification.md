---
section: notification
summary: How and to whom aimm sends notifications: [email.NAME] and [notification.NAME] sections and the [user.NAME] sections that receive them.
---
## Goal

The user gets aimm's notifications where they want them. There are two kinds of section that
send:

- An `[email.NAME]` section sends aimm's full email: all new listings in one message, with
  their photos. Best for reviewing listings.
- A `[notification.NAME]` section is one phone or chat channel (UnitySVC, Pushbullet,
  Pushover, ntfy, Telegram) that sends short text messages without photos. Best for being
  alerted quickly.

A `[user.NAME]` section is a person: where they receive messages (email address, chat ID, ...)
and which sections they receive (`notify_with`, as `email.<name>` and `notification.<name>`;
all of them when it is unset). Items and marketplaces refer to users, so every section needs a
user who receives it.

## Subtasks

### Who receives it

Most people have one user. `section_show` returns `default_user`: notifications go to that user,
which is `me` when there is no user yet; create `[user.me]` for them without asking. If there are
several users (`can_reference.users`), ask which ones should receive a new section.

### Choosing how to notify

Ask how they want to be notified if they did not say: by email, on their phone or in a chat, or
both.

**Email** (`[email.*]`). `section_show` lists `email_options` with the section and values to
write; offer them in that order.

- **UnitySVC email**: `[email.unitysvc]` with `smtp_username = "smtp-to-mailbox"` (required:
  the UnitySVC service that delivers it, here to the email address registered with their
  UnitySVC account, so no `email` is needed on the user). Its preset has the server, the port
  and the password `${UNITYSVC_API_KEY}`. The easiest option when they have a UnitySVC key
  (`unitysvc_api_key` in `section_show` says how to reference it); offer it first then. To send
  through another UnitySVC service (a relay), set its name as `smtp_username`.
- **Gmail**: `[email.gmail]`, with `smtp_username` (their Gmail address); the preset has the
  server and the password reference `${GMAIL_SMTP_PASSWORD}`. The user needs `email` (where they
  receive it) and a Gmail app password set as `GMAIL_SMTP_PASSWORD` (`needs` says how to create
  one; many people find it hard, so mention that UnitySVC email avoids it).
- **Another email account**: `[email.<provider>]` (e.g. `email.outlook`) with `smtp_server`,
  `smtp_username` and `smtp_password`.

**Phone and chat** (`[notification.*]`):

- **UnitySVC notifications**: `unitysvc_api_key = "${UNITYSVC_API_KEY}"`. Messages go to the
  UnitySVC inbox and the destination the user saved in UnitySVC (Discord, Slack, SMS, phone push
  and many other channels), so one section reaches any of them. Not for email: that is
  `[email.unitysvc]`.
- **Pushbullet** (`pushbullet_token`), **Pushover** (`pushover_api_token` on the notification,
  `pushover_user_key` on the user), **ntfy** (`ntfy_server` on the notification, `ntfy_topic` on
  the user), **Telegram** (`telegram_token` on the notification, `telegram_chat_id` on the user).

When they have a UnitySVC key and only say "UnitySVC", ask whether they want email or phone/chat
messages. Name a notification after its channel (`unitysvc`, `pushbullet`, `telegram`).

### The daily digest

`digest_at` on a section (a local time such as `"08:00"`) makes it send a daily summary of the
last 24 hours: the full digest from an `[email.*]` section, a short one from a
`[notification.*]` section. When the user gets email, set it on the email section only; a phone
digest next to an email one is rarely wanted. It uses a little AI (one short call per item with
new activity). Offer it once email or a phone channel is set up, and ask at what time.

### Switching channels

"Switch to UnitySVC email" (or any other channel) means the users get the new section instead
of the old one, not both. Set up the new section, then for each user who received the old one,
put the new section in its place: replace the old entry in `notify_with`, or, if the user has no
`notify_with` (it receives everything), give it a `notify_with` listing the sections it should
keep receiving. Move `digest_at` along if the old section had it. Keep the old section unless
the user wants it gone; set `enabled = false` on it if no one else should receive it. Tell the
user which channel they will get from now on.

### Secrets

Passwords, tokens and API keys are only ever written as environment-variable references such as
`${GMAIL_SMTP_PASSWORD}`; never ask the user to type them in the chat. Use the reference
`unitysvc_api_key` suggests for a UnitySVC key, otherwise a clear name (`GMAIL_SMTP_PASSWORD`,
`PUSHBULLET_TOKEN`, `PUSHOVER_API_TOKEN`, `PUSHOVER_USER_KEY`, `TELEGRAM_TOKEN`). After saving,
aimm tells the user which variables to set.

### Linking

A user receives a section when it is in the user's `notify_with` (write `email.<name>` or
`notification.<name>`), or when the user has no `notify_with` (then all of them). If the user
has a `notify_with` list, add the new section to it; if it has none, it already receives it. A
new user gets `notify_with` with the sections it should receive.

### Testing

After a section, or a user's channels, is saved, `save` returns `test_notification` with the
sections aimm can test. Offer the test (it sends a real message; metered channels may cost a
little) and call `test_notification` if the user agrees. Explain the result: on a failure, say
what the error likely means (a wrong token, a server that does not support STARTTLS, ...) and
help fix it, for example with another token or another channel, then save and offer the test
again. If the test cannot run here (`can_run_here` is false), pass on the `reason`.

### Options

`with_description` (include the listing description) and `message_format` on a notification,
`remind` on the user (remind about listings still available later). Ask only if the user cares.

## Completion

An email or notification section is complete when it can send (`smtp_password` for email, which
the presets have; the channel's fields for a notification), a `user` receives it, and each
receiving user has what it needs (`email`, `pushover_user_key`, `ntfy_topic`,
`telegram_chat_id`). A user is complete when it receives a section and has what each one needs.

## Rules

- Recipient fields (`email`, `pushover_user_key`, `ntfy_topic`, `telegram_chat_id`) go on the
  user; servers, credentials and `digest_at` go on the email or notification section.
- Do not change other users' `notify_with` unless the user asks.
