#!/usr/bin/env python
""" Ansible wrapper which set default args and parse output """

import subprocess
import argparse
import os
import re
from kubernetes import client, config
import pprint

API_GROUP = 'terraform.dst.io'
API_VERSION = 'v1'

class AnsibleResult:
    def __init__(self, host: str, ok: int, changed: int, unreachable: int, failed: int, skipped: int, rescued: int, ignored: int):
        self.host = host
        self.ok = ok
        self.changed = changed
        self.unreachable = unreachable
        self.failed = failed
        self.skipped = skipped
        self.recued = rescued
        self.ignored = ignored

    def is_success(self):
        if self.unreachable > 0 or self.failed > 0:
            return False
        else:
            return True


class AnsibleCall:
    def __init__(self, run_name, namespace, data_dir):
        self.run_name = run_name
        self.namespace = namespace
        self.log_path = "/tmp/ansible.log"
        self._data_dir = data_dir

    @classmethod
    def _parse_line(cls, line):
        match = re.search(r"\| (?P<host>\w+)\s+: ok=(?P<ok>\d+)\s+changed=(?P<changed>\d+)\s+unreachable=(?P<unreachable>\d+)\s+failed=(?P<failed>\d+)\s+skipped=(?P<skipped>\d+)\s+rescued=(?P<rescued>\d+)\s+ignored=(?P<ignored>\d+)" , line)
        result = AnsibleResult(match.group("host"), match.group("ok"), match.group("changed"), match.group("unreachable"), match.group("failed"), match.group("skipped"), match.group("rescued"), match.group("ignored"))
        return result


    def parse_log(self):
        with open(self.log_path) as log_file:
            line_to_parse = []
            found = False
            for line in log_file:
                if line.contains("PLAY RECAP **********************"):
                    found = True
                if found:
                    line_to_parse.append(line)

        success = True
        for line in line_to_parse:
            result = self._parse_line(line)
            if not result.is_success():
                success = False
        
        return success


    def _upload_result(self, success, check):
        try:
            config.load_kube_config()
        except config.ConfigException:
            config.load_incluster_config()
        api_instance = client.CustomObjectsApi()

        # If no error return code from ansible, we check the logs
        if success:
            result = self.parse_log()
        else:
            result = success

        with open(self.log_path) as log_file:
            logs = log_file.read()

        if check:
            ansible_result = "ansibleCheckResult"
            ansible_log = "ansibleCheckLog"
        else:
            ansible_result = "ansibleResult"
            ansible_log = "ansibleLog"

        run = {"spec": {ansible_result: result, ansible_log: logs}}
        api_response = api_instance.patch_namespaced_custom_object(API_GROUP, API_VERSION, self.namespace, 'ansibleruns', self.run_name, run)
        pprint.pprint(api_response)

    def call_ansible(self, check):
        """ Call ansible and parse result, if `check` is true, only perform check for the playbook """

        env = os.environ
        env["ANSIBLE_LOG_PATH"] = self.log_path

        command = ["ansible-playbook", "-D"]
        if check:
            command.append("-C")
        command.extend(["-i",  os.path.join(self._data_dir, "inventory.yaml"), os.path.join(self._data_dir, "playbook.yaml")])
        try:
            process = subprocess.run(command, check=True, env=env)
            out = process.stdout
            err = process.stderr
            success = self.parse_log()
        except subprocess.CalledProcessError as process_error:
            out = process_error.stdout
            err = process_error.stderr
            success = False
        self._upload_result(success, check)

def parse_args():
    """ Parse CLI argument """
    parser = argparse.ArgumentParser(description="Wrapper for ansible")
    parser.add_argument("-C", "--check", type=bool, help="Only check playbooks")

    args = parser.parse_args()
    return args

def main():
    """ Main entrypoint """
    args = parse_args()
    namespace = os.getenv("K8S_NAMESPACE")
    name = os.getenv("ANSIBLERUN_NAME")
    data_dir = os.getenv("ANSIBLE_DATA_DIR", "/data")
    if not namespace or not name:
        print("You must set the namespace and name environment variable")
        exit(1)
    ansible = AnsibleCall(name, namespace, data_dir)
    ansible.call_ansible(args.check)


if __name__ == "__main__":
    main()
    