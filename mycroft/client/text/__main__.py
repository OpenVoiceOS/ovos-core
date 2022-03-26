"""
This module contains back compat imports only
Text client moved into ovos_cli_client package
"""
from ovos_cli_client.__main__ import main


if __name__ == "__main__":
    main()
