"""Nox sessions."""

import platform

import nox
from nox_poetry import Session, session

nox.options.sessions = ["tests", "mypy"]
python_versions = ["3.9", "3.10", "3.11", "3.12"]


@session(python=python_versions)
def tests(session: Session) -> None:
    """Run the test suite."""
    session.install(".")
    session.install("invoke", "pytest", "xdoctest", "coverage[toml]", "pytest-cov")
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
