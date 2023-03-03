"""
This module contains back compat imports only
Text client moved into ovos_cli_client package
"""
from ovos_cli_client.__main__ import main
from ovos_utils.log import init_service_logger


if __name__ == "__main__":
    init_service_logger("cli")
    main()
