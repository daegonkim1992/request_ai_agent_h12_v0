"""개발 서버: python -m h12"""

import os

from h12.api import create_app

if __name__ == "__main__":
    create_app().run(
        host=os.getenv("H12_HOST", "127.0.0.1"),
        port=int(os.getenv("H12_PORT", "8512")),
        debug=os.getenv("H12_DEBUG", "0") == "1",
    )
