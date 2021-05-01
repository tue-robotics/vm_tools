#!/usr/bin/python3
"""libvirt executor"""

import sys
import logging
import traceback
import argparse
import pathlib
import os
import json
import uuid
import collections
import shutil
from vm_tools.hypervisor import Hypervisor
from vm_tools.ssh import Ssh

exit_code = os.getenv('BUILD_FAILURE_EXIT_CODE', 1)


def dump_env(settings, stage):
    with open('env-{}.json'.format(stage), mode='w') as filehandle:
        json.dump(settings.env, fp=filehandle)


def dump_script(settings, script, step):
    outpath = 'script-{}.ps1'.format(step)
    shutil.copyfile(script, outpath)


def load_settings():
    try:
        # currentPath = pathlib.Path().absolute()
        scriptPath = pathlib.Path(__file__).parent.absolute()
        # project_id = os.environ['CUSTOM_ENV_CI_CONCURRENT_PROJECT_ID']
        # path_slug = os.environ['CUSTOM_ENV_CI_PROJECT_PATH_SLUG']
        identity = os.path.join(scriptPath, 'secrets', 'id_win_vm')
        image_str = os.environ['CUSTOM_ENV_CI_JOB_IMAGE']
        id = os.getenv('LIBVIRT_EXECUTOR_ID', str(uuid.uuid4()))
        vm_name = 'gitlab-runner-{}'.format(id)
        ci_env = {k: os.environ[k] for k in os.environ.keys() if k.startswith('CUSTOM_ENV_')}
    except KeyError as e:
        logging.error('Could not find environment variable {}'.format(e.args[0]))
        raise
    Settings = collections.namedtuple(
        'Settings', ['id', 'env', 'hypervisor', 'storage_pool', 'image', 'vm_name', 'identity', 'username'])
    settings = Settings(
        id=id,
        env=ci_env,
        hypervisor='qemu:///system',
        storage_pool='vm',
        image=image_str,
        vm_name=vm_name,
        identity=identity,
        username='Test'
    )
    return settings


def do_config(settings):
    info = {
        'builds_dir': "runner/build",
        'cache_dir': "runner/cache",
        'shell': 'pwsh',
        'builds_dir_is_shared': False,
        'driver': {
            'name': "Libvirt gitlab executor by Robbert-Jan",
            'version': 'v0.0.1'
        },
        'job_env': {
            'LIBVIRT_EXECUTOR_ID': settings.id
        }
    }
    infoStr = json.dumps(info)
    print(infoStr)


def do_prepare(settings):
    logging.info('Libvirt gitlab executor - Prepare')

    h = Hypervisor(settings.hypervisor, settings.storage_pool)

    # create new vm
    vm = h.create_temp_vm(settings.image, settings.vm_name)

    # Start the VM
    logging.info('Starting the VM')
    vm.create()

    logging.info('Waiting until the VM has started...')
    ip = h.wait_until_vm_has_ip(vm, 60)
    logging.info('The vm has started {}'.format(ip))

    # Wait until ssh has started
    logging.info("Waiting until SSH has started...")
    ssh = Ssh(settings.identity, ip, settings.username)
    if ssh.test_connect().returncode != 0:
        raise TimeoutError

    # Prepare the dev env
    logging.info('Setting up the environment')
    ssh.setup_env()

    logging.info('Preperation done')


def do_run(settings, script, stage):
    logging.info('Libvirt gitlab executor - Run {} {}'.format(script, stage))

    dump_script(settings, script, stage)

    h = Hypervisor(settings.hypervisor, settings.storage_pool)

    vm = h.get_vm(settings.vm_name)
    ip = h.get_ip_from_vm(vm)
    logging.info('The VM IP address {}'.format(ip))
    ssh = Ssh(settings.identity, ip, settings.username)

    # Prepare the dev env
    script_name = os.path.basename(script)
    target_script_path = 'runner/scripts/' + script_name
    ssh.copy_file(script, target_script_path)

    logging.info('Executing script {}'.format(target_script_path))
    ssh.run_command('./'+target_script_path)

    logging.info('Completed script stage {}'.format(stage))


def do_cleanup(settings):
    logging.info('Libvirt gitlab executor - Cleanup')

    h = Hypervisor(settings.hypervisor, settings.storage_pool)

    vm = h.get_vm(settings.vm_name)

    # Kill the VM
    if vm.isActive():
        logging.info('Killing the VM')
        vm.destroy()

    # Remove the VM
    logging.info('Deleting the VM')
    h.delete_temp_vm(settings.vm_name)


try:
    logging.getLogger().setLevel(logging.INFO)

    parser = argparse.ArgumentParser(description='Libvirt gitlab executor')
    subparsers = parser.add_subparsers(help='Commands', dest='command', metavar='command')

    config_parser = subparsers.add_parser('config')

    prepare_parser = subparsers.add_parser('prepare')

    run_parser = subparsers.add_parser('run')
    run_parser.add_argument('script')
    run_parser.add_argument('stage')

    cleanup_parser = subparsers.add_parser('cleanup')

    args = parser.parse_args()

    # Load the settings
    settings = load_settings()

    dump_env(settings, args.command)

    # Execute the command
    if args.command == 'config':
        do_config(settings)
    elif args.command == 'prepare':
        do_prepare(settings)
    elif args.command == 'run':
        do_run(settings, args.script, args.stage)
    elif args.command == 'cleanup':
        do_cleanup(settings)


except Exception:
    logging.error(traceback.format_exc())
    sys.exit(exit_code)
