# Telegram Support Integration PRD

## Overview
Add Telegram notification support to AI Marketplace Monitor while maintaining the existing synchronous architecture. This integration will serve as the foundation for future async notification backends (Discord, etc.) by implementing a simple `asyncio.run()` pattern that isolates async operations without complex infrastructure.

The primary challenge is integrating the fully asynchronous `python-telegram-bot` library into the existing synchronous notification system while avoiding corruption issues and maintaining the established notification patterns.

## Core Features

### Telegram Text Notifications
- **What it does**: Sends marketplace listing notifications via Telegram bot messages using MarkdownV2 formatting
- **Why it's important**: Provides instant mobile notifications with rich text formatting for better user experience
- **How it works**: Integrates with existing notification pipeline, formatting listing data as Markdown and sending via Telegram Bot API

### Simple Async Integration Pattern
- **What it does**: Uses `asyncio.run()` to execute async Telegram operations within sync notification interface
- **Why it's important**: Enables use of official async libraries without complex infrastructure or corruption risk
- **How it works**: Each notification call uses `asyncio.run()` to create isolated event loop, execute async operation, and clean up automatically

### Configuration Integration
- **What it does**: Extends existing user configuration pattern to include Telegram credentials and settings
- **Why it's important**: Maintains consistency with existing notification backends (PushBullet, email, etc.)
- **How it works**: Follows established `[user.username]` configuration pattern with `telegram_token` and `telegram_chat_id` fields

### Error Handling and Retry Logic
- **What it does**: Implements the same retry patterns and error handling as existing notification backends
- **Why it's important**: Ensures reliability and consistent user experience across all notification methods
- **How it works**: Async notification calls wrapped with retry logic, timeouts, and proper exception handling

## Technical Architecture

### System Components

#### TelegramNotificationConfig (PushNotificationConfig subclass)
- Extends existing `PushNotificationConfig` following established patterns
- Fields: `telegram_token`, `telegram_chat_id`, `max_retries`, `retry_delay`
- Implements sync `send_message()` interface that internally uses `asyncio.run()`
- Validates Telegram-specific configuration requirements
- Integrates with existing user configuration loading

#### Async Implementation Methods
- `_send_message_async()`: Private async method handling actual Telegram Bot API calls
- Uses `telegram.Bot` class directly (not `telegram.ext.Application`) for simple message sending
- Uses `telegram.helpers.escape_markdown()` for safe MarkdownV2 formatting of user-generated content
- Handles message splitting for Telegram's 4096 character limit
- Implements rate limiting with 429 error handling and `Retry-After` header support
- Manages bot lifecycle (initialize, send, cleanup) within each call

#### No Base Class Changes Required
- Existing `NotificationConfig` and `PushNotificationConfig` remain unchanged
- Zero risk of corruption to existing notification backends
- Follows established inheritance patterns exactly

### Data Models
- Extend existing `User` model to include Telegram configuration fields
- Leverage existing `Listing` model for notification content
- Reuse existing retry and error tracking structures

### APIs and Integrations
- **Telegram Bot API**: HTTP-based API for sending messages
- **python-telegram-bot**: Async wrapper library for Telegram Bot API
- **asyncio**: Event loop management and coroutine scheduling
- **pytest-asyncio**: Testing framework for async components

### Infrastructure Requirements
- **Dependencies**: Add `python-telegram-bot` only (no additional testing dependencies required)
- **Threading**: No additional threads - `asyncio.run()` manages event loop lifecycle automatically
- **Memory**: Minimal overhead - bot connections created and cleaned up per notification
- **Network**: HTTP/HTTPS connectivity to Telegram Bot API servers

## Development Roadmap

### Phase 1: Basic Implementation
**MVP Requirements:**
- Implement `TelegramNotificationConfig` extending `PushNotificationConfig`
- Create `send_message()` sync wrapper using `asyncio.run()` pattern
- Implement `_send_message_async()` using `telegram.Bot` class directly for simple message sending
- Add `telegram.helpers.escape_markdown()` for safe MarkdownV2 formatting
- Add unit tests using `AsyncMock` for async function mocking

**Scope:**
- Focus on simplest possible integration following existing patterns
- Use `telegram.Bot` directly (not `telegram.ext.Application`) for simplicity
- Implement safe MarkdownV2 formatting with proper escaping from day one
- Ensure zero impact on existing sync notification system
- Validate `asyncio.run()` pattern works with existing test suite

### Phase 2: Enhanced Features
**MVP Requirements:**
- Implement message splitting for Telegram's 4096 character limit
- Add Telegram rate limiting with 429 error handling and `Retry-After` header support
- Enhance error messages and logging for Telegram-specific failures
- Enhance configuration validation for Telegram requirements

**Scope:**
- Handle long listing descriptions with automatic message splitting
- Implement proper rate limiting: 1 message/second per individual chat, 20/minute for groups, 30/second global
- Handle HTTP 429 "Too Many Requests" responses with appropriate backoff
- Enhanced error messages and logging for debugging common issues

### Phase 3: Testing and Documentation
**MVP Requirements:**
- Comprehensive unit test coverage using `AsyncMock` for async functions
- Validation of error handling and retry logic integration
- Enhanced documentation with configuration examples and troubleshooting
- User guide for obtaining Telegram bot token and chat ID

