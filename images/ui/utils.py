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

#def genAttrInput(inputtype, value, required, password):
#  required = 'required' if required else ''
#  if inputtype == "bValue" or inputtype== "lbValue":
#    true_selected = "selected" if value == True or value == "true" else ""
#    false_selected = "selected" if value == False or value == "false" else ""
#    i = f"""
#    <select class="form-control attrvalue" {required}>
#      <option value="true" {true_selected}>True</option>
#      <option value="false" {false_selected}>False</option>
#    </select>
#    """
#  else:
#    finputtype = "text" if inputtype == "sValue" or inputtype == "lsValue" else "number"
#    finputtype = "password" if password else finputtype
#    complete = 'autocomplete="off" readonly onclick="this.removeAttribute(\'readonly\');"' if password else ''
#    i = f"""
#    <input type="{finputtype}" class="form-control" value="{escape(str(value))}" {required} {complete} placeholder="Attribute Value">
#    """
#  return i
#
#def genFormAttribute(itemid, attributes, plural):
#  html = ""
#  for attr in attributes:
#    attrtypes = [
#      {"name": "String", "type": "sValue"},
#      {"name": "Integer", "type": "iValue"},
#      {"name": "Number", "type": "nValue"},
#      {"name": "Boolean", "type": "bValue"},
#      {"name": "String[]", "type": "lsValue"},
#      {"name": "Integer[]", "type" : "liValue"},
#      {"name": "Number[]", "type" : "lnValue"},
#      {"name": "Boolean[]", "type": "lbValue"},
#    ]
#    toggle  = '' if  itemid == 'requiredAttributes' else 'toggleattrtype'
#    html += f"""
#            <div class="form-group row">
#              <div class="col-sm-2 col-form-label">
#                <select class="form-control {toggle} attrtype">
#            """
#    key = None
#    for attrtype in attrtypes:
#      key = attrtype['type'] if attrtype['type'] in attr else key
#      selected = 'selected' if attrtype['type'] in attr else ''
#      disabled = 'disabled' if (itemid == 'requiredAttributes' and plural == "modules") or itemid == 'ansibleRoles' or itemid == 'ansibleHosts' else ''
#      html += f'<option value="{attrtype["type"]}" {selected} {disabled}>{attrtype["name"]}</option>'
#    html += "</select></div>"
#
#    if key.startswith('l'):
#      disabled = 'disabled' if (itemid == 'requiredAttributes' and plural == "modules") or itemid == 'ansibleRoles' or itemid == 'ansibleHosts' else ''
#      #disabled = 'disabled' if itemid == 'requiredAttributes' else ''
#      html += f"""
#      <div class="col-sm-8 col-form-label attrname">
#        <input type="text" class="form-control" value="{attr['name']}" {disabled}  placeholder="Attribute Name">
#      </div>
#      <div class="col-sm-1 col-form-label attrbtn">
#      """
#      html += '' if (itemid == 'requiredAttributes' and plural == "modules") or itemid == 'ansibleRoles' or itemid == 'ansibleHosts' else '<span data-feather="trash-2" class="btn-del-attribute delAttribute"></span> '
#      addElementAttribute = 'addAnsibleHost' if itemid == 'ansibleHosts' else 'addElementAttribute'
#      html += '' if itemid == 'requiredAttributes' and plural != 'modules' else f'<span data-feather="plus-circle" class="btn-del-attribute {addElementAttribute}"></span> '
#      #html += '<span data-feather="plus-circle" class="btn-del-attribute addElementAttribute"></span> '
#      html += "</div>"
#      for elementAttribute in attr[key]:
#        i = genAttrInput(key, elementAttribute, (itemid == 'requiredAttributes'), ('password' in attr['name']))
#        html += f"""
#        
#        <div class="col-sm-2 col-form-label col1 attrvalue">
#        </div>
#        <div class="col-sm-8 col-form-label col2 attrvalue">
#          {i}
#        </div>
#        <div class="col-sm-1 col-form-label attrvalue attrbtn">
#          <span data-feather="trash-2" class="btn-del-attribute delElementAttribute"></span>
#        </div>
#        
#        """
#    else:
#      disabled = 'disabled' if itemid == 'requiredAttributes' and plural == 'modules' else ''
#      revealpw = '<span data-feather="eye" class="btn-del-attribute revealPw"></span> ' if 'password' in attr['name'] else ''
#      i = genAttrInput(key, attr[key], (itemid == 'requiredAttributes'), ('password' in attr['name']))
#      if itemid == 'requiredAttributes' and plural != "modules":
#        html += f"""
#                <div class="col-sm-8 col-form-label attrname">
#                  <input type="text" class="form-control" value="{attr['name']}" {disabled} placeholder="Attribute Name">
#                </div>
#                """
#      else:
#        html += f"""
#                <div class="col-sm-3 col-form-label attrname">
#                  <input type="text" class="form-control" value="{attr['name']}" {disabled} placeholder="Attribute Name">
#                </div>
#                <div class="col-sm-5 col-form-label attrvalue">
#                  {i}
#                </div>
#              """
#      html += '' if itemid == 'requiredAttributes' and plural == 'modules' else f'<div class="col-sm-1 col-form-label attrbtn">{revealpw}<span data-feather="trash-2" class="btn-del-attribute delAttribute"></span></div>'
#    html += "</div>"
#  return html  

