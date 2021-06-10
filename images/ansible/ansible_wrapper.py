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
    def __init__(self, run_name, namespace, data_dir, plan: bool):
        self.run_name = run_name
        self.namespace = namespace
        self.log_path = "/tmp/ansible.log"
        self._data_dir = data_dir
        self._plan = plan

    @classmethod
    def _parse_line(cls, line):
        match = re.search(r"\| (?P<host>\w+)\s+: ok=(?P<ok>\d+)\s+changed=(?P<changed>\d+)\s+unreachable=(?P<unreachable>\d+)\s+failed=(?P<failed>\d+)\s+skipped=(?P<skipped>\d+)\s+rescued=(?P<rescued>\d+)\s+ignored=(?P<ignored>\d+)" , line)
        if match:
            result = AnsibleResult(match.group("host"), int(match.group("ok")), int(match.group("changed")), int(match.group("unreachable")), int(match.group("failed")), int(match.group("skipped")), int(match.group("rescued")), int(match.group("ignored")))
        else:
            result = None
        return result


    def parse_log(self):
        with open(self.log_path) as log_file:
            line_to_parse = []
            found = False
            for line in log_file:
                if "PLAY RECAP **********************" in line:
                    found = True
                if found:
                    line_to_parse.append(line)

        success = True
        hosts = []
        for line in line_to_parse:
            print(line)
            result = self._parse_line(line)
            if result is not None:
                hosts.append(result.host)
                if not result.is_success():
                    success = False
        
        return success, hosts



    def _upload_result(self, success, check):
        try:
            config.load_kube_config()
        except config.ConfigException:
            config.load_incluster_config()
        api_instance = client.CustomObjectsApi()

        # If no error return code from ansible, we check the logs
        if success:
            result, hosts = self.parse_log()
        else:
            _, hosts = self.parse_log()
            result = success

        with open(self.log_path) as log_file:
            #logs = log_file.read()
            log_array = []
            for log_line in log_file.readlines():
                try: 
                    clean_line = log_line.split("|")[1]
                except IndexError:
                    clean_line = log_line
                log_array.append(clean_line)
            logs = "\n".join(log_array)

        if check:
            ansible_result = "ansibleCheckResult"
            ansible_hosts = "ansibleCheckHosts"
            ansible_log = "ansibleCheckLog"
        else:
            ansible_result = "ansibleResult"
            ansible_hosts = "ansibleHosts"
            ansible_log = "ansibleLog"
        if self._plan:
            object_k8s = "ansibleplans"
        else:
            object_k8s = "ansibleruns"

        run = {"spec": {ansible_result: result, ansible_log: logs, ansible_hosts: hosts}}
        pprint.pprint(run)
        api_response = api_instance.patch_namespaced_custom_object(API_GROUP, API_VERSION, self.namespace, object_k8s, self.run_name, run)
        pprint.pprint(api_response)

    def call_ansible(self, check):
        """ Call ansible and parse result, if `check` is true, only perform check for the playbook """

        env = os.environ
        env["ANSIBLE_LOG_PATH"] = self.log_path
        env["ANSIBLE_CONFIG"] = os.path.join(self._data_dir, "ansible.cfg")

        #TODO better parse output to allow parallelism
        command = ["ansible-playbook", "-f", "1", "-D"]
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
    parser.add_argument("-C", "--check", action='store_true', help="Only check playbooks")
    parser.add_argument("-P", "--plan", action='store_true', help="Write result in plan object instead of run")

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
    print("###################### plan %s" % args)
        
    ansible = AnsibleCall(name, namespace, data_dir, args.plan)
    ansible.call_ansible(args.check)


if __name__ == "__main__":
    main()
    