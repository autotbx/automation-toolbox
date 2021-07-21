from html import escape
import yaml, kubernetes, re, json
from kubernetes.client.rest import ApiException
from ansi2html import Ansi2HTMLConverter
from dateutil.tz import tzutc
import datetime

try:
    kubernetes.config.load_kube_config()
except:
    kubernetes.config.load_incluster_config()

API_GROUP = 'terraform.dst.io'
API_VERSION = 'v1'
_k8s_custom = kubernetes.client.CustomObjectsApi()
_k8s_core = kubernetes.client.CoreV1Api()
plurals = [
  "plans",
  "planrequests",
  "states",
  "providers",
  "clusterproviders",
  "moduletemplates",
  "clustermoduletemplates",
  "modules"
]
namespace="default"

def getNamespace():
    ns = []
    for namespace in _k8s_core.list_namespace(label_selector="toolbox-managed=true").items:
        ns.append(namespace.metadata.name)
    return ns

def formatKind(kind, obj):
  name = obj["metadata"]["name"]
  namespace = obj["metadata"]["namespace"] if "namespace" in obj["metadata"] else None
  edit = '/edit' if kind not in ['plans', 'planrequests'] else ""
  link = f'<a href="/{kind}/{namespace}/{name}{edit}">{name}</a>' if namespace != None else f'<a href="/cluster/{kind}/{name}{edit}">{name}</a>'
  if namespace:
    nslink = f'<a href="/{kind}/{namespace}/">{namespace}</a>'

  if kind == "states":
    return {
      'name' : link,
      'autoPlanApprove': obj["spec"]["autoPlanApprove"],
      'autoPlanRequest' : obj["spec"]['autoPlanRequest'],
      'deleteJobsOnPlanDeleted': obj["spec"]['deleteJobsOnPlanDeleted'],
      'deletePlansOnPlanDeleted': obj["spec"]['deletePlansOnPlanDeleted'],
      'clusterProviders' : ','.join(obj["spec"]["clusterProviders"]) if "clusterProviders" in obj["spec"] else "",
      'environment' : obj["spec"]["environment"] if "environment" in obj["spec"] else "",
      'creationTimestamp' : obj["metadata"]["creationTimestamp"],
      'namespace' :  nslink
    }
  elif kind == "plans":
    return {
      'name' : link,
      'approved': obj["spec"]["approved"],
      'applyStatus' : obj["status"]['applyStatus'],
      'applyStartTime': obj["status"]['applyStartTime'],
      'applyCompleteTime': obj["status"]['applyCompleteTime'],
      'planStatus' : obj["status"]['planStatus'],
      'planStartTime': obj["status"]['planStartTime'],
      'planCompleteTime': obj["status"]['planCompleteTime'],
      'creationTimestamp' : obj["metadata"]["creationTimestamp"],
      'namespace' :  nslink
    }
  elif kind == "planrequests":
    out = {
      'name' : link,
      'deletePlanOnDeleted': obj["spec"]["deletePlanOnDeleted"],
      'creationTimestamp' : obj["metadata"]["creationTimestamp"],
      'namespace' :  nslink
    }
    if "status" in obj and "plans" in obj["status"]:
        out['plans'] = ','.join([ f'<a href="/plans/{x}">{x}</a>' for x in obj["status"]["plans"]])
    else:
        out['plans'] = ''
    return out
    
  elif kind == "providers" or kind == "clusterproviders":
    return {
      'name' : link,
      'type' : obj["spec"]["type"] if "type" in obj["spec"] else "",
      'autoPlanRequest' : obj['spec']['autoPlanRequest'],
      'creationTimestamp' : obj["metadata"]["creationTimestamp"],
      'namespace':  nslink if "namespace" in obj["metadata"] else None
    }
  elif kind == "moduletemplates" or kind == "clustermoduletemplates":
    return {
      'name' : link,
      "requiredAttributes" : ','.join([x['name'] for x in obj["spec"]["requiredAttributes"]]) if "requiredAttributes" in obj["spec"] else "",
      'creationTimestamp' : obj["metadata"]["creationTimestamp"],
      'namespace' :  nslink if "namespace" in obj["metadata"] else None
    }
  elif kind == "modules":
    return {
      'name' : link,
      "autoPlanRequest": obj["spec"]["autoPlanRequest"],
      "clusterModuleTemplate": f'<a href="/clustermoduletemplates/{obj["spec"]["clusterModuleTemplate"]}">{obj["spec"]["clusterModuleTemplate"]}</a>' if "clusterModuleTemplate" in obj["spec"] else "",
      "moduleTemplate": f'<a href="/moduletemplates/{obj["spec"]["moduleTemplate"]}">{obj["spec"]["moduleTemplate"]}</a>' if "moduleTemplate" in obj["spec"] else "",
      'creationTimestamp' : obj["metadata"]["creationTimestamp"],
      'namespace' :  nslink
    }