#def genForm(form, plural, action, namespace=None, bal=None, color=None, hr=None, hform=None):
#    bal  = 'h4' if bal == None else bal
#    color = 'blue' if color == None else color
#    hr = '<hr />' if hr == None else hr
#    hform = True if hform == None else False
#    link = f"/cluster/{plural}/?{action}=true" if namespace == None else f"/{plural}/{namespace}/?{action}=true"
#    html = ""
#    if hform:
#      html += f'<form method="POST" action="{link}" class="needs-validation" novalidate>'
#    print(form)
#    for item in form:
#      #if item['type'] != "attributes" and item['type'] != "requiredAttributes" and item['type'] != "defaultAttributes":
#      if item['type'] != "attributes" and item['type'] != "ansibleRoles" and item['type'] != "ansibleHosts":
#        disabled = "disabled" if "disabled" in item and item["disabled"] else ""
#        required = 'required' if 'required' in item and item['required'] else ''
#        requiredLabel = f'<strong>{item["name"]} *</strong>' if required != "" else item["name"]
#        if item['type'] != "title":
#          html += f'<div class="form-group row"><label for="form{item["id"]}" class="col-sm-4 col-form-label">{requiredLabel}</label><div class="col-sm-6">'
#        if item['type'] == "string":
#          value = escape(item["value"], quote=True) if "value" in item else ""
#          html += f'<input type="text" class="form-control" id="form{item["id"]}" name="{item["id"]}" value="{value}" {required} {disabled}>'
#          if disabled != "":
#              html += f'<input type="hidden" name="{item["id"]}" value="{value}" />'
#        elif item['type'] == "boolean":
#          trueselect = "selected" if item['value'] else ""
#          falseselect = "selected" if not item['value'] else ""
#          html += f"""
#          <select name="{item["id"]}" class="form-control" id="form{item["id"]}" {required} >
#                  <option {trueselect}>True</option>
#                  <option {falseselect}>False</option>
#           </select>
#          """
#
#        elif item['type'] == "list":
#          multiple = "multiple" if "multiple" in item and item["multiple"] else ""
#          m = "[]" if multiple != "" else ""
#          html += f'<select name="{item["id"]}{m}" class="form-control" id="form{item["id"]}" {multiple} {required}>'
#          html += f'<option value="">Select value</option>' if multiple == "" else ""
#          for option in item['options']:
#            if multiple == "":
#              if "value" in item:
#                selected = 'selected' if item['value'] == option else ""
#              else:
#                selected = ''
#            else:
#              if "values" in item:
#                selected = 'selected' if option in item['values'] else ""
#              else:
#                selected = ""
#            html += f'<option {selected}>{option}</option>'
#          html += '</select>'
#        elif item['type'] == "yaml":
#          value = yaml.dump(item["value"], default_flow_style = False) if "value" in item and item["value"] != "" else ""
#          value = escape(value, quote=True)
#          html += f'<div id="pre-editor-{item["id"]}"></div><div id="editor-{item["id"]}" class=" editor " {required} >{value}</div><script>editors["{item["id"]}"] = ace.edit("editor-{item["id"]}"); editors["{item["id"]}"].session.setMode("ace/mode/yaml"); </script>'
#        elif item['type'] == "title":
#          html += f"""
#          <hr />
#          <h4><span class="blue">{item['name']}</span></span>
#          </h4>
#          """
#        if item['type'] != "title":
#          html += '</div></div>'
#      elif item['id'] == "ansibleRoles":
#        html += f"""
#          {hr}
#          <div class="{item['id']}">
#          <{bal}><span class="{color}">{item['name']}</span></{bal}>
#          """
#        html += genFormAttribute(item['id'], [{'name': 'roles', 'lsValue': item['value'] if 'value' in item else []}], plural)
#        html += "</div>"
#      elif item['id'] == "ansibleHosts":
#        html += f"""
#          {hr}
#          <div class="{item['id']}">
#          <{bal}><span class="{color}">{item['name']}</span></{bal}>
#          """
#        html += genFormAttribute(item['id'], [{'name': 'fqdn', 'lsValue': item['value'] if 'value' in item else []}], plural)
#        html += "</div>"
#      else:
#        if item['id'] == 'environments':
#          html += f"""
#          <hr />
#          <div class="{item['id']}">
#          <h4>
#            <span class="blue">{item['name']}</span>
#            <span style="float: right; margin-right: 17%"><span data-feather="plus-circle" class="btn-add-attribute addEnv"></span></span>
#          </h4>
#          """
#          if 'value' in item:
#            for env in item['value']:
#              html += f"""
#              <div class="env">
#              <div class="form-group row">
#                <label class="col-sm-4 col-form-label">
#                  Environment Name
#                </label>
#                <div class="col-sm-6 col-form-label">
#                  <input type="text" class="form-control envname" value="{env['name']}" placeholder="Environment Name">
#                </div>
#                <div class="col-sm-1 col-form-label">
#                  <span data-feather="trash-2" class="btn-del-attribute delEnv"></span>
#                </div>
#              </div>
#              <div class="envattributes">
#              <h6>
#              Default Attributes
#              <span style="float: right; margin-right: 17%"><span data-feather="plus-circle" class="btn-add-attribute adddefaultAttributes"></span></span>
#              </h6>
#              """
#              key = 'defaultAttributes' if plural == "clustermoduletemplates" else 'attributes'
#              html += genFormAttribute(item['id'],env[key], plural)
#              html += '</div>'
#              if plural == "clustermoduletemplates":
#                ansibleSpec = [{
#                  "id": "ansible_cred_type",
#                  "name": "Authentication Type",
#                  "type": "list",
#                  "options": ["ssh", "winrm"],
#                  "value" : env['ansibleAttributes']['credentials']['user'] if "ansibleAttributes" in env and "credentials" in env['ansibleAttributes']  else ''
#                },
#                {
#                  "id": "ansible_cred_user",
#                  "name": "Username",
#                  "type": "string",
#                  "value" : env['ansibleAttributes']['credentials']['user'] if "ansibleAttributes" in env and "credentials" in env['ansibleAttributes']  else ''
#                },
#                {
#                  "id": "ansible_cred_password",
#                  "name": "Password",
#                  "type": "string",
#                  "value" : env['ansibleAttributes']['credentials']['password'] if "ansibleAttributes" in env and "credentials" in env['ansibleAttributes']  else ''
#                },
#                {
#                  "id": "ansible_cred_ssh_key",
#                  "name": "SSH Key",
#                  "type": "string",
#                  "value" : env['ansibleAttributes']['credentials']['ssh_key'] if "ansibleAttributes" in env and "credentials" in env['ansibleAttributes']  else ''
#                },
#                {
#                  "id": "ansible_defaultGalaxyServer",
#                  "type": "string",
#                  "name": "Default Galaxy Server",
#                  "value": env['ansibleAttributes']['defaultGalaxyServer'] if "ansibleAttributes" in env and "defaultGalaxyServer" in env['ansibleAttributes'] else ''
#                }]
#                html += """<h6>Ansible Speficications</h6>"""
#                html += genForm(ansibleSpec, plural, action, namespace=None, hform=False)
#                html += genForm([{"id": "ansibleRoles","type": "ansibleRoles","name": "Ansible Roles", "value": env['ansibleAttributes']['roles'] if "ansibleAttributes" in env and "roles" in env['ansibleAttributes']  else [] }], plural, action, namespace=None, hr="", color="", bal="h6", hform=False)
#                html += genForm([{"id": "ansibleVars","type": "attributes", "name": "Ansible Variables", "value": env['ansibleAttributes']['vars'] if "ansibleAttributes" in env and "vars" in env['ansibleAttributes']  else []}], plural, action, namespace=None, hr="", color="", bal='h6', hform=False)
#              html += '<hr class="env"/></div>'
#        else:
#          hidden = 'style="display: none"' if item['id'] == 'requiredAttributes' and plural == "modules" and not 'value' in item else ''
#          hidden =''
#          add_attribute = '' if item['id'] == 'requiredAttributes' and plural == "modules" else f'<span style="float: right; margin-right: 17%"><span data-feather="plus-circle" class="btn-add-attribute add{item["id"]}"></span></span>'
#          show_tpl_attribute = '<button type="button" class="btn btn-dark showtplattr">Show herited attributes</button>' if plural == "modules" and item['id'] == 'attributes' else ''
#          html += f"""
#          {hr}
#          <div {hidden} class="{item['id']}">
#          <{bal}>
#            <span class="{color}">{item['name']}</span>
#            {show_tpl_attribute}
#            {add_attribute}
#          </{bal}>
#          """
#          html += genFormAttribute(item['id'], item['value'], plural) if 'value' in item else ''
#          html += "</div>"
#    html += '<div class="offset-sm-5"><button type="submit" id="submit" style="display: none" class="btn btn-primary">Submit</button></div>'
#    if hform:
#      html += "</form>"
#    return html


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



