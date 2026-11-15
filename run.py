"""Single-command launcher for TLG SmartPrint."""

from __future__ import annotations

import os
import uvicorn


def main() -> None:
    host = os.environ.get("TLG_HOST", "127.0.0.1")
    port = int(os.environ.get("TLG_PORT", "8000"))
    print(f"TLG SmartPrint ishga tushmoqda: http://{host}:{port}")
    uvicorn.run("backend.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
