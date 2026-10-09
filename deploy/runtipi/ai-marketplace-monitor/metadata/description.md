# AI Marketplace Monitor

AI Marketplace Monitor (aimm) watches Facebook Marketplace for the items you want, rates each new listing with AI, and notifies you of good deals by email, phone, Discord, Slack, Telegram and more.

## Getting started

1. Open the app and sign in with the Facebook username and password you entered when installing.
2. aimm logs in to Facebook in its own browser. If Facebook asks for a CAPTCHA or a security code, click **Open browser** and complete it there.
3. Describe what you are looking for in the **Configure** chat, or edit `config.toml` in the web UI.

The default configuration uses one [UnitySVC](https://unitysvc.com) API key both for the AI that rates listings (OpenAI, Anthropic and other engines) and for email and phone notifications. You can configure other providers instead.

See the [Docker installation guide](https://github.com/BoPeng/ai-marketplace-monitor/blob/main/docs/docker-installation.md) for more.
