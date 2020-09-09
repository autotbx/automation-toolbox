import kopf
import kubernetes
from kubernetes import client, config, utils
import kubernetes.client
from kubernetes.client.rest import ApiException
import re

config.load_kube_config()
configuration = kubernetes.client.Configuration()

API_GROUP = 'terraform.dst.io'
API_VERSION = 'v1'
TERRAFORM_DELIMETER="-----------------------------------------------------------------------"

custom_api_instance = kubernetes.client.CustomObjectsApi(kubernetes.client.ApiClient(configuration))
batch_api_instance = kubernetes.client.BatchV1Api(kubernetes.client.ApiClient(configuration))
core_api_instance = kubernetes.client.CoreV1Api(kubernetes.client.ApiClient(configuration))
#TODO:
# deny multiple apply job for same state
# plans : use conditions
# jobsLog if failed
# realTime joblog ?


def updateCustomStatus(logger, plural, namespace, name, vals):
  currentStatus = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, plural, name)
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

  logger.debug('setting new status %s/%s[%s]: %s -> %s' % (plural, name, namespace, status, newstatus))
  body = {'status': newstatus}
  try:
    custom_api_instance.patch_namespaced_custom_object_status(API_GROUP, API_VERSION, namespace, plural, name, body)
  except ApiException as e:
    print("Exception when calling CustomObjectsApi->patch_namespaced_custom_object_status: %s\n" % e)
    pass
  except:
    pass

def createJob(namespace, name, tftype, planRequest):
  if tftype == "destroy":
    tf_args = ["echo DESTROYYY"]
    restart_policy = "Never"
    backoff_limit = 1
  elif tftype == "apply":
   # tf_args = ["env; kubectl get secrets $K8S_SECRET -n $K8S_NAMESPACE  -o=jsonpath='{.data.plan}' | base64 -d > /tmp/plan; cd /tf; terraform init; terraform show /tmp/plan;"]
    tf_args = ["kubectl get secrets $K8S_SECRET -n $K8S_NAMESPACE  -o=jsonpath='{.data.plan}' | base64 -d > /tmp/plan; cd /tf; terraform init; terraform apply /tmp/plan;"]
    restart_policy = "Never"
    backoff_limit = 0
  elif tftype == "plan":
    tf_args = ["cd /tf;  terraform init && terraform plan $TF_TARGET -out /tmp/plan && kubectl create secret generic $K8S_SECRET -n $K8S_NAMESPACE --from-file=plan=/tmp/plan"]
    restart_policy = "Never" #logs on onFailure/?
    backoff_limit = 0
  else:
    return False
    
  tf_container_name = "terraform"
  tf_container_image = planRequest.spec["tfExecutorImage"]
  tf_command = [ "/bin/sh", "-x", "-c"]
  tf_image_policy = planRequest.spec["tfExecutorImagePullPolicy"]

  gentf_container_name  = "gentf"
  gentf_container_image = planRequest.spec["tfGeneratorImage"]
  gentf_image_policy    = planRequest.spec["tfGeneratorImagePullPolicy"]

  
  target_env = ' '.join([ f'-target={x}' for x in planRequest['spec']['targets']]) if 'targets' in planRequest['spec'] else ''
  env_tf_target = client.V1EnvVar(name="TF_TARGET", value=target_env)

  env_tf_state = client.V1EnvVar(name="STATE", value=planRequest.spec['state'])

  env_tf_secret = client.V1EnvVar(name="K8S_SECRET", value=f"tf-plan-{name}")
  env_tf_path = client.V1EnvVar(name="TF_PATH", value="/tf/main.tf")
  env_tf_ns_val  = client.V1EnvVarSource(field_ref=client.V1ObjectFieldSelector(field_path="metadata.namespace"))
  env_tf_ns = client.V1EnvVar(name="K8S_NAMESPACE", value_from=env_tf_ns_val)
  env = [env_tf_ns, env_tf_path, env_tf_secret, env_tf_target, env_tf_state]
  vols_mount = [client.V1VolumeMount(name="tf", mount_path="/tf")]

  tf_container = client.V1Container(name=tf_container_name, image=tf_container_image, command=tf_command,args=tf_args, image_pull_policy=tf_image_policy, volume_mounts=vols_mount, env=env)
  gentf_container = client.V1Container(name=gentf_container_name, image=gentf_container_image, image_pull_policy=gentf_image_policy, volume_mounts=vols_mount, env=env)

  template = client.V1PodTemplate()
  template.template = client.V1PodTemplateSpec()
  template.template.spec = client.V1PodSpec(containers=[tf_container], init_containers=[gentf_container], service_account_name="tfgen",restart_policy=restart_policy, automount_service_account_token=True, volumes=[client.V1Volume(name="tf", empty_dir={})])
  
  body = client.V1Job(api_version="batch/v1", kind="Job")
  body.metadata = client.V1ObjectMeta(namespace=namespace, generate_name=f"tf-{tftype}-{name}-", labels={"app": "tfgen"}, annotations={'planName': name, 'type': tftype})
  body.status = client.V1JobStatus()
  #todo config backoff
  body.spec = client.V1JobSpec(ttl_seconds_after_finished=600, template=template.template, backoff_limit=backoff_limit)

  try: 
    api_response = batch_api_instance.create_namespaced_job("default", body, pretty=True)
    return api_response.metadata.name
  except ApiException as e:
    print("Exception when calling BatchV1Api->create_namespaced_job: %s\n" % e)
  return False


