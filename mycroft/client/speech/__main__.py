"""
This module contains back compat imports only
Speech client moved into mycroft.listener module
"""

from ovos_listener.service import SpeechService, on_error, on_stopping, on_ready
from ovos_config.locale import setup_locale
from ovos_utils import wait_for_exit_signal
from ovos_utils.process_utils import reset_sigint_handler, PIDLock
from ovos_utils.log import init_service_logger

# backwards compat - unused but remain available for import just in case
from ovos_listener.service import RecognizerLoop


def main(ready_hook=on_ready, error_hook=on_error, stopping_hook=on_stopping,
         watchdog=lambda: None):
    init_service_logger("voice")
    reset_sigint_handler()
    PIDLock("voice")
    setup_locale()
    service = SpeechService(on_ready=ready_hook,
                            on_error=error_hook,
                            on_stopping=stopping_hook,
                            watchdog=watchdog)
    service.daemon = True
    service.start()
    wait_for_exit_signal()


if __name__ == "__main__":
    main()
