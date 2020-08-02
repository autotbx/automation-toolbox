from kubernetes import client, config, utils
import kubernetes.client
import pprint
from kubernetes.client.rest import ApiException
from jinja2 import Template
import os
from sys import exit

API_GROUP='dst.org'
API_VERSION='v1'



template = '''terraform {
  required_providers {
	vsphere = "= 1.15"
	}
  backend "kubernetes" {
    in_cluster_config = true
#    load_config_file = true
    secret_suffix = "{{state_prefix}}"
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
state_prefix = os.environ.get("TF_PREFIX", "default-prefix")
state =  os.environ.get("STATE")
if state == None:
  print('STATE env var name defined, exiting')
  exit(1)

api_instance = client.CustomObjectsApi()

try:
  modules = api_instance.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, "modules")["items"]
  providers = api_instance.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, "providers")["items"]
  state = api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'states', state)
except ApiException as e:
  print("Exception when calling CustomObjectsApi->get_cluster_custom_object: %s\n" % e)

def ff(objs):
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


fmods = {}
for module in modules:
  if 'type' in module['spec'] and  module['spec']['type'] in state['spec']['types']:
    for defattr in state['spec']['types'][module['spec']['type']]:
      if not defattr in module['spec']['attributes']:
         module['spec']['attributes'][defattr] = state['spec']['types'][module['spec']['type']][defattr]

  fmods[module['metadata']['name']] = ff(module['spec']['attributes'])
  
fproviders = {}
for provider in providers:
  fproviders[provider['spec']['type']] = ff(provider['spec']['attributes'])


t = Template(template)
rendered = t.render(state_prefix=state_prefix, modules=fmods, providers=fproviders)

print(rendered)
with open(out_file, 'w') as f:
    f.write(rendered)
