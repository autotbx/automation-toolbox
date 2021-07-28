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
# plans : use conditions
# jobsLog if failed
# realTime joblog ?


def updateCustomStatus(logger, plural, namespace, name, vals):
  try:
    currentStatus = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, plural, name)
  except client.ApiException:
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
    env_ansible_run = client.V1EnvVar(name="ANSIBLEPLAN_NAME", value=name)
    env_ansible_color = client.V1EnvVar(name="ANSIBLE_FORCE_COLOR", value="1")
    env_ansible_color2 = client.V1EnvVar(name="PY_COLORS", value="1")
    env = [env_ansible_config, env_ansible_log, env_namespace, env_ansible_run, env_ansible_color, env_ansible_color2]
    vols_mount = [client.V1VolumeMount(name="data", mount_path="/data"), client.V1VolumeMount(name="ansible-config", mount_path="/config", read_only=True)]
    vols = [client.V1Volume(name="ansible-config", config_map=client.V1ConfigMapVolumeSource(name="ansible-config")), client.V1Volume(name="data", empty_dir={})]
    limit = ""
    if "targets" in obj:
      limit = " --limit " + ','.join(targets)
    if action == "plan":
      run_args = [f"python /ansible_run.py --plan {limit}"]
    elif action == "apply":
      run_args = [f"python /ansible_run.py --apply {limit}"]
    
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
  plural = 'plans' if jobtype == "terraform" else "ansplans"
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
      # module status ? 
    except ApiException as e:
      logger.error("Exception when calling CustomObjectsApi->create_namespaced_custom_object: %s\n" % e)

def create_plan(logger, stateName, namespace, planRequest, originalPlan=None, originalPlanRequest=None, targets=None):
  state = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'states', stateName)
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
@kopf.on.create(API_GROUP, API_VERSION, 'ansplans')
def createPlan(body, name, namespace, logger, **kwargs):
  jobtype = 'terraform' if body['kind'] == "Plan" else 'ansible'
  job(logger, body.metadata["name"], namespace, body, jobtype, 'plan')

@kopf.on.field(API_GROUP, API_VERSION, 'plans', field="status.planStatus")
@kopf.on.field(API_GROUP, API_VERSION, 'ansplans', field="status.planStatus")
def planStatus(diff, status, namespace, logger, body, **kwargs):
  plural = 'plans' if body['kind'] == "Plan" else "ansplans"
  if diff[0][2] != "Completed" and diff[0][3] == "Completed":
    log = get_pod_log(logger, namespace, body.status['planJob']) #TODO
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
    log = get_pod_log(logger, namespace, body.status['planJob']) #todo
    updateCustomStatus(logger, plural, namespace, body.metadata.name, {'planOutput' : log})
  
  if diff[0][2] != "Active" and diff[0][3] == "Active":
    logger.info(f'{body["kind"]} {body.metadata["name"]} become Active')

@kopf.on.field(API_GROUP, API_VERSION, 'plans', field="spec.approved")
@kopf.on.field(API_GROUP, API_VERSION, 'ansplans', field="spec.approved")
def approved(diff, status, namespace, logger, body, **kwargs):
  if diff[0][2] == False and diff[0][3] == True and body.status['applyStatus'] == 'Pending' and body.status['planStatus'] == 'Completed':
    jobtype = 'terraform' if body['kind'] == "Plan" else 'ansible'
    logger.info(f"{body['kind']} {body.metadata['name']} has been approved, request scheduling")
    job(logger, body.metadata["name"], namespace, body, jobtype, 'apply')

