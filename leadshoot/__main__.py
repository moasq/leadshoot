"""`python -m leadshoot` - same entry as the `leadshoot` script.

The auto-opened live map is spawned this way (sys.executable -m leadshoot
serve ...) so it works in any install, including ephemeral uvx environments
where no console script is on PATH.
"""

from .cli import app

app()
