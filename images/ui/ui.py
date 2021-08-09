from flask import Flask, request, render_template, abort, flash, redirect, url_for, jsonify, session, send_file
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user, current_user
from html import escape
from sys import exit
import os, json, re, kubernetes, random, string
from kubernetes import client
from kubernetes.client.rest import ApiException
import yaml
import utils
from functools import wraps

try:
    kubernetes.config.load_kube_config()
except:
    kubernetes.config.load_incluster_config()

API_GROUP = 'terraform.dst.io'
API_VERSION = 'v1'
_k8s_custom = kubernetes.client.CustomObjectsApi()
_k8s_core = kubernetes.client.CoreV1Api()
_k8s_rbac = kubernetes.client.RbacAuthorizationV1Api()

app_secret = os.getenv('APP_SECRET', 'default_secret')
app_debug = os.getenv('APP_DEBUG', False)
users_file = os.getenv('USERS_FILE', 'users.json')

try:
  with open(users_file) as f:
    users = json.load(f)
except:
  print('Unable to load json file : {}'.format(users_file))
  exit(1)


app = Flask(__name__)
app.secret_key = app_secret
app.debug = True if app_debug == "1" else False
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_message = None
login_manager.login_view = "login"


clusterplurals = ["clusterproviders", "clustermoduletemplates" ]
plurals = [
  "plans",
  "planrequests",
  "ansibleplans",
  "ansibleplanrequests",
  "states",
  "providers",
  "moduletemplates",
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

class User(UserMixin):
  def __init__(self, username):
    self.id = username
    self.username = username


def checkUser(username, password):
  for i in users:
    if i['username'] == username and i['password'] == password:
      return True
  return False

def getState(namespace):
    try:
        a = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'states', namespace)
        return True
    except:
        return False

def deleteKind(plural, name, namespace):
  cluster = True if namespace == None else False
  kind = utils.formatApiKind(plural)
  try:
    if cluster:
      _k8s_custom.delete_cluster_custom_object(API_GROUP, API_VERSION,  plural, name)
    else:
      _k8s_custom.delete_namespaced_custom_object(API_GROUP, API_VERSION,  namespace, plural, name)
    flash(f'{kind}/{name} successfully deleted', 'success')
  except ApiException as e:
    flash(f'Error occured during deleting {kind}/{name} : {e}', 'error')

def saveKind(plural, method, request, namespace):
  cluster  = True if namespace == None else False
  kind = utils.formatApiKind(plural)
  if method == 'edit':
    #_k8s_obj = _k8s_custom.replace_cluster_custom_object if cluster else _k8s_custom.replace_namespaced_custom_object
    _k8s_obj = _k8s_custom.patch_cluster_custom_object if cluster else _k8s_custom.patch_namespaced_custom_object
  else:
    _k8s_obj = _k8s_custom.create_cluster_custom_object if cluster else _k8s_custom.create_namespaced_custom_object
  body = utils.formData(request)
  if body == None:
    flash(f'Error occured during saving {kind}/{request.form["name"]} : JSON invalid', 'error')
    return
  print(f"Saving {plural}/{request.form["name"]} [{current_user.username}]: {body}")
  body['apiVersion'] = f'{API_GROUP}/{API_VERSION}'
  body['kind']= kind
  #version = ""
  #if method == "edit":
  #  obj = utils.getObj(plural, request.form["name"], namespace=namespace)
  #  version = obj['metadata']['resourceVersion']
  if cluster:
    body['metadata'] = client.V1ObjectMeta(name=f'{request.form["name"]}')
  else:
    body['metadata'] = client.V1ObjectMeta(name=f'{request.form["name"]}', namespace=namespace)
  if cluster:
    try:
      if method == "create":
        _k8s_obj(API_GROUP, API_VERSION, plural, body=body)
      else:
        _k8s_obj(API_GROUP, API_VERSION, plural, name=request.form['name'], body=body)
      flash(f'{kind}/{request.form["name"]} successfully saved', 'success')
    except ApiException as e:
      flash(f'Error occured during saving {kind}/{request.form["name"]} : {e} <br /> body: {body}', 'error')
  else:
    try:
      if method == "create":
        _k8s_obj(API_GROUP, API_VERSION, namespace, plural, body=body)
      else:
        _k8s_obj(API_GROUP, API_VERSION, namespace, plural, name=request.form['name'], body=body)
      flash(f'{kind}/{request.form["name"]} successfully saved', 'success')
    except ApiException as e:
      flash(f'Error occured during saving {kind}/{request.form["name"]} : {e} <br /> body: {body}', 'error')      

