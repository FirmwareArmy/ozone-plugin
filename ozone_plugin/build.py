import shutil
import os
import extargparse
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import ozone_plugin.build_commands.debug

def init_parser(parentparser, config):
    group = None
    for action in parentparser._choices_actions:
        if hasattr(action, 'id') and action.id=='build':
            group = action

    # init sub parsers
    ozone_plugin.build_commands.debug.init_parser(group, config)

