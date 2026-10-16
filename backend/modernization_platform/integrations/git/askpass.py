"""Cross-platform Git askpass script for secure credential injection.

Invoked by Git when authentication is required. Reads credentials from
process-private environment variables without command-line exposure.
"""

import os
import sys


def main() -> None:
    try:
        prompt = sys.argv[1].lower() if len(sys.argv) > 1 else ""
        if "username" in prompt:
            val = os.environ.get("GIT_USERNAME", "x-access-token")
        else:
            val = os.environ.get("GIT_PASSWORD") or os.environ.get("GIT_TOKEN", "")
        sys.stdout.write(val + "\n")
        sys.stdout.flush()
    except Exception as exc:
        sys.stderr.write(f"askpass error: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