def genToken():
  return ''.join(random.choice(string.ascii_letters) for i in range(16))

def nsexist(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
      if kwargs['namespace'] not in utils.getNamespace():
        abort(404)
      return function(**kwargs)
    return wrapper

@login_manager.user_loader
def load_user(userid):
  return User(userid)

@app.route("/logout")
@login_required
def logout():
  logout_user()
  return redirect('/login')


@app.route("/login", methods=["GET", "POST"])
def login():
  error = None
  if request.method == 'POST':
    username = request.form['username']
    password = request.form['password']
    if checkUser(username, password):
      user = User(username)
      login_user(user)
      return redirect(request.args.get("next") or '/')
    else:
      error = 'Invalid Credentials. Please try again.'
  return render_template('login.html', error=error)


@app.route('/')
@app.route('/plans')
@app.route('/plans/')
@login_required
def plans():
  session['namespace'] = None
  m = [{ "name" : "State", "field": "namespace"}] + utils.apiMapping('plans')
  m2 = [{ "name" : "State", "field": "namespace"}] + utils.apiMapping('planrequests')
  plansTable, plansJs = utils.genTable(m, 'plans', '/api/plans')
  planRequestsTable, planRequestsJs =  utils.genTable(m2, 'planrequests', '/api/planrequests')
  js = plansJs + planRequestsJs
  return render_template("plans.html",plural='plans', namespace=None, plansTable=plansTable, planRequestsTable=planRequestsTable, js=js, namespaces=utils.getNamespace(),username=current_user.username,state=False)

@app.route('/plans/<namespace>')
@app.route('/plans/<namespace>/')
@nsexist
@login_required
def plansNamespaced(namespace):
  session["namespace"]=namespace
  if request.args.get('approve') == "true" and request.args.get('name') != "":
    try:
      _k8s_custom.patch_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'plans', name=request.args.get('name'), body={'spec': {'approved': True}})
      flash(f'Plan {request.args.get("name")} successfully approved', 'success')
    except ApiException as e:
      flash(f'Error occured during approval {request.args.get("name")} : {e}', 'error')

  plansTable, plansJs = utils.genTable(utils.apiMapping('plans'), 'plans', f'/api/plans/{namespace}/')
  planRequestsTable, planRequestsJs =  utils.genTable(utils.apiMapping('planrequests'), 'planrequests', f'/api/planrequests/{namespace}/')
  js = plansJs + planRequestsJs
  return render_template("plans.html",plural='plans', namespace=namespace, plansTable=plansTable, planRequestsTable=planRequestsTable, js=js, namespaces=utils.getNamespace(),username=current_user.username,state=getState(namespace))

@app.route('/ansibleplans/<namespace>')
@app.route('/ansibleplans/<namespace>/')
@nsexist
@login_required
def ansplansNamespaced(namespace):
  session["namespace"]=namespace
  if request.args.get('approve') == "true" and request.args.get('name') != "":
    try:
      _k8s_custom.patch_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansibleplans', name=request.args.get('name'), body={'spec': {'approved': True}})
      flash(f'Plan {request.args.get("name")} successfully approved', 'success')
    except ApiException as e:
      flash(f'Error occured during approval {request.args.get("name")} : {e}', 'error')

  plansTable, plansJs = utils.genTable(utils.apiMapping('plans'), 'plans', f'/api/plans/{namespace}/')
  planRequestsTable, planRequestsJs =  utils.genTable(utils.apiMapping('planrequests'), 'planrequests', f'/api/planrequests/{namespace}/')
  js = plansJs + planRequestsJs
  return render_template("plans.html",plural='plans', namespace=namespace, plansTable=plansTable, planRequestsTable=planRequestsTable, js=js, namespaces=utils.getNamespace(),username=current_user.username,state=getState(namespace))