def formData(request):
  body = {'spec' : {}}
  jsonfields = ["environments", "attributes", "defaultAttributes", "requiredAttributes", "ansibleAttributes"]
  for k in request.form:
      v = request.form[k]
      if k != "name":
        if k in jsonfields:
          try:
            v = json.loads(v)
          except  ApiException as e:
            print(f'unable to parse json : {v} {e}')
            return  None
        else:
          if k.endswith('[]'):
            v = request.form.getlist(k)
          else:
            if type(v) == type(""):
              if v.lower() == "true":
                v = True
              elif v.lower() == "false":
                v = False
        if v != None and v != "":
          body['spec'][k.replace('[]','')] = v

  return body

def formatApiKind(name):
  m = {
    "plans": "Plan",
    "planrequests" : "PlanRequest",
    "states" : "State",
    "providers" : "Provider",
    "clusterproviders" : "ClusterProvider",
    "moduletemplates" : "ModuleTemplate",
    "clustermoduletemplates" : "ClusterModuleTemplate",
    "modules": "Module"
  }
  return m[name]


def getObj(plural, name, namespace=None):
    if not plural in plurals:
        return None
    if namespace == None:
        try:
            obj = _k8s_custom.get_cluster_custom_object(API_GROUP, API_VERSION, plural, name)
        except ApiException as e:
            print("Exception when calling CustomObjectsApi->get_cluster_custom_object: %s\n" % e)
            return None
    else:
        try:
            obj = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, plural , name)
        except ApiException as e:
            print("Exception when calling CustomObjectsApi->get_namespaced_custom_object: %s\n" % e)
            return None
    return obj