def job(logger, name, namespace, body, jobtype):
  job = createJob(namespace, body.metadata["name"], jobtype, body)
  if job != False:
      logger.info(f"{jobtype} {job} scheduled successfully")
      status = {f'{jobtype}Job': job}
      updateCustomStatus(logger, 'plans', namespace, name, status)
      return job
  else:
      logger.info(f"{jobtype} {job} scheduleding failed")
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
      log = core_api_instance.read_namespaced_pod_log(pod.metadata.name, namespace, container="gentf")
    except ApiException as e:
         log = str(e)
  return log

@kopf.on.login()
def login_fn(**kwargs):
    return kopf.login_via_client(**kwargs)

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
      # module status ? 
    except ApiException as e:
      logger.error("Exception when calling CustomObjectsApi->create_namespaced_custom_object: %s\n" % e)

def create_plan(logger, stateName, namespace, planRequest, originalPlan=None, originalPlanRequest=None, targets=None):
  state = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, 'default', 'states', stateName)
  originalPlanRequest = originalPlanRequest if originalPlanRequest != None else planRequest
  annotations = {'planRequest': originalPlanRequest}
  body = {
      'apiVersion': f'{API_GROUP}/{API_VERSION}',
      'kind': 'Plan',
      'metadata' : client.V1ObjectMeta(annotations=annotations, generate_name=f'{stateName}-', namespace=namespace),
      'spec': {
        "approved": False if originalPlan != None else state["spec"]["autoPlanApprove"],
        "deleteJobsOnDeleted": state["spec"]['deleteJobsOnPlanDeleted'],
        "deletePlansOnDeleted": state["spec"]['deletePlansOnPlanDeleted'],
        "state": state["metadata"]["name"],
        "tfGeneratorImage" : state["spec"]["tfGeneratorImage"],
        "tfGeneratorImagePullPolicy": state["spec"]["tfGeneratorImagePullPolicy"],
        "tfExecutorImage" : state["spec"]["tfExecutorImage"],
        "tfExecutorImagePullPolicy" : state["spec"]["tfExecutorImagePullPolicy"]
      }
  }
  if targets != None:
    body['spec']['targets'] = targets
  if originalPlan != None:
    body['spec']['originalPlan'] = originalPlan
  
  try:
    response = custom_api_instance.create_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'plans', body)
    logger.info(f'Plan {response["metadata"]["name"]} successfully created for PlanRequest {planRequest}')
    status = {'plans': [response["metadata"]["name"]]}
    updateCustomStatus(logger, 'planrequests', namespace, originalPlanRequest, status)
  except ApiException as e:
    logger.error("Exception when calling CustomObjectsApi->create_namespaced_custom_object: %s\n" % e)
  except Exception as e:
    logger.error(f'Failed to create plan for planRequest{planRequest}[{namespace}] in state {state["metadata"]["name"]}: {e}')

