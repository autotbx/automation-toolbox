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

API_GROUP = 'terraform.dst.io'
API_VERSION = 'v1'

try:
    config.load_kube_config()
except config.ConfigException:
    config.load_incluster_config()
api_instance = client.CustomObjectsApi()

def run_ansible(check: bool, limit):
    check = '--check' if check else ''
    limit = f'--limit {limit}' if limit != None else ''
    command = [ "/bin/sh", "-x", "-e", "-c", f"ansible-playbook {limit} {check} -f 1 -D -i /data/inventory.yaml /data/playbook.yaml 0</dev/null"]
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = process.stdout
    return (process.returncode, out)

def compare_diff(plan: str, run:str, ):
  plan = re.search('(PLAY.*)', plan,flags=re.DOTALL|re.MULTILINE)
  run = re.search('(PLAY.*)', run.decode('utf-8'),flags=re.DOTALL|re.MULTILINE)

  if plan == None or run == None:
    print('unable to parse output')
    return False 
  plan_lines = plan.group(0).splitlines()
  run_lines = run.group(0).splitlines()

  if len(plan_lines) != len(run_lines):
    print("plan and check run not same number of lines")

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

def main():
    """ Main entrypoint """
    args = parse_args()
    namespace = os.getenv("K8S_NAMESPACE")
    name = os.getenv("ANSIBLEPLAN_NAME")
    if not namespace or not name:
        print("You must set the namespace and name environment variable")
        exit(1)
    try:
        plan = api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansplans', name)
    except ApiException as e:
        printError("Exception when  CustomObjectsApi->get_namespaced_custom_object: %s\n" % e)
        exit(1)
    if args.plan:
      print('[INF] Running ansible check')
      checkrc, checkout = run_ansible(True, args.limit)
      print(checkout.decode('utf-8'))
      exit(checkrc)
    elif args.apply:
      planOutput = plan["status"]["planOutput"]
      print('[INF] Running ansible check')
      checkrc, checkout = run_ansible(True, args.limit)
      print(checkout.decode('utf-8'))
      exit(checkrc)
      if not compare_diff(planOutput, checkout):
        print('[ERROR] A difference has been detected between the previous plan and the new one, skipping applying')
        print(checkout.decode('utf-8'))
        exit(1)
      print('[INF] Running ansible')
      checkrc, checkout = run_ansible(False,args.limit)
      print(checkout.decode('utf-8'))
      exit(checkrc)
    else:
      print('nothing to do')
      exit(1)

if __name__ == "__main__":
    main()