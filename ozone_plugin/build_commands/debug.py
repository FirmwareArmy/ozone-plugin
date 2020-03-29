import shutil
import os
import extargparse
import sys
from config import Config
from config import load_project
from command import Command
import ozone_plugin
from log import log
import dependency
import re
import subprocess 

def to_relative_path(path):
    home = os.path.expanduser("~")
    abspath = os.path.abspath(path)
    if abspath.startswith(home):
        path = abspath.replace(home, "~", 1)
    cwd = os.path.abspath(os.path.expanduser(os.getcwd()))
    if abspath.startswith(cwd):
        path = os.path.relpath(abspath, cwd)
    return path

plugin_path = to_relative_path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

def init_parser(parentparser, config):
    parser = parentparser.add_parser('debug', help='debug firmware')
    parser.set_defaults(func=project_debug)

    # add army default commands
    subparser = parser.add_subparsers(metavar='COMMAND', title=None, description=None, help=None, parser_class=extargparse.ArgumentParser, required=False)
    
    flash_command = Command('debug', ozone_plugin.build_commands.debug, subparser, {})
    flash_command.register()
    flash_command.add_parent('flash', config)


def locate_ozone():
    global plugin_path

    # search for ozone folder
    ozone_path = os.path.join('ozone', 'Ozone')
    if os.path.exists(os.path.join(plugin_path, ozone_path))==False:
        log.error(f"ozone was not found inside '{plugin_path}', check plugin installation")
        exit(1)

    return ozone_path

def get_arch(config, target, dependencies):
    if 'arch' not in target:
        log.error(f"arch not defined for target '{target['name']}'")
        exit(1)
    target_arch = target['arch']
    
    res = None
    found_dependency = None
    for dependency in dependencies:
        dependency_arch = dependency['config'].arch()
        for arch in dependency_arch:
            if arch==target_arch:
                if found_dependency is not None:
                    log.error(f"arch from {dependency['module']} already defined in {found_dependency['module']}")
                    exit(1)
                res = dependency_arch[arch]
                res['path'] = dependency['path']
                res['module'] = dependency['module']
                found_dependency = dependency
                if 'definition' not in res:
                    log.error(f"missing arch definition from {dependency['module']}")
                    exit(1)

    if res is None:
        log.error(f"no configuration available for arch '{target_arch}'")
        exit(1)
    
    return res

def cmake_get_variable(path, name):
    log.debug(f"open {path}")
    try:
        with open(path, "r") as file:
            line = file.readline()
            while(line):
                name_search = re.search('set\((.*) (.*)\)', line, re.IGNORECASE)

                if name_search:
                    if name_search.group(1)==name:
                        return name_search.group(2)
    
                line = file.readline()
            
    except Exception as e:
        log.error(f"{e}")
        exit(1)
    
    return None
    
def project_debug(args, config, **kwargs):
    global plugin_path

    try:
        # load project configuration
        config = load_project(config)
        if not config:
            log.error("Current path is not a project")
            exit(1)
    except Exception as e:
        log.error(f"{e}")
        print_stack()
        return

    # get target config
    target = None
    if config.command_target():
        # if target is specified in command line then it is taken by default
        log.info(f"Search command target: {config.command_target()}")
        
        # get target config
        for t in config.targets():
            if t==config.command_target():
                target = config.targets()[t]
                target['name'] = t
        if target is None:
            log.error(f"Target not found '{config.command_target()}'")
            exit(1)
    elif config.default_target():
        log.info(f"Search default target: {config.default_target()}")
        for t in config.targets():
            if t==config.default_target():
                target = config.targets()[t]
                target['name'] = t
        if target is None:
            log.error(f"Target not found '{config.default_target()}'")
            exit(1)
    else:
        log.error(f"No target specified")
        exit(1)
    log.debug(f"target: {target}")

    build_path = os.path.join(config.output_path(), target["name"])
    log.debug(f"build path: {build_path}")
    
    try:
        # load built firmware configuration
        build_config = Config(None, os.path.join(build_path, 'army.toml'))
        build_config.load()
    except Exception as e:
        log.error(f"{e}")
        print_stack()
        return

    log.info("Debug $device with Ozone")
# 
    hex_file = os.path.join(build_path, "bin/firmware.hex")
    binfile = os.path.join(build_path, "bin/firmware.bin")
# 
    ozoneexe = locate_ozone()
    log.debug(f"ozone path: {ozoneexe}")
    
    try:
        commandline = [
            f"{os.path.join(plugin_path, ozoneexe)}",
        ]
        
        log.info(" ".join(commandline))
        subprocess.check_call(commandline)
    except Exception as e:
        log.error(f"{e}")
        exit(1)
        