---
section: notification
summary: How and to whom aimm sends notifications: [notification.NAME] channels and the [user.NAME] sections that receive them.
---
## Goal

The user gets aimm's notifications where they want them. A `[notification.NAME]` section is one
channel (an email account, a UnitySVC key, a push service) with its servers and credentials. A
`[user.NAME]` section is a person: where they receive messages (email address, chat ID, ...) and
which notifications they receive (`notify_with`; all of them when it is unset). Items and
marketplaces refer to users, so every notification needs a user who receives it.

## Subtasks

### Who receives it

Most people have one user. `section_show` returns `default_user`: notifications go to that user,
which is `me` when there is no user yet; create `[user.me]` for them without asking. If there are
several users (`can_reference.users`), ask which ones should receive a new notification.

### Choosing a channel

Ask how they want to be notified if they did not say. There are two kinds of channel:

**Email** sends aimm's full email: all new listings in one message, with their photos. Best for
reviewing listings.

- **UnitySVC email**: `smtp_server = "smtp.svcpass.com"`, `smtp_username = "smtp-to-mailbox"`,
  `smtp_password = "${UNITYSVC_API_KEY}"`. Sent to the email address registered with their
  UnitySVC account, so no `email` is needed on the user. The easiest email option when they have
  a UnitySVC key (`unitysvc_api_key` in `section_show` says how to reference it); offer it first
  then. Write all three fields so the section shows how the email is sent.
- **Gmail or another email account**: the user's `email` on the user, and `smtp_password` on the
  notification. Gmail needs an app password (Google account, Security, App passwords), which
  many people find hard to create; mention that UnitySVC email avoids it.

**Phone and chat notifications** send short text messages without photos. Best for being
alerted quickly.

- **UnitySVC notifications**: `unitysvc_api_key = "${UNITYSVC_API_KEY}"`. Messages go to the
  UnitySVC inbox and the destination the user saved in UnitySVC (Discord, Slack, SMS, phone push
  and many other channels), so one section reaches any of them. Not for email: use UnitySVC
  email instead.
- **Pushbullet** (`pushbullet_token`), **Pushover** (`pushover_api_token` on the notification,
  `pushover_user_key` on the user), **ntfy** (`ntfy_server` on the notification, `ntfy_topic` on
  the user), **Telegram** (`telegram_token` on the notification, `telegram_chat_id` on the user).

`section_show` lists `email_options` with the values to write for each email channel; when the
user wants email, offer them in that order. For Gmail, tell them how to get the app password
(`needs`). When they have
a UnitySVC key and only say "UnitySVC", ask whether they want email or phone/chat messages. Name
a new notification after its channel (`gmail`, `unitysvc_email`, `unitysvc`, `pushbullet`).

### Switching channels

"Switch to UnitySVC email" (or any other channel) means the users get the new channel instead
of the old one, not both. Set up the new notification, then for each user who received the old
one, put the new notification in its place: replace the old name in `notify_with`, or, if the
user has no `notify_with` (it receives everything), give it a `notify_with` listing the
notifications it should keep receiving. Keep the old notification section unless the user wants
it gone; set `enabled = false` on it if no one else should receive it. Tell the user which
channel they will get from now on.

### Secrets

Passwords, tokens and API keys are only ever written as environment-variable references such as
`${GMAIL_APP_PASSWORD}`; never ask the user to type them in the chat. Use the reference
`unitysvc_api_key` suggests for a UnitySVC key, otherwise a clear name (`GMAIL_APP_PASSWORD`,
`PUSHBULLET_TOKEN`, `PUSHOVER_API_TOKEN`, `PUSHOVER_USER_KEY`, `TELEGRAM_TOKEN`). After saving,
aimm tells the user which variables to set.

### Linking

A user receives a notification when it is in the user's `notify_with`, or when the user has no
`notify_with` (then all notifications). If the user has a `notify_with` list, add the new
notification to it; if it has none, it already receives it. A new user gets `notify_with` with
the notifications it should receive.

### Options

`with_description` (include the listing description), `message_format` for push channels,
`remind` on the user (remind about listings still available later), `digest_at` on the user (a
daily summary at a local time such as `"08:00"`: the full digest by email, a short one on push
channels; `digest_with` limits it to some of the notifications the user receives). Ask only if
the user cares.

## Completion

A notification is complete when its channel (`channel`) has the required fields (such as
`smtp_password` for email or `unitysvc_api_key` for UnitySVC), a `user` receives it, and each
receiving user has what that channel needs (`email`, `pushover_user_key`, `ntfy_topic`,
`telegram_chat_id`). A user is complete when it receives a `notification` and has what each one
needs.

## Rules

- Recipient fields (`email`, `pushover_user_key`, `ntfy_topic`, `telegram_chat_id`) go on the
  user; servers and credentials go on the notification.
- Do not change other users' `notify_with` unless the user asks.