@app.route('/plans/<namespace>/<name>')
@nsexist
@login_required
def plan(namespace, name):
  try:
    plan = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'plans', name)
  except:
    flash(f'Unable to find plan {name}', 'error')
    return render_template("plan.html", namespace=namespace, plan=None, namespaces=utils.getNamespace(),username=current_user.username,state=getState(namespace))
  
  planOutput, applyOutput, css = ("", "", "")
  if 'planOutput' in plan['status'] and plan['status']['planOutput']  != "":
    planOutput, planCSS = utils.ansi2html(plan['status']['planOutput'])
    css  = planCSS + css
  
  if 'applyOutput' in plan['status'] and plan['status']['applyOutput']  != "":
    applyOutput, applyCSS = utils.ansi2html(plan['status']['applyOutput'])
    css = css + applyCSS
  
  return render_template("plan.html",plural='plans', namespace=namespace, plan=plan, css=css, planOutput=planOutput, applyOutput=applyOutput, namespaces=utils.getNamespace(),username=current_user.username,state=getState(namespace))

@app.route('/ansibleplans/<namespace>/<name>')
@nsexist
@login_required
def ansplan(namespace, name):
  try:
    plan = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansibleplans', name)
  except:
    flash(f'Unable to find plan {name}', 'error')
    return render_template("plan.html", namespace=namespace, plan=None, namespaces=utils.getNamespace(),username=current_user.username,state=getState(namespace))
  
  planOutput, applyOutput, css = ("", "", "")
  if 'planOutput' in plan['status'] and plan['status']['planOutput']  != "":
    planOutput, planCSS = utils.ansi2html(plan['status']['planOutput'])
    css  = planCSS + css
  
  if 'applyOutput' in plan['status'] and plan['status']['applyOutput']  != "":
    applyOutput, applyCSS = utils.ansi2html(plan['status']['applyOutput'])
    css = css + applyCSS
  
  return render_template("plan.html",plural='ansibleplans', namespace=namespace, plan=plan, css=css, planOutput=planOutput, applyOutput=applyOutput, namespaces=utils.getNamespace(),username=current_user.username,state=getState(namespace))



@app.route('/states/_new')
@app.route('/states/_new/')
@login_required
def new_states():
  form = utils.getForm('states')
  form = json.dumps(utils.safeDump(form))
  return render_template("edit.html",pluralTitle='State', name=f"New State", plural='states', mode="create", action="create", form=form, namespaces=utils.getNamespace(),username=current_user.username, namespace=None)

