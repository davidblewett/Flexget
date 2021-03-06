#!/usr/bin/python

import os
import sys
import logging
from flexget import logger
from flexget.options import CoreOptionParser
from flexget.ui.options import UIOptionParser
from flexget.ui.manager import UIManager
import flexget.ui.webui
from flexget import plugin

log = logging.getLogger('main')


def main():
    """Main entry point for FlexGet UI"""

    logger.initialize()

    # The core plugins need a core parser to add their options to
    core_parser = CoreOptionParser()
    plugin.load_plugins(core_parser)

    # Use the ui options parser to parse the cli
    parser = UIOptionParser(core_parser)
    options = parser.parse_args()[0]
    try:
        manager = UIManager(options, core_parser)
    except IOError, e:
        # failed to load config
        log.critical(e.message)
        logger.flush_logging_to_console()
        sys.exit(1)

    log_level = logging.getLevelName(options.loglevel.upper())
    logger.start(os.path.join(manager.config_base, 'flexget.log'), log_level)

    flexget.ui.webui.start(manager)
