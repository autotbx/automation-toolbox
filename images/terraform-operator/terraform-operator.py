from sys import api_version
import kopf
import kubernetes
from kubernetes import client, config, utils
import kubernetes.client
from kubernetes.client.models.v1_config_map_volume_source import V1ConfigMapVolumeSource
from kubernetes.client.rest import ApiException
import re
import logging

try:
  config.load_kube_config()
except:
  config.load_incluster_config()

configuration = kubernetes.client.Configuration()
configuration.debug = True
configuration.logger_file = '/tmp/k8s.log'

API_GROUP = 'terraform.dst.io'
API_VERSION = 'v1'
TERRAFORM_DELIMETER="-----------------------------------------------------------------------"

custom_api_instance = kubernetes.client.CustomObjectsApi(kubernetes.client.ApiClient(configuration))
batch_api_instance = kubernetes.client.BatchV1Api(kubernetes.client.ApiClient(configuration))
core_api_instance = kubernetes.client.CoreV1Api(kubernetes.client.ApiClient(configuration))

#def login_fn(**kwargs):
#    return kopf.login_via_client(**kwargs)

def updateCustomStatus(logger, plural, namespace, name, vals):
  try:
    currentStatus = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, plural, name)
  except ApiException:
    currentStatus = {}
  if 'status' in currentStatus:
    status = currentStatus['status']
  else:
    status = {}
  newstatus = status
  for k in vals:
    if k == 'plans':
      if 'plans' in status:
        combined = status["plans"] + vals[k]
      else:
        combined = vals[k]
      newstatus[k] = combined
    else:
      newstatus[k] = vals[k]

  body = {'status': newstatus}
  try:
    ret = custom_api_instance.patch_namespaced_custom_object_status(API_GROUP, API_VERSION, namespace, plural, name, body)
    logger.info(ret)
  except ApiException as e:
    print("Exception when calling CustomObjectsApi->patch_namespaced_custom_object_status: %s\n" % e)
    pass
  except:
    pass