@app.route('/states', methods=['POST'])
@app.route('/states/', methods=['POST'])
@login_required
def states():
  kind = utils.formatApiKind('states')
  body = utils.formData(request)
  body['apiVersion'] = f'{API_GROUP}/{API_VERSION}'
  body['kind']= kind
  body['metadata'] = client.V1ObjectMeta(name=f'{request.form["name"]}', namespace=f'{request.form["name"]}')
  form = utils.getForm('states')
  form = json.dumps(utils.safeDump(form))
  try:
    api_response = _k8s_core.create_namespace(client.V1Namespace(metadata=client.V1ObjectMeta(name=request.form["name"], labels={"toolbox-managed": "true"})))
    if api_response.status.phase == 'Active':
      try:
        _k8s_custom.create_namespaced_custom_object(API_GROUP, API_VERSION, request.form["name"], "states", body=body)
        _k8s_core.create_namespaced_service_account(request.form["name"], client.V1ServiceAccount(metadata=client.V1ObjectMeta(name='tfgen')))
        _k8s_rbac.create_cluster_role_binding(client.V1ClusterRoleBinding(metadata=client.V1ObjectMeta(name=f'tfgen-cluster-admin-{request.form["name"]}'), role_ref=client.V1RoleRef(api_group="rbac.authorization.k8s.io", kind="ClusterRole", name="cluster-admin"), subjects=[client.V1Subject(name='tfgen', namespace=request.form["name"], kind='ServiceAccount')] ))
      except ApiException as e:
        flash(f'Error occured during saving {kind}/{request.form["name"]} : {e} <br /> body: {body}', 'error')
        return render_template("edit.html",pluralTitle='State', name=f"New State", plural='states', mode="create", action="create", form=form, namespaces=utils.getNamespace(),username=current_user.username, namespace=None)
  except ApiException as e:
    flash(f'Error occured during saving Namespace/{request.form["name"]} : {e} <br /> body: {body}', 'error')
    return render_template("edit.html",pluralTitle='State', name=f"New State", plural='states', mode="create", action="create", form=form, namespaces=utils.getNamespace(),username=current_user.username, namespace=None)

  flash(f'State/{request.form["name"]} successfully created', 'success')
  return redirect(f'/plans/{request.form["name"]}/')

@app.route('/<plural>/<namespace>/_new')
@nsexist
@login_required
def new(plural, namespace):
  if plural not in plurals:
    abort(404)
  form = utils.getForm(plural,namespace)
  
  if plural == "states":
    form[0]['fields'][0]['value'] = namespace
    form[0]['fields'][0]['disabled'] = True
  form = json.dumps(utils.safeDump(form))
  return render_template("edit.html",pluralTitle=plural.title(), action="create", namespace=namespace, name=f"New {plural.title()}", plural=plural, mode="create", form=form, namespaces=utils.getNamespace(),username=current_user.username,state=getState(namespace))


@app.route('/<plural>/<namespace>/<name>/edit')
@nsexist
@login_required
def edit(plural, namespace, name):
  obj = utils.getObj(plural, name, namespace=namespace)
  if obj == None:
    abort(404)

  form = utils.updateFieldsValues(utils.getForm(plural, namespace), plural, obj)
  form = json.dumps(utils.safeDump(form))
  return render_template("edit.html",pluralTitle=plural.title(), action="edit", plural=plural, name=name, namespace=namespace, form=form, namespaces=utils.getNamespace(),username=current_user.username,state=getState(namespace))

@app.route('/cluster/<plural>/<name>/edit')
@login_required
def editCluster(plural, name):
  obj = utils.getObj(plural, name)
  if obj == None:
    abort(404)
  
  form = utils.updateFieldsValues(utils.getForm(plural), plural, obj)
  form = json.dumps(utils.safeDump(form))

  return render_template("edit.html",pluralTitle=plural.title(), plural=plural,  action="edit", name=name, namespace=session.get("namespace",None), form=form, namespaces=utils.getNamespace(),username=current_user.username)

@app.route('/cluster/<plural>/_new')
@login_required
def newCluster(plural):
  if plural not in clusterplurals:
    abort(404)
  form = utils.getForm(plural)
  form = json.dumps(utils.safeDump(form))
  return render_template("edit.html",pluralTitle=plural.title(), action="create", namespace=session.get("namespace",None), name=f"New {plural.title()}", plural=plural, mode="create", form=form, namespaces=utils.getNamespace(),username=current_user.username)


@app.route('/<plural>')
@app.route('/<plural>/')
@login_required
def plural(plural):
  if plural not in plurals:
    abort(404)

  plural = plural
  m = [{ "name" : "NS", "field": "namespace"}] + utils.apiMapping(plural)
  table, js = utils.genTable(m, plural, f'/api/{plural}')
  return render_template("objs.html", plural=plural, objs=plural.title(), pluralTitle=plural.title(), namespace=None, table=table, js=js, namespaces=utils.getNamespace(),username=current_user.username)

  
