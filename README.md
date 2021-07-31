# AUTOMATION-TOOLBOX

This is the reposity for the automation-toolbox.

automation-toolbox is is an operator for Kubernetes.

The goal of this operator is to provide Kubernetes CRDs to manage :

* the plan, execution and the state of a terraform project based on external terraform module
* the plan, execution of a ansible project based on external ansible role

The idea is to have a simple way to consume a terraform module/ansible roles without advanced terraform/ansible understanding.

# High level Overview

Usually, a terraform project is managed by terraform planning/apply operation and is composed with :

* State
* Providers
* Modules (Resources/DataSources/Variables)

The operator define these same objects/actions by extending Kubernetes API with the following objects:

* ClusterProviders (cluster-wide)
* Providers (namespaced)
* States (namespaced)
* Modules (namespaced)
* PlanRequests (namespaced)
* Plans  (namespaced)

In addition to the previous items, a templating engine is available for the Modules object to avoid to share the attributes between various modules with the following objects:

* ClusterModuleTemplates (cluster-wide)
* ModuleTemplates (namespaced)

Cluster-wide objects are used to be shared between multiple namespace.

Module is also used for ansible configuration

At the moment, one Kubernetes namespace represent a terraform project that use the same terraform state.
These objects can be represented like this:

![terraform-operator-k8s-view](https://github.com/dstoffel/terraform-operator/blob/master/docs/images/terraform-operator-k8s-view.png?raw=true)

# Terraform global execution workflow

The workflow can be represented as : 

![terraform-op-workflow](https://github.com/dstoffel/terraform-operator/blob/master/docs/images/terraform-op-workflow.png?raw=true)

## Stale plan / Locked state

During a terraform apply, 3 known kinds of errors can be returned:

* Staled plan : the plan was generated with a previous version of the state (ie another plan was executed in the mean time)
* Locked state: Cannot lock the state, another terraform apply is currently running. (not yet implemented)
* Common terraform error: need to review the applyJobStatus to understand the terraform error and fix it

The operator will manage automatically the Staled plan & Locked state scenario.

* Staled plan : Another PlanRequest is submitted with an originalPlan attribute and the attribute Approved=true. The plan is strictly compared to the previous generated plan and will raise a Failed status if the plan is different, otherwise, the plan will be appied.
* Locked state: Wait for the retry period attribute of the state and submit another PlanRequests with Approved=true.


## Environment support

Environment support is a feature that enable the following object to overwrite attributes from the defaultAttributes for the **working environment**:

* ClusterModuleTemplate
* ClusterProvider

The state defined the **working environment**. This allow to avoid to create multiple resources with only a few differents settings that depend on the environment.

Example with a ClusterModuleTemplate with environment support enabled :

```
apiVersion: terraform.dst.io/v1
kind: ClusterModuleTemplate
metadata:
  name: svvm
spec:
  defaultAttributes:
  - name: cluster_name
    sValue: VxRail
  - name: datacenter_name
    sValue: Datacenter
  - name: datastore_name
    sValue: VSAN
  - name: dns_servers
    lsValue:
    - 172.19.36.2
  - name: domain
    sValue: vm.lab.platform-essential.com
  - name: folder_path
    sValue: dst
  - name: network_name
    sValue: vm_network
  - name: source
    sValue: git::http://toolbox.vm.lab.platform-essential.com/toolbox-repos/terraform-module-svvm.git
  - name: template_name
    sValue: ubuntu-1804-tpl-davy
  environments:
  - name: dev 
    defaultAttributes:
    - name: folder
      sValue: dst-dev
  requiredAttributes:
  - name: vmnames
    type: lsValue
  - name: num_cpus
    type: iValue
  - name: memory
```

With this definition, if the ClusterModuleTemplate is used with a state that have the environment attribute to DEV will use the folder_path: 'dst-dev' attributes instead of the defaultAttributes defined previously.
*A Module can also overwrite an attribute*

## Terraform code generation

The code of terraform is automatically created from the various objects defined. The container tfgen is responsible to generate the all terraform files.
All the following objects are defined using the term **Attributes** which correspond to the line generated in the corresponding object during a terraform operation:

* ClusterProviders (cluster-wide)
* Providers (namespaced)
* Modules (namespaced)


For example, a Provider with the following definition :

```
apiVersion: terraform.dst.io/v1
kind: Provider
metadata:
  name: vcsa
spec:
  type: vsphere
  autoPlanRequest: true
  attributes:
  - name: user
    sValue: "toolbox2@lab.platform-essential.com"
  - name: password
    sValue: "Toolbox12*"
  - name: vsphere_server
    sValue: vcsa.mgt.lab.platform-essential.com
  - name: allow_unverified_ssl
    bValue: true
```

will generated the corresponding terraform file :

```
provider "vsphere" {
	user     = "administrator@vsphere.local"
	password = "VMware123!"
	vsphere_server   = "vcsa.local""
	allow_unverified_ssl = true
}

```

The same behaviour happens the previous listed objets, except for the Modules that support attributes heritance from the referenced template.
State is automatically managed by the operator.

You can use the commands ``` kubectl logs POD-ID -c terraform-gen``` to have the generated output.

## Ansible code generation

The code is generated from the modules ansibleAttributes key. These attributes take the attributes heritence from the referenced templates.


# Objects definitions
## Attributes type

Multiple type of attributes is available:

| type | description  |
|----------|----------|
|iValue    | integer  |
|sValue    | string   |
|bValue    | boolean  |
|nValue    | number   |
|liValue    | list of integer  |
|lsValue    | list of string   |
|lbValue    | list of boolean  |
|lnValue    | list of number   |

## ClusterProviders 
This object represent a terraform provider at the cluster. Cluster level is used to shared a Providers with multiple namespace.

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the provider|
|spec.type |string|true      |         |Type of the provider (terraform name)|
|spec.autoPlanRequest|boolean|true||Create auto PlanRequest if modified|
|spec.attributes| array[attributes]   |true|         | attributes to use for terraform|
|spec.environments | array[array[attributes]] |false|| Overwrite attributes for defined env|

```
apiVersion: terraform.dst.io/v1
kind: ClusterProvider
metadata:
  name: vcsa
spec:
  type: vsphere
  autoPlanRequest: true
  attributes:
  - name: user
    sValue: "toolbox2@lab.platform-essential.com"
  - name: password
    sValue: "Toolbox12*"
  - name: vsphere_server
    sValue: vcsa.mgt.lab.platform-essential.com
  - name: allow_unverified_ssl
    bValue: true
  environments:
  - name: fakeenv
    attributes:
    - name: user
      sValue: 'XXXX'
```

## Providers

This object represent a terraform provider at the namespace level.

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the provider|
|spec.type |string|true      |         |Type of the provider (terraform name)|
|spec.autoPlanRequest|boolean|true||Create auto PlanRequest if modified|
|spec.attributes| array[attributes]   |true|         | attributes to use for terraform|


```
apiVersion: terraform.dst.io/v1
kind: Provider
metadata:
  name: vcsa
spec:
  type: vsphere
  autoPlanRequest: true
  attributes:
  - name: user
    sValue: "toolbox2@lab.platform-essential.com"
  - name: password
    sValue: "Toolbox12*"
  - name: vsphere_server
    sValue: vcsa.mgt.lab.platform-essential.com
  - name: allow_unverified_ssl
    bValue: true
```

## States

This object define the state properties

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the state|
|spec.clusterProviders |array[string]|false      |         |Provider to include in this state|
|spec.autoPlanRequest|boolean|true||Create auto PlanRequest if modified|
|spec.autoPlanApprove|boolean|true||Automatically approve generated plan|
|spec.deleteJobsOnPlanDeleted| boolean |true||Delete jobs created by the deleted plan|
|spec.deletePlansOnPlanDeleted| boolean |true||todo|
|spec.customTerraformInit| string |false|| Custom terraform section { } code|
|spec.tfGeneratorImage| string |false|TODO| Terraform code generator image pulling path|
|spec.tfExecutorImage| string |false|TODO| Terraform executor image pulling path|
|spec.tfGeneratorImagePullPolicy| string |false|TODO| erraform code generator image policy|
|spec.tfExecutorImagePullPolicy| string |false|TODO| erraform code generator image policy|

```
apiVersion: terraform.dst.io/v1
kind: State
metadata:
  name: mystate
spec:
  clusterProviders:
  - vcsa
  environment: dev
  autoPlanApprove: false
  autoPlanRequest: true
  deleteJobsOnPlanDeleted: true
  deletePlansOnPlanDeleted: true
  customTerraformInit: 'required_providers { vsphere = "= 1.15" }'
```

## Modules
### ClusterModuleTemplates

ClusterModuleTemplates can be consumed by a Module to provides default configuration with the possibilities to overwrite specific parameters


| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the ClusterModuleTemplate|
|spec.autoPlanRequest | string |false | true       |Enable auto plan request on object modificiation|
|spec.requiredAttributes|array[attributes]|true      |         |Required attributes for module that consume this template|
|spec.defaultAttributes|array[attributes]|true      |         |Default attributes for module that consume this template|
|spec.environments|array[array[attributes]]|false      |         |Default attributes for module that consume this template in the specify environment|

```
apiVersion: terraform.dst.io/v1
kind: ClusterModuleTemplate
metadata:
  name: svvm
spec:
  defaultAttributes:
  - name: cluster_name
    sValue: VxRail
  - name: datacenter_name
    sValue: Datacenter
  - name: datastore_name
    sValue: VSAN
  - name: dns_servers
    lsValue:
    - 172.19.36.2
  - name: domain
    sValue: vm.lab.platform-essential.com
  - name: folder_path
    sValue: dst
  - name: network_name
    sValue: vm_network
  - name: source
    sValue: git::http://toolbox.vm.lab.platform-essential.com/toolbox-repos/terraform-module-svvm.git
  - name: template_name
    sValue: ubuntu-1804-tpl-davy
  environments:
  - name: dev 
    defaultAttributes:
    - name: folder
      sValue: dst-dev
  requiredAttributes:
  - name: vmnames
    type: lsValue
  - name: num_cpus
    type: iValue
  - name: memory
    type: iValue
 ```

### ModuleTemplates

ModuleTemplates can be consumed by a Module to provides default configuration with the possibilities to overwrite specific parameters


| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the ModuleTemplate|
|spec.autoPlanRequest | string |false | true       |Enable auto plan request on object modificiation|
|spec.requiredAttributes|array[attributes]|true      |         |Required attributes for module that consume this template|
|spec.defaultAttributes|array[attributes]|true      |         |Default attributes for module that consume this template|

```
apiVersion: terraform.dst.io/v1
kind: ModuleTemplate
metadata:
  name: svvm
spec:
  defaultAttributes:
  - name: cluster_name
    sValue: VxRail
  - name: datacenter_name
    sValue: Datacenter
  - name: datastore_name
    sValue: VSAN
  - name: dns_servers
    lsValue:
    - 172.19.36.2
  - name: domain
    sValue: vm.lab.platform-essential.com
  - name: folder_path
    sValue: dst
  - name: network_name
    sValue: vm_network
  - name: source
    sValue: git::http://toolbox.vm.lab.platform-essential.com/toolbox-repos/terraform-module-svvm.git
  - name: template_name
    sValue: ubuntu-1804-tpl-davy
  requiredAttributes:
  - name: vmnames
    type: lsValue
  - name: num_cpus
    type: iValue
  - name: memory
    type: iValue
 ```

### Modules

A module object represent a terraform module.

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the Module|
|spec.autoPlanRequest | string |false | true       |Enable auto plan request on object modificiation|
|spec.requiredAttributes|array[attributes]|true      |         |Required attributes for module that consume this template|
|spec.defaultAttributes|array[attributes]|true      |         |Default attributes for module that consume this template|

```
apiVersion: terraform.dst.io/v1
kind: Module
metadata:
  name: myvms
spec:
  attributes:
  - name: network_name
    sValue: heheh
  - name: vmnames
    lsValue:
    - myvm2
    - myvm1
  - name: memory
    iValue: 2048
  - name: num_cpus
    iValue: 2
  clusterModuleTemplate: svvm
```


## PlanRequests

PlanRequest are used to request the generation of a new Plan.

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the PlanRequest|
|spec.deletePlanOnDeleted |boolean|false      |false         |Delete generated Plan on deletion|
|spec.targets|array[string]|false||Target limitation during terraform operation|


## Plans

Plan is the equivalent of the terraform plan/apply. You should create this object as they are created by the PlanRequest object.

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the Plan|
|spec.approved |boolean]|true      |         |Approved plan (ie terraform apply will run with this plan)|
|spec.targets|array[string]|false||Target limitation during terraform operation|
|spec.tfGeneratorImage| string |false|TODO| Terraform code generator image pulling path|
|spec.tfExecutorImage| string |false|TODO| Terraform executor image pulling path|
|spec.tfGeneratorImagePullPolicy| string |false|TODO| erraform code generator image policy|
|spec.tfExecutorImagePullPolicy| string |false|TODO| erraform code generator image policy|




## Ansible

Ansible runs are launched when a Terraform run is finished or manually when  a user request it

```
      +---+
      |   |
      |   |                        +---------------+
      +-+-+                        |               |
        |                          | TerraformRun  |
        |  User                    |               |
        |                          +-------+-------+
        |                                  |
        |                                  |
     +--+--+                               |
     |     |                               |
     +  +  +                               |
        |                                  |
        |                                  |
        |                                  |
        |                                  v
        v
                                     AnsiblePlan   +
AnsibleRunRequest  +-------------->                |
                                         auto:     |
  ansiblePlan:
   -
   -                                        hosts:  +----> ansible-playbook -C
                                             -
                                             -
                                            terraformPlan: 
                                         approved
                                         executionDate
                                         hostImpacted
                                         diff
                                         status
                                         ansibleRunRequest: 
                                         +
                                         |
                                         v

                                     AnsibleRun
                                                  +
                                      ansiblePlan |
                                                  +-----> ansible-playbook -C
                                                             +
                                     executionDate
                                     hostImpacted
                                     diff
                                     status
                                                  <----------+

                                                  +-----> ansible-playbook
```

The workflow is the following:

When a Terraform apply is finished, a AnsiblePlan is created with the `auto`
parameter, which contains the list of hosts impacted by Ansible (copied from
the `ansibleArgs.hosts` from the module). `ansible-playbook -C` is run on all
playbook, the output is parsed and the hosts impacted by the run are
analysed. Only if `auto.hosts` is equal to `hostImpacted` is equal, the
`ansible-plan is auto-approved.

If a user create an `AnsibleRunRequest` the plan is created (without the
`auto` parameter), a check is run and the plan must be manually approved to
generate an `Ansiblerun `.

If no changes are detected, the plan will not generate a run.

When the plan is approved, an `AnsibleRun` is created, first, it will run
`ansible-playbook` -C and validate that the diff of change from the plan are
the same. If it's the same, `ansible-playbook` is run.

### Ansible config

Global ansible config must be defined in `ansible-config` ConfigMap, e.g.:

```
apiVersion: v1
data:
  ansible.cfg: |
    [defaults]
    log_file=/tmp/ansible.log
  certs: |-
    -----BEGIN CERTIFICATE-----
    MIIDMzCCAhugAwIBAgIJANUZ1ChD0mPGMA0GCSqGSIb3DQEBCwUAMDAxLjAsBgNV
    BAMMJXRvb2xib3gudm0ubGFiLnBsYXRmb3JtLWVzc2VudGlhbC5jb20wHhcNMjEw
    MzE1MTgyODM1WhcNMzEwMzEzMTgyODM1WjAwMS4wLAYDVQQDDCV0b29sYm94LnZt
    LmxhYi5wbGF0Zm9ybS1lc3NlbnRpYWwuY29tMIIBIjANBgkqhkiG9w0BAQEFAAOC
    AQ8AMIIBCgKCAQEAtsbi1Ag7WOujRQHDCOVQFtReON3rNpO+dBlXXuAH2ZYaVMJA
    FzAHWI3IYY8bwT7VBWP2BmMLNHjPh17eeoC72FyeqvS3DNsWcZNnpDk64cljTEJC
    d3dRJixIgFrufoa7oqa/fv8VdchGJgxExjpicd3gp6HW5+Tz+YsJ5qYhQgogJ/Kl
    agthf3AGedGdoDIaU7zvzwkVt29fi425We4JVUXKhhb7jG17aWU2Oko5lgkFFy+1
    7nJrXfSko1eFNv4SG0vC0flNlF0Hod3P7tdf0pDfmQ3fVp1jFP6W9m+swQeqtVzN
    ae3vNBn7QXORgbm0KQzDeYS4/Pwq+9uz75SAjwIDAQABo1AwTjAdBgNVHQ4EFgQU
    Nc51dwzwSuctHGxv8ookgGIQ3AswHwYDVR0jBBgwFoAUNc51dwzwSuctHGxv8ook
    gGIQ3AswDAYDVR0TBAUwAwEB/zANBgkqhkiG9w0BAQsFAAOCAQEADCKviNl9Xp1a
    bsaoNKOjOX2hNc1xLLAyAEtWv1j38EhLcO8ya/iIu6fcCt/GJKhyXT+9W6A1lNkv
    Fvh7PTtj34UWkgPLomJFalLFVgLjxXn0Rs+Oe+wgEh9JTzFXgJxzlY+7SkBSoFmH
    N30Grp3YRE0KRb1lprtJOUstMnOSEttlq8hMczmhDkjZpJQTSBn5A3Fph4rWA7aF
    cCjozMtmNLyc4yUeiXg7fr2TmLMpA9BEA+z+qWJDfCycqeyCx8I8hf1BMH8MeJ2R
    +R7RNhjj2sdvEnywNpk0f2TTFObwkt7plxIw5aXdWU7qWuS0eUo3I0JGWjLHKN7z
    jrDKTa1yHA==
    -----END CERTIFICATE-----
kind: ConfigMap
metadata:
  name: ansible-config
  namespace: default
```

### Modules

To configure ansible in the module, the following args must be used:

```yaml
apiVersion: terraform.dst.io/v1
kind: Module
metadata:
  name: mymod2
  label:
spec:
  ...
  ansibleAttributes:
    defautGalaxyServer: string
    roles:
      - exampleRole
      - otherRole
    targets:
      - fqdn: myhost1
        credentials:
          login:
          password:
          sshkey:
          type: winrm/ssh
        vars:
          override: value
      - fqdn: myhost2

    vars:
      abc: def
      other: value
    credentials:
     ...
```

# TODO

- Check what happens when CRD are created when ansible not there
- Lock strategy when Ansible or Terraform job is running to prevent two jobs to run in the same namespace 
- Retry strategy when a job is finished to launch waiting Ansible or Terraform jobs
- ModuleTemplate for ansible
- Galaxy server: https://docs.ansible.com/ansible/latest/galaxy/user_guide.html#downloading-a-collection-from-automation-hub
- Plan request sur plan, déplacer d'annotation dans spec
- Verify than a ansible plan is always created after an terraform plan, even if no changes
- credentilas
