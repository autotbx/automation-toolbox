from cgi import escape
import yaml, kubernetes, re
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
    for namespace in _k8s_core.list_namespace().items:
        ns.append(namespace.metadata.name)
    return ns

def formatKind(kind, obj):
  name = obj["metadata"]["name"]
  namespace = obj["metadata"]["namespace"] if "namespace" in obj["metadata"] else None
  link = f'<a href="/{kind}/{namespace}/{name}">{name}</a>' if namespace != None else f'<a href="/cluster/{kind}/{name}">{name}</a>'
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
      'state' : f'<a href="/states/{obj["spec"]["state"]}">{obj["spec"]["state"]}</a>',
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
      "requiredAttributes" : ','.join(obj["spec"]["requiredAttributes"]) if "requiredAttributes" in obj["spec"] else "",
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

def genForm(form, plural, action, namespace=None):
    print(namespace)
    link = f"/{plural}/?{action}=true" if namespace == None else f"/{plural}/{namespace}/?{action}=true"
    html = f'<form method="POST" action="{link}" class="needs-validation" novalidate>'
    for item in form:
      disabled = "disabled" if "disabled" in item and item["disabled"] else ""
      required = 'required' if 'required' in item and item['required'] else ''
      requiredLabel = f'<strong>{item["name"]} *</strong>' if required != "" else item["name"]
      html += f'<div class="form-group row"><label for="form{item["id"]}" class="col-sm-4 col-form-label mr-2">{requiredLabel}</label><div class="col-sm-6">'
      if item['type'] == "string":
        value = escape(item["value"], quote=True) if "value" in item else ""
        html += f'<input type="text" class="form-control" id="form{item["id"]}" name="{item["id"]}" value="{value}" {required} {disabled}>'
        if disabled != "":
            html += f'<input type="hidden" name="{item["id"]}" value="{value}" />'
      elif item['type'] == "boolean":
        trueselect = "selected" if item['value'] else ""
        falseselect = "selected" if not item['value'] else ""
        html += f"""
        <select name="{item["id"]}" class="form-control" id="form{item["id"]}" {required} >
                <option {trueselect}>True</option>
                <option {falseselect}>False</option>
         </select>
        """

      elif item['type'] == "list":
        multiple = "multiple" if "multiple" in item and item["multiple"] else ""
        m = "[]" if multiple != "" else ""
        html += f'<select name="{item["id"]}{m}" class="form-control" id="form{item["id"]}" {multiple} {required}>'
        html += f'<option value="">Select value</option>' if multiple == "" else ""
        for option in item['options']:
          if multiple == "":
            if "value" in item:
              selected = 'selected' if item['value'] == option else ""
            else:
              selected = ''
          else:
            if "values" in item:
              selected = 'selected' if option in item['values'] else ""
            else:
              selected = ""
          html += f'<option {selected}>{option}</option>'
        html += '</select>'
      elif item['type'] == "yaml":
        value = yaml.dump(item["value"], default_flow_style = False) if "value" in item and item["value"] != "" else ""
        value = escape(value, quote=True)
        html += f'<div id="pre-editor-{item["id"]}"></div><div id="editor-{item["id"]}" class=" editor " {required} >{value}</div><script>editors["{item["id"]}"] = ace.edit("editor-{item["id"]}"); editors["{item["id"]}"].session.setMode("ace/mode/yaml"); </script>'
      html += '</div></div>'
    html += '<div class="offset-sm-5"><button type="submit" id="submit" style="display: none" class="btn btn-primary">Submit</button></div>'
    html += "</form>"
    return html


