"""Regression test for the shutdown-hang bug where the SkillManager's
messagebus client is never closed, leaving the websocket dispatch thread
alive to race against interpreter teardown and raise
`RuntimeError: cannot schedule new futures after shutdown`
(https://github.com/OpenVoiceOS/ovos-core - shutdown hang / SIGKILL after
60s on `systemctl restart`).
"""
import socket
import time
import unittest
from unittest.mock import MagicMock, patch

from ovos_bus_client import MessageBusClient


class TestMainShutdown(unittest.TestCase):

    @patch('ovos_core.__main__.setup_locale')
    @patch('ovos_core.__main__.init_service_logger')
    @patch('ovos_core.__main__.wait_for_exit_signal')
    @patch('ovos_core.__main__.SkillManager')
    @patch('ovos_core.__main__.MessageBusClient')
    def test_bus_is_closed_before_main_returns(self, mock_bus_cls, mock_manager_cls,
                                               mock_wait, mock_init_logger,
                                               mock_setup_locale):
        """After the exit signal arrives and the skill manager has been
        shut down, `main()` must close the bus's websocket connection and
        join the receiver thread so the background dispatch thread stops
        before the interpreter starts tearing down. Without this, the
        daemon thread spawned by `bus.run_in_thread()` keeps calling
        `emitter.emit()` -> `executor.submit()` and can lose the race with
        the executor/interpreter shutdown, raising `RuntimeError: cannot
        schedule new futures after shutdown` and hanging the process until
        SIGKILL. `bus.close()` alone is fire-and-forget and does not wait
        for the thread to exit, so `main()` must also join it with a
        bounded timeout.
        """
        from ovos_core.__main__ import main

        mock_bus = MagicMock()
        mock_bus_thread = MagicMock()
        mock_bus.run_in_thread.return_value = mock_bus_thread
        mock_bus_cls.return_value = mock_bus
        mock_manager = MagicMock()
        mock_manager_cls.return_value = mock_manager

        main()

        # shutdown must happen before the bus is closed, and both must
        # happen before main() returns
        mock_manager.shutdown.assert_called_once()
        mock_bus.close.assert_called_once()

        # the receiver thread returned by `bus.run_in_thread()` must be
        # joined with a bounded timeout after `bus.close()`, so `main()`
        # doesn't block forever if the thread never stops
        mock_bus_thread.join.assert_called_once()
        join_args, join_kwargs = mock_bus_thread.join.call_args
        timeout = join_kwargs.get('timeout', join_args[0] if join_args else None)
        self.assertIsNotNone(timeout)
        self.assertGreater(timeout, 0)


class TestMainShutdownRealSocket(unittest.TestCase):
    """The mocked test above only proves `main()` calls `bus.close()` then
    `bus_thread.join(timeout=...)` in the right order — a mocked
    `Thread.join()` always "succeeds" instantly, so it cannot detect
    whether a REAL receiver thread stuck in `on_error()`'s reconnect
    backoff actually exits. This test drives that path with a real
    `MessageBusClient` pointed at a closed local port (nothing ever
    accepts the connection, so the client sits in the reconnect loop
    exactly like it would against a bus that dropped mid-shutdown), then
    reproduces `main()`'s own `bus.close(); bus_thread.join(timeout=3)`
    shutdown sequence directly and asserts the thread actually exits.
    """

    @staticmethod
    def _closed_port() -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()  # nothing listens on this port once closed
        return port

    def test_close_and_join_stops_reconnecting_bus_thread(self):
        bus = MessageBusClient(host="127.0.0.1", port=self._closed_port())
        bus.retry = 0.1  # keep the reconnect backoff short for the test
        bus_thread = bus.run_in_thread()
        time.sleep(0.3)  # let it fail to connect and enter the backoff

        # main()'s own shutdown sequence:
        bus.close()
        bus_thread.join(timeout=3)

        self.assertFalse(bus_thread.is_alive())


if __name__ == '__main__':
    unittest.main()