@kopf.on.field(API_GROUP, API_VERSION, 'plans', field="status.applyStatus")
@kopf.on.field(API_GROUP, API_VERSION, 'ansplans', field="status.applyStatus")
def applyStatus(diff, status, namespace, logger, body, **kwargs):
  plural = 'plans' if body['kind'] == "Plan" else "ansplans"
  if diff[0][2] != "Completed" and diff[0][3] == "Completed":
    logger.info(f'{body["kind"]} {body.metadata["name"]} applying completed')
    log = get_pod_log(logger, namespace, body.status['applyJob']) #todo
    updateCustomStatus(logger ,plural, namespace, body.metadata.name, {'applyOutput' : log})

  if diff[0][2] != "Failed" and diff[0][3] == "Failed":
    logger.error(f'Plan {body.metadata["name"]} applying failed')
    try: 
      log = get_pod_log(logger, namespace, body.status['applyJob'])
    except kubernetes.client.ApiException:
      log = "pod not found"
    updateCustomStatus(logger, plural, namespace, body.metadata.name, {'applyOutput' : log})
    if body['kind'] == "Plan" and log and "Saved plan is stale" in log:
      logger.info(f"Saved plan is stale, trying to request a new plan with OriginalPlan {body.metadata.name}")
      ori = body.spec['originalPlan'] if 'originalPlan' in body.spec else body.metadata.name
      targets = body.spec['targets'] if 'targets' in body.spec else None
      create_plan(logger, body.spec['state'], namespace, f'auto-fix-{ori}', originalPlan=ori, originalPlanRequest=body.metadata.annotations['planRequest'], targets=targets)

  if diff[0][2] != "Active" and diff[0][3] == "Active":
    logger.info(f'{body["kind"]} {body.metadata["name"]} become Active')

@kopf.on.delete(API_GROUP, API_VERSION, 'plans')
def planDelete(body, name, namespace, logger, **kwargs):
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
def planRequestDelete(body, name, namespace, logger,  **kwargs):
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

## ANSIBLE NEW handlers

#def ansjob(logger, name, namespace, body, jobtype):
#  job = _ans_run(body.metadata["name"], namespace, body, jobtype)
#  if job != False:
#      logger.info(f"Ansible{jobtype} {job} scheduled successfully")
#      status = {f'{jobtype}Job': job}
#      updateCustomStatus(logger, 'ansplans', namespace, name, status)
#      return job
#  else:
#      logger.info(f"{jobtype} {job} scheduling failed")
#      return False
#
#def _ans_run(name: str, namespace: str, body, jobtype: str):
#  """ Create an ansible run job, which will only check or apply the changes
#  name: the object name where the job status will be reported
#  namespace: the kubernetes namespace where the job will run
#  check: whether the changes will be applied or not
#  plan: whether the check info should be reported on ansibleplan or ansiblerun
#  """
#  if jobtype == "plan":
#    options = "--check"
#    label = "ansible-plan"
#  else:
#    options = ""
#    label = "ansible-apply"
#  if "targets" in body:
#    options += " --limit " + ','.join(targets)
#
#  run_args = [f"cat /data/inventory.yaml; cat /data/playbook.yaml; ansible-playbook -f 1 -D {options} -i /data/inventory.yaml /data/playbook.yaml; ls /config "]
#  restart_policy = "Never"
#  backoff_limit = 0
#
#  share_vol_mount = client.V1VolumeMount(name="data", mount_path="/data")
#  config_vol_mount = client.V1VolumeMount(name="ansible-config", mount_path="/config", read_only=True)
#    
#  #TODO tf_container_image = planRequest.spec["tfExecutorImage"]
#  a5e_container_name = "ansible"
#  a5e_container_image =  body.spec["ansibleExecutorImage"]
#  a5e_image_policy =  body.spec["ansibleExecutorImagePolicy"]
#  a5e_command = [ "/bin/sh", "-x", "-c"]
#  a5e_vols_mounts = [config_vol_mount, share_vol_mount]
#  #TODO tf_image_policy = planRequest.spec["tfExecutorImagePullPolicy"]
#
#  gen_a5e_container_name  = "ansible-gen"
#  gen_a5e_container_image = body.spec["ansibleExecutorImage"]
#  gen_a5e_command = ["/bin/sh", "-x", "-c"]
#  gen_a5e_args = ["cp /config/certs /usr/local/share/ca-certificates/local.crt ; update-ca-certificates ; python ansible_gen.py"]
#  gen_a5e_vols_mount = [config_vol_mount, share_vol_mount]
#
#  env_ansible_config = client.V1EnvVar(name="ANSIBLE_CONFIG", value="/config/ansible.cfg")
#  env_ansible_log = client.V1EnvVar(name="ANSIBLE_LOG_PATH", value="/tmp/ansible.log")
#  env_namespace = client.V1EnvVar(name="K8S_NAMESPACE", value=namespace)
#  env_ansible_run = client.V1EnvVar(name="ANSIBLERUN_NAME", value=name)
#  env = [env_ansible_config, env_ansible_log, env_namespace, env_ansible_run]
#
#  a5e_container = client.V1Container(name=a5e_container_name, image=a5e_container_image, command=a5e_command,args=run_args, volume_mounts=a5e_vols_mounts, env=env)#, image_pull_policy=tf_image_policy, volume_mounts=vols_mount, env=env)
#  gen_a5e_container = client.V1Container(name=gen_a5e_container_name, image=gen_a5e_container_image, command=gen_a5e_command, args=gen_a5e_args, volume_mounts=gen_a5e_vols_mount, env=env)#, image_pull_policy=gentf_image_policy, env=env)
#
#  vols = [client.V1Volume(name="ansible-config", config_map=client.V1ConfigMapVolumeSource(name="ansible-config")), client.V1Volume(name="data", empty_dir={})]
#
#  template = client.V1PodTemplate()
#  template.template = client.V1PodTemplateSpec()
#  template.template.spec = client.V1PodSpec(containers=[a5e_container], init_containers=[gen_a5e_container], service_account_name="tfgen",restart_policy=restart_policy, automount_service_account_token=True, volumes=vols)#, volumes=[client.V1Volume(name="tf", empty_dir={})])
#  
#  body = client.V1Job()
#  body.metadata = client.V1ObjectMeta(namespace=namespace, generate_name=f"ans-{name}-", labels={"app": "ansible"}, annotations={'planName': name, 'type': jobtype})
#  body.status = client.V1JobStatus()
#  body.spec = client.V1JobSpec(ttl_seconds_after_finished=600, template=template.template, backoff_limit=backoff_limit)
#  
#  try: 
#    api_response = batch_api_instance.create_namespaced_job(namespace, body, pretty=True)
#    return api_response.metadata.name
#  except ApiException as e:
#    print("Exception when calling BatchV1Api->create_namespaced_job: %s\n" % e)





