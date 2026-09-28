"""Builds tests/fixture_site/ once per session and serves it over HTTP for Playwright."""

import functools
import http.server
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixture_site"


@pytest.fixture(scope="session")
def built_site(tmp_path_factory):
    site_dir = tmp_path_factory.mktemp("site")
    proc = subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "--site-dir", str(site_dir), "--clean"],
        cwd=FIXTURE_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"fixture site failed to build:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "WARNING" not in proc.stdout and "WARNING" not in proc.stderr, (
        f"fixture site build produced warnings:\n{proc.stdout}\n{proc.stderr}"
    )
    return {"site_dir": site_dir}


@pytest.fixture(scope="session")
def site_url(built_site):
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(built_site["site_dir"])
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


# axe-core 4.10.2. To update, replace this file with a newer axe.min.js from
# https://github.com/dequelabs/axe-core/releases.
VENDOR_AXE_JS = Path(__file__).parent / "vendor" / "axe.min.js"

# Violations in Material's own templates, not the plugin.
KNOWN_UPSTREAM_RULES = {
    "aria-dialog-name",  # Material's search dialog has no accessible name
}

# These come from Material's default palette (.md-tabs__link, .md-copyright) and the
# fixture's plain prose link. They're skipped only for full-page scans, so the scan
# scoped to .md-cheatsheet still checks the toggle's contrast.
FULL_PAGE_ONLY_DISABLED_RULES = {
    "color-contrast",
    "link-in-text-block",
}

DISABLED_RULES = KNOWN_UPSTREAM_RULES


def run_axe(page, extra_disabled=(), context=None):
    page.add_script_tag(path=str(VENDOR_AXE_JS))
    disabled = sorted(set(DISABLED_RULES).union(extra_disabled))
    result = page.evaluate(
        """([disabledRules, ctx]) => axe.run(ctx || document, {
            rules: Object.fromEntries(disabledRules.map((id) => [id, { enabled: false }]))
        })""",
        [disabled, context],
    )
    return result["violations"]


def format_violations(violations):
    lines = []
    for v in violations:
        targets = [n["target"] for n in v["nodes"][:5]]
        lines.append(
            f"[{v['impact']}] {v['id']}: {v['help']} ({len(v['nodes'])} node(s)): {targets}"
        )
    return "\n".join(lines)