def getForm(plural):
    clproviders = _k8s_custom.list_cluster_custom_object(API_GROUP, API_VERSION, 'clusterproviders')["items"]
    cltemplates = _k8s_custom.list_cluster_custom_object(API_GROUP, API_VERSION, 'clustermoduletemplates')["items"]
    templates = _k8s_custom.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'moduletemplates')["items"]
    clusterProviders = [k['metadata']["name"] for k in clproviders]
    clusterModuleTemplates  = [k['metadata']["name"] for k in cltemplates]
    moduleTemplates = [k['metadata']["name"] for k in templates]
    form = {
    "planrequests": [
      {
        "id" : "spec",
        "name": "Specification",
        "fields": [
        {
        "id": "name",
        "type": "string",
        "name": "Name",
        "required": True,
        },
        {
        "id": "deletePlanOnDeleted",
        "type": "boolean",
        "name": "Delete Plan On Deleted",
        "required": True,
        "value": True
        }
        ]
      }
    ],
    "providers": [
      {
      "id" : "spec",
      "name" : "Specification",
      "fields": [
        {
        "id": "name",
        "type": "string",
        "name": "Name",
        "required": True,
        "value": ""
        },
        {
        "id": "type",
        "type": "string",
        "name": "Type",
        "required": True
        },
        {
        "id": "autoPlanRequest",
        "type": "boolean",
        "name": "Auto Plan Request",
        "required": True,
        "value": True
        }],
      },
      {
        "id": "attributes",
        "name": "Attributes",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "attributes",
            "value" : [],
          }
        ]
      }
    ],
    "clusterproviders": [
        {
      "id" : "spec",
      "name" : "Specification",
      "fields": [
        {
        "id": "name",
        "type": "string",
        "name": "Name",
        "required": True,
        "value": ""
        },
        {
        "id": "type",
        "type": "string",
        "name": "Type",
        "required": True
        },
        {
        "id": "autoPlanRequest",
        "type": "boolean",
        "name": "Auto Plan Request",
        "required": True,
        "value": True
        }],
      },
      {
        "id": "attributes",
        "name": "Attributes",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "attributes",
            "value" : [],
          }
        ]
      },
      {
        "id" : "environments",
        "name" : "Environments",
        "add": "addEnv",
        "fields": [
          {
            "type": "environments",
            "id": "environments",
            "value" : [],
          }
        ]
      }
    ],
    "modules": [
      {
        "id": "spec",
        "name": 'Specification <button type="button" class="btn btn-dark showtplattr">Show herited configuration</button>',
        "fields": [
          {
          "id": "name",
          "type": "string",
          "name": "Name",
          "required": True,
          "value": ""
          },
          {
          "id": "autoPlanRequest",
          "type": "boolean",
          "name": "Auto Plan Request",
          "required": True,
          "value": True
          },
          {
          "id": "clusterModuleTemplate",
          "type": "list",
          "name": "Cluster Module Template",
          "options" : clusterModuleTemplates,
          },
          {
          "id": "moduleTemplate",
          "type": "list",
          "name": "Module Template",
          "options" : moduleTemplates
          },
        ]
      },
      {
        "id": "requiredAttributes",
        "name": "Required Attributes",
        "fields": [
          {
            "type": "fillRequiredAttributes",
            "id": "requiredAttributes",
            "value" : [],
          }
        ]
      },
      {
        "id": "attributes",
        "name": "Attributes",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "attributes",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleHosts",
        "name": "Ansible Hosts",
        "fields": [
          {
            "type": "ansibleHosts",
            "id": "ansibleHosts",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleSpec",
        "name": "Ansible Specification",
        "fields": [
        {
          "id": "ansible_cred_type",
          "name": "Authentication Type",
          "type": "list",
          "options": ["ssh", "winrm"],
        },
        {
          "id": "ansible_cred_user",
          "name": "Username",
          "type": "string",
        },
        {
          "id": "ansible_cred_password",
          "name": "Password",
          "type": "string",
        },
        {
          "id": "ansible_cred_ssh_key",
          "name": "SSH Key",
          "type": "string",
        },
        {
          "id": "ansible_defaultGalaxyServer",
          "type": "string",
          "name": "Default Galaxy Server",
        },
        ]
      },
      {
        "id": "ansibleRoles",
        "name": "Ansible Roles",
        "fields": [
          {
            "type": "ansibleRoles",
            "id": "ansibleRoles",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleVars",
        "name": "Ansible Variables",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "ansibleVars",
            "value" : [],
          }
        ]
      }
    ],
    "clustermoduletemplates": [
      {
      "id" : "spec",
      "name" : "Specification",
      "fields": [
        {
        "id": "name",
        "type": "string",
        "name": "Name",
        "required": True,
        "value": ""
        },
        ],
      },
      {
        "id": "requiredAttributes",
        "name": "Required Attributes",
        "add" : "insertRequiredAttribute",
        "fields": [
          {
            "type": "requiredAttributes",
            "id": "requiredAttributes",
            "value" : [],
          }
        ]
      },
      {
        "id": "defaultAttributes",
        "name": "Default Attributes",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "defaultAttributes",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleSpec",
        "name": "Ansible Specification",
        "fields": [
        {
          "id": "ansible_cred_type",
          "name": "Authentication Type",
          "type": "list",
          "options": ["ssh", "winrm"],
        },
        {
          "id": "ansible_cred_user",
          "name": "Username",
          "type": "string",
        },
        {
          "id": "ansible_cred_password",
          "name": "Password",
          "type": "string",
        },
        {
          "id": "ansible_cred_ssh_key",
          "name": "SSH Key",
          "type": "string",
        },
        {
          "id": "ansible_defaultGalaxyServer",
          "type": "string",
          "name": "Default Galaxy Server",
        },
        ]
      },
      {
        "id": "ansibleRoles",
        "name": "Ansible Roles",
        "fields": [
          {
            "type": "ansibleRoles",
            "id": "ansibleRoles",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleVars",
        "name": "Ansible Variables",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "ansibleVars",
            "value" : [],
          }
        ]
      },
      {
        "id" : "environments",
        "name" : "Environments",
        "add": "addEnv",
        "fields": [
          {
            "type": "environments",
            "id": "environments",
            "value" : [],
          }
        ]
      }
    ],
    "moduletemplates": [
      {
      "id" : "spec",
      "name" : "Specification",
      "fields": [
        {
        "id": "name",
        "type": "string",
        "name": "Name",
        "required": True,
        "value": ""
        },
        ],
      },
      {
        "id": "requiredAttributes",
        "name": "Required Attributes",
        "add" : "insertRequiredAttribute",
        "fields": [
          {
            "type": "requiredAttributes",
            "id": "requiredAttributes",
            "value" : [],
          }
        ]
      },
      {
        "id": "defaultAttributes",
        "name": "Default Attributes",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "defaultAttributes",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleSpec",
        "name": "Ansible Specification",
        "fields": [
        {
          "id": "ansible_cred_type",
          "name": "Authentication Type",
          "type": "list",
          "options": ["ssh", "winrm"],
        },
        {
          "id": "ansible_cred_user",
          "name": "Username",
          "type": "string",
        },
        {
          "id": "ansible_cred_password",
          "name": "Password",
          "type": "string",
        },
        {
          "id": "ansible_cred_ssh_key",
          "name": "SSH Key",
          "type": "string",
        },
        {
          "id": "ansible_defaultGalaxyServer",
          "type": "string",
          "name": "Default Galaxy Server",
        },
        ]
      },
      {
        "id": "ansibleRoles",
        "name": "Ansible Roles",
        "fields": [
          {
            "type": "ansibleRoles",
            "id": "ansibleRoles",
            "value" : [],
          }
        ]
      },
      {
        "id": "ansibleVars",
        "name": "Ansible Variables",
        "add" : "insertAttribute",
        "fields": [
          {
            "type": "attributes",
            "id": "ansibleVars",
            "value" : [],
          }
        ]
      },
    ],
    "states" : [
    {
      "id": "spec",
      "name": "Specification",
      "fields": [
        {
        "id": "name",
        "type": "string",
        "name": "Name",
        "required": True,
        },
        {
        "id": "autoPlanApprove",
        "type": "boolean",
        "name": "Auto Plan Approve",
        "required": True,
        "value": False
        },
        {
        "id": "autoPlanRequest",
        "type": "boolean",
        "name": "Auto Plan Request",
        "required": True,
        "value": True
        },
        {
        "id": "deleteJobsOnPlanDeleted",
        "type": "boolean",
        "name": "Auto Delete Job On Plan Deleted",
        "required": True,
        "value": True
        },
        {
        "id": "deletePlansOnPlanDeleted",
        "type": "boolean",
        "name": "Auto Delete Plan On Plan Deleted",
        "required": True,
        "value": True
        },
        {
        "id": "environment",
        "type": "string",
        "name": "Environment",
        },
        {
        "id": "clusterProviders",
        "type": "list",
        "name": "Cluster Providers",
        "multiple": True,
        "options" : clusterProviders
        },
        {
        "id": "customTerraformInit",
        "type": "string",
        "name": "Custom Terraform Init",
        },
        {
        "id": "tfExecutorImage",
        "type": "string",
        "name": "TF Executor Image",
        },
        {
        "id": "tfExecutorImagePullPolicy",
        "type": "list",
        "name": "TF Executor Image Pull Policy",
        "options": ["Always", "Never", "IfNotPresent"],
        },
        {
        "id": "tfGeneratorImage",
        "type": "string",
        "name": "TF Generator Image",
        },
        {
        "id": "tfGeneratorImagePullPolicy",
        "type": "list",
        "name": "TF Generator Image Pull Policy",
        "options": ["Always", "Never", "IfNotPresent"],
        }
      ]
    }
    ]
    }
    #form['clusterproviders'] = form['providers']
    #form['clustermoduletemplates'] = form['moduletemplates']
    return form[plural]

def updateFieldsValues(form, plural, obj):
  if plural == "planrequests":
    form = updateFieldsValue(form, "spec", "name", "value", obj['metadata']['name'])
    form = updateFieldsValue(form, "spec", "name", "disabled", True)
    form = updateFieldsValue(form, "spec", "deletePlanOnDeleted", "value", obj['spec']['deletePlanOnDeleted'])
  elif plural == "states":
    form = updateFieldsValue(form, "spec", "name", "value", obj['metadata']['name'])
    form = updateFieldsValue(form, "spec", "name", "disabled", True)
    form = updateFieldsValue(form, "spec", "autoPlanApprove", "value", obj['spec']['autoPlanApprove'])
    form = updateFieldsValue(form, "spec", "autoPlanRequest", "value", obj['spec']['autoPlanRequest'])
    form = updateFieldsValue(form, "spec", "deleteJobsOnPlanDeleted", "value", obj['spec']['deleteJobsOnPlanDeleted'])
    form = updateFieldsValue(form, "spec", "deletePlansOnPlanDeleted", "value", obj['spec']['deletePlansOnPlanDeleted'])
    form = updateFieldsValue(form, "spec", "customTerraformInit", "value", obj['spec']['customTerraformInit'] if "customTerraformInit" in obj['spec'] else '')
    form = updateFieldsValue(form, "spec", "tfExecutorImage", "value", obj['spec']['tfExecutorImage'])
    form = updateFieldsValue(form, "spec", "tfExecutorImagePullPolicy", "value", obj['spec']['tfExecutorImagePullPolicy'])
    form = updateFieldsValue(form, "spec", "tfGeneratorImage", "value", obj['spec']['tfGeneratorImage'])
    form = updateFieldsValue(form, "spec", "tfGeneratorImagePullPolicy", "value", obj['spec']['tfGeneratorImagePullPolicy'])
    form = updateFieldsValue(form, "spec", "clusterProviders", "values", obj['spec']['clusterProviders'] if "clusterProviders" in obj["spec"] else "")
    form = updateFieldsValue(form, "spec", "environment", "value", obj['spec']['environment'] if 'environment' in obj["spec"] else "")
  elif plural == "providers" or plural == "clusterproviders":
    form = updateFieldsValue(form, "spec", "name", "value", obj['metadata']['name'])
    form = updateFieldsValue(form, "spec", "name", "disabled", True)
    form = updateFieldsValue(form, "spec", "autoPlanRequest", "value", obj['spec']['autoPlanRequest'])
    form = updateFieldsValue(form, "spec", "type", "value", obj['spec']['type'])
    form = updateFieldsValue(form, "environments", "environments", "value", obj['spec']['environments'] if 'environments' in obj["spec"] else "")
    form = updateFieldsValue(form, "attributes", "attributes", "value", obj['spec']['attributes'] if 'attributes' in obj["spec"] else "")
  elif plural == "moduletemplates" or plural == "clustermoduletemplates":
    form = updateFieldsValue(form, "spec", "name", "value", obj['metadata']['name'])
    form = updateFieldsValue(form, "spec", "name", "disabled", True)
    form = updateFieldsValue(form, "environments", "environments", "value", obj['spec']['environments'] if 'environments' in obj["spec"] else "")
    form = updateFieldsValue(form, "defaultAttributes", "defaultAttributes", "value", obj['spec']['defaultAttributes'] if 'defaultAttributes' in obj["spec"] else "")
    if "ansibleAttributes" in obj['spec']:
      if  "credentials" in obj['spec']['ansibleAttributes']:
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_type", "value", obj['spec']['ansibleAttributes']['credentials']['type'] if "type" in obj['spec']['ansibleAttributes']["credentials"] else '')
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_user", "value", obj['spec']['ansibleAttributes']['credentials']['user'] if "user" in obj['spec']['ansibleAttributes']["credentials"] else '')
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_password", "value", obj['spec']['ansibleAttributes']['credentials']['password'] if "password" in obj['spec']['ansibleAttributes']["credentials"] else '')
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_ssh_key", "value", obj['spec']['ansibleAttributes']['credentials']['ssh_key'] if "ssh_key" in obj['spec']['ansibleAttributes']["credentials"] else '')
      form = updateFieldsValue(form, "ansibleSpec", "ansible_defaultGalaxyServer", "value", obj['spec']['ansibleAttributes']['defaultGalaxyServer'] if "defaultGalaxyServer" in obj['spec']['ansibleAttributes'] else '')
      form = updateFieldsValue(form, "ansibleRoles", "ansibleRoles", "value", obj['spec']['ansibleAttributes']['roles'] if "roles" in obj['spec']['ansibleAttributes'] else '')
      form = updateFieldsValue(form, "ansibleVars", "ansibleVars", "value", obj['spec']['ansibleAttributes']['vars'] if "vars" in obj['spec']['ansibleAttributes'] else '')
    attrs = []
    if 'requiredAttributes' in obj['spec']:
      for attr in obj['spec']['requiredAttributes']:
       #get = getAttribute(attr['name'], obj['spec']['attributes'], attr['type'])
        attrs.append({'name' : attr['name'], attr['type'] : '' })
    form = updateFieldsValue(form, "requiredAttributes", "requiredAttributes", "value", attrs)
  elif plural == "modules":
    form = updateFieldsValue(form, "spec", "name", "value", obj['metadata']['name'])
    form = updateFieldsValue(form, "spec", "name", "disabled", True)
    form = updateFieldsValue(form, "spec", "moduleTemplate", "value", obj['spec']['moduleTemplate']  if 'moduleTemplate' in obj["spec"] else "")
    form = updateFieldsValue(form, "spec", "clusterModuleTemplate", "value", obj['spec']['clusterModuleTemplate']  if 'clusterModuleTemplate' in obj["spec"] else "")
    form = updateFieldsValue(form, "spec", "autoPlanRequest", "value", obj['spec']['autoPlanRequest'])
    attributes = obj['spec']['attributes']
    tplobj = None
    if 'clusterModuleTemplate' in obj["spec"]:
      try:
        tplobj = _k8s_custom.get_cluster_custom_object(API_GROUP, API_VERSION, 'clustermoduletemplates', obj["spec"]['clusterModuleTemplate'])
      except ApiException as e:
        print("Exception when calling CustomObjectsApi->get_cluster_custom_object: %s\n" % e)
        tplobj = None
    elif 'moduleTemplate' in obj["spec"]:
      try:
        tplobj = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'moduletemplates', obj["spec"]['moduleTemplate'])
      except ApiException as e:
        print("Exception when calling CustomObjectsApi->get_namespaced_custom_object: %s\n" % e)      
        tplobj = None    
    if tplobj != None:
      attrs = []
      for attr in tplobj['spec']['requiredAttributes']:
        get = getAttribute(attr['name'], obj['spec']['attributes'], attr['type'])
        if get != '':
          attributes = popAttribute(attr['name'], attributes)
        attrs.append({'name' : attr['name'], attr['type'] : get })
      form = updateFieldsValue(form, "requiredAttributes", "requiredAttributes", "value", attrs)
    form = updateFieldsValue(form, "attributes", "attributes", "value", attributes)
    if "ansibleAttributes" in obj["spec"]:
      if  "credentials" in obj['spec']['ansibleAttributes']:
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_type", "value", obj['spec']['ansibleAttributes']['credentials']['type'] if "type" in obj['spec']['ansibleAttributes']["credentials"] else '')
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_user", "value", obj['spec']['ansibleAttributes']['credentials']['user'] if "user" in obj['spec']['ansibleAttributes']["credentials"] else '')
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_password", "value", obj['spec']['ansibleAttributes']['credentials']['password'] if "password" in obj['spec']['ansibleAttributes']["credentials"] else '')
        form = updateFieldsValue(form, "ansibleSpec", "ansible_cred_ssh_key", "value", obj['spec']['ansibleAttributes']['credentials']['ssh_key'] if "ssh_key" in obj['spec']['ansibleAttributes']["credentials"] else '')
      form = updateFieldsValue(form, "ansibleSpec", "ansible_defaultGalaxyServer", "value", obj['spec']['ansibleAttributes']['defaultGalaxyServer'] if "defaultGalaxyServer" in obj['spec']['ansibleAttributes'] else '')
      form = updateFieldsValue(form, "ansibleRoles", "ansibleRoles", "value", obj['spec']['ansibleAttributes']['roles'] if "roles" in obj['spec']['ansibleAttributes'] else [])
      form = updateFieldsValue(form, "ansibleVars", "ansibleVars", "value", obj['spec']['ansibleAttributes']['vars'] if "vars" in obj['spec']['ansibleAttributes'] else '')
      form = updateFieldsValue(form, "ansibleHosts", "ansibleHosts", "value", [target['fqdn'] for target in obj['spec']['ansibleAttributes']['targets']] if "targets" in obj['spec']['ansibleAttributes'] else [])
  return form

