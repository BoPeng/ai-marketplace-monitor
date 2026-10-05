# aimm-configure: users and notifications

Builds on [the marketplace design](2026-10-05-configure-marketplace-design.md) and
[the item toolkit](2026-10-05-configure-item-design.md).

## Summary

`aimm-configure notification[.NAME]` and `aimm-configure user[.NAME]` run one session that may
change any `[user.*]` and `[notification.*]` section and nothing else; users and notifications
are set up together because neither is useful alone. The router sends requests such as "notify
me through email" to the same toolkits.

## Decisions

| Topic | Decision |
|---|---|
| Commands | One combined session for both types; the address only picks where the AI starts. `only` gains a wildcard: `(type, "*")` allows any section of that type |
| Default user | The first user (saved, then drafted); with none, a new `[user.me]`. Notifications go there unless the user has several users, when the AI asks |
| Layout | Canonical: recipient fields (`email`, `pushover_user_key`, `ntfy_topic`, `telegram_chat_id`) on the user; channel fields (servers, credentials) and delivery options on the notification; linked by `notify_with` (unset = every notification). Field roles come from the existing `CHANNEL` / `RECIPIENT` / `COMMON` metadata |
| Channels | Email through UnitySVC (`smtp.svcpass.com`, no address needed), Gmail (app password), UnitySVC notifications, Pushbullet, Pushover, ntfy, Telegram. `unitysvc_base_url` is not offered |
| Secrets | Only `${VAR}` references (existing rule). `section_show` tells the AI how to reference the user's UnitySVC key (`${UNITYSVC_API_KEY}` from `[ai.unitysvc]` or the environment), never the key. Inline secrets in old `[user.*]` sections are masked too |
| After saving | `Toolkit.after_save` notes: aimm (not the LLM) lists unset variables with `export` lines; the notes are also returned to the LLM as `shown_to_user` |
| Completeness | Notification: one channel with its required fields, at least one user receives it, and each receiver has the channel's recipient field. User: receives a notification (or has an inline channel) and has each one's recipient field |
| Drafts together | `Toolkit.can_apply` decides whether a draft is part of the config other sections are checked against (default: complete). A notification counts once its channel is complete, so a user can name it before the user exists; a user counts once the notifications it names do |
| Playbook | One `notification.md` for both types; the system prompt and `section_guide` include it once, with both field tables, and reading it marks both types as read |

## Testing

Guide coverage; masking; the UnitySVC key reference; completeness (channel, user, recipients,
UnitySVC email preset, `notify_with` unset); validation (mixed channels, bad values, unknown
`notify_with`, secrets); drafts checked together; after-save notes; start summary and default
user; shared guide; a scripted email session creating `[notification.unitysvc_email]` and
`[user.me]` in one save; the session cannot touch other types; CLI dispatch.