def createJob(namespace, name, jobtype, action, obj):
  update_trust_ca = "kubectl get states "+namespace+" -n "+namespace+"  -o=jsonpath='{.spec.trustedCA}' > /usr/local/share/ca-certificates/local.crt ; update-ca-certificates ; "
  tf_option = "$(kubectl get states "+namespace+" -n "+namespace+"  -o=jsonpath='{.spec.terraformOption}')"
  if jobtype == "terraform":
    container_name = "terraform"
    init_container_name = "terraform-gen"
    container_image = obj["spec"]["tfExecutorImage"]
    init_container_image = obj["spec"]["tfGeneratorImage"]
    container_image_policy = obj["spec"]["tfExecutorImagePullPolicy"]
    init_container_image_policy = obj["spec"]["tfGeneratorImagePullPolicy"]
    target_env = ' '.join([ f'-target=module.{x}' for x in obj['spec']['targets']]) if 'targets' in obj['spec'] else ''
    env_tf_target = client.V1EnvVar(name="TF_TARGET", value=target_env)
    env_tf_state = client.V1EnvVar(name="STATE", value=namespace)
    env_tf_secret = client.V1EnvVar(name="K8S_SECRET", value=f"tf-plan-{name}")
    env_tf_path = client.V1EnvVar(name="TF_PATH", value="/tf/main.tf")
    env_tf_ns_val  = client.V1EnvVarSource(field_ref=client.V1ObjectFieldSelector(field_path="metadata.namespace"))
    env_tf_ns = client.V1EnvVar(name="K8S_NAMESPACE", value=namespace)
    env = [env_tf_ns, env_tf_path, env_tf_secret, env_tf_target, env_tf_state]
    vols_mount = [client.V1VolumeMount(name="tf", mount_path="/tf")]
    vols = [client.V1Volume(name="tf", empty_dir={})]
    init_run_args = ["python /tfgen.py"]
    if action == "destroy":
      run_args = ["echo DESTROYYY"]
    elif action == "apply":
      run_args = [update_trust_ca + "kubectl get secrets $K8S_SECRET -n $K8S_NAMESPACE  -o=jsonpath='{.data.plan}' | base64 -d > /tmp/plan; mkdir /tmp/empty; cd /tf; terraform init; terraform apply "+tf_option+"  /tmp/plan;"]
    elif action == "plan":
      run_args = [update_trust_ca + "mkdir /tmp/empty; cd /tf;  terraform init && terraform plan "+tf_option+" $TF_TARGET -out /tmp/plan && kubectl create secret generic $K8S_SECRET -n $K8S_NAMESPACE --from-file=plan=/tmp/plan"]
  elif jobtype == "ansible":
    container_name = "ansible"
    init_container_name = "ansible-gen"
    container_image = obj.spec["ansibleExecutorImage"]
    init_container_image = obj.spec["ansibleGeneratorImage"]
    container_image_policy = obj.spec["ansibleExecutorImagePullPolicy"]
    init_container_image_policy = obj.spec["ansibleGeneratorImagePullPolicy"]
    env_ansible_log = client.V1EnvVar(name="ANSIBLE_LOG_PATH", value="/tmp/ansible.log")
    env_namespace = client.V1EnvVar(name="K8S_NAMESPACE", value=namespace)
    env_ansible_run = client.V1EnvVar(name="ANSIBLE_PLAN", value=name)
    env_ansible_color = client.V1EnvVar(name="ANSIBLE_FORCE_COLOR", value="1")
    env_ansible_color2 = client.V1EnvVar(name="PY_COLORS", value="1")
    env_ansible_checkkey = client.V1EnvVar(name="ANSIBLE_HOST_KEY_CHECKING", value="False")
    env = [ env_ansible_checkkey, env_ansible_log, env_namespace, env_ansible_run, env_ansible_color, env_ansible_color2]
    vols_mount = [client.V1VolumeMount(name="data", mount_path="/data")]
    vols = [client.V1Volume(name="data", empty_dir={})]
    if action == "plan":
      run_args = [f"python /ansible_run.py --plan"]
    elif action == "apply":
      run_args = [f"python /ansible_run.py --apply"]
    
    init_run_args = [f" {update_trust_ca}  python ansible_gen.py; cat /data/inventory.yaml; cat /data/playbook.yaml;"]
  else:
    return False

  restart_policy = "Never"
  backoff_limit = 0
  command = [ "/bin/sh", "-x", "-c", "-e"]

  container = client.V1Container(name=container_name, image=container_image, command=command, args=run_args, image_pull_policy=container_image_policy, volume_mounts=vols_mount, env=env)
  init_container = client.V1Container(name=init_container_name, image=init_container_image, command=command, args= init_run_args, image_pull_policy=init_container_image_policy, volume_mounts=vols_mount, env=env)

  template = client.V1PodTemplate()
  template.template = client.V1PodTemplateSpec()
  template.template.spec = client.V1PodSpec(containers=[container], init_containers=[init_container], service_account_name="tfgen",restart_policy=restart_policy, automount_service_account_token=True, volumes=vols)
  
  body = client.V1Job(api_version="batch/v1", kind="Job")
  body.metadata = client.V1ObjectMeta(namespace=namespace, generate_name=f"{jobtype}-{action}-{name}-", labels={"app": jobtype}, annotations={'planName': name, 'type': action})
  body.status = client.V1JobStatus()
  body.spec = client.V1JobSpec(ttl_seconds_after_finished=600, template=template.template, backoff_limit=backoff_limit)

  try: 
    api_response = batch_api_instance.create_namespaced_job(namespace, body, pretty=True)
    return api_response.metadata.name
  except ApiException as e:
    print("Exception when calling BatchV1Api->create_namespaced_job: %s\n" % e)
  return False


def job(logger, name, namespace, body, jobtype, action):
  job = createJob(namespace, body["metadata"]["name"], jobtype, action, body)
  plural = 'plans' if jobtype == "terraform" else "ansibleplans"
  if job != False:
    logger.info(f"{jobtype}-{action} {job} scheduled successfully")
    status = {f'{action}Job': job}
    updateCustomStatus(logger, plural, namespace, name, status)
    return job
  else:
    logger.info(f"{jobtype}-{action} scheduling failed")
    return False

