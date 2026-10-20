"""Optional desktop surfaces for VoxFlow.

The package is importable on headless systems; GTK is loaded only by the
settings window entry point.
"""

from .models import SettingsCommandResult, SettingsView

__all__ = ["SettingsCommandResult", "SettingsView"]
