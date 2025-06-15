"""Nox sessions."""

import platform

import nox
from nox_poetry import Session, session

nox.options.sessions = ["tests", "mypy"]
python_versions = ["3.10", "3.11", "3.12"]


@session(python=python_versions)
def tests(session: Session) -> None:
    """Run the test suite with event loop conflict prevention.

    This session installs pytest-asyncio alongside pytest-playwright to support
    both async test methods and browser automation tests. The event loop conflict
    between these frameworks is resolved through test splitting in tasks.py.

    Dependencies explained:
    - pytest-playwright: Browser automation for end-to-end tests
    - pytest-asyncio: Async test method support for telegram functionality
    - Both are needed but run in separate pytest invocations to avoid conflicts
    """
    session.install(".")
    session.install(
        "invoke",
        "pytest",
        "xdoctest",
        "coverage[toml]",
        "pytest-cov",
        "pytest-playwright",
        "pytest-asyncio",  # Required for telegram async tests, isolated from playwright
    )
    try:
        session.run(
            "inv",
            "tests",
            env={
                "COVERAGE_FILE": f".coverage.{platform.system()}.{platform.python_version()}",
            },
        )
    finally:
        if session.interactive:
            session.notify("coverage")


@session(python=python_versions)
def coverage(session: Session) -> None:
    """Produce the coverage report."""
    args = session.posargs if session.posargs and len(session._runner.manifest) == 1 else []
    session.install("invoke", "coverage[toml]")
    session.run("inv", "coverage", *args)


@session(python=python_versions)
def mypy(session: Session) -> None:
    """Type-check using mypy."""
    session.install(".")
    session.install("invoke", "mypy")
    session.run("inv", "mypy")


@session(python="3.12")
def security(session: Session) -> None:
    """Scan dependencies for insecure packages."""
    session.install("invoke", "safety")
    session.run("inv", "security")