def get_pod_log(logger, namespace, jobName):
  pods = core_api_instance.list_namespaced_pod(namespace, label_selector=f'job-name={jobName}').items
  nbpods = len(pods)
  if nbpods != 1:
    logger.error(f'{nbpods} pods found for jobName {jobName}. Shoudl always be ONE')
    return
  pod = pods[0]
  try:
    log = core_api_instance.read_namespaced_pod_log(pod.metadata.name, namespace)
  except ApiException as e:
    try:
      log = core_api_instance.read_namespaced_pod_log(pod.metadata.name, namespace, container=pod.spec.init_containers[0].name)
    except ApiException as e:
      log = str(e)
  return log

def get_state(namespace):
  try:
    state = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'states', namespace)
  except ApiException as e:
    state = None
  return state

def create_plan(logger, kind, jobPrefx, namespace, planRequest, originalPlan=None, originalPlanRequest=None, targets=None):
  state = get_state(namespace)
  if state == None:
    logger.error(f"Cannot get state in namespace {namespace}, skipping create plan")
    return

  plural = 'plans' if kind == 'PlanRequest' else 'ansibleplans'
  originalPlanRequest = originalPlanRequest if originalPlanRequest != None else planRequest
  annotations = {'planRequest': originalPlanRequest}
  body = {
      'apiVersion': f'{API_GROUP}/{API_VERSION}',
      'kind': 'Plan' if kind == 'PlanRequest' else 'AnsiblePlan',
      'metadata' : client.V1ObjectMeta(annotations=annotations, generate_name=f'{jobPrefx}-', namespace=namespace),
      'spec': {
        "approved": False if originalPlan != None else state["spec"]["autoPlanApprove"],
        "deleteJobsOnDeleted": state["spec"]['deleteJobsOnPlanDeleted']
      }
  }
  if kind == 'PlanRequest':
    body['spec']["state"] = state["metadata"]["name"]
    body['spec']["tfGeneratorImage"] = state["spec"]["tfGeneratorImage"]
    body['spec']["tfGeneratorImagePullPolicy"] = state["spec"]["tfGeneratorImagePullPolicy"]
    body['spec']["tfExecutorImage"] = state["spec"]["tfExecutorImage"]
    body['spec']["tfExecutorImagePullPolicy"] = state["spec"]["tfExecutorImagePullPolicy"]
    if originalPlan != None:
      body['spec']['originalPlan'] = originalPlan
  else:
    body['spec']["ansibleGeneratorImage"] = state["spec"]["ansibleGeneratorImage"]
    body['spec']["ansibleGeneratorImagePullPolicy"] = state["spec"]["ansibleGeneratorImagePullPolicy"]
    body['spec']["ansibleExecutorImage"] = state["spec"]["ansibleExecutorImage"]
    body['spec']["ansibleExecutorImagePullPolicy"] = state["spec"]["ansibleExecutorImagePullPolicy"]

  if targets != None and len(targets) != 0:
    body['spec']['targets'] = targets
  
  try:
    response = custom_api_instance.create_namespaced_custom_object(API_GROUP, API_VERSION, namespace, plural, body)
    logger.info(f'Plan {response["metadata"]["name"]} successfully created for {kind} {planRequest}')
    status = {'plans': [response["metadata"]["name"]]}
    updateCustomStatus(logger, kind.lower()+'s', namespace, originalPlanRequest, status)
  except ApiException as e:
    logger.error("Exception when calling CustomObjectsApi->create_namespaced_custom_object: %s\n" % e)
  except Exception as e:
    logger.error(f'Failed to create plan for {kind} {planRequest}[{namespace}] in state {state["metadata"]["name"]}: {e}')

## CREATE CRD handlers

@kopf.on.create(API_GROUP, API_VERSION, 'planrequests')
@kopf.on.create(API_GROUP, API_VERSION, 'ansibleplanrequests')
def planRequests(body, name, namespace, logger, **kwargs):
  targets = body.spec['targets'] if 'targets' in body.spec else None
  create_plan(logger,body['kind'], namespace, namespace, name, targets=targets)