## ANSIBLE handlers





#def _ansible_run(name: str, namespace: str, check: bool, plan: bool):
#  """ Create an ansible run job, which will only check or apply the changes
#  name: the object name where the job status will be reported
#  namespace: the kubernetes namespace where the job will run
#  check: whether the changes will be applied or not
#  plan: whether the check info should be reported on ansibleplan or ansiblerun
#  """
#  if check:
#    options = "-C"
#    if not plan:
#      label = "ansible-check"
#  else:
#    options = ""
#  if plan:
#    options += "P"
#    label = "ansible-plan"
#    annotation = "ansiblePlan"
#  else:
#    annotation = "ansibleRun"
#    if not check:
#      label = "ansible-run"
#  run_args = [f"cat /data/inventory.yaml; /ansible_wrapper.py {options}; ls /config "]
#  restart_policy = "Never"
#  backoff_limit = 0
#
#  share_vol_mount = client.V1VolumeMount(name="data", mount_path="/data")
#  config_vol_mount = client.V1VolumeMount(name="ansible-config", mount_path="/config", read_only=True)
#    
#  #TODO tf_container_image = planRequest.spec["tfExecutorImage"]
#  a5e_container_name = "ansible"
#  a5e_container_image = "harbor.pks.lab.platform-essential.com/library/ansible:latest"
#  a5e_command = [ "/bin/sh", "-x", "-c"]
#  a5e_vols_mounts = [config_vol_mount, share_vol_mount]
#  #TODO tf_image_policy = planRequest.spec["tfExecutorImagePullPolicy"]
#
#  gen_a5e_container_name  = "ansible-gen"
#  gen_a5e_container_image ="harbor.pks.lab.platform-essential.com/library/ansible-gen:latest" 
#  gen_a5e_command = ["/bin/sh", "-x", "-c"]
#  gen_a5e_args = ["cp /config/certs /usr/local/share/ca-certificates/local.crt ; update-ca-certificates ; python ansible_gen.py"]
#  gen_a5e_vols_mount = [config_vol_mount, share_vol_mount]
#
#  env_ansible_config = client.V1EnvVar(name="ANSIBLE_CONFIG", value="/config/ansible.cfg")
#  env_ansible_log = client.V1EnvVar(name="ANSIBLE_LOG_PATH", value="/tmp/ansible.log")
#  env_namespace = client.V1EnvVar(name="K8S_NAMESPACE", value=namespace)
#  env_ansible_run = client.V1EnvVar(name="ANSIBLERUN_NAME", value=name)
#  env = [env_ansible_config, env_ansible_log, env_namespace, env_ansible_run]
#
#  a5e_container = client.V1Container(name=a5e_container_name, image=a5e_container_image, command=a5e_command,args=run_args, volume_mounts=a5e_vols_mounts, env=env)#, image_pull_policy=tf_image_policy, volume_mounts=vols_mount, env=env)
#  gen_a5e_container = client.V1Container(name=gen_a5e_container_name, image=gen_a5e_container_image, command=gen_a5e_command, args=gen_a5e_args, volume_mounts=gen_a5e_vols_mount, env=env)#, image_pull_policy=gentf_image_policy, env=env)
#
#  vols = [client.V1Volume(name="ansible-config", config_map=client.V1ConfigMapVolumeSource(name="ansible-config")), client.V1Volume(name="data", empty_dir={})]
#
#
#  template = client.V1PodTemplate()
#  template.template = client.V1PodTemplateSpec()
#  template.template.spec = client.V1PodSpec(containers=[a5e_container], init_containers=[gen_a5e_container], service_account_name="tfgen",restart_policy=restart_policy, automount_service_account_token=True, volumes=vols)#, volumes=[client.V1Volume(name="tf", empty_dir={})])
#  
#  body = client.V1Job()
#  body.metadata = client.V1ObjectMeta(namespace=namespace, generate_name=f"ans-{name}-", labels={"app": label}, annotations={'ansiblePlan': name})#, 'type': tftype})
#  body.status = client.V1JobStatus()
#  #todo config backoff
#  body.spec = client.V1JobSpec(ttl_seconds_after_finished=600, template=template.template, backoff_limit=backoff_limit)
#  
#  try: 
#    api_response = batch_api_instance.create_namespaced_job(namespace, body, pretty=True)
#    return api_response.metadata.name
#  except ApiException as e:
#    print("Exception when calling BatchV1Api->create_namespaced_job: %s\n" % e)
# #   print(e.args)
# #   print(e.with_traceback)
# #   print(body)
#    return False
#
#def _update_ans_status(namespace: str, plural: str, name: str, values: dict):
#  body = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, plural, name)
#  newstatus = body['status'] if 'status' in body else {}
#  for key, value in values.items():
#    newstatus[key] = value
#  body = {'status': newstatus}
#  try:
#    ret = custom_api_instance.patch_namespaced_custom_object_status(API_GROUP, API_VERSION, namespace, plural, name, body)
#  except ApiException as e:
#    print("Exception when calling CustomObjectsApi->patch_namespaced_custom_object_status: %s\n" % e)
#
#@kopf.on.create(API_GROUP, API_VERSION, 'ansiblerun')
#def ansible_run(body, name, namespace, logger, **kwargs):
#  #logging.getLogger("urllib3").setLevel(logging.DEBUG)
#  #import http.client
#  #http.client.HTTPConnection.debuglevel = 5
#
#  return _ansible_run(name, namespace, True, False)
#
#
#@kopf.on.create(API_GROUP, API_VERSION, 'ansiblerunrequest')
#def ansible_run_request(body, name, namespace, logger, **kwargs):
#  api_instance = client.CustomObjectsApi()
#  body = {
#      'apiVersion': f'{API_GROUP}/{API_VERSION}',
#      'kind': 'AnsiblePlan',
#      'metadata' : client.V1ObjectMeta(generate_name=f'arr-{name}-', namespace=namespace, labels={'source': 'ansibleRunRequest'}),
#      'spec': {
#        "approved": False,
#        "ansibleRunRequest": name
#      }
#  }
#
#  api_response = api_instance.create_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansibleplans',body)
#  _update_ans_status(namespace,'ansiblerunrequests', name, {'AnsiblePlan': api_response['metadata']['name']})
#
#
#@kopf.on.create(API_GROUP, API_VERSION, 'ansibleplan')
#def ansible_plan(body, name, namespace, logger, **kwargs):
#  _update_ans_status(namespace,'ansibleplans', name, {'Status': 'Init'})
#  _ansible_run(name, namespace, True, True)
#
#@kopf.on.field(API_GROUP, API_VERSION, 'ansibleplans', field="spec.approved")
#def ansPlanApproved(diff, status, namespace, logger, body, **kwargs):
#  logger.info("plan approbation changed")
#  approved = body["spec"]["approved"]
#  if approved:
#    api_instance = client.CustomObjectsApi()
#    plan_name = body["metadata"]["name"]
#    body = {
#        'apiVersion': f'{API_GROUP}/{API_VERSION}',
#        'kind': 'AnsibleRun',
#        'metadata' : client.V1ObjectMeta(generate_name=f'arr-{plan_name}-', namespace=namespace, labels={'source': 'ansibleplan'}),
#        'spec': {
#          'ansiblePlan': plan_name
#
#        }
#    }
#    api_instance.create_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansibleruns',body)
#

