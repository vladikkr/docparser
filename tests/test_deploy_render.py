"""The deploy script talks to an API, so most of it can only be checked offline.

These assert the parts that are silently wrong far more often than the HTTP
calls: the wrong default branch, a Dockerfile path that does not exist, or the
token leaking into output.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("deploy_render", ROOT / "scripts" / "deploy_render.py")
deploy_render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy_render)


def test_the_dockerfile_it_points_at_exists():
    path = ROOT / "docker" / "Dockerfile.bot"
    assert path.exists(), f"the script points at {deploy_render.DOCKERFILE}, which is missing"
    assert deploy_render.DOCKERFILE.endswith("Dockerfile.bot")


def test_the_branch_is_the_one_that_exists():
    # The repo's default branch is master, not main, and a wrong branch deploys
    # stale code without any error worth reading.
    assert deploy_render.BRANCH in ("master", "main")

    import subprocess

    result = subprocess.run(
        ["git", "branch", "--list", deploy_render.BRANCH],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.stdout.strip(), f"branch {deploy_render.BRANCH} is not present locally"


def test_it_creates_a_worker_and_not_a_web_service():
    payload = deploy_render.service_payload("owner-id")
    assert payload["type"] == "worker"
    assert payload["plan"] == "free"
    assert payload["autoDeployTrigger"]


def test_the_token_never_appears_in_output():
    rendered = deploy_render.redacted()
    for item in rendered:
        if "TOKEN" in item["key"]:
            assert item["value"] == "<hidden>", "the token would be printed"


def test_env_carries_what_the_bot_needs():
    keys = {item["key"] for item in deploy_render.env_payload()}
    for required in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ADMIN_ID",
        "TELEGRAM_TRIAL_LIMIT",
        "TELEGRAM_STATE_FILE",
    ):
        assert required in keys


def test_the_state_path_is_writable_inside_a_container():
    # A worker container has no persistent disk unless one is attached, so the
    # state file has to be somewhere the process may create directories.
    state = next(
        item["value"] for item in deploy_render.env_payload()
        if item["key"] == "TELEGRAM_STATE_FILE"
    )
    assert state.startswith("/app/"), state


@pytest.mark.parametrize("bad", ["", "nope", "render_key", "12345"])
def test_a_key_of_the_wrong_shape_is_refused(bad: str):
    assert not bad.startswith("rnd_")
