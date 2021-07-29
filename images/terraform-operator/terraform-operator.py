# TODO remove disable when refactoring file
# pylint: disable=bad-indentation
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
#TODO:
# deny multiple apply job for same state
# realTime joblog ?


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
  if jobtype == "terraform":
    container_name = "terraform"
    init_container_name = "terraform-gen"
    container_image = obj.spec["tfExecutorImage"]
    init_container_image = obj.spec["tfGeneratorImage"]
    container_image_policy = obj.spec["tfExecutorImagePullPolicy"]
    init_container_image_policy = obj.spec["tfGeneratorImagePullPolicy"]
    target_env = ' '.join([ f'-target={x}' for x in obj['spec']['targets']]) if 'targets' in obj['spec'] else ''
    env_tf_target = client.V1EnvVar(name="TF_TARGET", value=target_env)
    env_tf_state = client.V1EnvVar(name="STATE", value=obj.spec['state'])
    env_tf_secret = client.V1EnvVar(name="K8S_SECRET", value=f"tf-plan-{name}")
    env_tf_path = client.V1EnvVar(name="TF_PATH", value="/tf/main.tf")
    env_tf_ns_val  = client.V1EnvVarSource(field_ref=client.V1ObjectFieldSelector(field_path="metadata.namespace"))
    env_tf_ns = client.V1EnvVar(name="K8S_NAMESPACE", value=namespace)
    env = [env_tf_ns, env_tf_path, env_tf_secret, env_tf_target, env_tf_state]
    vols_mount = [client.V1VolumeMount(name="tf", mount_path="/tf")]
    vols = [client.V1Volume(name="tf", empty_dir={})]
    if action == "destroy":
      tf_args = ["echo DESTROYYY"]
    elif action == "apply":
     # tf_args = ["env; kubectl get secrets $K8S_SECRET -n $K8S_NAMESPACE  -o=jsonpath='{.data.plan}' | base64 -d > /tmp/plan; cd /tf; terraform init; terraform show /tmp/plan;"]
      run_args = ["kubectl get secrets $K8S_SECRET -n $K8S_NAMESPACE  -o=jsonpath='{.data.plan}' | base64 -d > /tmp/plan; cd /tf; terraform init; terraform apply /tmp/plan;"]
    elif action == "plan":
      run_args = ["cd /tf;  terraform init && terraform plan $TF_TARGET -out /tmp/plan && kubectl create secret generic $K8S_SECRET -n $K8S_NAMESPACE --from-file=plan=/tmp/plan"]
      init_run_args = ["python /tfgen.py"]
  elif jobtype == "ansible":
    container_name = "ansible"
    init_container_name = "ansible-gen"
    container_image = obj.spec["ansibleExecutorImage"]
    init_container_image = obj.spec["ansibleGeneratorImage"]
    container_image_policy = obj.spec["ansibleExecutorImagePullPolicy"]
    init_container_image_policy = obj.spec["ansibleGeneratorImagePullPolicy"]
    env_ansible_config = client.V1EnvVar(name="ANSIBLE_CONFIG", value="/config/ansible.cfg")
    env_ansible_log = client.V1EnvVar(name="ANSIBLE_LOG_PATH", value="/tmp/ansible.log")
    env_namespace = client.V1EnvVar(name="K8S_NAMESPACE", value=namespace)
    env_ansible_run = client.V1EnvVar(name="ANSIBLE_PLAN", value=name)
    env_ansible_color = client.V1EnvVar(name="ANSIBLE_FORCE_COLOR", value="1")
    env_ansible_color2 = client.V1EnvVar(name="PY_COLORS", value="1")
    env = [env_ansible_config, env_ansible_log, env_namespace, env_ansible_run, env_ansible_color, env_ansible_color2]
    vols_mount = [client.V1VolumeMount(name="data", mount_path="/data"), client.V1VolumeMount(name="ansible-config", mount_path="/config", read_only=True)]
    vols = [client.V1Volume(name="ansible-config", config_map=client.V1ConfigMapVolumeSource(name="ansible-config")), client.V1Volume(name="data", empty_dir={})]
    if action == "plan":
      run_args = [f"python /ansible_run.py --plan"]
    elif action == "apply":
      run_args = [f"python /ansible_run.py --apply"]
    
    init_run_args = ["cp /config/certs /usr/local/share/ca-certificates/local.crt ; update-ca-certificates ; python ansible_gen.py; cat /data/inventory.yaml; cat /data/playbook.yaml; cat /config/ansible.cfg; "]
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
  #todo config backoff
  body.spec = client.V1JobSpec(ttl_seconds_after_finished=600, template=template.template, backoff_limit=backoff_limit)

  try: 
    api_response = batch_api_instance.create_namespaced_job(namespace, body, pretty=True)
    return api_response.metadata.name
  except ApiException as e:
    print("Exception when calling BatchV1Api->create_namespaced_job: %s\n" % e)
  return False


