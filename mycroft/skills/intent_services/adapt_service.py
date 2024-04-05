# Copyright 2020 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""An intent parsing service using the Adapt parser."""
from adapt.context import ContextManagerFrame
from adapt.engine import IntentDeterminationEngine
from ovos_workshop.intents import IntentBuilder, Intent
from ovos_core.intent_services.adapt_service import ContextManager, AdaptService


class AdaptIntent(IntentBuilder):
    def __init__(self, name=''):
        super().__init__(name)
