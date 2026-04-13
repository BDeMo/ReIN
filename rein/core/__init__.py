from .config import Settings, SettingsManager
from .conversation import Message, Conversation

# Harness imported lazily to avoid circular imports
def __getattr__(name):
    if name == "Harness":
        from .harness import Harness
        return Harness
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
