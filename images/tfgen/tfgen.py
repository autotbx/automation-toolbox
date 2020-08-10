from kubernetes import client, config, utils
import kubernetes.client
import pprint
from kubernetes.client.rest import ApiException
from jinja2 import Template
import os
from sys import exit, stderr

API_GROUP = 'terraform.dst.io'
API_VERSION = 'v1'


def printError(err):
  stderr.write(f"{err}\n")

  #required_providers {
	#vsphere = "= 1.15"
	#}
template = '''terraform {
  {{customTerraformInit}}
  backend "kubernetes" {
    {%- if in_kubernetes %}
    in_cluster_config = true
    {%- else %}
    load_config_file = true
    {%- endif %}
    secret_suffix = "{{state}}"
  }
}
{%- for provider in providers %}
provider "{{provider}}" {
  {%- for key in providers[provider] %}
  {{key}} = {{ providers[provider][key] }}
  {%- endfor %}
}
{%- endfor %}
{%- for module in modules %}
module "{{module}}" {
  {%- for key in modules[module] %}
  {{key}} = {{ modules[module][key] }}
  {%- endfor %}
}
{%- endfor %}
''' 

try:
    config.load_kube_config()
except:
    config.load_incluster_config()

namespace = os.environ.get("K8S_NAMESPACE", "default")
out_file = os.environ.get("TF_PATH", "/tmp/main.tf")
in_kubernetes = os.environ.get("KUBERNETES_PORT",  False)
state =  os.environ.get("STATE")
if state == None:
  printError('STATE env var name not, exiting')
  exit(1)

api_instance = client.CustomObjectsApi()

def formatAttr(objs):
  for key in objs:
    val = objs[key]
    if type(val) == type(''):
        objs[key] = f'"{val}"'
        continue

    if type(val) == type(True):
      if val:
        objs[key] = f'true'
      else:
        objs[key] = f'false'
      continue

    if type(val) == type([]):
      objs[key] = str(val).replace("'", '"')
      continue
  return objs

# resolve env
def getAttr(obj, environment):
  out = {}
  for attr in obj["spec"]["defaultAttributes"]:
    out[attr] = obj["spec"]["defaultAttributes"][attr]
  if 'environments' in obj["spec"]:
    for env in obj["spec"]["environments"]:
      if env['name'] == environment:
        for attr in env['defaultAttributes']:
          out[attr] = env['defaultAttributes'][attr]
  return out

try:
  state = api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'states', state)
except:
  printError(f"Fatal Error, unable to retrieve state {state}")
  exit(1)

try:
  modules = api_instance.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, "modules")["items"]
  providers = api_instance.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, "providers")["items"]
except ApiException as e:
  printError("Exception when calling CustomObjectsApi->namespaced_custom_object: %s\n" % e)

stateEnv = state['spec']['environment'] if 'environment' in state['spec'] else None
customTerraformInit = state['spec']['customTerraformInit'] if 'customTerraformInit' in state['spec'] else ''

realProviders=[]
for provider in providers:
  realProviders.append(provider)

if 'clusterProviders' in state['spec']:
  for clusterProvider in state['spec']['clusterProviders']:
    try:
      realProviders.append(api_instance.get_cluster_custom_object(API_GROUP, API_VERSION, 'clusterproviders', clusterProvider))
    except ApiException as e:
      printError("[clusterProvidersSKIP] Exception when calling CustomObjectsApi->get_namespaced_custom_object: %s" % e)

# provider Overwritten by ClusterProvider if same type 
fproviders = {}
for provider in realProviders:
  fproviders[provider['spec']['type']] = formatAttr(getAttr(provider, stateEnv))

fmodules = {}
for module in modules:
  tpl = None
  moduleName = module['metadata']['name']
  #clusterModuleTemplate prioity
  if 'clusterModuleTemplate' in module['spec']:
    try:
      tpl = api_instance.get_cluster_custom_object(API_GROUP, API_VERSION, 'clustermoduletemplates', module['spec']['clusterModuleTemplate'])
    except ApiException as e:
      printError(f"[MODULESKIP] {moduleName}: Exception when calling CustomObjectsApi->get_cluster_custom_object: %s" % e)
      continue
  elif 'moduleTemplate' in module['spec']:
    try:
      tpl = api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, 'moduletemplates', module['metadata']['namespace'], module['spec']['clusterModuleTemplate'])
    except ApiException as e:
      printError(f"[MODULESKIP] {moduleName}: Exception when calling CustomObjectsApi->get_cluster_custom_object: %s" % e)
      continue
  if tpl != None:
    if 'requiredAttributes' in tpl['spec']:
      missingRequiredAttributes = []
      for requiredAttribute in tpl['spec']['requiredAttributes']:
        if requiredAttribute not in module['spec']['attributes']:
          missingRequiredAttributes.append(requiredAttribute)
      if len(missingRequiredAttributes) != 0:
        printError(f"[MODULESKIP] {moduleName} : template {tpl['metadata']['name']}, missing requiredAttributes {missingRequiredAttributes}")
        continue
    attributes = formatAttr(getAttr(tpl, stateEnv))
    modAttributes = formatAttr(module['spec']['attributes'])
    for attribute in modAttributes:
      #overwrite tpl attribute if defined in module
      attributes[attribute] = modAttributes[attribute]
  else:
    attributes = module['spec']['attributes']

  fmodules[moduleName] = attributes

t = Template(template)
rendered = t.render(state=state['metadata']['name'],customTerraformInit=customTerraformInit, modules=fmodules, providers=fproviders, in_kubernetes=in_kubernetes)

print(rendered)
with open(out_file, 'w') as f:
    f.write(rendered)
