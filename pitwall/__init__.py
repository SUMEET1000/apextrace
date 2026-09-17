"""Pit Wall - F1 telemetry analysis library.

Pure pandas/numpy (plus plotly, in ``pitwall.viz`` only). This package must
never import a UI or web framework - no streamlit, no fastapi - so that every
analysis function stays unit-testable and can be lifted into a notebook.

That boundary is what made replacing the Streamlit frontend with React a
change to ``api/`` and ``frontend/`` alone: nothing in here knew which one was
in front of it.
"""

__version__ = "0.1.0"