#def editForm(form, plural, obj):
#    if plural == "planrequests":
#        form = updateForm(form, "name", "value", obj['metadata']['name'])
#        form = updateForm(form, "name", "disabled", True)
#        form = updateForm(form, "deletePlanOnDeleted", "value", obj['spec']['deletePlanOnDeleted'])
#    elif plural == "states":
#        form = updateForm(form, "name", "value", obj['metadata']['name'])
#        form = updateForm(form, "name", "disabled", True)
#        form = updateForm(form, "autoPlanApprove", "value", obj['spec']['autoPlanApprove'])
#        form = updateForm(form, "autoPlanRequest", "value", obj['spec']['autoPlanRequest'])
#        form = updateForm(form, "deleteJobsOnPlanDeleted", "value", obj['spec']['deleteJobsOnPlanDeleted'])
#        form = updateForm(form, "deletePlansOnPlanDeleted", "value", obj['spec']['deletePlansOnPlanDeleted'])
#        form = updateForm(form, "customTerraformInit", "value", obj['spec']['customTerraformInit'] if "customTerraformInit" in obj['spec'] else '')
#        form = updateForm(form, "tfExecutorImage", "value", obj['spec']['tfExecutorImage'])
#        form = updateForm(form, "tfExecutorImagePullPolicy", "value", obj['spec']['tfExecutorImagePullPolicy'])
#        form = updateForm(form, "tfGeneratorImage", "value", obj['spec']['tfGeneratorImage'])
#        form = updateForm(form, "tfGeneratorImagePullPolicy", "value", obj['spec']['tfGeneratorImagePullPolicy'])
#        form = updateForm(form, "clusterProviders", "values", obj['spec']['clusterProviders'] if "clusterProviders" in obj["spec"] else "")
#        form = updateForm(form, "environment", "values", obj['spec']['environment'] if 'environment' in obj["spec"] else "")
#    elif plural == "providers" or plural == "clusterproviders":
#        form = updateForm(form, "name", "value", obj['metadata']['name'])
#        form = updateForm(form, "name", "disabled", True)
#        form = updateForm(form, "autoPlanRequest", "value", obj['spec']['autoPlanRequest'])
#        form = updateForm(form, "type", "value", obj['spec']['type'])
#        form = updateForm(form, "environments", "value", obj['spec']['environments'] if 'environments' in obj["spec"] else "")
#        form = updateForm(form, "attributes", "value", obj['spec']['attributes'] if 'attributes' in obj["spec"] else "")
#    elif plural == "moduletemplates" or plural == "clustermoduletemplates":
#        form = updateForm(form, "name", "value", obj['metadata']['name'])
#        form = updateForm(form, "name", "disabled", True)
#        form = updateForm(form, "environments", "value", obj['spec']['environments'] if 'environments' in obj["spec"] else "")
#        form = updateForm(form, "defaultAttributes", "value", obj['spec']['defaultAttributes'] if 'defaultAttributes' in obj["spec"] else "")
#        if "ansibleAttributes" in obj['spec']:
#          if  "credentials" in obj['spec']['ansibleAttributes']:
#            form = updateForm(form, "ansible_cred_type", "value", obj['spec']['ansibleAttributes']['credentials']['type'] if "type" in obj['spec']['ansibleAttributes']["credentials"] else '')
#            form = updateForm(form, "ansible_cred_user", "value", obj['spec']['ansibleAttributes']['credentials']['user'] if "user" in obj['spec']['ansibleAttributes']["credentials"] else '')
#            form = updateForm(form, "ansible_cred_password", "value", obj['spec']['ansibleAttributes']['credentials']['password'] if "password" in obj['spec']['ansibleAttributes']["credentials"] else '')
#            form = updateForm(form, "ansible_cred_ssh_key", "value", obj['spec']['ansibleAttributes']['credentials']['ssh_key'] if "ssh_key" in obj['spec']['ansibleAttributes']["credentials"] else '')
#          form = updateForm(form, "ansible_defaultGalaxyServer", "value", obj['spec']['ansibleAttributes']['defaultGalaxyServer'] if "defaultGalaxyServer" in obj['spec']['ansibleAttributes'] else '')
#          form = updateForm(form, "ansibleRoles", "value", obj['spec']['ansibleAttributes']['roles'] if "roles" in obj['spec']['ansibleAttributes'] else '')
#          form = updateForm(form, "ansibleVars", "value", obj['spec']['ansibleAttributes']['vars'] if "vars" in obj['spec']['ansibleAttributes'] else '')
#        
#        attrs = []
#        if 'requiredAttributes' in obj['spec']:
#          for attr in obj['spec']['requiredAttributes']:
#           #get = getAttribute(attr['name'], obj['spec']['attributes'], attr['type'])
#            attrs.append({'name' : attr['name'], attr['type'] : '' })
#        form = updateForm(form, "requiredAttributes", "value", attrs)
#        #form = updateForm(form, "requiredAttributes", "value", obj['spec']['requiredAttributes'] if 'requiredAttributes' in obj["spec"] else "")
#    elif plural == "modules":
#        form = updateForm(form, "name", "value", obj['metadata']['name'])
#        form = updateForm(form, "name", "disabled", True)
#        form = updateForm(form, "moduleTemplate", "value", obj['spec']['moduleTemplate']  if 'moduleTemplate' in obj["spec"] else "")
#        form = updateForm(form, "clusterModuleTemplate", "value", obj['spec']['clusterModuleTemplate']  if 'clusterModuleTemplate' in obj["spec"] else "")
#        form = updateForm(form, "autoPlanRequest", "value", obj['spec']['autoPlanRequest'])
#        attributes = obj['spec']['attributes']
#        tplobj = None
#        if 'clusterModuleTemplate' in obj["spec"]:
#          try:
#            tplobj = _k8s_custom.get_cluster_custom_object(API_GROUP, API_VERSION, 'clustermoduletemplates', obj["spec"]['clusterModuleTemplate'])
#          except ApiException as e:
#            print("Exception when calling CustomObjectsApi->get_cluster_custom_object: %s\n" % e)
#            tplobj = None
#        elif 'moduleTemplate' in obj["spec"]:
#          try:
#            tplobj = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'moduletemplates', obj["spec"]['moduleTemplate'])
#          except ApiException as e:
#            print("Exception when calling CustomObjectsApi->get_namespaced_custom_object: %s\n" % e)      
#            tplobj = None    
#        if tplobj != None:
#          attrs = []
#          for attr in tplobj['spec']['requiredAttributes']:
#            get = getAttribute(attr['name'], obj['spec']['attributes'], attr['type'])
#            if get != '':
#              attributes = popAttribute(attr['name'], attributes)
#            attrs.append({'name' : attr['name'], attr['type'] : get })
#          form = updateForm(form, "requiredAttributes", "value", attrs)
#        form = updateForm(form, "attributes", "value", attributes)
#    return form

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

#def updateForm(form, keyid, attr, val):
#  i = 0
#  for k in form:
#    if k["id"] == keyid:
#      form[i][attr] = val
#    i = i + 1
#  return form

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