## JOBS handlers
@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'terraform'}, field="status.succeeded")
@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible'}, field="status.succeeded")
def jobSucceeded(diff, status, namespace, logger, body, **kwargs):
  if diff == ():
    return
  if diff[0][2] != True and diff[0][3] == True:
    end = body.status['completionTime']
    plural = 'plans' if body['kind'] == "Plan" else "ansplans"
    tftype =  'apply' if body["metadata"]["annotations"]["type"] == "apply" else 'plan'
    status = {f'{tftype}StartTime': body.status['startTime'], f'{tftype}Status' : 'Completed', f'{tftype}CompleteTime' : end}
    plan_name = body.metadata.annotations['planName']
    updateCustomStatus(logger, plural, namespace, plan_name, status)
    
    if body['kind'] == 'Plan' and tftype == "apply":
      # TODO: targets not mandatory ?
      plan = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'plans', plan_name)
      targets = plan["spec"]["targets"]
      hosts = []
      module_names = []
      for target in targets:
        module_name = target.split(".")[1]
        module_names.append(module_name)
        module = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'modules', module_name)

        if "ansibleAttributes" in module["spec"] and "targets" in module["spec"]["ansibleAttributes"]:
          for host in module["spec"]["ansibleAttributes"]["targets"]:
            hosts.append(host['fqdn'])
      if len(hosts) == 0:
        logger.info(f"No FQDN found for module {modules_names}, skipping AnsiblePlan creation")
        return
      plan_body = {
        'apiVersion': f'{API_GROUP}/{API_VERSION}',
        'kind': 'AnsiblePlan',
        'metadata' : client.V1ObjectMeta(generate_name=f'ter-{plan_name}-', namespace=namespace, labels={'source': 'TerraformPlan', "terraformPlan": plan_name}),
        'spec': {
          "approved": False,
          "auto": {
            "hosts": hosts,
            "terraformPlan": plan_name
          }
        }
      }
      api_response = custom_api_instance.create_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansibleplans', plan_body)
      updateCustomStatus(logger, 'plans', namespace, plan_name, {'AnsiblePlan': api_response['metadata']['name']})

