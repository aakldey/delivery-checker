import datetime
import glob
import json
import os
import shutil
import zipfile
from collections import namedtuple
from enum import Enum

from classes.helpers.ssh import SshClient, Credentials
from classes.helpers.zip import Zip

RemoteInfo = namedtuple(
    typename='RemoteInfo',
    field_names=('credentials', 'archive', 'remote_dir'),
)


class Result(str, Enum):
    NO_TEST = 'NO TEST'
    SKIP = 'SKIP'
    OK = 'OK'
    TIMEOUT = 'TIMEOUT'
    ERROR = 'ERROR'
    FAIL = 'FAIL'


RESULTS_PRIORITY = {
    Result.NO_TEST: 1,
    Result.SKIP: 2,
    Result.TIMEOUT: 3,
    Result.ERROR: 4,
    Result.FAIL: 5,
    Result.OK: 6,
}

OK_RESULTS = [
    Result.NO_TEST,
    Result.SKIP,
    Result.OK,
]


class ResultsManager:
    def __init__(self, config, log_func=print):
        self.__parse_config(config)

        self.log = log_func

        self.__zip = Zip()

    def __parse_config(self, config):
        self.__local_dir = './local'
        self.__remote_dir = './remote'
        self.__archive_dir = './archive'
        self.__results_file = f'{self.__local_dir}/results.json'

        self.__send_to_remote = None
        if config.get('send_to_remote') is not None:
            login = config['send_to_remote'].get('login')
            assert login is not None, 'Login is required in send_to_remote section'
            password = config['send_to_remote'].get('password')
            assert password is not None, 'Password is required in send_to_remote section'
            host = config['send_to_remote'].get('host')
            assert host is not None, 'Host is required in send_to_remote section'

            archive = config['send_to_remote'].get('archive')
            assert archive is not None, 'Archive name is required in send_to_remote section'

            self.__send_to_remote = RemoteInfo(
                credentials=Credentials(
                    login=login,
                    password=password,
                    host=host,
                    port=config['send_to_remote'].get('port', 22),
                ),
                archive=archive,
                remote_dir=config['send_to_remote'].get('remote_dir', '/opt/delivery_checker/remote')
            )

        self.__load_remote_cache = config.get('use_remote_results', False)

    def send_results(self, timeout=3 * 60):
        if self.__send_to_remote is None:
            return True

        zip_name = f'{self.__send_to_remote.archive}.zip'

        try:
            self.__zip.zip_path(
                path=self.__local_dir,
                rel_dir=self.__local_dir,
                zip_name=zip_name,
            )

            ssh = SshClient(self.__send_to_remote.credentials, log_func=self.log)
            ssh.send_file(
                zip_name=zip_name,
                remote_dir=f'{self.__send_to_remote.remote_dir}',
                timeout=timeout,
            )
            return True

        except Exception as e:
            self.log(f'Impossible to send results to remote server:\n{e}')

        finally:
            os.remove(zip_name)

        return False

    def __merge_results(self, remote_path):
        with open(self.__results_file, mode='r') as fs:
            local_results = json.load(fs)

        with open(remote_path, mode='r') as fs:
            remote_results = json.load(fs)

        for os_name, builds in remote_results.items():
            local_results[os_name] = local_results.get(os_name, {})
            for build_name, remote_result in builds.items():
                local_result = local_results[os_name].get(build_name, Result.NO_TEST)
                if RESULTS_PRIORITY[remote_result] >= RESULTS_PRIORITY[local_result]:
                    local_results[os_name][build_name] = remote_result

        with open(self.__results_file, mode='w') as fs:
            fs.write(json.dumps(local_results))

    def use_remote_results(self, temp_dir='./temp'):
        if not self.__load_remote_cache:
            return

        for archive in glob.glob(f'{self.__remote_dir}/*.zip'):
            with zipfile.ZipFile(archive, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            for root, _, files in os.walk(f'{temp_dir}/logs'):
                for file in files:
                    shutil.move(os.path.join(root, file), f'{self.__local_dir}/logs')

            for root, _, files in os.walk(f'{temp_dir}/results'):
                for file in files:
                    shutil.move(os.path.join(root, file), f'{self.__local_dir}/results')

            self.__merge_results(f'{temp_dir}/results.json')

            shutil.rmtree(temp_dir, ignore_errors=True)

    def find_lost_results(self, all_builds):
        with open(self.__results_file, mode='r') as fs:
            results = json.load(fs)

        new_results = {}
        for build in all_builds:
            os_name = build[0]
            build_name = build[1]
            if not any(map(
                lambda os_name_version: os_name in os_name_version,
                results.keys(),
            )):
                new_results[os_name] = new_results.get(os_name, {})
                new_results[os_name][build_name] = Result.NO_TEST.value

        for os_name, builds in new_results.items():
            results[os_name] = builds

        with open(self.__results_file, mode='w') as fs:
            fs.write(json.dumps(results, sort_keys=True, indent=4))

    def sync_results(self, all_builds):
        self.send_results()
        self.use_remote_results()
        self.find_lost_results(all_builds)

    def archive_results(self):
        os.makedirs(self.__archive_dir, exist_ok=True)
        zip_name = f'results_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
        zip_name = os.path.join(self.__archive_dir, zip_name)
        self.__zip.zip_path(
            path=self.__local_dir,
            rel_dir=self.__local_dir,
            zip_name=zip_name,
        )

    def is_results_ok(self):
        with open(self.__results_file, mode='r') as fs:
            results = json.load(fs)
        return all(map(
            lambda builds: all(map(
                lambda build_res: build_res in OK_RESULTS,
                builds.values(),
            )),
            results.values(),
        ))
