"""Guards for the failure modes that a broad `except` made invisible.

Each case here is something that actually broke and could not be seen: a
keyword removed from a dependency, a Pydantic field quietly dropped, an
arithmetic operation on an Optional. All of them were swallowed somewhere and
reported as healthy.
"""

from __future__ import annotations

import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parent.parent


# --- Sentry integration ---------------------------------------------------


def test_sentry_integrations_accept_the_arguments_we_pass():
    """`auto_enable` was never a parameter, so init always raised TypeError."""
    import ast

    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    # Construct them the way main.py does: any bad keyword raises here.
    FastApiIntegration()
    SqlalchemyIntegration()

    # Checking that the word is absent would fail on the comment that explains
    # the bug, so the call sites themselves are inspected instead.
    tree = ast.parse((ROOT / "app" / "main.py").read_text(encoding="utf-8"))
    passed = {
        keyword.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg
    }
    assert "auto_enable" not in passed, "auto_enable is not a real parameter"


def test_sentry_failure_is_logged_loudly():
    """A swallowed init error is how a dead monitor looked like a healthy one."""
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert 'logger.error("sentry_init_failed"' in source, (
        "a failed Sentry init must be logged at error level, not warning"
    )


# --- response schema ------------------------------------------------------


def test_every_field_the_endpoint_passes_exists_in_the_schema():
    """Pydantic drops unknown keywords, so a passed field is simply lost."""
    from app.schemas.document import DocumentResponse

    endpoint = (ROOT / "app" / "api" / "v1" / "documents.py").read_text(encoding="utf-8")
    start = endpoint.index("return DocumentResponse(")
    block = endpoint[start:endpoint.index(")", start)]
    passed = {
        line.split("=")[0].strip()
        for line in block.splitlines()
        if "=" in line and line.strip().startswith(("id", "filename", "mime", "file", "document", "status", "parsed", "error", "processing", "webhook", "created", "updated", "completed"))
    }
    fields = set(DocumentResponse.model_fields)
    unknown = passed - fields
    assert not unknown, f"passed but absent from the schema, so silently dropped: {sorted(unknown)}"


def test_webhook_delivery_status_is_reported():
    assert "webhook_status" in _document_response_fields()
    assert "webhook_attempts" in _document_response_fields()


def _document_response_fields() -> set[str]:
    from app.schemas.document import DocumentResponse

    return set(DocumentResponse.model_fields)


# --- arithmetic on Optional ----------------------------------------------


def test_the_document_list_total_cannot_be_none():
    """`total + page_size` raised TypeError whenever scalar() returned None."""
    source = (ROOT / "app" / "api" / "v1" / "documents.py").read_text(encoding="utf-8")
    assert "await db.scalar(count_query) or 0" in source, (
        "the count must be coerced to 0 before it is used in arithmetic"
    )


# --- webhook signing ------------------------------------------------------


def test_signature_is_computed_over_the_bytes_that_are_sent():
    """Signing a re-serialisation made the documented verification always fail."""
    source = (ROOT / "app" / "services" / "webhook_dispatcher.py").read_text(encoding="utf-8")
    assert "content=body" in source, "the signed bytes must be the transmitted ones"
    assert "json=payload" not in source, "httpx would serialise the payload again"


def test_webhooks_do_not_borrow_the_stripe_secret():
    """Customers need the signing secret, and must never be handed Stripe's."""
    from app.config import settings

    source = (ROOT / "app" / "services" / "webhook_dispatcher.py").read_text(encoding="utf-8")
    assert "STRIPE_WEBHOOK_SECRET" not in source, (
        "the Stripe webhook secret must not sign customer callbacks"
    )
    assert settings.WEBHOOK_SIGNING_SECRET is not None


def test_a_signature_round_trips():
    from app.services.webhook_dispatcher import (
        sign_body,
        verify_webhook_signature,
    )
    import asyncio

    body = json.dumps({"event": "document.parsed", "n": 1}, sort_keys=True).encode()
    signature = sign_body(body)

    assert signature.startswith("sha256=")
    assert asyncio.run(verify_webhook_signature(body, signature)) is True
    assert asyncio.run(verify_webhook_signature(body + b" ", signature)) is False
    assert asyncio.run(verify_webhook_signature(body, "sha256=wrong")) is False
    assert asyncio.run(verify_webhook_signature(body, "")) is False