def formData(request):
  body = {'spec' : {}}
  yamlfields = ["environments", "attributes", "defaultAttributes", "requiredAttributes"]
  for k in request.form:
      v = request.form[k]
      if k != "name":
        if k in yamlfields:
          try:
            v = yaml.load(v)
          except:
            print(f'unable to parse yaml : {v}')
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
    ],
    "providers": [
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
        },
        {
        "id": "defaultAttributes",
        "type": "yaml",
        "name": "Default Attributes",
        },
        {
        "id": "environments",
        "type": "yaml",
        "name": "Environments",
        },
    ],
    "modules": [
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
        {
        "id": "attributes",
        "type": "yaml",
        "name": "Attributes",
        "required": True,
        },
    ],
    "moduletemplates": [
        {
        "id": "name",
        "type": "string",
        "name": "Name",
        "required": True,
        "value": ""
        },
        {
        "id": "defaultAttributes",
        "type": "yaml",
        "name": "Default Attributes",
        "required": True,
        },
        {
        "id": "requiredAttributes",
        "type": "yaml",
        "name": "Required Attributes",
        },
        {
        "id": "environments",
        "type": "yaml",
        "name": "Environments",
        }
    ],

    "states" : [
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
        "name": "Auto Delete Job On Plan Delated",
        "required": True,
        "value": True
        },
        {
        "id": "deletePlansOnPlanDeleted",
        "type": "boolean",
        "name": "Auto Delete Plan On Plan Delated",
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
    form['clusterproviders'] = form['providers']
    form['clustermoduletemplates'] = form['moduletemplates']
    return form[plural]

def editForm(form, plural, obj):
    if plural == "planrequests":
        form = updateForm(form, "name", "value", obj['metadata']['name'])
        form = updateForm(form, "name", "disabled", True)
        form = updateForm(form, "deletePlanOnDeleted", "value", obj['spec']['deletePlanOnDeleted'])
    elif plural == "states":
        form = updateForm(form, "name", "value", obj['metadata']['name'])
        form = updateForm(form, "name", "disabled", True)
        form = updateForm(form, "autoPlanApprove", "value", obj['spec']['autoPlanApprove'])
        form = updateForm(form, "autoPlanRequest", "value", obj['spec']['autoPlanRequest'])
        form = updateForm(form, "deleteJobsOnPlanDeleted", "value", obj['spec']['deleteJobsOnPlanDeleted'])
        form = updateForm(form, "deletePlansOnPlanDeleted", "value", obj['spec']['deletePlansOnPlanDeleted'])
        form = updateForm(form, "customTerraformInit", "value", obj['spec']['customTerraformInit'])
        form = updateForm(form, "tfExecutorImage", "value", obj['spec']['tfExecutorImage'])
        form = updateForm(form, "tfExecutorImagePullPolicy", "value", obj['spec']['tfExecutorImagePullPolicy'])
        form = updateForm(form, "tfGeneratorImage", "value", obj['spec']['tfGeneratorImage'])
        form = updateForm(form, "tfGeneratorImagePullPolicy", "value", obj['spec']['tfGeneratorImagePullPolicy'])
        form = updateForm(form, "clusterProviders", "values", obj['spec']['clusterProviders'] if "clusterProviders" in obj["spec"] else "")
        form = updateForm(form, "environment", "values", obj['spec']['environment'] if 'environment' in obj["spec"] else "")
    elif plural == "providers" or plural == "clusterproviders":
        form = updateForm(form, "name", "value", obj['metadata']['name'])
        form = updateForm(form, "name", "disabled", True)
        form = updateForm(form, "autoPlanRequest", "value", obj['spec']['autoPlanRequest'])
        form = updateForm(form, "type", "value", obj['spec']['type'])
        form = updateForm(form, "environments", "value", obj['spec']['environments'] if 'environments' in obj["spec"] else "")
        form = updateForm(form, "defaultAttributes", "value", obj['spec']['defaultAttributes'] if 'defaultAttributes' in obj["spec"] else "")
    elif plural == "moduletemplates" or plural == "clustermoduletemplates":
        form = updateForm(form, "name", "value", obj['metadata']['name'])
        form = updateForm(form, "name", "disabled", True)
        form = updateForm(form, "environments", "value", obj['spec']['environments'] if 'environments' in obj["spec"] else "")
        form = updateForm(form, "defaultAttributes", "value", obj['spec']['defaultAttributes'] if 'defaultAttributes' in obj["spec"] else "")
        form = updateForm(form, "requiredAttributes", "value", obj['spec']['requiredAttributes'] if 'requiredAttributes' in obj["spec"] else "")
    elif plural == "modules":
        form = updateForm(form, "name", "value", obj['metadata']['name'])
        form = updateForm(form, "name", "disabled", True)
        form = updateForm(form, "moduleTemplate", "value", obj['spec']['moduleTemplate']  if 'moduleTemplate' in obj["spec"] else "")
        form = updateForm(form, "clusterModuleTemplate", "value", obj['spec']['clusterModuleTemplate']  if 'clusterModuleTemplate' in obj["spec"] else "")
        form = updateForm(form, "attributes", "value", obj['spec']['attributes'])
        form = updateForm(form, "autoPlanRequest", "value", obj['spec']['autoPlanRequest'])
    return form

def updateForm(form, keyid, attr, val):
  i = 0
  for k in form:
    if k["id"] == keyid:
      form[i][attr] = val
    i = i + 1
  return form

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
      { "name" : "State", "field": "state"},
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

def genTable(mapping, name, ajax):
  ths = ""
  for k in mapping:
    ths+= f'<th>{k["name"]}</th>'
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
        // "order": [[1, 'asc']]
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
