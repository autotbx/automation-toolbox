#!/usr/bin/env python
"""
Module to generate Ansible inventoriy and playbooks from Terraform operator
"""
from sys import api_version, exit
from typing import Iterable
import os
import logging
import subprocess
from urllib.parse import urlparse
from kubernetes import client, config
from kubernetes.client.api.custom_objects_api import CustomObjectsApi
from kubernetes.client.rest import ApiException
import yaml

try:
    config.load_kube_config()
except config.ConfigException:
    config.load_incluster_config()
api_instance = client.CustomObjectsApi()

API_GROUP = 'autotbx.io'
API_VERSION = 'v1'
ANSIBLE_ATTRIBUTES = 'ansibleAttributes'
ATTRIBUTE_TYPE = ['iValue', 'nValue', 'sValue', 'bValue', 'liValue', 'lnValue', 'lsValue', 'lbValue']

class AnsibleCredentials:
    def __init__(self, login = None, password = None, sshkey = None, con_type = "ssh", winrm_server_cert_validation = "ignore"):
        self._login = login if login != None else 'root'
        self._password = password if password != None else ''
        self._sshkey = sshkey if sshkey != None else ''
        self._con_type = con_type
        self._winrm_server_cert_validation = winrm_server_cert_validation

    def to_dict(self):
        vars = {"ansible_user": self._login }
        #if self._password:
        vars["ansible_password"] = self._password
        # TODO write to file
        if self._sshkey:
            vars["ansible_sshkey"] = self._sshkey
        vars["ansible_connection"] = self._con_type
        if self._con_type == "winrm":
            vars["ansible_winrm_server_cert_validation"] = self._winrm_server_cert_validation
            vars["ansible_winrm_transport"] = "ntlm"
        return vars
        

class AnsibleTarget:
    """ Represent a target to which Ansible will be run (host, group, etc.)"""
    def __init__(self, name: str, ansible_vars: dict):
        self.name = name
        self.vars = ansible_vars if ansible_vars is not None else {}

    def add_credentials(self, ansible_creds: AnsibleCredentials):
        for key, value in ansible_creds.to_dict().items():
            self.vars[key] = value

class AnsibleHost(AnsibleTarget):
    """ Represent a host to which Ansible will be run """

class AnsibleGroup(AnsibleTarget):
    """ Represent a group of hosts """
    def __init__(self, name: str, ansible_vars: dict):
        self.hosts = []
        super().__init__(name=name, ansible_vars=ansible_vars)

    def add_host(self, host: AnsibleHost):
        """ Add a host in the Ansible group """
        if isinstance(host, list):
            self.hosts.extend(host)
        else:
            self.hosts.append(host)

class AnsiblePlaybook:
    """ Represent a Ansible playbook """
    def __init__(self, name: str, targets: AnsibleTarget, roles: list, credentials: AnsibleCredentials, default_server: str):
        self.name = name
        self.targets = targets
        self._roles = roles
        self.creds = credentials
        self._default_server = default_server

    def get_roles(self):
        fqdn_roles = []
        for role in self._roles:
            url_role = urlparse(role)
            if not url_role.scheme:
                role = self._default_server + role
            fqdn_roles.append(role)

        return fqdn_roles

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
        for role in playbook.get_roles():
            role_path = urlparse(role).path
            role_name = role_path.split('/')[-1]
            roles.append(role_name)
        creds = playbook.creds.to_dict()
        if "ansible_connection" in creds and creds["ansible_connection"] == "winrm":
            become = False
        else:
            become = True
        pb_dict = {"name": playbook.name, "hosts": playbook.targets.name, "become": become, "roles": roles, "vars": creds}
        pb_collection.append(pb_dict)

    return pb_collection

def write_yaml(inventory: dict, path: str):
    """ Write a YAML file to the destination with the given dictionnary """
    with open(path, 'w') as inventory_file:
        print(path)
        print('------------')
        print(yaml.dump(inventory))
        yaml.dump(inventory, inventory_file)


