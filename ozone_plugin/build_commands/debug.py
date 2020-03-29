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
from debugtools import print_stack
import tornado.template as template

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
        print_stack()
        log.error(f"{e}")
        exit(1)
    
    return None

def add_project_file(arch, target):
    project_load = [
        f'Project.AddPathSubstitute ("{os.path.abspath(os.getcwd())}", "$(ProjectDir)");',
    ]

    definition = os.path.join(arch['path'], arch['module'], arch['definition'])
    device = cmake_get_variable(definition, "DEVICE")
    cpu = cmake_get_variable(definition, "CPU")

    cpu_map = {}
    cpu_svd = {}
    cpu_freertos = {}
    device_svd = {}

    cpu_map['cortex-m0plus'] = "Cortex-M0+"
    cpu_svd['cortex-m0plus'] = "Cortex-M0"
    cpu_freertos['cortex-m0plus'] = "CM0"
    device_svd['samd21g18au'] = "ATSAMD51G18A"
    
    if cpu not in cpu_map:
        low.warning(f"No correspondance defined for device {cpu}")
        return False
    
    if device not in device_svd:
        low.warning(f"No correspondance defined for device {device}")
        return False
    
    project_load.append(f'Project.SetDevice ("{cpu_map[cpu]}");') 
    project_load.append('Project.SetHostIF ("USB", "");')
    project_load.append('Project.SetTargetIF ("SWD");')
    project_load.append('Project.SetTIFSpeed ("12 MHz");')

    project_load.append(f'Project.AddSvdFile ("{os.path.abspath(plugin_path)}/ozone/Config/CPU/{cpu_svd[cpu]}.svd");')
    project_load.append(f'Project.AddSvdFile ("{os.path.abspath(plugin_path)}/ozone/Config/Peripherals/{device_svd[device]}.svd");')
    project_load.append(f'Project.SetOSPlugin("FreeRTOSPlugin_{cpu_freertos[cpu]}");')
    project_load.append(f'File.Open ("$(ProjectDir)/output/{target["name"]}/bin/firmware.elf");')
    
    # write CMakeLists.txt from template
    try:
        loader = template.Loader(os.path.join(plugin_path, 'template'), autoescape=None)
        cmakelists = loader.load("project.jdebug").generate(
            project_load="\n".join(project_load)
        )
        with open("project.jdebug", "w") as f:
            f.write(cmakelists.decode("utf-8"))
    except Exception as e:
        print_stack()
        log.error(f"{e}")
        exit(1)

    return True

def project_debug(args, config, **kwargs):
    global plugin_path

    try:
        # load project configuration
        config = load_project(config)
        if not config:
            log.error("Current path is not a project")
            exit(1)
    except Exception as e:
        print_stack()
        log.error(f"{e}")
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
        print_stack()
        log.error(f"{e}")
        return

    # load dependencies
    if build_config.config['build']['debug']:
        dependencies = dependency.load_dev_dependencies(config, target)
    else:
        dependencies = dependency.load_dependencies(config, target)

    # get device
    arch = get_arch(config, target, dependencies)

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

        # add CMakeLists.txt
        if add_project_file(arch, target):
            commandline += [
                '-project', f'project.jdebug'
            ]

        commandline += ['&']
        log.info(" ".join(commandline))
        #subprocess.check_call(commandline)
        os.system(" ".join(commandline))        
    except Exception as e:
        print_stack()
        log.error(f"{e}")
        exit(1)
        