def updateFieldsValue(form, section, keyid, attr, val):
  j = 0
  for sec in form:
    if sec["id"] == section:
      i = 0
      for k in sec["fields"]:
        #print(k)
        if k["id"] == keyid:
          form[j]['fields'][i][attr] = val
        i = i + 1
    j = j + 1
  return form

def popAttribute(attribute, attributes):
  out = []
  for attr in attributes:
    if attr['name'] != attribute:
      out.append(attr)
  return out

def getAttribute(attribute, attributes, attrtype):
  for attr in attributes:
    if attr['name'] == attribute:
      return attr[attrtype]
  return ''

def apiMapping(kind):
  if kind == "states":
    return [
        { "name" : "Name", "field": "name"},
        { "name" : "autoPlanApprove", "field": "autoPlanApprove"},
        { "name" : "autoPlanRequest", "field": "autoPlanRequest"},
        { "name" : "deleteJobsOnPlanDeleted", "field": "deleteJobsOnPlanDeleted"},
        { "name" : "deletePlansOnPlanDeleted", "field": "deletePlansOnPlanDeleted"},
        { "name" : "clusterProviders", "field": "clusterProviders"},
        { "name" : "Environment", "field" : "environment"},
        { "name" : "CreationTime", "field": "creationTimestamp"},
    ]
  elif kind == "plans":
    return [
      { "name" : "Name", "field": "name"},
      { "name" : "Approved", "field": "approved"},
      { "name" : "Plan", "field": "planStatus"},
      { "name" : "Plan Start", "field": "planStartTime"},
      { "name" : "Plan End", "field": "planCompleteTime"},
      { "name" : "Apply", "field": "applyStatus"},
      { "name" : "Apply Start", "field": "applyStartTime"},
      { "name" : "Apply End", "field": "applyCompleteTime"},
      { "name" : "CreationTime", "field": "creationTimestamp"},
    ]
  elif kind == "planrequests":
    return [
      { "name" : "Name", "field": "name"},
      { "name" : "Plans", "field": "plans"},
      { "name" : "deletePlanOnDeleted", "field": "deletePlanOnDeleted"},
      { "name" : "CreationTime", "field": "creationTimestamp"},
    ]
  elif kind == "providers" or kind == "clusterproviders":
    return [
      { "name": "Name", "field": "name"},
      { "name": "Type", "field": "type"},
      { "name": "autoPlanRequest", "field": "autoPlanRequest"},
      { "name" : "CreationTime", "field": "creationTimestamp"},
    ]
  elif kind == "moduletemplates" or kind == "clustermoduletemplates":
    return [
      {"name" : "Name", "field": "name"},
      {"name" : "requiredAttributes:", "field": "requiredAttributes"},
      { "name" : "CreationTime", "field": "creationTimestamp"},
    ]
  elif kind == "modules":
    return [
      {"name" : "Name", "field": "name"},
      {"name" : "autoPlanRequest", "field": "autoPlanRequest"},
      {"name" : "clusterModuleTemplate", "field": "clusterModuleTemplate"},
      {"name" : "moduleTemplate", "field": "moduleTemplate"},
      { "name" : "CreationTime", "field": "creationTimestamp"},
    ]

