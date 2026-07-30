import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from launcher.app import UroborosApplication


def main():
    app = UroborosApplication()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
