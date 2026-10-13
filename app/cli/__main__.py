"""Allow `python -m app.cli` to run the CLI."""
from app.cli import main

raise SystemExit(main())
