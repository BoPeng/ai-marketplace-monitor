# Overview

The AI Marketplace Monitor is currently a synchronous Python application that monitors Facebook Marketplace for items matching user criteria. While functional, the project needs to migrate to an async-first architecture to maintain compatibility with modern Python libraries and prepare for future extensibility. The focus is on simplicity and readability rather than performance optimization, as the current application doesn't have performance issues.

# Core Features

## Current Synchronous Architecture

- **Simple Sequential Flow**: Operations run one after another in a predictable, easy-to-debug manner
- **Synchronous I/O**: Network requests use blocking calls with straightforward error handling
- **Mature Libraries**: Currently uses well-established synchronous libraries (requests, sync Playwright)
- **Straightforward Debugging**: Linear execution makes troubleshooting simpler

## Target Async Benefits (Focused on Simplicity)

- **Modern Library Compatibility**: Enable future integration with async-first Python libraries
- **Maintainable Patterns**: Establish clean async/await patterns throughout the codebase
- **Future-Proofing**: Position the project for ecosystem evolution without major rewrites
- **Readable Async Code**: Implement async patterns that are clear and maintainable

# User Experience

## User Personas

- **End Users**: Continue to experience the same CLI interface and functionality with no disruption
- **Developers**: Work with clean, readable async/await patterns that are easy to understand and extend
- **Future Maintainers**: Benefit from modern async patterns that align with Python ecosystem trends

## Key User Flows (Preserved Behavior)

- **Startup**: Application initializes with async foundation but maintains same startup experience
- **Search Execution**: Same search behavior but implemented with async patterns internally
- **AI Processing**: Same AI evaluation flow but using async HTTP clients
- **Notifications**: Same notification delivery but with async implementation
- **Configuration Updates**: Existing config reloading behavior preserved

## UI/UX Considerations

- Maintain existing CLI interface behavior and output formatting
- Preserve keyboard interrupt handling and interactive features
- Keep existing logging and progress reporting patterns

# Technical Architecture

## System Components Migration

### Core Architecture Changes

- **Event Loop Foundation**: Migrate from sync main loop to asyncio event loop
- **Async Task Management**: Replace `schedule` library with async task scheduling
- **Concurrent Execution**: Transform sequential operations into concurrent async tasks

### Component-Level Async Migration

1. **CLI Layer (`cli.py`)**

   - Wrap async main function with `asyncio.run()`
   - Maintain synchronous CLI interface while enabling async internals

2. **Monitor Core (`monitor.py`)**

   - Replace `MarketplaceMonitor` sync methods with async equivalents
   - Convert `schedule` library usage to `asyncio` task scheduling
   - Implement async context managers for browser lifecycle
   - Add concurrent task management for multiple searches

3. **Marketplace Integration (`facebook.py`)**

   - Migrate from `playwright.sync_api` to `playwright.async_api`
   - Convert page navigation and element interactions to async
   - Implement async context managers for browser/page lifecycle
   - Add concurrent listing processing capabilities

4. **AI Backend (`ai.py`)**

   - Replace synchronous OpenAI client with async client
   - Implement async retry logic and error handling
   - Enable concurrent AI evaluations across multiple listings
   - Add async caching operations

5. **Notification System (`notification.py`)**

   - Convert all notification providers to async implementations
   - Implement async HTTP clients for notification APIs
   - Enable concurrent notification sending to multiple users
   - Add async retry mechanisms

6. **Utility Functions (`utils.py`)**
   - Replace `time.sleep()` with `asyncio.sleep()`
   - Convert file I/O operations to async where beneficial
   - Implement async versions of utility functions

## Data Models

- **Listing Model**: No changes required - dataclass remains synchronous
- **Configuration**: Maintain existing TOML-based config system
- **Cache Operations**: Evaluate migration to async cache operations for performance

## APIs and Integrations

- **Facebook Marketplace**: Async web scraping with Playwright async API
- **OpenAI API**: Async client for concurrent AI evaluations
- **Notification APIs**: Async HTTP clients for all notification providers
- **File System**: Async file operations where beneficial

## Infrastructure Requirements

- **Python 3.10+**: Required for modern async/await syntax and asyncio features
- **Async Library Dependencies**:
  - `playwright` (async API)
  - `aiohttp` or `httpx` for async HTTP requests
  - `aiofiles` for async file operations (if needed)
- **Testing Infrastructure**: Async-compatible test framework setup

# Development Roadmap

## Phase 0: Analysis & Preparation

**Scope**: Technical validation and planning (1-2 days)

- Map sync-to-async API conversions for Playwright and OpenAI
- Verify library version compatibility for async APIs
- Create simple async proof-of-concept for browser lifecycle
- Test existing schedule patterns can be replicated with asyncio
- **Deliverable**: Technical validation that async migration is straightforward

## Phase 1: Foundation & Core Loop (MVP)

**Scope**: Establish minimal async foundation while preserving existing behavior

- Convert CLI entry point to use `asyncio.run()` wrapper around existing logic
- Migrate `MarketplaceMonitor` main loop to async (keeping sequential execution initially)
- Replace `time.sleep()` calls with `asyncio.sleep()`
- Update basic utility functions to async where needed
- **Deliverable**: Same functional behavior but running in async event loop
- **Test**: All existing tests pass with async foundation

## Phase 2: Web Scraping Migration (Most Critical)

**Scope**: Convert Playwright operations to async API

- Migrate Facebook Marketplace implementation to async Playwright API
- Convert page navigation and element interactions to async
- Update browser/page lifecycle management to async context managers
- Preserve existing scraping logic and error handling patterns
- **Deliverable**: Async web scraping with identical scraping behavior
- **Test**: Browser tests pass with async Playwright

