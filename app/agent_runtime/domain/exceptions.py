class PreviewError(ValueError):
    """Confirmation no longer matches the current model request."""


class InputLimitError(PreviewError):
    """Confirmed material exceeds the gateway policy."""
