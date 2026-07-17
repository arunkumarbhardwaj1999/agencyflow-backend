"""UTC timezone constant compatible with Python 3.10+.

``datetime.UTC`` exists only on Python 3.11+. PythonAnywhere and other hosts
often still run 3.10, so we expose the same name via ``timezone.utc``.
"""

from datetime import timezone

UTC = timezone.utc
