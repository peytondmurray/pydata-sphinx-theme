"""Configuration of the pytest session."""

import re
import time

from http.client import HTTPConnection
from os import environ
from pathlib import Path
from shutil import copytree
from subprocess import PIPE, Popen
from typing import Callable

import pytest
import sphinx

from bs4 import BeautifulSoup
from sphinx.testing.util import SphinxTestApp
from typing_extensions import Self


pytest_plugins = "sphinx.testing.fixtures"

tests_path = Path(__file__).parent
repo_path = tests_path.parent
docs_build_path = repo_path / "docs" / "_build" / "html"

# -- Utils method ------------------------------------------------------------


def escape_ansi(string: str) -> str:
    """Helper function to remove ansi coloring from sphinx warnings."""
    ansi_escape = re.compile(r"(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]")
    return ansi_escape.sub("", string)


# -- global fixture to build sphinx tmp docs ---------------------------------


class SphinxBuild:
    """Helper class to build a test documentation."""

    def __init__(self, app: SphinxTestApp, src: Path):
        self.app = app
        self.src = src

    def build(self, no_warning: bool = True) -> Self:
        """Build the application."""
        self.app.build()
        if no_warning is True:
            assert self.warnings == "", self.status
        return self

    @property
    def status(self) -> str:
        """Returns the status of the current build."""
        return self.app._status.getvalue()

    @property
    def warnings(self) -> str:
        """Returns the warnings raised by the current build."""
        return self.app._warning.getvalue()

    @property
    def outdir(self) -> Path:
        """Returns the output directory of the current build."""
        return Path(self.app.outdir)

    def html_tree(self, *path) -> str:
        """Returns the html tree of the current build."""
        path_page = self.outdir.joinpath(*path)
        if not path_page.exists():
            raise ValueError(f"{path_page} does not exist")
        return BeautifulSoup(path_page.read_text("utf8"), "html.parser")


@pytest.fixture()
def sphinx_build_factory(make_app: Callable, tmp_path: Path, request) -> Callable:
    """Return a factory builder pointing to the tmp directory."""

    def _func(src_folder: str, **kwargs) -> SphinxBuild:
        """Create the Sphinxbuild from the source folder."""
        no_temp = environ.get("PST_TEST_HTML_DIR")
        nonlocal tmp_path
        if no_temp is not None:
            tmp_path = Path(no_temp) / request.node.name / str(src_folder)
        srcdir = tmp_path / src_folder
        if sphinx.version_info < (7, 2):
            from sphinx.testing.path import path as sphinx_path

            srcdir = sphinx_path(srcdir)

        copytree(tests_path / "sites" / src_folder, tmp_path / src_folder)
        app = make_app(srcdir=srcdir, **kwargs)
        return SphinxBuild(app, tmp_path / src_folder)

    yield _func


@pytest.fixture(scope="module")
def url_base():
    """Start local server on built docs and return the localhost URL as the base URL."""
    # Use a port that is not commonly used during development or else you will
    # force the developer to stop running their dev server in order to run the
    # tests.
    port = "8213"
    host = "localhost"
    url = f"http://{host}:{port}"

    if not docs_build_path.exists():
        raise ValueError(
            f"No built documentation exists at {docs_build_path}. Unable to run tests."
        )

    # Try starting the server
    process = Popen(
        ["python", "-m", "http.server", port, "--directory", docs_build_path],
        stdout=PIPE,
    )

    print(f"Starting test server at {url}...")

    # Try connecting to the server
    retries = 5
    while retries > 0:
        conn = HTTPConnection(host, port)
        print("Checking that the server is running...")
        try:
            conn.request("HEAD", "/")
            response = conn.getresponse()
            if response.status == 200:
                yield url
                break
        except ConnectionRefusedError:
            pass

        time.sleep(1)
        retries -= 1

    # Clean up by stopping the server
    process.terminate()
    process.wait()

    # Raise an error if we were unable to get a 200 response from the server
    if not retries:
        raise ConnectionAbortedError(
            "Unable to serve the docs for running tests. Response:\n"
            f"  status: {response.status}\n  reason: {response.reason}"
        )
