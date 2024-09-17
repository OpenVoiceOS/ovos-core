"""
NOTE: this is dead code! do not use!
This file is only present to ensure backwards compatibility
in case someone is importing from here
This is only meant for 3rd party code expecting ovos-core
to be a drop in replacement for mycroft-core
"""

import collections
import csv
import re
from os import walk
from os.path import splitext, join
from ovos_backend_client.pairing import is_paired
from ovos_bus_client.apis.enclosure import EnclosureAPI
from mycroft.util.format import expand_options
from ovos_utils.log import LOG
from ovos_workshop.intents import munge_regex, to_alnum

RASPBERRY_PI_PLATFORMS = ('mycroft_mark_1', 'picroft', 'mycroft_mark_2pi')

ONE_MINUTE = 60


def skill_is_blacklisted(skill):
    """DEPRECATED: do not use, method only for api backwards compatibility
    Logs a warning and returns False
    """
    # this is a internal msm helper
    # it should have been private
    # cant remove to keep api compatibility
    # nothing in the wild should be using this
    LOG.warning("skill_is_blacklisted is an internal method and has been deprecated. Stop using it!")
    return False


class DevicePrimer:
    """DEPRECATED: this class has been fully deprecated, stop using it!
    Only here to provide public api compatibility but it does absolutely nothing!
    """

    def __init__(self, message_bus_client, config=None):
        self.bus = message_bus_client
        self.platform = "unknown"
        self.enclosure = EnclosureAPI(self.bus)
        self.backend_down = False

    @property
    def is_paired(self):
        return is_paired()

    def prepare_device(self):
        """Internet dependent updates of various aspects of the device."""
        LOG.warning("DevicePrimer has been deprecated!")


def read_vocab_file(path):
    """ Read voc file.

        This reads a .voc file, stripping out empty lines comments and expand
        parentheses. It returns each line as a list of all expanded
        alternatives.

        Args:
            path (str): path to vocab file.

        Returns:
            List of Lists of strings.
    """
    LOG.warning("read_vocab_file is deprecated! "
                "use SkillResources class instead")
    vocab = []
    with open(path, 'r', encoding='utf8') as voc_file:
        for line in voc_file.readlines():
            if line.startswith('#') or line.strip() == '':
                continue
            vocab.append(expand_options(line.lower()))
    return vocab


def load_regex_from_file(path, skill_id):
    """Load regex from file
    The regex is sent to the intent handler using the message bus

    Args:
        path:       path to vocabulary file (*.voc)
        skill_id:   skill_id to the regex is tied to
    """
    LOG.warning("read_regex_from_file is deprecated! "
                "use SkillResources class instead")
    regexes = []
    if path.endswith('.rx'):
        with open(path, 'r', encoding='utf8') as reg_file:
            for line in reg_file.readlines():
                if line.startswith("#"):
                    continue
                LOG.debug('regex pre-munge: ' + line.strip())
                regex = munge_regex(line.strip(), skill_id)
                LOG.debug('regex post-munge: ' + regex)
                # Raise error if regex can't be compiled
                try:
                    re.compile(regex)
                    regexes.append(regex)
                except Exception as e:
                    LOG.warning(f'Failed to compile regex {regex}: {e}')

    return regexes


def load_vocabulary(basedir, skill_id):
    """Load vocabulary from all files in the specified directory.

    Args:
        basedir (str): path of directory to load from (will recurse)
        skill_id: skill the data belongs to
    Returns:
        dict with intent_type as keys and list of list of lists as value.
    """
    LOG.warning("load_vocabulary is deprecated! "
                "use SkillResources class instead")
    vocabs = {}
    for path, _, files in walk(basedir):
        for f in files:
            if f.endswith(".voc"):
                vocab_type = to_alnum(skill_id) + splitext(f)[0]
                vocs = read_vocab_file(join(path, f))
                if vocs:
                    vocabs[vocab_type] = vocs
    return vocabs


def load_regex(basedir, skill_id):
    """Load regex from all files in the specified directory.

    Args:
        basedir (str): path of directory to load from
        bus (messagebus emitter): messagebus instance used to send the vocab to
                                  the intent service
        skill_id (str): skill identifier
    """
    LOG.warning("load_regex is deprecated! "
                "use SkillResources class instead")
    regexes = []
    for path, _, files in walk(basedir):
        for f in files:
            if f.endswith(".rx"):
                regexes += load_regex_from_file(join(path, f), skill_id)
    return regexes


def read_value_file(filename, delim):
    """Read value file.

    The value file is a simple csv structure with a key and value.

    Args:
        filename (str): file to read
        delim (str): csv delimiter

    Returns:
        OrderedDict with results.
    """
    LOG.warning("read_value_file is deprecated! "
                "use SkillResources class instead")
    result = collections.OrderedDict()

    if filename:
        with open(filename) as f:
            reader = csv.reader(f, delimiter=delim)
            for row in reader:
                # skip blank or comment lines
                if not row or row[0].startswith("#"):
                    continue
                if len(row) != 2:
                    continue

                result[row[0]] = row[1]
    return result


def read_translated_file(filename, data):
    """Read a file inserting data.

    Args:
        filename (str): file to read
        data (dict): dictionary with data to insert into file

    Returns:
        list of lines.
    """
    LOG.warning("read_translated_file is deprecated! "
                "use SkillResources class instead")
    if filename:
        with open(filename) as f:
            text = f.read().replace('{{', '{').replace('}}', '}')
            return text.format(**data or {}).rstrip('\n').split('\n')
    else:
        return None
