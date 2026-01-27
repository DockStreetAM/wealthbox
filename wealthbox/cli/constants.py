"""Exit codes and constants for the WealthBox CLI."""

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    GENERAL_ERROR = 1
    AUTH_ERROR = 2
    NOT_FOUND = 3
    VALIDATION_ERROR = 4
    RATE_LIMIT = 5
    NETWORK_ERROR = 6
    READONLY_BLOCKED = 10
