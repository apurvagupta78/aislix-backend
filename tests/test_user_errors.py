from app.user_errors import (
    MSG_NO_PRODUCTS,
    MSG_SAMPLE_UNAVAILABLE,
    MSG_SCAN_FAILED,
    MSG_SERVER_ERROR,
    MSG_SERVICE_UNAVAILABLE,
    MSG_TIMEOUT,
    public_error_from_exception,
    sanitize_error_message,
)


def test_empty_products_openai_message_maps_to_no_products():
    raw = (
        "Make.com response did not include inventory or facings. Received keys: products, "
        "executive_summary. OpenAI returned an empty products list — try Reasoning effort Medium."
    )
    assert sanitize_error_message(raw) == MSG_NO_PRODUCTS


def test_openai_credits_exhausted_is_generic():
    raw = (
        "Make.com returned HTTP 500: OpenAI credits exhausted — add billing at "
        "platform.openai.com"
    )
    assert sanitize_error_message(raw) == MSG_SERVICE_UNAVAILABLE
    assert "openai" not in sanitize_error_message(raw).lower()
    assert "make" not in sanitize_error_message(raw).lower()


def test_make_http_500_is_generic():
    raw = "Make.com returned HTTP 500: Scenario failed"
    assert sanitize_error_message(raw) == MSG_SCAN_FAILED


def test_rate_limit_error_is_generic():
    raw = "RateLimitError: You exceeded your current quota"
    assert sanitize_error_message(raw) == MSG_SERVICE_UNAVAILABLE


def test_timeout_is_user_friendly():
    raw = "Make.com scan timed out after 120s."
    assert sanitize_error_message(raw) == MSG_TIMEOUT


def test_no_products_preserved():
    raw = "No products detected in this shelf image."
    assert sanitize_error_message(raw) == MSG_NO_PRODUCTS


def test_validation_errors_preserved():
    assert sanitize_error_message("Select a category before uploading your shelf photo.") == (
        "Select a category before uploading your shelf photo."
    )
    assert sanitize_error_message("Empty file upload.") == "Empty file upload."


def test_unknown_sample_sanitized():
    raw = "Unknown sample_id 'foo'. Known samples: toothpaste-a1l, lays-a1l"
    assert sanitize_error_message(raw) == MSG_SAMPLE_UNAVAILABLE


def test_demo_rate_limit_preserved():
    raw = "Daily demo scan limit reached (5 per day). Sign up for full access."
    assert sanitize_error_message(raw) == raw


def test_random_exception_defaults_generic():
    assert sanitize_error_message("some weird internal bug") == MSG_SCAN_FAILED


def test_public_error_from_exception():
    class FakeError(Exception):
        pass

    assert public_error_from_exception(FakeError("MAKE_SCAN_WEBHOOK_URL is not configured.")) == (
        MSG_SCAN_FAILED
    )


def test_server_context():
    assert sanitize_error_message("unexpected", context="server") == MSG_SERVER_ERROR
