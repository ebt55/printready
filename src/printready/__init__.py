"""printready: check and fix die-cut sticker artwork against a printer's paraphrased rules."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("printready")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0"