@app.route('/cluster/<plural>', methods=['GET', 'POST'])
@app.route('/cluster/<plural>/', methods=['GET', 'POST'])
@login_required
def clusterPlural(plural):
  if plural not in clusterplurals:
    abort(404)
  if request.method == "POST":
    method = "edit" if request.args.get('edit') == "true" else "create"
    saveKind(plural, method, request, None)
  if request.args.get('delete') == "true" and request.args.get('name') != "":
    deleteKind(plural, request.args.get('name'), None)

  plural = plural
  table, js = utils.genTable(utils.apiMapping(plural), plural, f'/api/{plural}')
  return render_template("objs.html", plural=plural, objs=plural.title(), pluralTitle=plural.title(), namespace=session.get("namespace",None), table=table, js=js, namespaces=utils.getNamespace(),username=current_user.username)
 

@app.route('/cluster/<plural>/<name>')
@login_required
def pluralName(plural, name):
  obj = utils.getObj(plural, name)
  if obj == None:
    abort(404)
  return render_template("obj.html", obj=obj, plural=plural, pluralTitle=plural.title(), name=name, namespace=None, namespaces=utils.getNamespace(),username=current_user.username)

@app.route('/<plural>/<namespace>', methods=['GET', 'POST'])
@app.route('/<plural>/<namespace>/', methods=['GET', 'POST'])
@nsexist
@login_required
def pluralNamespaced(plural, namespace):
  if plural not in plurals:
    abort(404)
  session["namespace"]=namespace
  
  if request.method == "POST":
    method = "edit" if request.args.get('edit') == "true" else "create"
    saveKind(plural, method, request, namespace)

  if request.args.get('delete') == "true" and request.args.get('name') != "":
    deleteKind(plural, request.args.get('name'), namespace)

  table, js = utils.genTable(utils.apiMapping(plural), plural, f'/api/{plural}/{namespace}')
  if plural == "states":
    return redirect(f'/plans/{namespace}/')
  else:
    return render_template("objs.html", plural=plural, objs=plural.title(), pluralTitle=plural.title(), table=table, namespace=namespace, js=js, namespaces=utils.getNamespace(),username=current_user.username,state=getState(namespace))


@app.route('/<plural>/<namespace>/<name>')
@nsexist
@login_required
def pluralNameNamespaced(plural, namespace, name):
  obj = utils.getObj(plural, name, namespace=namespace)
  if obj == None:
    abort(404)
    return
  session["namespace"]=namespace
  return render_template("obj.html", namespace=namespace, obj=obj, plural=plural, pluralTitle=plural.title(), name=name, namespaces=utils.getNamespace(),username=current_user.username,state=getState(namespace))

@app.route('/api/<plural>')
@app.route('/api/<plural>/')
@login_required
def apiPlural(plural):
  if plural not in clusterplurals and plural not in plurals:
    abort(404)
  out = []

  for item in _k8s_custom.list_cluster_custom_object(API_GROUP, API_VERSION, plural)["items"]:
    out.append(utils.formatKind(plural, item))
  if plural == "plans":
    for item in _k8s_custom.list_cluster_custom_object(API_GROUP, API_VERSION, "ansibleplans")["items"]:
      out.append(utils.formatKind("ansibleplans", item))
  if plural == "planrequests":
    for item in _k8s_custom.list_cluster_custom_object(API_GROUP, API_VERSION, "ansibleplanrequests")["items"]:
      out.append(utils.formatKind("ansibleplanrequests", item))
  out = [ utils.escapeAttribute(x) for x in out ]
  return jsonify({'data': out})

@app.route('/api/<plural>/<namespace>')
@app.route('/api/<plural>/<namespace>/')
@nsexist
@login_required
def apiPluralNamespaced(plural, namespace):
  if plural not in plurals:
    abort(404)
  out = []
  for item in _k8s_custom.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, plural)["items"]:
    out.append(utils.formatKind(plural, item))
  if plural == "plans":
    for item in _k8s_custom.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, "ansibleplans")["items"]:
      out.append(utils.formatKind("ansibleplans", item))
  if plural == "planrequests":
    for item in _k8s_custom.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, "ansibleplanrequests")["items"]:
      out.append(utils.formatKind("ansibleplanrequests", item))

  return jsonify({'data': out})