def job(logger, name, namespace, body, jobtype, action):
  job = createJob(namespace, body.metadata["name"], jobtype, action, body)
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

#@kopf.on.login()
#def login_fn(**kwargs):
#    return kopf.login_via_client(**kwargs)

## autoPlanRequest handlers
# TODO: handle cluster* / deletedModule
@kopf.on.create(API_GROUP, API_VERSION, 'modules')
@kopf.on.update(API_GROUP, API_VERSION, 'modules')
@kopf.on.update(API_GROUP, API_VERSION, 'states')
@kopf.on.update(API_GROUP, API_VERSION, 'providers')
def autoPlan(body, name, namespace, logger, **kwargs):
  if body.spec['autoPlanRequest']:
    requestPlan = {
        'apiVersion': f'{API_GROUP}/{API_VERSION}',
        'kind': 'PlanRequest',
        'metadata' : client.V1ObjectMeta(generate_name=f'auto-{name}-', namespace=namespace),
        'spec': { "deletePlanOnDeleted": True}
    }
    if body['kind'] == 'Module':
      requestPlan['spec']['targets'] = [f'module.{name}']
  
    try:
      response = custom_api_instance.create_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'planrequests', requestPlan)
      logger.info(f'PlanRequest {response["metadata"]["name"]} successfully created for {name}')
    except ApiException as e:
      logger.error("Exception when calling CustomObjectsApi->create_namespaced_custom_object: %s\n" % e)

def create_plan(logger, kind, stateName, namespace, planRequest, originalPlan=None, originalPlanRequest=None, targets=None):
  try:
    state = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'states', stateName)
  except ApiException as e:
    logger.error(f"Cannot get state {stateName} in namespace {namespace}, skipping create plan")
    return
  plural = 'plans' if kind == 'PlanRequest' else 'ansibleplans'
  originalPlanRequest = originalPlanRequest if originalPlanRequest != None else planRequest
  annotations = {'planRequest': originalPlanRequest}
  body = {
      'apiVersion': f'{API_GROUP}/{API_VERSION}',
      'kind': 'Plan' if kind == 'PlanRequest' else 'AnsiblePlan',
      'metadata' : client.V1ObjectMeta(annotations=annotations, generate_name=f'{stateName}-', namespace=namespace),
      'spec': {
        "approved": False if originalPlan != None else state["spec"]["autoPlanApprove"],
        "deleteJobsOnDeleted": state["spec"]['deleteJobsOnPlanDeleted']
      }
  }
  if kind == 'PlanRequest':
    body['spec']["deletePlansOnDeleted"]: state["spec"]['deletePlansOnPlanDeleted']
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

  if targets != None:
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

## PLANREQUESTS handlers
@kopf.on.create(API_GROUP, API_VERSION, 'planrequests')
@kopf.on.create(API_GROUP, API_VERSION, 'ansibleplanrequests')
def planRequests(body, name, namespace, logger, **kwargs):
  targets = body.spec['targets'] if 'targets' in body.spec else None
  create_plan(logger,body['kind'], namespace, namespace, name, targets=targets)

## PLANS handlers
@kopf.on.create(API_GROUP, API_VERSION, 'plans')
@kopf.on.create(API_GROUP, API_VERSION, 'ansibleplans')
def createPlan(body, name, namespace, logger, **kwargs):
  jobtype = 'terraform' if body['kind'] == "Plan" else 'ansible'
  job(logger, body.metadata["name"], namespace, body, jobtype, 'plan')

