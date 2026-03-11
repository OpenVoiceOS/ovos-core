#!/usr/bin/env python3
"""
script used for healthchecks by docker containers
SERVICE_NAME env var MUST be set
"""
import os
import sys
from ovos_bus_client import MessageBusClient
from ovos_bus_client.message import Message

NAMESPACE = os.environ.get("OVOS_NAMESPACE") or "mycroft"
SERVICE_NAME = os.environ.get("OVOS_SERVICE_NAME") or "voice"
CLIENT = "docker"  # metadata for message.context

if not SERVICE_NAME:
    print("OVOS_SERVICE_NAME environment variable not set, can not perform healthcheck")
    sys.exit(1)

client = MessageBusClient()
client.run_in_thread()


def check_svc_readiness():
    ready_msg = Message(
        f"{NAMESPACE}.{SERVICE_NAME}.is_ready",
        context={"source": CLIENT,
                 "destination": SERVICE_NAME,
                 "session": {"session_id": "healthcheck"}},
    )
    resp = client.wait_for_response(ready_msg)
    if resp:
        if resp.data.get("status"):
            print("Healthcheck OK")
            sys.exit(0)

    print("Healthcheck FAILED")
    sys.exit(1)


check_svc_readiness()

client.close()
