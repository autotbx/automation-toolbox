from flask import Flask, request, render_template, abort, flash, redirect, url_for, jsonify, session, send_file
#from flask.ext.session import Session
from sys import exit
import os, json, re, kubernetes
from kubernetes import client
from kubernetes.client.rest import ApiException
from cgi import escape
import yaml
import utils

try:
    kubernetes.config.load_kube_config()
except:
    kubernetes.config.load_incluster_config()

API_GROUP = 'terraform.dst.io'
API_VERSION = 'v1'
_k8s_custom = kubernetes.client.CustomObjectsApi()

os.environ['APP_SECRET'] = 'aze'
os.environ['APP_DEBUG'] = "1"

required_env = ['APP_SECRET', 'APP_DEBUG']

def initcheck():
  missing_keys = []
  for key in required_env:
    if not key in os.environ:
      missing_keys.append(key)
  if len(missing_keys) != 0:
    print('Missing required env vars : {}'.format(','.join(missing_keys)))
    exit(4)

initcheck()
app = Flask(__name__)
app.secret_key = os.environ['APP_SECRET']
app.debug = True if os.environ['APP_DEBUG'] == "1" else False
#Session(app)
#app.config['aze'] = os.environ['aze']

# TODO
# custom format spec/status for generic argument
# custom action:
#   editable: true|false
#   html field from spec ? 

namespace="default"

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

@app.template_filter('yaml')
def ym(val):
  if type(val) == type(''):
    return val
  if type(val) == type(True):
    return val
  else:
    return escape(yaml.dump(val, default_flow_style = False), quote=True).replace("\n", "<br />")

@app.route('/')
@app.route('/dashboard')
def hello_world():
  if 'aze' in session:
    print('ok')
  else:
    print('uuu')
    session['aze'] = "oooo"
  return render_template("dashboard.html", namespaces=utils.getNamespace())


@app.route('/plans')
@app.route('/plans/')
def plans():
  m = [{ "name" : "NS", "field": "namespace"}] + utils.apiMapping('plans')
  m2 = [{ "name" : "NS", "field": "namespace"}] + utils.apiMapping('planrequests')
  plansTable, plansJs = utils.genTable(m, 'plans', '/api/plans')
  planRequestsTable, planRequestsJs =  utils.genTable(m2, 'planrequests', '/api/planrequests')
  js = plansJs + planRequestsJs
  return render_template("plans.html",plural='plans', namespace=None, plansTable=plansTable, planRequestsTable=planRequestsTable, js=js, namespaces=utils.getNamespace())

@app.route('/plans/<namespace>')
@app.route('/plans/<namespace>/')
def plansNamespaced(namespace):
  if request.args.get('approve') == "true" and request.args.get('name') != "":
    try:
      _k8s_custom.patch_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'plans', name=request.args.get('name'), body={'spec': {'approved': True}})
      flash(f'Plan {request.args.get("name")} successfully approved', 'success')
    except ApiException as e:
      flash(f'Error occured during approval {request.args.get("name")} : {e}', 'error')

  plansTable, plansJs = utils.genTable(utils.apiMapping('plans'), 'plans', f'/api/plans/{namespace}/')
  planRequestsTable, planRequestsJs =  utils.genTable(utils.apiMapping('planrequests'), 'planrequests', f'/api/planrequests/{namespace}/')
  js = plansJs + planRequestsJs
  return render_template("plans.html",plural='plans', namespace=namespace, plansTable=plansTable, planRequestsTable=planRequestsTable, js=js, namespaces=utils.getNamespace())


@app.route('/plans/<namespace>/<name>')
def plan(namespace, name):
  try:
    plan = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'plans', name)
  except:
    flash(f'Unable to find plan {name}', 'error')
    return render_template("plan.html", namespace=namespace, plan=None, namespaces=utils.getNamespace())
  
  planOutput, applyOutput, css = ("", "", "")
  if 'planOutput' in plan['status'] and plan['status']['planOutput']  != "":
    planOutput, planCSS = utils.ansi2html(plan['status']['planOutput'])
    css  = planCSS + css
  
  if 'applyOutput' in plan['status'] and plan['status']['applyOutput']  != "":
    applyOutput, applyCSS = utils.ansi2html(plan['status']['applyOutput'])
    css = css + applyCSS
  
  return render_template("plan.html",plural='plans', namespace=namespace, plan=plan, css=css, planOutput=planOutput, applyOutput=applyOutput, namespaces=utils.getNamespace())