@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'terraform'}, field="status.active")
@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible'}, field="status.active")
def jobActive(diff, status, namespace, logger, body, **kwargs):
  if diff == ():
    return
  if diff[0][2] != True and diff[0][3] == True:
    state = 'Active'
    tftype =  'apply' if body["metadata"]["annotations"]["type"] == "apply" else 'plan'
    status = {f'{tftype}StartTime': body.status['startTime'], f'{tftype}Status' : state}
    plural = 'plans' if body["metadata"]['labels']["app"] == "terraform" else "ansplans"
    updateCustomStatus(logger, plural, namespace, body.metadata.annotations['planName'], status)

@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'terraform'}, field="status.conditions")
@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible'}, field="status.conditions")
def jobCondition(diff, status, namespace, logger, body, **kwargs):
  if diff == ():
    return
  tftype =  'apply' if body["metadata"]["annotations"]["type"] == "apply" else 'plan'
  plural = 'plans' if body["metadata"]['labels']["app"] == "terraform" else "ansplans"
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
#  plural = 'plans' if body["metadata"]['labels']["app"] == "tfgen" else "ansplans"
#  if diff[0][3] > 0:
#    status = {f'{tftype}Status' : 'Failed', f'{tftype}CompleteTime' : "Failed"}
#    updateCustomStatus(logger, plural, namespace, body.metadata.annotations['planName'], status)


#@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible-plan'}, field="status.active")
#def ansPlanActive(diff, status, namespace, logger, body, **kwargs):
#  ansible_plan = body['metadata']['annotations']['ansiblePlan']
#  _update_ans_status(namespace, 'ansplans', ansible_plan, {'planStatus': 'Active', 'planStartTime': body.status['startTime']})
#
#@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible-plan'}, field="status.failed")
#def ansPlanFailed(diff, status, namespace, logger, body, **kwargs):
#  ansible_plan = body['metadata']['annotations']['ansiblePlan']
#  # TODO check if other path possible
#  if diff[0][3] > 0:
#    status = {'planStatus' : 'Failed', 'planCompleteTime' : body.status['completionTime']}
#    updateCustomStatus(logger, 'ansplans', namespace, ansible_plan, status)


