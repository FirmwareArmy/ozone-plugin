from army.api.click import verbose_option 
from army.api.debugtools import print_stack
from army.api.log import log, get_log_level
from army.army import cli, build
import click
import subprocess
import os
import tornado.template as template

# import shutil
# import extargparse
# import sys
# from config import Config
# from config import load_project
# from command import Command
# import ozone_plugin
# from log import log
# import dependency
# import re
# import subprocess 
# from debugtools import print_stack

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

@build.command(name='debug', help='Debug firmware')
@verbose_option()
@click.pass_context
def debug(ctx, **kwargs):
    global plugin_path

    log.info(f"debug")
    
    # load configuration
    config = ctx.parent.config

    # load project
    project = None
    if os.path.exists('army.toml'):
        try:
            # load project configuration
            project = load_project()
        except Exception as e:
            print_stack()
            print(f"army.toml: {e}", sys.stderr)
            exit(1)
    if project is None:
        print(f"no project found", sys.stderr)
        exit(1)

    # get target config
    target = None
    target_name = None
    if config.target.value()!="":
        # if target is specified in command line then it is taken by default
        log.info(f"Search command target: {config.target}")
        
        # get target config
        for t in project.target:
            if t==config.target.value():
                target = project.target[t]
                target_name = t
        if target is None:
            print(f"{config.target}: target not found", file=sys.stderr)
            exit(1)
    elif project.default_target:
        log.info(f"Search default target: {project.default_target}")
        for t in project.target:
            if t==project.default_target:
                target = project.target[t]
                target_name = t
        if target is None:
            print(f"{project.default_target}: target not found", file=sys.stderr)
            exit(1)
    else:
        print(f"no target specified", file=sys.stderr)
        exit(1)
    log.debug(f"target: {target}")

    # set build path
    build_path = os.path.join(output_path, target_name)
    log.info(f"build_path: {build_path}")
    
    # load dependencies
    dependencies = load_project_packages(project, target_name)
    log.debug(f"dependencies: {dependencies}")

    # set build arch 
    arch, arch_pkg = get_arch(config, target, dependencies)
    log.debug(f"arch: {arch}")

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

def locate_ozone():
    global plugin_path

    # search for ozone folder
    ozone_path = os.path.join('ozone', 'Ozone')
    if os.path.exists(os.path.join(plugin_path, ozone_path))==False:
        log.error(f"ozone was not found inside '{plugin_path}', check plugin installation")
        exit(1)

    return ozone_path

def get_arch(config, target, dependencies):
    target_arch = target.arch
    
    res = None
    found_dependency = None
    for dependency in dependencies:
        for arch in dependency.arch:
            if arch==target.arch:
                if found_dependency is not None:
                    log.error(f"arch '{arch}' redefinition from'{found_dependency[1].name}' in {dependency.name}")
                    exit(1)
                found_dependency = (dependency.arch[arch], dependency)
                if dependency.arch[arch].definition=="":
                    log.error(f"missing definition in arch '{arch}' from '{dependency.name}'")
                    exit(1)

    if found_dependency is None:
        log.error(f"no configuration available for arch '{target.arch}'")
        exit(1)
    
    return found_dependency

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
        