@kopf.on.create(API_GROUP, API_VERSION, 'plans')
@kopf.on.create(API_GROUP, API_VERSION, 'ansibleplans')
def createPlan(body, name, namespace, logger, **kwargs):
  jobtype = 'terraform' if body['kind'] == "Plan" else 'ansible'
  job(logger, body.metadata["name"], namespace, body, jobtype, 'plan')

@kopf.on.create(API_GROUP, API_VERSION, 'modules')
def moduleCreate(body, name, namespace, logger, **kwargs):
  if not body.spec['autoPlanRequest']:
    return
  targets = [ name ] 
  create_plan(logger, 'PlanRequest',  f'create-mod-{name}', namespace, name, targets=targets)

## PLANS specific handlers

@kopf.on.field(API_GROUP, API_VERSION, 'plans', field="status.planStatus")
@kopf.on.field(API_GROUP, API_VERSION, 'ansibleplans', field="status.planStatus")
def planStatus(diff, status, namespace, logger, body, **kwargs):
  plural = 'plans' if body['kind'] == "Plan" else "ansibleplans"
  if diff[0][2] != "Completed" and diff[0][3] == "Completed":
    log = get_pod_log(logger, namespace, body.status['planJob'])
    updateCustomStatus(logger, plural, namespace, body.metadata.name, {'planOutput' : log})
    if body.spec['approved']:
        logger.info(f"{body['kind']} {body.metadata['name']} completed and approved, request scheduling")
        job(logger, body.metadata["name"], namespace, body, 'terraform' if body['kind'] == "Plan" else "ansible", 'apply')
    else:
      if body["kind"] == "Plan":
        if "Your infrastructure matches the configuration." in log:
          logger.info(f"Plan {body.metadata.name} produces an up-to-date plan, autoApproving")
          custom_api_instance.patch_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'plans', body.metadata.name, {'spec': {'approved': True}})
        else:
          if "originalPlan" in body.spec and body.spec['originalPlan'] != "":
            logger.info(f"originalPlan detected for {body.metadata['name']}: {body.spec['originalPlan']}")
            lastOutput = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'plans', body.spec['originalPlan'])['status']['planOutput']
            planLast = re.search(f'.*{TERRAFORM_DELIMETER}(.*){TERRAFORM_DELIMETER}.*', lastOutput, flags=re.DOTALL)
            planNew = re.search(f'.*{TERRAFORM_DELIMETER}(.*){TERRAFORM_DELIMETER}.*', log, flags=re.DOTALL)
            if planLast == None or planNew == None:
                logger.error(f"Unable to parse terraform plan output, skipping autoApproving")
                return
            if planLast.group(1) != planNew.group(1):
              logger.error(f"Difference detected between originalPLan {body.spec['originalPlan']} and new plan {body.metadata.name}, manual Approval required")
            else:
              logger.info(f"No difference detected between originalPLan {body.spec['originalPlan']} and new plan {body.metadata.name}, autoApproving new plan")
              custom_api_instance.patch_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'plans', body.metadata.name, {'spec': {'approved': True}})
          else:
            logger.info(f"Plan {body.metadata['name']} completed but not approved, waiting approval")

  if diff[0][2] != "Failed" and diff[0][3] == "Failed":
    logger.error (f"{body['kind']} {body.metadata['name']} planning failed")
    log = get_pod_log(logger, namespace, body.status['planJob'])
    updateCustomStatus(logger, plural, namespace, body.metadata.name, {'planOutput' : log})
  
  if diff[0][2] != "Active" and diff[0][3] == "Active":
    logger.info(f'{body["kind"]} {body.metadata["name"]} become Active')

@kopf.on.field(API_GROUP, API_VERSION, 'plans', field="spec.approved")
@kopf.on.field(API_GROUP, API_VERSION, 'ansibleplans', field="spec.approved")
def approved(diff, status, namespace, logger, body, **kwargs):
  if diff[0][2] == False and diff[0][3] == True and body.status['applyStatus'] == 'Pending' and body.status['planStatus'] == 'Completed':
    jobtype = 'terraform' if body['kind'] == "Plan" else 'ansible'
    logger.info(f"{body['kind']} {body.metadata['name']} has been approved, request scheduling")
    job(logger, body.metadata["name"], namespace, body, jobtype, 'apply')