@app.route('/<plural>/<namespace>/_new')
def new(plural, namespace):
  if plural not in plurals:
    abort(404)
  form =  utils.getForm(plural)
  print('uuu ' + namespace)
  return render_template("edit.html",pluralTitle=plural.title(), namespace=namespace, name=f"New {plural.title()}", plural=plural, mode="create", form=utils.genForm(form, plural, 'new', namespace), namespaces=utils.getNamespace())

@app.route('/<plural>/<namespace>/<name>/edit')
def edit(plural, namespace, name):
  obj = utils.getObj(plural, name, namespace=namespace)
  if obj == None:
    abort(404)
  form = utils.getForm(plural)
  form = utils.editForm(form, plural, obj)

  if form == None:
    abort(404)

  return render_template("edit.html",pluralTitle=plural.title(), plural=plural, name=name, namespace=namespace, form=utils.genForm(form, plural, 'edit', namespace), namespaces=utils.getNamespace())

@app.route('/cluster/<plural>/<name>/edit')
def editCluster(plural, name):
  obj = utils.getObj(plural, name)
  if obj == None:
    abort(404)
  form = utils.getForm(plural)
  form = utils.editForm(form, plural, obj)

  if form == None:
    abort(404)

  return render_template("edit.html",pluralTitle=plural.title(), plural=plural, name=name, namespace=None, form=utils.genForm(form, plural, 'edit', None), namespaces=utils.getNamespace())

@app.route('/cluster/<plural>/_new')
def newCluster(plural):
  if plural not in plurals:
    abort(404)
  form =  utils.getForm(plural)
  return render_template("edit.html",pluralTitle=plural.title(), namespace=None, name=f"New {plural.title()}", plural=plural, mode="create", form=utils.genForm(form, plural, 'new', None), namespaces=utils.getNamespace())


@app.route('/<plural>', methods=['GET', 'POST'])
@app.route('/<plural>/', methods=['GET', 'POST'])
@app.route('/cluster/<plural>', methods=['GET', 'POST'])
@app.route('/cluster/<plural>/', methods=['GET', 'POST'])
def plural(plural):
  if plural not in plurals:
    abort(404)

  if plural in plurals:
    plural = plural
    m = [{ "name" : "NS", "field": "namespace"}] + utils.apiMapping(plural)
    table, js = utils.genTable(m, plural, f'/api/{plural}')
    return render_template("objs.html", plural=plural, objs=plural.title(), pluralTitle=plural.title(), namespace=None, table=table, js=js, namespaces=utils.getNamespace())
  else:
    abort(404) 

@app.route('/cluster/<plural>/<name>')
def pluralName(plural, name):
  obj = utils.getObj(plural, name)
  if obj == None:
    abort(404)
  return render_template("obj.html", obj=obj, plural=plural, pluralTitle=plural.title(), name=name, namespace=None, namespaces=utils.getNamespace())