def clone_roles(playbooks: Iterable, directory: str, check_ssl: bool):
    """ Install the roles in the configured directory """
    roles = []
    for playbook in playbooks:
        for role in playbook.get_roles():
            if role not in roles:
                roles.append(role)
    clone_error = False
    for role in roles:
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
            clone_error = True
    if clone_error:
        exit(1)

def _get_ansible_attribute(module: dict, attribute: str, namespace: str):
    """ Return an attribute value in an module or in its template """
    def_value = {'defaultGalaxyServer' : '', 'credentials': { 'user': None, 'password': None, 'ssh_key': None}, 'vars': [], 'targets': [], 'roles': [], 'dependencies': []}
    template_spec = None
    out = def_value[attribute]
    module_spec = module['spec']
    ansible_spec = module_spec[ANSIBLE_ATTRIBUTES]
    state_spec = api_instance.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'states')["items"][0]['spec']
    if 'clusterModuleTemplate' in module_spec:
        template_name = module_spec['clusterModuleTemplate']
        template_spec = api_instance.get_cluster_custom_object(API_GROUP, API_VERSION, 'clustermoduletemplates', template_name)["spec"]
    elif 'moduleTemplate' in module_spec:
        template_name = module_spec['moduleTemplate']
        template_spec = api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'moduletemplates', template_name)["spec"]

    if attribute != 'vars':
        if ANSIBLE_ATTRIBUTES in module_spec and attribute in module_spec[ANSIBLE_ATTRIBUTES]:
            out = module_spec[ANSIBLE_ATTRIBUTES][attribute]
        else:
            if template_spec != None and ANSIBLE_ATTRIBUTES in template_spec and attribute in template_spec[ANSIBLE_ATTRIBUTES]:
                out = template_spec[ANSIBLE_ATTRIBUTES][attribute]
            if 'environment' in state_spec:
                env_name = state_spec['environment']
                if template_spec != None and "environments" in template_spec:
                    for env in template_spec['environments']:
                        if env['name'] == env_name and ANSIBLE_ATTRIBUTES in env and attribute in env[ANSIBLE_ATTRIBUTES]:
                            out = env[ANSIBLE_ATTRIBUTES][attribute]
    else:
        out = []
        if template_spec != None and ANSIBLE_ATTRIBUTES in template_spec and attribute in template_spec[ANSIBLE_ATTRIBUTES]:
            for var in template_spec[ANSIBLE_ATTRIBUTES][attribute]:
                out = upsert(var, out)
        if 'environment' in state_spec:
            env_name = state_spec['environment']
            if template_spec != None and "environments" in template_spec:
                for env in template_spec['environments']:
                    if env['name'] == env_name and ANSIBLE_ATTRIBUTES in env and attribute in env[ANSIBLE_ATTRIBUTES]:
                        for var in  env[ANSIBLE_ATTRIBUTES][attribute]:
                            out = upsert(var, out)
        if attribute in module_spec[ANSIBLE_ATTRIBUTES]:
            for var in module_spec[ANSIBLE_ATTRIBUTES][attribute]:
                out = upsert(var, out)
    return out

def upsert(var, vars):
    out = []
    if len(vars) == 0:
        out.append(var)
    else:
        for v in vars:
            if v['name'] == var['name']:
                out.append(var)
            else:
                out.append(v)
    found = False
    for v in out:
        if var['name'] == v['name']:
            found = True
    if not found:
        out.append(var)
    return out

def _parse_variables(vars_list):
    """Transform the list of vars stored in module definition in dictionnary"""
    vars = {}
    for var in vars_list:
       key = var['name']
       value = None
       for var_type in ATTRIBUTE_TYPE:
           if var_type in var:
               value = var[var_type]
               break
       vars[key] = value
    return vars

