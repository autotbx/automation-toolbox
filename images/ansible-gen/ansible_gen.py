#!/usr/bin/env python
"""
Module to generate Ansible inventoriy and playbooks from Terraform operator completion
"""
from typing import Iterable
import os
import logging
import subprocess
from urllib.parse import urlparse
from kubernetes import client, config
#import kubernetes.client
import yaml

API_GROUP = 'terraform.dst.io'
API_VERSION = 'v1'

ANSIBLE_ATTRIBUTES = 'ansibleAttributes'

class AnsibleCredentials:
    def __init__(self, login, password, sshkey = None, con_type = "ssh"):
        self._login = login
        self._password = password
        self._sshkey = sshkey
        self._con_type = con_type

    def to_dict(self):
        vars = {"ansible_user": self._login }
        if self._password:
            vars["ansible_password"] = self._password
        # TODO write to file
        if self._sshkey:
            vars["ansible_sshkey"] = self._sshkey
        if self._con_type == "winrm":
            vars["ansible_connection"] = self._con_type
        return vars
        

class AnsibleTarget:
    """ Represent a target to which Ansible will be run (host, group, etc.)"""
    def __init__(self, name: str, ansible_vars: dict):
        self.name = name
        self.vars = ansible_vars

class AnsibleHost(AnsibleTarget):
    """ Represent a host to which Ansible will be run """

class AnsibleGroup(AnsibleTarget):
    """ Represent a group of hosts """
    def __init__(self, name: str, ansible_vars: dict):
        self.hosts = []
        #super(AnsibleGroup, self).__init__(name=name, vars=vars)
        super().__init__(name=name, ansible_vars=ansible_vars)

    def add_host(self, host: AnsibleHost):
        """ Add a host in the Ansible group """
        if isinstance(host, list):
            self.hosts.extend(host)
        else:
            self.hosts.append(host)

class AnsiblePlaybook:
    """ Represent a Ansible playbook """
    def __init__(self, name: str, targets: AnsibleTarget, roles: list, credentials: AnsibleCredentials):
        self.name = name
        self.targets = targets
        self.roles = roles
        self.creds = credentials

def gen_inventory(groups: Iterable):
    """ Generate an inventory based on the groups givent """
    inventory = {"all": {"children": {}}}
    for group in groups:
        hosts = {}
        for host in group.hosts:
            hosts[host.name] = host.vars
        ans_group = {"hosts": hosts, "vars": group.vars}
        inventory["all"]["children"][group.name] = ans_group
    return inventory
def gen_playbook(playbooks: Iterable):
    """ Generate a playbook list base on the given playbooks """
    pb_collection = []
    for playbook in playbooks:
        roles = []
        for role in playbook.roles:
            role_path = urlparse(role).path
            role_name = role_path.split('/')[-1]
            roles.append(role_name)
        pb_dict = {"name": playbook.name, "hosts": playbook.targets.name, "become": True, "roles": roles, "vars": playbook.creds.to_dict()}
        pb_collection.append(pb_dict)

    return pb_collection

def write_yaml(inventory: dict, path: str):
    """ Write a YAML file to the destination with the given dictionnary """
    with open(path, 'w') as inventory_file:
        yaml.dump(inventory, inventory_file)


def clone_roles(playbooks: Iterable, directory: str, check_ssl: bool):
    """ Install the roles in the configured directory """
    roles = []
    for playbook in playbooks:
        for role in playbook.roles:
            if role not in roles:
                roles.append(role)
    for role in roles:
        #git.Repo.clone_from(role, '/tmp/roles/%s' % role)
        command = ["ansible-galaxy", "install", "-p", directory]
        env = os.environ
        if not check_ssl:
            command.append("-c")
            env["GIT_SSL_NO_VERIFY"] = "true"
        command.append(role)
        print(command)
        try:
            subprocess.run(command, env=env, check=True)
        except subprocess.CalledProcessError as process_error:
            logging.error("Unable to clone repo %s", role)
            logging.error("stdout: %s", process_error.stdout)
            logging.error("stderr: %s", process_error.stderr)



def parse_modules(modules: Iterable):
    """ Parse the module from the Terraform operator to generate the groups and playbooks for Ansible """
    groups = []
    playbooks = []

    for module in modules:
        if ANSIBLE_ATTRIBUTES in module['spec']:
            group_name = module["metadata"]["name"]
            ansible_attribute = module['spec'][ANSIBLE_ATTRIBUTES]
            # print(ansible_attribute)

            roles = ansible_attribute["roles"]
            targets = ansible_attribute["targets"]
            try: 
                creds = ansible_attribute["credentials"]
                # TODO add sshkey and winrm
                credentials = AnsibleCredentials(creds["user"], creds["password"])
            except KeyError:
                credentials = None
            if "variables" in ansible_attribute:
                variables = ansible_attribute["variables"]
            else:
                variables = {}

            group = AnsibleGroup(group_name, variables)
            groups.append(group)

            for host in targets:
                if isinstance(host, str):
                    name = host
                    ansible_vars = {}
                else:
                    name = list(host.keys())[0]
                    ansible_vars = host[name]
                target = AnsibleHost(name, ansible_vars)
                group.add_host(target)


            playbook = AnsiblePlaybook(group_name, group, roles, credentials)
            playbooks.append(playbook)

    return groups, playbooks

def write_config(dest: str):
    with open(dest, "w") as conf_file:
        conf_file.write("[defaults]\nhost_key_checking = false")

def main():
    """ Entrypoint  """
    try:
        config.load_kube_config()
    except config.ConfigException:
        config.load_incluster_config()

    namespace = os.environ.get("K8S_NAMESPACE", "default")
    data_dir = os.environ.get("ANSIBLE_DATA_DIR", "/data")
    check_ssl = os.environ.get("CHECK_SSL", True)
    if check_ssl == "FALSE":
        check_ssl = False
    # in_kubernetes = os.environ.get("KUBERNETES_PORT",  False)
#    state =  os.environ.get("STATE")

    api_instance = client.CustomObjectsApi()

    modules = api_instance.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, "modules")["items"]

    groups, playbooks = parse_modules(modules)

    write_config(os.path.join(data_dir, "ansible.cfg"))
    write_yaml(gen_inventory(groups), os.path.join(data_dir, "inventory.yaml"))
    write_yaml(gen_playbook(playbooks), os.path.join(data_dir, "playbook.yaml"))
    logging.error(list(os.walk('/tmp')))
    clone_roles(playbooks, os.path.join(data_dir, "roles/"), check_ssl)


if __name__ == "__main__":
    main()
    print('finished')