def ansi2html(output):
  output = Ansi2HTMLConverter().convert(output)
  b = re.search(f'.*<body [^>]*>(.*)</body>.*', output, flags=re.DOTALL)
  c = re.search(f'.*<style.*>(.*)</style>.*', output, flags=re.DOTALL)
  if b == None or c == None:
    print(f'ERROR: unable to parse output : {output}')
    return ("", "")
  return (b.group(1), c.group(1))

def genTable(mapping, name, ajax,):
  ths = ""
  sortindex = 0
  i = 0
  for k in mapping:
    if k["name"] == "CreationTime":
      sortindex = i
    ths+= f'<th>{k["name"]}</th>'
    i = i + 1
  table = f'<table id="{name}" class="table" style="width:100%"><thead><tr>{ths}</tr></thead><tfoot><tr>{ths}</tr></tfoot></table>'

  js = """
    var data;
    table = $("#%NAME%").DataTable( {
        "ajax": "%AJAX%",
        "createdRow": function( row, data, dataIndex){
            $(row).addClass('table-row');
            $("td:contains('Failed')", row).css("color", "red");
            $("td:contains('Pending')", row).css("color", "orange");
            $("td:contains('Completed')", row).css("color", "green");
            $("td:contains('Active')", row).css("color", "yellow");

      //    if( data[2] ==  "someVal"){
        },
        "fnInitComplete": function(oSettings, json) {
          $(".dataTables_length select").addClass("table-input");
          $(".dataTables_length").addClass("table-length");
          $(".dataTables_filter input").addClass("table-input");
          $(".dataTables_filter").addClass("table-length");
          $(".dataTables_info").addClass("table-length");
        },
        "order": [["""+str(sortindex)+""", 'desc']],
        "columns": [
  """
  i=0
  for k in mapping:
    js += '{"data": "'+mapping[i]["field"]+'"},'
    i = i + 1
  js += """
        ]
    });
    //$('<button class="table-button" id="refresh">Refresh</button>').appendTo("div.dataTables_filter");
    //$("#%NAME% tbody").on("click", "tr", function () {
    //    var data = table.row( this ).data();
    //    location.href = "/plan/"+data["name"];
    //} );
  """
  js = js.replace('%NAME%', name).replace('%AJAX%', ajax)
  return (table, js)
