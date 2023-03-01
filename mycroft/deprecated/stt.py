# TODO add missing plugins!
from mycroft.listener.stt import *
from ovos_plugin_manager.templates.stt import STT, TokenSTT, GoogleJsonSTT, \
    StreamingSTT, StreamThread, BasicSTT, KeySTT

# for compat in case its being imported elsewhere
# TODO: This should really be deprecated as Selene STT is deprecated by Mycroft
from ovos_stt_plugin_server import OVOSHTTPServerSTT as MycroftSTT