def _parse_credentials(creds: dict):
    """ Parse credentials from dict retrieve in yaml to AnsibleCredentials object """
    conn_type = "winrm" if "type" in creds and creds["type"] == "winrm" else "ssh"
    winrm_server_cert_validation = creds["winrm_server_cert_validation"] if "winrm_server_cert_validation" in creds else "ignore"
    credentials = AnsibleCredentials(creds["user"], creds["password"], None, conn_type, winrm_server_cert_validation)

    return credentials

def parse_modules(modules: Iterable, namespace: str, api_instance: CustomObjectsApi):
    """ Parse the module from the Terraform operator to generate the groups and playbooks for Ansible """
    groups = []
    playbooks = []

    for module in modules:
        if ANSIBLE_ATTRIBUTES in module['spec']:
            group_name = module["metadata"]["name"]

            default_server = _get_ansible_attribute(module, "defaultGalaxyServer", namespace)
            roles = _get_ansible_attribute(module, "roles", namespace)
            targets = _get_ansible_attribute(module, "targets", namespace)

            credentials = _parse_credentials(_get_ansible_attribute(module, "credentials", namespace))
            variables = _get_ansible_attribute(module, "vars", namespace)
            variables = _parse_variables(variables)

            group = AnsibleGroup(group_name, variables)
            groups.append(group)

            for host in targets:
                name = host['fqdn']
                ansible_vars = {}
                if 'vars' in host:
                    for var in host['vars']:
                        key = var['name']
                        for val_name in ATTRIBUTE_TYPE:
                            if val_name  in var:
                                value = var[val_name]
                        ansible_vars[key] = value
                target = AnsibleHost(name, ansible_vars)

                if 'credentials' in host:
                    creds = _parse_credentials(host['credentials'])
                    target.add_credentials(creds)
                group.add_host(target)
            playbook = AnsiblePlaybook(group_name, group, roles, credentials, default_server)
            playbooks.append(playbook)

    return groups, playbooks

#def write_config(dest: str):
#    with open(dest, "w") as conf_file:
#        conf_file.write("[defaults]\nhost_key_checking = false")
def resolveDependencies(namespace, module):
    modules = []
    try:
        module = api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'modules', module)
    except ApiException as e:
        print(f'[WARN] Unable to find module {module}, skipping')
        return modules
    
    if ANSIBLE_ATTRIBUTES in module['spec'] and 'targets' in module['spec'][ANSIBLE_ATTRIBUTES]:
        modules.append(module)
        dependencies = _get_ansible_attribute(module, "dependencies", namespace)
        for deptarget in dependencies:
            modules = modules + resolveDependencies(namespace, deptarget)
    return modules

def main():
    """ Entrypoint  """

    namespace = os.environ.get("K8S_NAMESPACE")
    data_dir = os.environ.get("ANSIBLE_DATA_DIR", "/data")
    name = os.environ.get('ANSIBLE_PLAN')
    check_ssl = os.environ.get("CHECK_SSL", True)
    if check_ssl == "FALSE":
        check_ssl = False
    if not namespace or not name:
        print("You must set the namespace and name environment variable")
        exit(1)

    try:
        plan = api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansibleplans', name)
    except ApiException as e:
        printError("Exception when  CustomObjectsApi->get_namespaced_custom_object: %s\n" % e)
        exit(1)
    
    if "targets" in plan['spec']:
        targets = []
        for target in plan['spec']['targets']:
            targets = targets + resolveDependencies(namespace, target)
    else:
        targets = api_instance.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, "modules")["items"]
    
    groups, playbooks = parse_modules(targets, namespace, api_instance)

    #write_config(os.path.join(data_dir, "ansible.cfg"))
    write_yaml(gen_inventory(groups), os.path.join(data_dir, "inventory.yaml"))
    write_yaml(gen_playbook(playbooks), os.path.join(data_dir, "playbook.yaml"))
    #logging.error(list(os.walk('/tmp')))
    clone_roles(playbooks, os.path.join(data_dir, "roles/"), check_ssl)

if __name__ == "__main__":
    main()