@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible-plan'}, field="status.succeeded")
def ansPlanSuccess(diff, status, namespace, logger, body, **kwargs):
  ansible_plan = body['metadata']['annotations']['ansiblePlan']
  if diff[0][2] != True and diff[0][3] == True:
    end = body.status['completionTime']
    plan = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansibleplans', ansible_plan)
    if plan['spec']['ansibleCheckResult']:
      check_status = 'Completed'
    else:
      check_status = 'Failed'

    status = {'StartTime': body.status['startTime'], 'Status' : check_status, 'CompleteTime' : end}
    updateCustomStatus(logger, 'ansibleplans', namespace, ansible_plan, status)

    if 'auto' in plan['spec']:
      custom_api_instance.patch_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansibleplans', ansible_plan, {'spec': { 'approved': True }})


def _compare_diff(plan: str, run:str, logger):
  plan_lines = plan.splitlines()
  run_lines = run.splitlines()

  if len(plan_lines) != len(run_lines):
    logger.info("plan and check run not same number of lines")

  equal = True
  for i in range(0, len(plan_lines)):
    p_line = plan_lines[i]
    r_line = run_lines[i]

    if "/.ansible/tmp/" not in p_line:
      if p_line != r_line:
        equal = False
        break
  return equal

#@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible-check'}, field="status.active")
#def ansCheckActive(diff, status, namespace, logger, body, **kwargs):
#  ansible_run_name = body['metadata']['annotations']['ansibleRun']
#  status = {'Status' : 'Check started'}
#  updateCustomStatus(logger, 'ansibleruns', namespace, ansible_run_name, status)
#
#@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible-check'}, field="status.failed")
#def ansCheckFailed(diff, status, namespace, logger, body, **kwargs):
#  ansible_run_name = body['metadata']['annotations']['ansibleRun']
#  status = {'Status' : 'Check failed'}
#  updateCustomStatus(logger, 'ansibleruns', namespace, ansible_run_name, status)
#
#@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible-check'}, field="status.succeeded")
#def ansCheckSuccess(diff, status, namespace, logger, body, **kwargs):
#  ansible_run_name = body['metadata']['annotations']['ansibleRun']
#  ansible_run = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansibleruns', ansible_run_name)
#  ansible_plan_name = ansible_run['spec']['ansiblePlan'] 
#  ansible_plan = custom_api_instance.get_namespaced_custom_object(API_GROUP, API_VERSION, namespace, 'ansibleplans', ansible_plan_name)
#
#  if _compare_diff(ansible_plan['spec']['ansibleCheckLog'],ansible_run['spec']['ansibleCheckLog'], logger):
#    status = {'Status': 'check completed'}
#    updateCustomStatus(logger, 'ansibleruns', namespace, ansible_run_name, status)
#    _ansible_run(ansible_run_name, namespace, False, False)
#  else:
#    status = {'Status': 'diff between plan and check are not equal'}
#    updateCustomStatus(logger, 'ansibleruns', namespace, ansible_run_name, status)
#    logger.info("diff between plan and check")
#
#@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible-run'}, field="status.active")
#def ansCheckActive(diff, status, namespace, logger, body, **kwargs):
#  ansible_run_name = body['metadata']['annotations']['ansibleRun']
#  status = {'Status' : 'Apply started'}
#  updateCustomStatus(logger, 'ansibleruns', namespace, ansible_run_name, status)
#
#@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible-run'}, field="status.failed")
#def ansCheckFailed(diff, status, namespace, logger, body, **kwargs):
#  ansible_run_name = body['metadata']['annotations']['ansibleRun']
#  status = {'Status' : 'Apply failed'}
#  updateCustomStatus(logger, 'ansibleruns', namespace, ansible_run_name, status)
#
#@kopf.on.field('batch', 'v1', 'jobs', labels={'app': 'ansible-run'}, field="status.succeeded")
#def ansRunSuccess(diff, status, namespace, logger, body, **kwargs):
#  ansible_run_name = body['metadata']['annotations']['ansibleRun']
#  status = {'Status' : 'apply completed'}
#  updateCustomStatus(logger, 'ansibleruns', namespace, ansible_run_name, status)

@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_):
    settings.posting.level = logging.DEBUG
