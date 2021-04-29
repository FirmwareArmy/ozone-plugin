from army.api.command import get_army_parser
import sys
import os

parser = get_army_parser()
if parser.find_group("build") is None:
    parser.add_group(name="build", help="Build Commands", chain=True)

import debug