## PLANREQUESTS handlers
@kopf.on.create(API_GROUP, API_VERSION, 'planrequests')
def planRequests(body, name, namespace, logger, **kwargs):
  #match all state atm
  for state in custom_api_instance.list_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'states')["items"]:
    targets = body.spec['targets'] if 'targets' in body.spec else None
    create_plan(logger, state["metadata"]["name"], namespace, name, targets=targets)

## PLANS handlers
@kopf.on.create(API_GROUP, API_VERSION, 'plans')
def createPlan(body, name, namespace, logger, **kwargs):
  job(logger, body.metadata["name"], namespace, body, 'plan')

@kopf.on.field(API_GROUP, API_VERSION, 'plans', field="status.planStatus")
def planStatus(diff, status, namespace, logger, body, **kwargs):
  if diff[0][2] != "Completed" and diff[0][3] == "Completed":
    log = get_pod_log(logger, namespace, body.status['planJob'])
    updateCustomStatus(logger, 'plans', namespace, body.metadata.name, {'planOutput' : log})
    if body.spec['approved']:
        logger.info(f"Plan {body.metadata['name']} completed and approved, request scheduling")
        job(logger, body.metadata["name"], namespace, body, 'apply')
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
    logger.error (f"Plan {body.metadata['name']} planning failed")
    log = get_pod_log(logger, namespace, body.status['planJob'])
    updateCustomStatus(logger, 'plans', namespace, body.metadata.name, {'planOutput' : log})
  
  if diff[0][2] != "Active" and diff[0][3] == "Active":
    logger.info(f'Plan {body.metadata["name"]} become Active')

@kopf.on.field(API_GROUP, API_VERSION, 'plans', field="spec.approved")
def approved(diff, status, namespace, logger, body, **kwargs):
  if diff[0][2] == False and diff[0][3] == True and body.status['applyStatus'] == 'Pending' and body.status['planStatus'] == 'Completed':
    logger.info(f"Plan {body.metadata['name']} has been approved, request scheduling")
    job(logger, body.metadata["name"], namespace, body, 'apply')

@kopf.on.field(API_GROUP, API_VERSION, 'plans', field="status.applyStatus")
def applyStatus(diff, status, namespace, logger, body, **kwargs):
  if diff[0][2] != "Completed" and diff[0][3] == "Completed":
    logger.info(f'Plan {body.metadata["name"]} applying completed')
    log = get_pod_log(logger, namespace, body.status['applyJob'])
    updateCustomStatus(logger, 'plans', namespace, body.metadata.name, {'applyOutput' : log})

  if diff[0][2] != "Failed" and diff[0][3] == "Failed":
    logger.error(f'Plan {body.metadata["name"]} applying failed')
    log = get_pod_log(logger, namespace, body.status['applyJob'])
    updateCustomStatus(logger, 'plans', namespace, body.metadata.name, {'applyOutput' : log})
    if "Saved plan is stale" in log:
      logger.info(f"Saved plan is stale, trying to request a new plan with OriginalPlan {body.metadata.name}")
      ori = body.spec['originalPlan'] if 'originalPlan' in body.spec else body.metadata.name
      targets = body.spec['targets'] if 'targets' in body.spec else None
      create_plan(logger, body.spec['state'], namespace, f'auto-fix-{ori}', originalPlan=ori, originalPlanRequest=body.metadata.annotations['planRequest'], targets=targets)

  if diff[0][2] != "Active" and diff[0][3] == "Active":
    logger.info(f'Plan {body.metadata["name"]} become Active')

