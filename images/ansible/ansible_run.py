#!/usr/bin/env python
""" Ansible wrapper which set default args and parse output """

import subprocess
import argparse
import os
import re
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import pprint
from sys import exit
import difflib

API_GROUP = 'terraform.dst.io'
API_VERSION = 'v1'

try:
    config.load_kube_config()
except config.ConfigException:
    config.load_incluster_config()
api_instance = client.CustomObjectsApi()

def run_ansible(check: bool):
    check = '--check' if check else ''
    command = [ "/bin/sh", "-x", "-e", "-c", f"ansible-playbook {check} -f 1 -D -i /data/inventory.yaml /data/playbook.yaml 0</dev/null"]
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = process.stdout
    return (process.returncode, out)

def get_ans_log(output: str):
  if type(output) != type(''):
    output = output.decode('utf-8')
  m = re.search('(PLAY.*)', output,flags=re.DOTALL|re.MULTILINE)
  if m == None:
    print('unable to parse output')
    return None 
  return [s for s in m.group(0).splitlines() if s]

def compare_diff(plan: str, run:str ):
  plan_lines = get_ans_log(plan)
  run_lines = get_ans_log(run)
  if len(plan_lines) != len(run_lines):
    print(f"plan and check run not same number of lines {len(plan_lines)} - {len(run_lines)}")
    return False
  equal = True
  for i in range(0, len(plan_lines)):
    p_line = plan_lines[i]
    r_line = run_lines[i]
    if "/.ansible/tmp/" not in p_line:
      if p_line != r_line:
        equal = False
        break
  return equal

def parse_args():
    """ Parse CLI argument """
    parser = argparse.ArgumentParser(description="Wrapper for ansible")
    parser.add_argument("-P", "--plan", action='store_true', help="Check playbooks")
    parser.add_argument("-A", "--apply", action='store_true', help="Check old plans & apply playbooks")
    args = parser.parse_args()
    return args

def getModuleHosts(namespace, targets):
  hosts = []
  for target in targets:
    try:
      module = api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'modules', target)
    except ApiException as e:
        print(f'[WARN] Unable to find module {module}, skipping')
        continue
    if "ansibleAttributes" in module['spec'] and "targets" in module['spec']['ansibleAttributes']:
      hosts = hosts + [h['fqdn'] for h in module['spec']['ansibleAttributes']['targets']]
  return hosts

def checkHosts(output, hosts):
  if hosts  == None:
    return True
  hostsImpacted = getHostsImpacted(output)
  error = False
  for host in hostsImpacted:
    if host not in hosts:
      error = True
  if error:
    print(f'[INF] Hosts changes allowed : {hosts} / Impacted hosts : {hostsImpacted}')
    return False
  return True

def getHostsImpacted(output):
  ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
  line_to_parse = []
  found = False
  hostsImpacted = []
  for line in output.splitlines():
    if found:
      line_to_parse.append(ansi_escape.sub('', line))
    if "PLAY RECAP **********************" in line:
      found = True
  for line in line_to_parse:
    match = re.search(r"(?P<host>[0-9A-Za-z._-]+)\s+: ok=(?P<ok>\d+)\s+changed=(?P<changed>\d+)\s+unreachable=(?P<unreachable>\d+)\s+failed=(?P<failed>\d+)\s+skipped=(?P<skipped>\d+)\s+rescued=(?P<rescued>\d+)\s+ignored=(?P<ignored>\d+)" , line)
    if match:
      if int(match.group("changed")) != 0:
        hostsImpacted.append(match.group('host'))
  return hostsImpacted

def main():
    """ Main entrypoint """
    args = parse_args()
    namespace = os.getenv("K8S_NAMESPACE")
    name = os.getenv("ANSIBLE_PLAN")
    if not namespace or not name:
        print("You must set the namespace and name environment variable")
        exit(1)
    try:
        plan = api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansibleplans', name)
    except ApiException as e:
        printError("Exception when  CustomObjectsApi->get_namespaced_custom_object: %s\n" % e)
        exit(1)
  
    hosts = getModuleHosts(namespace, plan['spec']['targets']) if "targets" in plan['spec'] else None
    
    if args.plan:
      print('[INF] Running ansible check')
      checkrc, checkout = run_ansible(True)
      print(checkout.decode('utf-8'))
      if checkrc != 0:
        exit(checkrc)
      if checkHosts(checkout.decode('utf-8'), hosts) != True:
        print('[ERROR] Hosts impacted by the ansible run does not match exactly the defined targets')
        exit(1)
      else:
        exit(0)
    elif args.apply:
      planOutput = plan["status"]["planOutput"]
      print('[INF] Running ansible check')
      checkrc, checkout = run_ansible(True)
      if checkrc != 0:
        exit(checkrc)
      if not compare_diff(planOutput, checkout):
        print('[ERROR] A difference has been detected between the previous plan and the new one, skipping applying')
        for l in difflib.unified_diff(get_ans_log(planOutput), get_ans_log(checkout), fromfile='plan.output', tofile='apply.output'):
          print(l)
        exit(1)
      print('[INF] Running ansible')
      checkrc, checkout = run_ansible(False)
      print(checkout.decode('utf-8'))
      exit(checkrc)
    else:
      print('nothing to do')
      exit(1)

if __name__ == "__main__":
    main()