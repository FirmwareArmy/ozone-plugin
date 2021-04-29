from army.api.command import parser, group, command, option, argument
from army.api.debugtools import print_stack
from army.api.log import log, get_log_level
from army.api.package import load_project_packages, load_installed_package
from army.api.project import load_project
import os
import re
from subprocess import Popen, PIPE, STDOUT
import tornado.template as template
import sys


def to_relative_path(path):
    home = os.path.expanduser("~")
    abspath = os.path.abspath(path)
    if abspath.startswith(home):
        path = abspath.replace(home, "~", 1)
    cwd = os.path.abspath(os.path.expanduser(os.getcwd()))
    if abspath.startswith(cwd):
        path = os.path.relpath(abspath, cwd)
    return path

tools_path = to_relative_path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

@parser
@group(name="build")
@command(name='debug', help='Debug firmware with Ozone')
def debug(ctx, **kwargs):
    log.info(f"debug")
    
    # load configuration
    config = ctx.config

    # load profile
    profile = ctx.profile
    
    # load project
    project = ctx.project
    if project is None:
        print(f"no project found", sys.stderr)
        exit(1)

    # load dependencies
    try:
        dependencies = load_project_packages(project)
        log.debug(f"dependencies: {dependencies}")
    except Exception as e:
        print_stack()
        print(f"{e}", file=sys.stderr)
        clean_exit()

    # get arch from profile
    arch, arch_package = get_arch(profile, project, dependencies)

    # get target from profile
    target = get_target(profile)

    if arch.mpu is None:
        print("Missing mpu informations from arch", file=sys.stderr)
        exit(1)

    # set code build path
    output_path = 'output'
    build_path = os.path.join(output_path, arch.mpu)
    log.info(f"build_path: {build_path}")

    device = arch.mpu
    if device.startswith("ATSAMD"):
        device = device.replace("ATSAMD", "SAMD")

    log.info(f"Debug {device} with Ozone")
# 
    hex_file = os.path.join(build_path, "bin/firmware.hex")
    binfile = os.path.join(build_path, "bin/firmware.bin")
# 
    ozoneexe = locate_ozone(profile)
    log.debug(f"ozone path: {ozoneexe}")
    
    try:
        commandline = [
            f"{os.path.join(tools_path, ozoneexe)}",
        ]

        # add CMakeLists.txt
        if add_project_file(arch):
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

def get_target(profile):
    target = None
    
    if "target" in profile.data:
        target = profile.data["/target"]
    
    return target

def locate_jlink():
    global tools_path

    # search for jlink folder
    jlink_path = os.path.join('jlink', 'JLinkExe')
    if os.path.exists(os.path.join(tools_path, jlink_path))==False:
        log.error(f"jlink was not found inside '{tools_path}', check plugin installation")
        exit(1)

    return jlink_path

def locate_ozone(profile):
    global tools_path

    # search for jlink folder
    ozone_path = profile.data[f"/tools/ozone/path"] 
    if os.path.exists(os.path.expanduser(ozone_path))==False:
        print(f"{ozone_path}: path not found for Ozone", file=sys.stderr)
        exit(1)

    return ozone_path

def get_arch(profile, project, dependencies):
    # add arch
    try:
        arch = profile.data["/arch"]
        arch_name = profile.data["/arch/name"]
    except Exception as e:
        print_stack()
        log.error(e)
        print("No arch definition provided by profile", file=sys.stderr)
        exit(1)
    
    if 'name' not in arch:
        print("Arch name missing", file=sys.stderr)
        exit(1)

    package = None
    res_package = None
    if 'package' in arch:
        if 'version' in arch:
            package_version = arch['version']
        else:
            package_version = 'latest'
        package_name = arch['package']
        package = load_installed_package(package_name, package_version)
        res_package = package
    
    if package is None:
        package = project
    
    # search arch in found package
    archs = package.archs
    arch = next(arch for arch in archs if arch.name==arch_name)
    if arch is None:
        print(f"Arch {arch_name} not found in {package}", file=sys.stderr)
        exit(1)
    
    return arch, res_package

def add_project_file(arch):
    global tools_path
    
    project_load = [
        f'Project.AddPathSubstitute ("{os.path.abspath(os.getcwd())}", "$(ProjectDir)");',
    ]

    cpu = arch.cpu
    peripheral = arch.mpu

    cpu_map = {
        'cortex-m0plus': "Cortex-M0+",
        'cortex-m0': "Cortex-M0"
        }
    cpu_svd = {
        'cortex-m0plus': "Cortex-M0",
        'cortex-m0': "Cortex-M0"
        }
    cpu_freertos = {
        'cortex-m0': "CM0",
        'cortex-m0plus': "CM0"
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
        project_load.append(f'Project.AddSvdFile ("{os.path.abspath(os.path.expanduser(tools_path))}/ozone/Config/CPU/{cpu_svd[cpu]}.svd");')
    else:
        project_load.append(f'Project.AddSvdFile ("{os.path.abspath(os.path.expanduser(tools_path))}/ozone/Config/CPU/{cpu}.svd");')

    if cpu in device_svd:
        svd_file = f"{os.path.abspath(tools_path)}/ozone/Config/Peripherals/AT{device_svd[device]}.svd"
    else:
        svd_file = f"{os.path.abspath(tools_path)}/ozone/Config/Peripherals/AT{peripheral}.svd"
    if os.path.exists(svd_file):
        project_load.append(f'Project.AddSvdFile ("{svd_file}");')
    else:
        log.warning(f"No peripherals found for {peripheral}")
        
    if cpu in cpu_freertos:
        project_load.append(f'Project.SetOSPlugin("FreeRTOSPlugin_{cpu_freertos[cpu]}");')
    else:
        log.warning(f"No freertos correspondance defined for device {cpu}")
    
    project_load.append(f'File.Open ("$(ProjectDir)/output/{arch.mpu}/bin/firmware.elf");')
    
    # write CMakeLists.txt from template
    try:
        loader = template.Loader(os.path.join(os.path.expanduser(tools_path), 'template'), autoescape=None)
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
        