attrtypes = [
  {"name": "String", "type": "sValue"},
  {"name": "Integer", "type": "iValue"},
  {"name": "Number", "type": "nValue"},
  {"name": "Boolean", "type": "bValue"},
  {"name": "String[]", "type": "lsValue"},
  {"name": "Integer[]", "type" : "liValue"},
  {"name": "Number[]", "type" : "lnValue"},
  {"name": "Boolean[]", "type": "lbValue"},
]

@app.route('/api/moduletemplates/<namespace>/<name>/requiredAttributes')
@nsexist
@login_required
def apiModRequiredAttributes(namespace, name):
  try:
    item = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'moduletemplates', name)
  except ApiException:
    abort(404)
  r = []
  if "requiredAttributes" in item['spec']:
    for attribute in item['spec']["requiredAttributes"]:
      val = [] if attribute['type'].startswith('l') else ''
      r.append({"name": attribute["name"], attribute["type"]: val})
  return jsonify(utils.escapeAttribute(r))

@app.route('/api/moduletemplates/<namespace>/<name>/hattributes')
@nsexist
@login_required
def apiHeritedModAttributes(namespace, name):
  try:
    item = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'moduletemplates', name)
  except ApiException:
    abort(404)
  r = []
  for sec in utils.safeDump(utils.updateFieldsValues(utils.getForm('moduletemplates', namespace), 'moduletemplates', item)):
    if sec['id'] in ['defaultAttributes', 'ansibleSpec', 'ansibleRoles', 'ansibleVars', "ansibleDependencies"]:
      r.append(sec) 
  return jsonify(r)

@app.route('/api/moduletemplates/<namespace>/<name>/attributes')
@nsexist
@login_required
def apiModAttributes(namespace, name):
  try:
    item = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'moduletemplates', name)
  except ApiException:
    abort(404)
  r =  []
  attrtype = 'requiredAttributes' if request.args.get('required') == "true" else "defaultAttributes"

  for attribute in item['spec']["defaultAttributes"]:
    key = None
    for attrtype in attrtypes:
      key = attrtype['type'] if attrtype['type'] in attribute else key
    if request.args.get('qry') in attribute['name']:
      r.append({'value': utils.escapeAttribute(key), 'text': utils.escapeAttribute(attribute['name'])})
  return jsonify(r)

@app.route('/api/clustermoduletemplates/<name>/requiredAttributes')
@login_required
def apiClusterModRequiredAttributes(name):
  try:
    item = _k8s_custom.get_cluster_custom_object(API_GROUP, API_VERSION, 'clustermoduletemplates', name)
  except ApiException:
    abort(404)
  r = []
  if "requiredAttributes" in item['spec']:
    for attribute in item['spec']["requiredAttributes"]:
      val = [] if attribute['type'].startswith('l') else ''
      r.append({"name": attribute["name"], attribute["type"]: val})
  return jsonify(utils.escapeAttribute(r))


def updateAttribute(sections, section_id, field_id, newattribute):
  out = []
  for section in sections:
    if section_id == section['id']:
      fields = []
      for field in section['fields']:
        if field['id'] == field_id:
          value = '' if type(newattribute) == type('') else []
          if type(newattribute) == type(''):
            value = newattribute
          elif len(field['value']) != 0 and type(field['value'][0]) == type(''):
              value.append(newattribute)
          else:
            for attribute in field['value']:
                if attribute['name'] == newattribute['name']:
                  value.append(newattribute)
                else: 
                  value.append(attribute)
            found = False
            for attribute in value:
              if attribute['name'] == newattribute['name']:
                found = True
            if not found:
              value.append(newattribute) 
          newfield = {'type': field['type'], 'id': field['id'], 'value': value}
          if 'name' in field:
            newfield['name'] = field['name']
          if "options" in field:
            newfield['options'] = field['options']
          fields.append(newfield)
        else:
          fields.append(field)
      out.append({'id': section['id'], 'name': section['name'], 'fields' : fields})
    else:
      out.append(section)
  return out


