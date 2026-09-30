"""Keep API keys and credentials out of the logs.

Anything logged - a message, its arguments, or a traceback - passes through `redact_secrets`
before it is formatted, so a key that ends up in an exception message, a request dump or a
stray f-string is masked in every handler. The literal value of ANTHROPIC_API_KEY is masked
too, whatever it looks like.
"""
import logging
import os
import re
import traceback

_MASK = "[redacted]"

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"),                      # Anthropic keys
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),                        # other provider-style secret keys
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]{8,}"),         # bearer tokens
]
# key: value / key=value forms for credential-bearing names; keep the name, mask the value
_NAMED = re.compile(
    r"""(?ix)
    (?P<name>x-api-key|api[_-]?key|authorization|anthropic_api_key|auth[_-]?token)
    (?P<sep>["']?\s*[:=]\s*["']?)
    (?P<value>(?!%)[^\s"',}]+)
    """
)


def redact_secrets(text) -> str:
    out = str(text)
    literal = os.environ.get("ANTHROPIC_API_KEY", "")
    if len(literal) >= 8:
        out = out.replace(literal, _MASK)
    for pattern in _PATTERNS:
        out = pattern.sub(_MASK, out)
    return _NAMED.sub(lambda m: f"{m.group('name')}{m.group('sep')}{_MASK}", out)


def _mask_args(args):
    """Mask secrets inside the arguments while keeping their count and types.

    Formatters such as uvicorn's AccessFormatter unpack `record.args` positionally, and
    `%d` needs a number, so the tuple must keep its shape. Only strings (and other objects
    whose text carries a secret) are replaced.
    """
    def one(value):
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        if isinstance(value, str):
            return redact_secrets(value)
        return value if redact_secrets(value) == str(value) else redact_secrets(value)

    if isinstance(args, tuple):
        return tuple(one(v) for v in args)
    if isinstance(args, dict):
        return {k: one(v) for k, v in args.items()}
    return args


def _redact_record(record) -> None:
    message = record.getMessage()
    redacted = redact_secrets(message)
    if redacted != message:
        # keep the record's structure; flatten only if in-place masking is not enough
        record.msg = redact_secrets(record.msg) if isinstance(record.msg, str) else record.msg
        record.args = _mask_args(record.args)
        try:
            ok = record.getMessage() == redacted
        except Exception:
            ok = False
        if not ok:
            record.msg, record.args = redacted, ()
    if record.exc_info and not record.exc_text:
        record.exc_text = redact_secrets("".join(traceback.format_exception(*record.exc_info)).rstrip("\n"))


_installed = False


def install_secret_redaction() -> None:
    """Redact every log record as it is created (idempotent).

    A record factory rather than a handler filter, so it covers every logger and handler,
    including ones configured later by the server. The traceback is rendered here and
    redacted, so an exception message cannot carry a key into the log.
    """
    global _installed
    if _installed:
        return
    _installed = True
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        try:
            _redact_record(record)
        except Exception:  # logging must never fail because redaction did
            pass
        return record

    logging.setLogRecordFactory(factory)