@app.route('/<plural>/<namespace>', methods=['GET', 'POST'])
@app.route('/<plural>/<namespace>/', methods=['GET', 'POST'])
def pluralNamespaced(plural, namespace):
  if plural not in plurals:
    abort(404)
  print('hh')
  
  cluster = plural.startswith('cluster') 
  kind = utils.formatApiKind(plural)
  if request.method == "POST":
    if request.args.get('edit') == "true":
      _k8s_obj = _k8s_custom.patch_cluster_custom_object if cluster else _k8s_custom.patch_namespaced_custom_object
    else:
      _k8s_obj = _k8s_custom.create_cluster_custom_object if cluster else _k8s_custom.create_namespaced_custom_object

    body = utils.formData(request)
    print(f"Saving {plural} : {body}")
    if body == None:
      flash(f'Error occured during saving {kind}/{request.form["name"]} : YAML invalid', 'error')
    else:
      if request.args.get('new') == "true":
        body['apiVersion'] = f'{API_GROUP}/{API_VERSION}'
        body['kind']= kind
        if cluster:
          body['metadata'] = client.V1ObjectMeta(name=f'{request.form["name"]}')
        else:
          body['metadata'] = client.V1ObjectMeta(name=f'{request.form["name"]}', namespace=namespace)

      if cluster:
        try:
          if request.args.get('new') == "true":
            _k8s_obj(API_GROUP, API_VERSION, plural, body=body)
          else:
            _k8s_obj(API_GROUP, API_VERSION, plural, name=request.form['name'], body=body)
          flash(f'{kind}/{request.form["name"]} successfully saved', 'success')
        except ApiException as e:
          flash(f'Error occured during saving {kind}/{request.form["name"]} : {e} <br /> body: {body}', 'error')
      else:
        try:
          if request.args.get('new') == "true":
            _k8s_obj(API_GROUP, API_VERSION, namespace, plural, body=body)
          else:
            _k8s_obj(API_GROUP, API_VERSION, namespace, plural, name=request.form['name'], body=body)
          flash(f'{kind}/{request.form["name"]} successfully saved', 'success')
        except ApiException as e:
          flash(f'Error occured during saving {kind}/{request.form["name"]} : {e} <br /> body: {body}', 'error')      

  if request.args.get('delete') == "true" and request.args.get('name') != "":
    try:
      if cluster:
        _k8s_custom.delete_cluster_custom_object(API_GROUP, API_VERSION,  plural, request.args.get('name'))
      else:
        _k8s_custom.delete_namespaced_custom_object(API_GROUP, API_VERSION,  namespace, plural, request.args.get('name'))
      flash(f'{kind}/{request.args.get("name")} successfully deleted', 'success')
    except ApiException as e:
        flash(f'Error occured during deleting {kind}/{request.args.get("name")} : {e}', 'error')
  table, js = utils.genTable(utils.apiMapping(plural), plural, f'/api/{plural}/{namespace}')
  return render_template("objs.html", plural=plural, objs=plural.title(), pluralTitle=plural.title(), table=table, namespace=namespace, js=js, namespaces=utils.getNamespace())


@app.route('/<plural>/<namespace>/<name>')
def pluralNameNamespaced(plural, namespace, name):
  obj = utils.getObj(plural, name, namespace=namespace)
  if obj == None:
    abort(404)
    return
  return render_template("obj.html", namespace=namespace, obj=obj, plural=plural, pluralTitle=plural.title(), name=name, namespaces=utils.getNamespace())

@app.route('/api/<plural>')
@app.route('/api/<plural>/')
def apiPlural(plural):
  if plural not in plurals:
    abort(404)
  out = []
  for item in _k8s_custom.list_cluster_custom_object(API_GROUP, API_VERSION, plural)["items"]:
    out.append(utils.formatKind(plural, item))
  return jsonify({'data': out})

@app.route('/api/<plural>/<namespace>')
@app.route('/api/<plural>/<namespace>/')
def apiPluralNamespaced(plural, namespace):
  if plural not in plurals:
    abort(404)
  out = []
  for item in _k8s_custom.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, plural)["items"]:
    out.append(utils.formatKind(plural, item))
  return jsonify({'data': out})

@app.route('/api/moduletemplates/<namespace>/<name>/attributes')
def apiModAttributes(namespace, name):
  try:
    item = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'moduletemplates', name)
  except ApiException:
    abort(404)

  return yaml.dump({
    'defaultAttributes': item['spec']["defaultAttributes"] if "defaultAttributes" in item['spec'] else {},
    'requiredAttributes': item['spec']["requiredAttributes"] if "requiredAttributes" in item['spec'] else [],
    }, default_flow_style = False)

@app.route('/api/clustermoduletemplates/<name>/attributes')
def apiClusterModAttributes(name):
  try:
    item = _k8s_custom.get_cluster_custom_object(API_GROUP, API_VERSION, 'clustermoduletemplates', name)
  except ApiException:
    abort(404)

  return yaml.dump({
    'defaultAttributes': item['spec']["defaultAttributes"] if "defaultAttributes" in item['spec'] else {},
    'requiredAttributes': item['spec']["requiredAttributes"] if "requiredAttributes" in item['spec'] else [],
    }, default_flow_style = False)