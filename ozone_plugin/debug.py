from army.api.click import verbose_option 
from army.api.debugtools import print_stack
from army.api.log import log, get_log_level
from army import cli, build
from army.api.package import load_project_packages
import click
import subprocess
import os
import tornado.template as template
import sys

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

plugin_path = to_relative_path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

@build.command(name='debug', help='Debug firmware')
@verbose_option()
@click.pass_context
def debug(ctx, **kwargs):
    global plugin_path

    log.info(f"debug")
    
    # load configuration
    config = ctx.parent.config

    # load project
    project = ctx.parent.project
    if project is None:
        print(f"no project found", sys.stderr)
        exit(1)
    
    # get target config
    target = ctx.parent.target
    target_name = ctx.parent.target_name
    if target is None:
        print(f"no target specified", file=sys.stderr)
        exit(1)

    output_path = 'output'

    # set build path
    build_path = os.path.join(output_path, target_name)
    log.info(f"build_path: {build_path}")
    
    # load dependencies
    try:
        dependencies = load_project_packages(project, target_name)
        log.debug(f"dependencies: {dependencies}")
    except Exception as e:
        print_stack()
        print(f"{e}", file=sys.stderr)
        clean_exit()
 
    # set build arch 
    arch, arch_pkg = get_arch(config, target, dependencies)
    log.debug(f"arch: {arch}")

    device = target.arch

    log.info(f"Debug {device} with Ozone")
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
        if add_project_file(arch, target, target_name):
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
        print(f"no configuration available for arch '{target.arch}'", file=sys.stderr)
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

def add_project_file(arch, target, target_name):
    project_load = [
        f'Project.AddPathSubstitute ("{os.path.abspath(os.getcwd())}", "$(ProjectDir)");',
    ]

    if arch.cpu is None:
        cpu = target.arch
    else:
        cpu = arch.cpu

    cpu_map = {
        }
    cpu_svd = {
        'Cortex-M0+': "Cortex-M0"
        }
    cpu_freertos = {
        'Cortex-M0+': "CM0"
        }
    device_svd = {}

    
#     if cpu not in cpu_map:
#         print(f"No correspondance defined for device {cpu}", file=sys.stderr)
#         return False
    if cpu in cpu_map:
        project_load.append(f'Project.SetDevice ("{cpu_map[cpu]}");') 
    else:
        project_load.append(f'Project.SetDevice ("{cpu}");') 
        
    project_load.append('Project.SetHostIF ("USB", "");')
    project_load.append('Project.SetTargetIF ("SWD");')
    project_load.append('Project.SetTIFSpeed ("12 MHz");')

    if cpu in cpu_svd:
        project_load.append(f'Project.AddSvdFile ("{os.path.abspath(plugin_path)}/ozone/Config/CPU/{cpu_svd[cpu]}.svd");')
    else:
        project_load.append(f'Project.AddSvdFile ("{os.path.abspath(plugin_path)}/ozone/Config/CPU/{cpu}.svd");')

    if cpu in device_svd:        
        project_load.append(f'Project.AddSvdFile ("{os.path.abspath(plugin_path)}/ozone/Config/Peripherals/{device_svd[device]}.svd");')
    else:
        project_load.append(f'Project.AddSvdFile ("{os.path.abspath(plugin_path)}/ozone/Config/Peripherals/{cpu}.svd");')
        
    if cpu in cpu_freertos:
        project_load.append(f'Project.SetOSPlugin("FreeRTOSPlugin_{cpu_freertos[cpu]}");')
    else:
        log.warning(f"No freertos correspondance defined for device {cpu}")
    
    project_load.append(f'File.Open ("$(ProjectDir)/output/{target_name}/bin/firmware.elf");')
    
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
        