@kopf.on.field(API_GROUP, API_VERSION, 'plans', field="status.applyStatus")
@kopf.on.field(API_GROUP, API_VERSION, 'ansibleplans', field="status.applyStatus")
def applyStatus(diff, status, namespace, logger, body, **kwargs):
  plural = 'plans' if body['kind'] == "Plan" else "ansibleplans"
  if diff[0][2] != "Completed" and diff[0][3] == "Completed":
    logger.info(f'{body["kind"]} {body.metadata["name"]} applying completed')
    log = get_pod_log(logger, namespace, body.status['applyJob'])
    updateCustomStatus(logger ,plural, namespace, body.metadata.name, {'applyOutput' : log})
    if body['kind'] == "Plan" and not body['metadata']['name'].startswith('delete-mod-'):
      module_names = []
      for target in body["spec"]["targets"] if "targets" in body['spec'] else []:
        module_name = target
        try:
          module = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'modules', module_name)
        except ApiException:
          logger.error(f'Unable to find module {module_name}, skipping this module for ansibleplan')
          continue
        if "ansibleAttributes" in module["spec"] and "targets" in module["spec"]["ansibleAttributes"] and len(module["spec"]["ansibleAttributes"]["targets"]) != 0:
          module_names.append(module_name)
        else:
          logger.info(f'No targets defined in module {module_name}, skipping this module for ansibleplan')
      if len(module_names) != 0 or not "targets" in body["spec"]:
        state = get_state(namespace)
        if state == None:
          logger.error(f"Cannot get state in namespace {namespace}, skipping create AnsiblePlan")
          return
        #approved = True if len(module_names) != 0 else state['spec']['autoPlanApprove']
        approved = True if body['metadata']['name'].startswith('create-mod-') else state['spec']['autoPlanApprove']
        plan_body = {
          'apiVersion': f'{API_GROUP}/{API_VERSION}',
          'kind': 'AnsiblePlan',
          'metadata' : client.V1ObjectMeta(generate_name=f'{body.metadata.name}-', namespace=namespace),
          'spec': {
            "approved": approved,
            'ansibleGeneratorImage': state['spec']['ansibleGeneratorImage'],
            'ansibleExecutorImage': state['spec']['ansibleExecutorImage'],
            'ansibleGeneratorImagePullPolicy': state['spec']['ansibleGeneratorImagePullPolicy'],
            'ansibleExecutorImagePullPolicy': state['spec']['ansibleExecutorImagePullPolicy']
          }
        }
        if len(module_names) != 0:
          plan_body['spec']['targets'] = module_names
        logger.info(f'Creating AnsiblePlans')
        api_response = custom_api_instance.create_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansibleplans', plan_body)

  if diff[0][2] != "Failed" and diff[0][3] == "Failed":
    logger.error(f'Plan {body.metadata["name"]} applying failed')
    try: 
      log = get_pod_log(logger, namespace, body.status['applyJob'])
    except ApiException:
      log = "pod not found"
    #todo : retry when locked state
    updateCustomStatus(logger, plural, namespace, body.metadata.name, {'applyOutput' : log})
    if body['kind'] == "Plan" and log and "Saved plan is stale" in log:
      logger.info(f"Saved plan is stale, trying to request a new plan with OriginalPlan {body.metadata.name}")
      ori = body.spec['originalPlan'] if 'originalPlan' in body.spec else body.metadata.name
      targets = body.spec['targets'] if 'targets' in body.spec else None
      create_plan(logger, 'PlanRequest', body.spec['state'], namespace, f'auto-fix-{ori}', originalPlan=ori, originalPlanRequest=body.metadata.annotations['planRequest'], targets=targets)

  if diff[0][2] != "Active" and diff[0][3] == "Active":
    logger.info(f'{body["kind"]} {body.metadata["name"]} become Active')

## DELETE CRD HANDLERS

@kopf.on.delete(API_GROUP, API_VERSION, 'modules')
def moduleDelete(body, name, namespace, logger, **kwargs):
  if not body.spec['autoPlanRequest']:
    return
  create_plan(logger, 'PlanRequest', f'delete-mod-{name}', namespace, name, targets=[name])