**Scope:**
- Use existing sync test suite with `AsyncMock` for async function testing
- Mock-based testing approach (no real Telegram API integration tests)
- Focus on behavior testing rather than implementation details
- User documentation with step-by-step setup guide and common error solutions

## Logical Dependency Chain

### Basic Implementation (Phase 1)
1. **TelegramNotificationConfig Class** - Extend `PushNotificationConfig` with Telegram fields
2. **Sync Wrapper Method** - Implement `send_message()` using `asyncio.run()` pattern
3. **telegram.Bot Implementation** - Use `telegram.Bot` directly for simple message sending
4. **Safe MarkdownV2 Formatting** - Implement `telegram.helpers.escape_markdown()` from day one
5. **Initial Testing** - Unit tests with `AsyncMock` to validate async function calls

### Enhanced Features (Phase 2)
6. **Message Splitting Logic** - Handle Telegram's 4096 character limit for long descriptions
7. **Rate Limiting Implementation** - Handle 429 errors with `Retry-After` header support
8. **Enhanced Error Handling** - Add Telegram-specific error messages and logging
9. **Configuration Validation** - Validate bot tokens and chat IDs

### Testing and Documentation (Phase 3)
10. **Comprehensive Test Coverage** - Expand unit tests for all features and edge cases
11. **User Setup Guide** - Documentation for obtaining bot tokens and chat IDs
12. **Troubleshooting Guide** - Common errors (401 unauthorized, invalid chat_id, etc.)
13. **Future Foundation** - Establish pattern for Discord and other async notification backends

## Risks and Mitigations

### Technical Challenges

**Risk**: Event loop conflicts with existing sync codebase
- **Mitigation**: Use `asyncio.run()` for complete event loop isolation per notification call
- **Validation**: Each async operation gets fresh event loop, preventing conflicts

**Risk**: Notification system corruption due to improper async integration
- **Mitigation**: Zero changes to existing base classes, extend `PushNotificationConfig` only
- **Validation**: Existing notification tests remain unchanged and must pass

**Risk**: Testing async functions called by `asyncio.run()`
- **Mitigation**: Use `AsyncMock` to mock async functions before `asyncio.run()` calls
- **Validation**: Unit tests verify expected async function calls without actual API interactions

### MVP Definition and Scope Control

**Risk**: Feature creep beyond basic text notifications
- **Mitigation**: Strict adherence to text-only notifications with MarkdownV2 formatting
- **Validation**: Clear acceptance criteria focused on core notification functionality

**Risk**: Over-engineering the async integration
- **Mitigation**: Use simple `asyncio.run()` pattern, no background threads or complex services
- **Validation**: Code review focused on following existing `PushNotificationConfig` patterns exactly

### Resource and Integration Constraints

**Risk**: Breaking existing notification system
- **Mitigation**: No base class changes, extend existing classes only, maintain 100% backward compatibility
- **Validation**: All existing notification tests must pass unchanged

**Risk**: Performance degradation from `asyncio.run()` overhead
- **Mitigation**: Acceptable for notification frequency, bot connection cleanup per call
- **Validation**: Validate notification latency acceptable for marketplace monitoring use case

## Appendix

### Research Findings
- **Async/Sync Integration**: `asyncio.run()` pattern provides simplest async integration for notification-frequency operations
- **Testing Strategy**: Existing sync tests handle `asyncio.run()` normally, `AsyncMock` enables proper async function mocking
- **Event Loop Management**: Per-call event loop creation via `asyncio.run()` eliminates complex lifecycle management
- **Telegram API**: `python-telegram-bot` v20+ provides stable API abstraction, handles Telegram Bot API changes automatically

### Technical Specifications
- **Python Version**: Compatible with existing 3.10+ requirement
- **Dependencies**: `python-telegram-bot>=20.0` only (no additional testing dependencies)
- **Threading Model**: No additional threads - `asyncio.run()` manages event loop per call
- **Message Format**: Telegram MarkdownV2 syntax for rich text formatting
- **Error Handling**: Reuse existing retry patterns from `PushNotificationConfig` base class

### Configuration Example
```toml
[user.user1]
email = 'user@example.com'
pushbullet_token = 'existing_token'
telegram_token = 'bot_token_from_botfather'  # Get from @BotFather on Telegram
telegram_chat_id = '123456789'               # Get from @userinfobot or messaging your bot
```

### Setup Instructions
**Getting Telegram Bot Token:**
1. Message @BotFather on Telegram
2. Send `/newbot` command
3. Follow prompts to create bot and get token

**Getting Chat ID:**
1. Message @userinfobot on Telegram to get your user ID, OR
2. Send a message to your bot, then call `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
3. Look for `"chat":{"id":...}` in the response

**Common Issues:**
- **401 Unauthorized**: Invalid bot token - regenerate from @BotFather
- **400 Bad Request (chat not found)**: Invalid chat_id - verify using methods above
- **403 Forbidden**: Bot was blocked by user or can't initiate conversation

### Future Considerations
This architecture establishes the foundation for additional async notification backends:
- **Discord**: Same `asyncio.run()` pattern with `discord.py` library
- **Slack**: Can leverage same pattern for async Slack SDK
- **Matrix**: Similar async-only client libraries

The `asyncio.run()` pattern will support these future integrations following the exact same implementation approach established by Telegram integration.
