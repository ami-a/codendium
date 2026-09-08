"""Codendium.

Builds US Copyright Office compliant source-code deposit PDFs
(Compendium sections 721.6 and 721.7) from an arbitrary source tree.
"""

__version__ = "1.0.0"

#: Product name, shown to people: window title, PDF metadata, reports.
DISPLAY_NAME = "Codendium"

#: Storage key for the settings/history directory under %APPDATA%.
#: Deliberately NOT the display name - renaming it would orphan the
#: profiles and build history of anyone who already has them.
APP_NAME = "CopyrightDepositBuilder"