@kopf.on.delete(API_GROUP, API_VERSION, 'plans')
@kopf.on.delete(API_GROUP, API_VERSION, 'ansibleplans')
def planDelete(body, name, namespace, logger, **kwargs):
  logger.info(f"Deleting {body['kind']} {name}[{namespace}], cleaning associate planOutputs & job")
  if body['kind'] == 'Plans': 
    secretPlan = f'tf-plan-{name}'
    try:
      logger.info(f"Deleting secret plan {secretPlan}[{namespace}]")
      core_api_instance.delete_namespaced_secret(secretPlan, namespace)
    except ApiException as e:
      logger.error(f"Exception when trying to delete secret {secretPlan} : {e}")
  
  if body.spec["deleteJobsOnDeleted"]: 
    for job in [body.status["planJob"], body.status["applyJob"]]:
      if job == "":
        continue
      try:
        batch_api_instance.read_namespaced_job(job, namespace)
        logger.info(f"Deleting job {job}[{namespace}]")
        batch_api_instance.delete_namespaced_job(job, namespace)
      except ApiException as e:
        logger.error(f"Exception when trying to delete job {job} : {e}")
        return

@kopf.on.delete(API_GROUP, API_VERSION, 'planrequests')
@kopf.on.delete(API_GROUP, API_VERSION, 'ansibleplanrequests')
def planRequestDelete(body, name, namespace, logger,  **kwargs):
  if "spec" in body and body['spec']["deletePlanOnDeleted"]: 
    plural = 'plans' if body['kind'] == "PlanRequest" else 'ansibleplans'
    for plan in body['status']['plans'] if 'plans' in body['status'] else []:
      logger.info(f"Deleting {body['kind']} {plan}[{namespace}]")
      try:
        custom_api_instance.delete_namespaced_custom_object(API_GROUP, API_VERSION, namespace, plural, plan)
      except ApiException as e:
        logger.error(f"Exception when trying to delete {body['kind']} {plan} : {e}")
        return

## UPDATE CRD HANDLERS

@kopf.on.update(API_GROUP, API_VERSION, 'states')
def stateUpdate(body, name, namespace, logger, **kwargs):
  if not body.spec['autoPlanRequest']:
    return
  create_plan(logger, 'PlanRequest',  f'update-state-{name}', namespace, name)

@kopf.on.update(API_GROUP, API_VERSION, 'providers')
def  providersUpdate(body, name, namespace, logger, **kwargs):
  targets = [ module['metadata']['name']  for module in custom_api_instance.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'modules')["items"] if module['spec']['autoPlanRequest']]
  if len(targets) != 0:
    create_plan(logger, 'PlanRequest',  f'update-prs-{name}', namespace, name, targets=targets)

@kopf.on.update(API_GROUP, API_VERSION, 'moduletemplates')
def  moduleTemplateUpdate(body, name, namespace, logger, **kwargs):
  targets = [ module['metadata']['name']  for module in custom_api_instance.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'modules')["items"] if module['spec']['autoPlanRequest'] and "moduleTemplate" in module['spec'] and module['spec']['moduleTemplate'] == name]
  if len(targets) != 0:
    create_plan(logger, 'PlanRequest', f'update-modtpl-{name}', namespace, name, targets=targets)

@kopf.on.update(API_GROUP, API_VERSION, 'clusterproviders')
def clusterProvidersUpdate(body, name, logger, **kwargs):
  for ns in core_api_instance.list_namespace(label_selector="toolbox-managed=true").items:
    state = get_state(ns.metadata.name)
    if state == None:
      logger.error(f'Unable to find state in namespace {ns.metadata.name}')
      continue
    if "clusterProviders" in state['spec'] and name in state['spec']['clusterProviders']:
      targets = [ module['metadata']['name']  for module in custom_api_instance.list_namespaced_custom_object(API_GROUP, API_VERSION, ns.metadata.name, 'modules')["items"] if module['spec']['autoPlanRequest']]
      if len(targets) != 0:
        create_plan(logger, 'PlanRequest', f'update-clmodprds-{name}', ns.metadata.name, name, targets=targets)