@app.route('/api/clustermoduletemplates/<namespace>/<name>/hattributes')
@login_required
def apiClusterHeritedModAttributes(namespace, name):
  try:
    item = _k8s_custom.get_cluster_custom_object(API_GROUP, API_VERSION, 'clustermoduletemplates', name)
  except ApiException:
    abort(404)
  try:
    stateenv = _k8s_custom.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'states', namespace)
  except ApiException:
    abort(404)
  r = []
  for sec in utils.safeDump(utils.updateFieldsValues(utils.getForm('clustermoduletemplates'), 'clustermoduletemplates', item)):
    if sec['id'] in ['defaultAttributes', 'ansibleSpec', 'ansibleRoles', 'ansibleVars', "ansibleDependencies"]:
      r.append(sec)
  if "environment" in stateenv['spec'] and "environments" in item['spec']:
    for env in item['spec']['environments']:
      if env['name'] == stateenv['spec']['environment']:
        if "defaultAttributes" in env:
          for envattr in env['defaultAttributes']:
            r = updateAttribute(r, "defaultAttributes", "defaultAttributes", utils.escapeAttribute(envattr))
        if "ansibleAttributes" in env and "vars" in env["ansibleAttributes"]:
          for envattr in env["ansibleAttributes"]['vars']:
            r = updateAttribute(r, "ansibleVars", "ansibleVars", utils.escapeAttribute(envattr))
        if "ansibleAttributes" in env and "roles" in env["ansibleAttributes"]:
          r = updateAttribute(r, "ansibleRoles", "ansibleRoles", utils.escapeAttribute(env["ansibleAttributes"]['roles']))
        if "ansibleAttributes" in env and "dependencies" in env["ansibleAttributes"]:
          r = updateAttribute(r, "ansibleDependencies", "ansibleDependencies", utils.escapeAttribute(env["ansibleAttributes"]['dependencies']))
        if "ansibleAttributes" in env and "defaultGalaxyServer" in env["ansibleAttributes"]:
          r = updateAttribute(r, "ansibleSpec", "ansible_defaultGalaxyServer", utils.escapeAttribute(env["ansibleAttributes"]["defaultGalaxyServer"]))
        if "ansibleAttributes" in env and "credentials" in env["ansibleAttributes"]:
          r = updateAttribute(r, "ansibleSpec", "ansible_cred_user", utils.escapeAttribute(env["ansibleAttributes"]["credentials"]['user']))
          r = updateAttribute(r, "ansibleSpec", "ansible_cred_password", utils.escapeAttribute(env["ansibleAttributes"]["credentials"]['password']))
          r = updateAttribute(r, "ansibleSpec", "ansible_cred_ssh_key", utils.escapeAttribute(env["ansibleAttributes"]["credentials"]['ssh_key']))
          r = updateAttribute(r, "ansibleSpec", "ansible_cred_type", utils.escapeAttribute(env["ansibleAttributes"]["credentials"]['type']))
  return jsonify(r)

@app.route('/api/clustermoduletemplates/<name>/attributes')
@login_required
def apiClusterModAttributes(name):
  try:
    item = _k8s_custom.get_cluster_custom_object(API_GROUP, API_VERSION, 'clustermoduletemplates', name)
  except ApiException:
    abort(404)
  r =  []

  for attribute in item['spec']["defaultAttributes"]:
    key = None
    for attrtype in attrtypes:
      key = attrtype['type'] if attrtype['type'] in attribute else key
    if request.args.get('qry') in attribute['name']:
      r.append({'value': utils.escapeAttribute(key), 'text': utils.escapeAttribute(attribute['name'])})
  return jsonify(r)