@kopf.on.delete(API_GROUP, API_VERSION, 'plans')
def planDelete(body, name, namespace, logger, event, **kwargs):
  logger.info(f"Deleting plan {name}[{namespace}], cleaning associate planOutputs & job")
  if body.spec["deletePlansOnDeleted"]: 
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
def planRequestDelete(body, name, namespace, logger, event, **kwargs):
  if "spec" in body and body['spec']["deletePlanOnDeleted"]: 
    try:
      a = body['status']['plans']
    except:
      return
    for plan in body['status']['plans']:
      logger.info(f"Deleting plan {plan}[{namespace}]")
      try:
        custom_api_instance.delete_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'plans', plan)
      except ApiException as e:
        logger.error(f"Exception when trying to delete plan {plan} : {e}")
        return

## JOBS handlers
@kopf.on.field('batch', 'v1', 'jobs', field="status.failed")
def jobFailed(diff, status, namespace, logger, body, **kwargs):
  if diff == ():
    return
  try:
    body["metadata"]["labels"]["app"] == "tfgen" == True
  except:
    return
  tftype =  'apply' if body["metadata"]["annotations"]["type"] == "apply" else 'plan'
  if diff[0][3] > 0:
    status = {f'{tftype}Status' : 'Failed', f'{tftype}CompleteTime' : "Failed"}
    updateCustomStatus(logger, 'plans', namespace, body.metadata.annotations['planName'], status)


@kopf.on.field('batch', 'v1', 'jobs', field="status.succeeded")
def jobSucceeded(diff, status, namespace, logger, body, **kwargs):
  if diff == ():
    return
  try:
    body["metadata"]["labels"]["app"] == "tfgen" == True
  except:
    return
  if diff[0][2] != True and diff[0][3] == True:
    end = body.status['completionTime']
    tftype =  'apply' if body["metadata"]["annotations"]["type"] == "apply" else 'plan'
    status = {f'{tftype}StartTime': body.status['startTime'], f'{tftype}Status' : 'Completed', f'{tftype}CompleteTime' : end}
    updateCustomStatus(logger, 'plans', namespace, body.metadata.annotations['planName'], status)

@kopf.on.field('batch', 'v1', 'jobs', field="status.active")
def jobActive(diff, status, namespace, logger, body, **kwargs):
  if diff == ():
    return
  try:
    body["metadata"]["labels"]["app"] == "tfgen" == True
  except:
    return
  if diff[0][2] != True and diff[0][3] == True:
    state = 'Active'
    tftype =  'apply' if body["metadata"]["annotations"]["type"] == "apply" else 'plan'
    status = {f'{tftype}StartTime': body.status['startTime'], f'{tftype}Status' : state}
    updateCustomStatus(logger, 'plans', namespace, body.metadata.annotations['planName'], status)

@kopf.on.field('batch', 'v1', 'jobs', field="status.conditions")
def jobCondition(diff, status, namespace, logger, body, **kwargs):
  if diff == ():
    return
  try:
    body["metadata"]["labels"]["app"] == "tfgen" == True
  except:
    return
  tftype =  'apply' if body["metadata"]["annotations"]["type"] == "apply" else 'plan'
  status = {f'{tftype}Conditions': body.status['conditions']}
  updateCustomStatus(logger, 'plans', namespace, body.metadata.annotations['planName'], status)
  
  if len(diff[0][3]) > 0:
    evs = diff[0][3]
    failed=0
    for ev in evs:
      if ev['type'] == "Failed":
        failed=1
        end = ev['lastTransitionTime']
    if failed:
      status = {f'{tftype}Status' : 'Failed', f'{tftype}CompleteTime' : end}
      updateCustomStatus(logger, 'plans', namespace, body.metadata.annotations['planName'], status)