@kopf.on.update(API_GROUP, API_VERSION, 'clustermoduletemplates')
def clusterModuleUpdate(body, name, logger, **kwargs):
  for ns in core_api_instance.list_namespace(label_selector="toolbox-managed=true").items:
    targets = [ module['metadata']['name']  for module in custom_api_instance.list_namespaced_custom_object(API_GROUP, API_VERSION, ns.metadata.name, 'modules')["items"] if module['spec']['autoPlanRequest'] and "clusterModuleTemplate" in module['spec'] and module['spec']['clusterModuleTemplate'] == name]
    if len(targets) != 0:
      create_plan(logger, 'PlanRequest', f'update-clmodtpl-{name}', ns.metadata.name, name, targets=targets)

@kopf.on.update(API_GROUP, API_VERSION, 'modules')
def moduleUpdate(body, name, namespace, logger, **kwargs):
  if not body.spec['autoPlanRequest']:
    return
  targets = [ name ] 
  create_plan(logger, 'PlanRequest',  f'update-mod-{name}', namespace, name, targets=targets)


## JOBS handlers
@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'terraform'}, field="status.succeeded")
@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible'}, field="status.succeeded")
def jobSucceeded(diff, status, namespace, logger, body, **kwargs):
  if diff == ():
    return
  if diff[0][2] != True and diff[0][3] == True:
    end = body.status['completionTime']
    plural = 'plans'  if body["metadata"]['labels']["app"] == "terraform" else "ansibleplans"
    tftype =  'apply' if body["metadata"]["annotations"]["type"] == "apply" else 'plan'
    status = {f'{tftype}StartTime': body.status['startTime'], f'{tftype}Status' : 'Completed', f'{tftype}CompleteTime' : end}
    plan_name = body.metadata.annotations['planName']
    updateCustomStatus(logger, plural, namespace, plan_name, status)

@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'terraform'}, field="status.active")
@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible'}, field="status.active")
def jobActive(diff, status, namespace, logger, body, **kwargs):
  if diff == ():
    return
  if diff[0][2] != True and diff[0][3] == True:
    state = 'Active'
    tftype =  'apply' if body["metadata"]["annotations"]["type"] == "apply" else 'plan'
    status = {f'{tftype}StartTime': body.status['startTime'], f'{tftype}Status' : state}
    plural = 'plans' if body["metadata"]['labels']["app"] == "terraform" else "ansibleplans"
    updateCustomStatus(logger, plural, namespace, body.metadata.annotations['planName'], status)

@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'terraform'}, field="status.conditions")
@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible'}, field="status.conditions")
def jobCondition(diff, status, namespace, logger, body, **kwargs):
  if diff == ():
    return
  tftype = 'apply' if body["metadata"]["annotations"]["type"] == "apply" else 'plan'
  plural = 'plans' if body["metadata"]['labels']["app"] == "terraform" else "ansibleplans"
  status = {f'{tftype}Conditions': body.status['conditions']}
  updateCustomStatus(logger, plural, namespace, body.metadata.annotations['planName'], status)
  
  if len(diff[0][3]) > 0:
    evs = diff[0][3]
    failed=0
    for ev in evs:
      if ev['type'] == "Failed":
        failed=1
        end = ev['lastTransitionTime']
    if failed:
      status = {f'{tftype}Status' : 'Failed', f'{tftype}CompleteTime' : end}
      updateCustomStatus(logger, plural, namespace, body.metadata.annotations['planName'], status)

#@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'tfgen'}, field="status.failed")
#@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible'}, field="status.failed")
#def jobFailed(diff, status, namespace, logger, body, **kwargs):
#  if diff == ():
#    return
#  tftype =  'apply' if body["metadata"]["annotations"]["type"] == "apply" else 'plan'
#  plural = 'plans' if body["metadata"]['labels']["app"] == "tfgen" else "ansibleplans"
#  if diff[0][3] > 0:
#    status = {f'{tftype}Status' : 'Failed', f'{tftype}CompleteTime' : "Failed"}
#    updateCustomStatus(logger, plural, namespace, body.metadata.annotations['planName'], status)


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_):
  settings.posting.level = logging.DEBUG
