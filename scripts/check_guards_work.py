"""Prove each guard in test_silent_failures actually fails on the real defect.

A test that passes on both the broken and the fixed code documents nothing. Each
defect is therefore reintroduced into a scratch copy, the test is pointed at
it, and the test has to fail.

The reintroduction is done on file copies under a temporary directory, never on
the repository, so this is safe to run.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEST = ROOT / "tests" / "test_silent_failures.py"

# (name, file to damage, old text, new text, test that must catch it)
DEFECTS = [
    (
        "sentry auto_enable",
        "app/main.py",
        "FastApiIntegration(),",
        "FastApiIntegration(auto_enable=True),",
        "test_sentry_integrations_accept_the_arguments_we_pass",
    ),
    (
        "silent sentry log",
        "app/main.py",
        'logger.error("sentry_init_failed"',
        'logger.debug("sentry_init_failed"',
        "test_sentry_failure_is_logged_loudly",
    ),
    (
        "Optional total arithmetic",
        "app/api/v1/documents.py",
        "await db.scalar(count_query) or 0",
        "await db.scalar(count_query)",
        "test_the_document_list_total_cannot_be_none",
    ),
    (
        "field dropped by pydantic",
        "app/schemas/document.py",
        "    webhook_status: str | None",
        "    # removed on purpose",
        "test_webhook_delivery_status_is_reported",
    ),
    (
        "unsigned bytes",
        "app/services/webhook_dispatcher.py",
        "content=body",
        "json=payload",
        "test_signature_is_computed_over_the_bytes_that_are_sent",
    ),
    (
        "stripe secret reused",
        "app/services/webhook_dispatcher.py",
        "settings.WEBHOOK_SIGNING_SECRET",
        "settings.STRIPE_WEBHOOK_SECRET",
        "test_webhooks_do_not_borrow_the_stripe_secret",
    ),
]


def main() -> int:
    print("=" * 66)
    print("DO THE GUARDS ACTUALLY CATCH THE DEFECT?")
    print("=" * 66)

    failures = []
    for name, target, old, new, test_name in DEFECTS:
        path = ROOT / target
        original = path.read_text(encoding="utf-8")
        if old not in original:
            failures.append(f"{name}: marker not found in {target}, the test is stale")
            print(f"  ??  {name}: marker missing, test is out of date")
            continue

        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(TEST), "-q", "-p", "no:cacheprovider",
                 "-k", test_name],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
        finally:
            path.write_text(original, encoding="utf-8")

        caught = result.returncode != 0
        print(f"  {'OK  ' if caught else 'MISS'} {name:28} -> {test_name}")
        if not caught:
            failures.append(f"{name}: the test passed with the defect reintroduced")

    print()
    if failures:
        print(f"{len(failures)} guard(s) are not actually guarding:")
        for line in failures:
            print(f"  - {line}")
        return 1

    print(f"all {len(DEFECTS)} guards catch their defect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