@kopf.on.field(API_GROUP, API_VERSION, 'plans', field="status.planStatus")
@kopf.on.field(API_GROUP, API_VERSION, 'ansibleplans', field="status.planStatus")
def planStatus(diff, status, namespace, logger, body, **kwargs):
  plural = 'plans' if body['kind'] == "Plan" else "ansibleplans"
  if diff[0][2] != "Completed" and diff[0][3] == "Completed":
    log = get_pod_log(logger, namespace, body.status['planJob'])
    updateCustomStatus(logger, plural, namespace, body.metadata.name, {'planOutput' : log})
    if body.spec['approved']:
        logger.info(f"{body['kind']} {body.metadata['name']} completed and approved, request scheduling")
        job(logger, body.metadata["name"], namespace, body, 'terraform', 'apply')
    else:
      if body["kind"] == "Plan":
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

  if diff[0][2] != "Failed" and diff[0][3] == "Failed":
    logger.error(f'Plan {body.metadata["name"]} applying failed')
    try: 
      log = get_pod_log(logger, namespace, body.status['applyJob'])
    except ApiException:
      log = "pod not found"
    updateCustomStatus(logger, plural, namespace, body.metadata.name, {'applyOutput' : log})
    if body['kind'] == "Plan" and log and "Saved plan is stale" in log:
      logger.info(f"Saved plan is stale, trying to request a new plan with OriginalPlan {body.metadata.name}")
      ori = body.spec['originalPlan'] if 'originalPlan' in body.spec else body.metadata.name
      targets = body.spec['targets'] if 'targets' in body.spec else None
      create_plan(logger, 'PlanRequest', body.spec['state'], namespace, f'auto-fix-{ori}', originalPlan=ori, originalPlanRequest=body.metadata.annotations['planRequest'], targets=targets)

  if diff[0][2] != "Active" and diff[0][3] == "Active":
    logger.info(f'{body["kind"]} {body.metadata["name"]} become Active')

@kopf.on.delete(API_GROUP, API_VERSION, 'plans')
@kopf.on.delete(API_GROUP, API_VERSION, 'ansibleplans')
def planDelete(body, name, namespace, logger, **kwargs):
  logger.info(f"Deleting {body['kind']} {name}[{namespace}], cleaning associate planOutputs & job")
  if body['kind'] == 'Plans' and body.spec["deletePlansOnDeleted"]: 
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
    try:
      a = body['status']['plans']
    except:
      return
    for plan in body['status']['plans']:
      logger.info(f"Deleting {body['kind']} {plan}[{namespace}]")
      try:
        custom_api_instance.delete_namespaced_custom_object(API_GROUP, API_VERSION, namespace, plural, plan)
      except ApiException as e:
        logger.error(f"Exception when trying to delete {body['kind']} {plan} : {e}")
        return

## JOBS handlers
@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'terraform'}, field="status.succeeded")
@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible'}, field="status.succeeded")
def jobSucceeded(diff, status, namespace, logger, body, **kwargs):
  if diff == ():
    return
  if diff[0][2] != True and diff[0][3] == True:
    end = body.status['completionTime']
    plural = 'plans' if body['kind'] == "Plan" else "ansibleplans"
    tftype =  'apply' if body["metadata"]["annotations"]["type"] == "apply" else 'plan'
    status = {f'{tftype}StartTime': body.status['startTime'], f'{tftype}Status' : 'Completed', f'{tftype}CompleteTime' : end}
    plan_name = body.metadata.annotations['planName']
    updateCustomStatus(logger, plural, namespace, plan_name, status)
    
    #if body['kind'] == 'Plan' and tftype == "apply":
    #  # TODO: targets not mandatory ?
    #  #TODO ansible call
    #  plan = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'plans', plan_name)
    #  targets = plan["spec"]["targets"]
    #  hosts = []
    #  module_names = []
    #  for target in targets:
    #    module_name = target.split(".")[1]
    #    module_names.append(module_name)
    #    module = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'modules', module_name)
#
    #    if "ansibleAttributes" in module["spec"] and "targets" in module["spec"]["ansibleAttributes"]:
    #      for host in module["spec"]["ansibleAttributes"]["targets"]:
    #        hosts.append(host['fqdn'])
    #  if len(hosts) == 0:
    #    logger.info(f"No FQDN found for module {modules_names}, skipping AnsiblePlan creation")
    #    return
    #  plan_body = {
    #    'apiVersion': f'{API_GROUP}/{API_VERSION}',
    #    'kind': 'AnsiblePlan',
    #    'metadata' : client.V1ObjectMeta(generate_name=f'ter-{plan_name}-', namespace=namespace, labels={'source': 'TerraformPlan', "terraformPlan": plan_name}),
    #    'spec': {
    #      "approved": False,
    #      "auto": {
    #        "hosts": hosts,
    #        "terraformPlan": plan_name
    #      }
    #    }
    #  }
    #  api_response = custom_api_instance.create_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansibleplans', plan_body)
    #  updateCustomStatus(logger, 'plans', namespace, plan_name, {'AnsiblePlan': api_response['metadata']['name']})

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
  tftype =  'apply' if body["metadata"]["annotations"]["type"] == "apply" else 'plan'
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