## Phase 3: AI & HTTP Client Migration

**Scope**: Convert API calls to async implementations

- Migrate OpenAI integration to async client
- Convert notification HTTP requests to async
- Update retry logic and error handling for async patterns
- Keep cache operations synchronous (diskcache is inherently sync)
- **Deliverable**: All external API calls use async HTTP clients
- **Test**: AI evaluation and notifications work identically

## Phase 4: Testing & Validation

**Scope**: Ensure comprehensive async test coverage

- Add `pytest-asyncio` for async test execution
- Convert existing tests to async patterns incrementally
- Validate keyboard interrupt handling works with async event loop
- Verify config reloading works with async main loop
- **Deliverable**: Full async test suite with same coverage as sync version

# Logical Dependency Chain

## Conservative Foundation Approach

1. **Async Event Loop Setup** - Minimal change to wrap existing logic in asyncio.run()
2. **Sequential Async Conversion** - Convert one component at a time while preserving behavior
3. **Testing at Each Step** - Validate functionality matches sync version before proceeding
4. **No Concurrency Initially** - Focus on async conversion first, concurrency later if needed

## Simplicity-First Migration Strategy

1. **Phase 1**: Async wrapper - minimal change to establish async foundation
2. **Phase 2**: Web scraping - most critical async conversion for Playwright compatibility
3. **Phase 3**: API clients - convert HTTP calls to async for library compatibility
4. **Phase 4**: Testing validation - ensure no regressions introduced
5. **Phase 5**: Documentation - record patterns for future maintainers

## Risk Mitigation Through Simplicity

- Preserve existing sequential execution order during initial migration
- Maintain identical error handling and logging behavior
- Keep complex concurrent patterns out of scope for this migration
- Focus on clean, readable async/await patterns over performance optimization

# Risks and Mitigations

## Technical Challenges

### Risk: Browser Lifecycle Management Complexity

- **Issue**: Current browser sharing and context management needs careful async conversion
- **Mitigation**: Phase 0 proof-of-concept to validate browser lifecycle patterns
- **Rollback**: Keep sync fallback until async browser management is validated

### Risk: Schedule Library Replacement

- **Issue**: Current `schedule` library patterns need asyncio equivalents
- **Mitigation**: Phase 0 validation that asyncio can replicate existing scheduling
- **Alternative**: Keep schedule library and wrap with async if needed

### Risk: Keyboard Interrupt & Config Reload

- **Issue**: Interactive features and file watching may conflict with async event loop
- **Mitigation**: Test these patterns early in Phase 1
- **Conservative**: Maintain existing behavior rather than optimize

### Risk: Test Migration Breaking Coverage

- **Mitigation**: Convert tests incrementally alongside implementation phases
- **Validation**: Each phase includes test validation as deliverable

## MVP Scope Definition (Simplified)

### Minimum Viable Async System

- Same CLI interface and user experience
- Async event loop foundation established
- All I/O operations converted to async (Playwright, HTTP clients)
- Preserved sequential execution behavior
- Same error handling and logging patterns

### Success Criteria (Conservative)

- Zero functional regressions compared to sync version
- All existing tests pass in async form
- Clean, readable async/await code patterns
- No performance degradation from sync version
- Modern library compatibility achieved (main goal)

## Resource Constraints

### Development Time

- **Risk**: Async migration requires significant refactoring effort
- **Mitigation**: Phased approach allows for incremental progress and testing

### Learning Curve

- **Risk**: Team familiarity with async patterns may be limited
- **Mitigation**: Start with simple async conversions and build expertise gradually

### Testing Overhead

- **Risk**: Async testing requires new patterns and potentially new tools
- **Mitigation**: Invest in async testing infrastructure early in Phase 1

# Appendix

## Research Findings

- **Playwright Async Performance**: Async API shows 2-3x improvement in concurrent scenarios
- **OpenAI Async Client**: Native async support available, well-documented migration path
- **Python Async Ecosystem**: Mature libraries available for all current dependencies

## Technical Specifications

### Library Dependencies (Minimal Changes)

```toml
# Existing dependencies that already support async
playwright = ">=1.41.0"  # Already has async API available
openai = ">=1.24.0"      # Already has async client support

# Testing dependency additions
pytest-asyncio = ">=0.21.0"  # For async test execution

# No new HTTP client dependencies needed - OpenAI client handles async HTTP
# No new file I/O dependencies needed - minimal async file operations required
```

### Current Testing Framework Analysis

The project uses:

- **pytest** as the main testing framework
- **pytest-playwright** for browser automation testing
- **Sync Playwright API** throughout test suite
- **Standard pytest fixtures** in `conftest.py`
- **Parametrized tests** for configuration validation
- **No async test patterns** currently implemented

### Required Testing Changes

- Add `pytest-asyncio` plugin to support async test execution
- Convert Playwright tests from sync to async API incrementally
- Update fixtures to provide async context managers
- Maintain identical test coverage and assertions
- Preserve existing test data and HTML fixtures

### Error Handling Strategy

- Keep existing try/catch patterns around browser operations
- Add async-compatible retry mechanisms for HTTP clients
- Maintain current logging patterns (Rich library is async-compatible)
- Preserve keyboard interrupt handling with asyncio event loop

### Backward Compatibility

- CLI interface remains unchanged for end users
- Configuration files maintain same format and structure
- Existing caching and logging functionality preserved
- Graceful degradation to sequential processing if needed
