"""Nox sessions."""

import platform

import nox
from nox import Session

nox.options.sessions = ["tests", "mypy"]
python_versions = ["3.10", "3.11", "3.12"]


@nox.session(python=python_versions)
def tests(session: Session) -> None:
    """Run the test suite."""
    session.run("uv", "sync", "--extra", "test", external=True)
    session.install("invoke")
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


@nox.session(python=python_versions)
def coverage(session: Session) -> None:
    """Produce the coverage report."""
    args = session.posargs if session.posargs and len(session._runner.manifest) == 1 else []
    session.run("uv", "sync", "--extra", "test", external=True)
    session.install("invoke")
    session.run("inv", "coverage", *args)


@nox.session(python=python_versions)
def mypy(session: Session) -> None:
    """Type-check using mypy."""
    session.run("uv", "sync", "--extra", "typing", external=True)
    session.install("invoke")
    session.run("inv", "mypy")


@nox.session(python="3.12")
def security(session: Session) -> None:
    """Scan dependencies for insecure packages."""
    session.run("uv", "sync", "--extra", "security", external=True)
    session.install("invoke")
    session.run("inv", "security")
