# AUTOMATION-TOOLBOX

This is the reposity for the automation-toolbox.

automation-toolbox is an operator for Kubernetes.

The goal of this operator is to provide Kubernetes CRDs to manage :

* Terraform: the plan, execution and the state of a terraform project based on external terraform module
* Ansible:  the plan, execution of an ansible project based on external ansible role

The idea is to have a simple way to consume a terraform module/ansible roles without advanced terraform/ansible understanding.


# Table of contents
1. [High Level Overview](#hld)
2. [Execution workflow](#workflow)
3. [Environment support](#env)
4. [Templates inheritance](#tpl)
5. [Web Interface](#ui)
6. [Terraform code generation](#tfcode)
7. [Ansible code generation](#anscode)
8. [Objects definitions](#objs)
9. [Installation/Upgrade](#install)

# High Level Overview <a name="hld"></a>

Usually, a project is managed by plan/apply operation and is composed with :

* State   (terraform)
* Providers (terraform)
* Modules (terraform Resources/DataSources/Variables)
* Inventory (ansible)
* Playbook (ansible)

The operator define these same objects/actions by extending Kubernetes API with the following objects:

* ClusterProviders (cluster-wide)
* Providers (namespaced)
* States (namespaced)
* Modules (namespaced)
* PlanRequests (namespaced)
* Plans  (namespaced)
* AnsiblePlanRequests (namespaced)
* AnsiblePlans (namespaced)

In addition to the previous items, a templating engine is available for the Modules object to avoid to share the attributes between various modules with the following objects: (see template inheritance)

* ClusterModuleTemplates (cluster-wide)
* ModuleTemplates (namespaced)

Cluster-wide objects are used to be shared between multiple namespace.

Module object are also used to provide ansible configuration.

At the moment, one Kubernetes namespace represent a terraform project that use the same terraform state.
These objects can be represented like this:

![terraform-operator-k8s-view](docs/images/terraform-operator-k8s-view.png?raw=true)

# Execution workflow <a name="workflow"></a>

The workflow can be summarized as :

![terraform-op-workflow](docs/images/terraform-op-workflow.png?raw=true)

The complete flow is :

![tf-ans-workflow](docs/images/tf-ans-workflow.png?raw=true)


## Stale plan / Locked state

During a terraform apply, 3 known kinds of errors can be returned:

* Staled plan : the plan was generated with a previous version of the state (ie another plan was executed in the mean time)
* Locked state: Cannot lock the state, another terraform apply is currently running. (not yet implemented)
* Common terraform error: need to review the applyJobStatus to understand the terraform error and fix it

The operator will manage automatically the Staled plan & Locked state scenario.

* Staled plan : Another PlanRequest is submitted with an originalPlan attribute and the attribute Approved=true. The plan is strictly compared to the previous generated plan and will raise a Failed status if the plan is different, otherwise, the plan will be appied.
* Locked state: Wait for the retry period attribute of the state and submit another PlanRequests with Approved=true. (todo)


# Environment support <a name="env"></a>

Environment support is a feature that enable the following object to overwrite attributes from the defaultAttributes or the ansibleAttributes for the **working environment**:

* ClusterModuleTemplate
* ClusterProvider

The state defines the **working environment**. This allow to avoid to create multiple resources with only a few differents settings that depend on the environment.

Example with a ClusterModuleTemplate with environment support enabled :

```yml
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

The same logic is apply to the ansibleAttributes definition.

*A Module can also overwrite an attribute*

# Templates inheritance <a name="tpl"></a>

Module object can use a clusterModuleTemplate or a moduleTemplate attributes.
If a template is defined, the template attributes are evaluated during the code generation. The module can overwrite an attribute.

This can be illustrated as follow (same logic for moduleTemplate except you don't have the first override from the environment): 

![templating](docs/images/templating.png?raw=true)

Inheritance is apply for each attributes except for the ansibleAttributes['credential'] object, the whole object credentials is taken.

# Web Interface <a name="ui"></a>

During the helm chart installation, the ui is enabled by default, reacheable by an service of type Load Balancer.

The webinterface provide functionality to managed all the objects. 

However, a default username/password is defined and you have to update this default value with your users.
The pod will restart itself if the users configuration change.

custom-values.yaml
```yml
ui:
  users: [{"username": "admin", "password" : "password"}]
```

```bash
helm install/upgrade -f custom-values.yaml automation-toolbox  automation-toolbox-chart/  --namespace automation-toolbox
```

The usage of a user provided kubeconfig instead of working with local user is on the roadmap. This will allow to respect K8S rbac for the authenticated users.


# Terraform code generation <a name="tfcode"></a>

The code of terraform is automatically created from the various objects defined. The container terraform-gen is responsible to generate the terraform files.
All the following objects are defined using the term **Attributes** which correspond to the line generated in the corresponding object during a terraform operation:

* ClusterProviders (cluster-wide)
* Providers (namespaced)
* Modules (namespaced)


For example, a Provider with the following definition :

```yml
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

will generated the corresponding terraform content :

```hcl
provider "vsphere" {
	user     = "administrator@vsphere.local"
	password = "VMware123!"
	vsphere_server   = "vcsa.local"
	allow_unverified_ssl = true
}

```

The same behaviour happens the previous listed objets, except for the Modules that support attributes inheritance from a referenced template.
State is automatically managed by the operator.

You can use the commands ``` kubectl logs POD-ID -c terraform-gen``` to have the generated output.

# Ansible code generation <a name="anscode"></a>

The code is generated from the modules ansibleAttributes keys. These attributes can be inherited from a referenced template. (see template inheritance) 
Each module with an ansibleAttributes will be added to the inventory/playbook definition.
If a target is defined by the ansiblePlan, only module defined in target + their dependencies are used for the generation.
The container ansible-gen is responsible to generate the ansible code.

This generation can be illustrated as follow :

![ansible-gen](docs/images/ansible-gen.png?raw=true)

For example, modules with the following definition :

```yml
apiVersion: terraform.dst.io/v1
kind: Module
metadata:
  name: mod1
spec:
  attributes:
  [...]
  ansibleAttributes:
    credentials:
      type: ssh
      user: myuser
      password: mypassword
    roles:
    - myrole1
    targets:
    - fqdn: my.host.local
      vars:
      - name: myhostvar
        sValue: myhostval
    - fqdn: my.host2.local
    vars:
    - name: myvar
      sValue: myval
---
apiVersion: terraform.dst.io/v1
kind: Module
metadata:
  name: mod2
spec:
  attributes:
  [...]
  ansibleAttributes:
    credentials:
      type: ssh
      user: myuser
      password: mypassword
    roles:
    - myrole1
    targets:
    - fqdn: my.host3.local
      vars:
      - name: myhostvar
        sValue: myhostval
    - fqdn: my.host4.local
    vars:
    - name: myvar
      sValue: myval
```

will produce :

- inventory.yaml

```yml
all:
  children:
    mod1:
      hosts:
        my.host.local:
          myhostvar: myhostval
         my.host2.local: {}
      vars:
        myvar: myval
    mod2:
      hosts:
        my.host3.local:
          myhostvar: myhostval
         my.host4.local: {}
      vars:
        myvar: myval
```

- playbook.yml

```yml
- become: true
  hosts: mod1
  name: mod1
  roles:
  - myrole1
  vars:
    ansible_connection: ssh
    ansible_password: mypassord
    ansible_user: myuser
- become: true
  hosts: mod2
  name: mod2
  roles:
  - myrole1
  vars:
    ansible_connection: ssh
    ansible_password: mypassord
    ansible_user: myuser
```

# Objects definitions <a name="objs"></a>
## Attributes type <a name="attr"></a>

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

## AnsibleAttributes <a name="ansattr"></a>

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|defaultGalaxyServer| string |false |         |Default Galaxy Server for roles|
|roles| array[string] | false |       |List of roles|
|dependencies| array[string] | false |       |List of modules dependencies|
|credentials|object|false||credentials object|
|credentials.type|string|||type of credentials|
|credentials.user|string|||user|
|credentials.password|string|||password|
|credentials.ssh_key|string|||ssh key|
|vars|string|array[attributes]|false|ansible variable|

```yml
ansibleAttributes:
  credentials:
    type: ssh
    user: myuser
    password: mypassword
  roles:
  - myrole1
  vars:
  - name: myvar
    sValue: myval
```

When defining ansibleAttribute on a module, the *targets* attributes is added:

```yml
ansibleAttributes:
  credentials:
    type: ssh
    user: myuser
    password: mypassword
  roles:
  - myrole1
  targets:
  - fqdn: my.host.local
    vars:
     - name: myhostvar
       sValue: myhostval
  vars:
  - name: myvar
    sValue: myval
```


## ClusterProviders <a name="clprds"></a>
This object represent a terraform provider at the cluster. Cluster level is used to shared a Providers with multiple namespace.

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the provider|
|spec.type |string|true      |         |Type of the provider (terraform name)|
|spec.attributes| array[attributes]   |true|         | attributes to use for terraform|
|spec.environments | array[array[attributes]] |false|| Overwrite attributes for defined env|

```yml
apiVersion: terraform.dst.io/v1
kind: ClusterProvider
metadata:
  name: vcsa
spec:
  type: vsphere
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

## Providers <a name="prds"></a>

This object represent a terraform provider at the namespace level.

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the provider|
|spec.type |string|true      |         |Type of the provider (terraform name)|
|spec.attributes| array[attributes]   |true|         | attributes to use for terraform|


```yml
apiVersion: terraform.dst.io/v1
kind: Provider
metadata:
  name: vcsa
spec:
  type: vsphere
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

## States <a name="states"></a>

This object define the state properties

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the state|
|spec.clusterProviders |array[string]|false      |         |Provider to include in this state|
|spec.autoPlanRequest|boolean|true||Create auto PlanRequest if modified|
|spec.autoPlanApprove|boolean|true||Automatically approve generated plan|
|spec.deleteJobsOnPlanDeleted| boolean |true||Delete jobs created by the deleted plan, used by auto plan|
|spec.customTerraformInit| string |false|| Custom terraform section { } code|
|spec.terraformOption| string |false||  terraform CLI option to pass during the execution|
|spec.trustedCA|string|false||Addition trusted CA|
|spec.tfGeneratorImage| string |false|dstoffel/terraform-gen| Terraform code generator image pulling path|
|spec.tfExecutorImage| string |false|dstoffel/terraform| Terraform executor image pulling path|
|spec.tfGeneratorImagePullPolicy| string |false|IfNotPresent| Terraform code generator image policy|
|spec.tfExecutorImagePullPolicy| string |false|IfNotPresent| Terraform code generator image policy|
|spec.ansibleGeneratorImage| string |false|dstoffel/ansible| Ansible code generator image path|
|spec.ansibleExecutorImage| string |false|dstoffel/ansible-gen| Ansible executor image path|
|spec.ansibleGeneratorImagePullPolicy| string |false|IfNotPresent| erraform code generator image policy|
|spec.ansibleExecutorImagePullPolicy| string |false|IfNotPresent| Terraform code generator image policy|
|spec.ansibleExecutorImagePullPolicy| string |false|IfNotPresent| Terraform code generator image policy|

```yml
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
  customTerraformInit: 'required_providers { vsphere = "= 1.15" }'
```

## Modules
### ClusterModuleTemplates <a name="clmodtpl"></a>

ClusterModuleTemplates can be consumed by a Module to provides default configuration with the possibilities to overwrite specific parameters


| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the ClusterModuleTemplate|
|spec.autoPlanRequest | string |false | true       |Enable auto plan request on object modificiation|
|spec.requiredAttributes|array[attributes]|true      |         |Required attributes for module that consume this template|
|spec.defaultAttributes|array[attributes]|true      |         |Default attributes for module that consume this template|
|spec.environments|array[array[attributes]]|false      |         |Default attributes for module that consume this template in the specify environment|
|spec.ansibleAttribute|ansibleAttributes|false      |         |Default ansibleAttributes for module that consume this template in the specify environment|

```yml
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

### ModuleTemplates <a name="modtpl"></a>

ModuleTemplates can be consumed by a Module to provides default configuration with the possibilities to overwrite specific parameters


| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the ModuleTemplate|
|spec.autoPlanRequest | string |false | true       |Enable auto plan request on object modificiation|
|spec.requiredAttributes|array[attributes]|true      |         |Required attributes for module that consume this template|
|spec.defaultAttributes|array[attributes]|true      |         |Default attributes for module that consume this template|
|spec.ansibleAttribute|ansibleAttributes|false      |         |Default ansibleAttributes for module that consume this template in the specify environment|

```yml
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

### Modules <a name="mod"></a>

A module object represent a terraform module.

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the Module|
|spec.autoPlanRequest | string |false | true       |Enable auto plan request on object modificiation|
|spec.requiredAttributes|array[attributes]|true      |         |Required attributes for module that consume this template|
|spec.defaultAttributes|array[attributes]|true      |         |Default attributes for module that consume this template|
|spec.ansibleAttribute|ansibleAttributes|false      |         |Default ansibleAttributes for module that consume this template in the specify environment|

```yml
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


## PlanRequests / AnsiblePlanRequests <a name="pr"></a>

PlanRequest are used to request the generation of a new Plan.

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the PlanRequest|
|spec.deletePlanOnDeleted |boolean|false      |false         |Delete generated Plan on deletion|
|spec.targets|array[string]|false||Target limitation during terraform operation|


## Plans / AnsiblePlans <a name="plans"></a>

Plan is the equivalent of the terraform/ansible plan/apply. You should not create this object as they are created by the PlanRequest object.

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the Plan|
|spec.approved |boolean]|true      |         |Approved plan (ie terraform apply will run with this plan)|
|spec.targets|array[string]|false||Target limitation during terraform operation|
|spec.tfGeneratorImage| string |false|dstoffel/terraform-gen| Terraform code generator image pulling path|
|spec.tfExecutorImage| string |false|dstoffel/terraform| Terraform executor image pulling path|
|spec.tfGeneratorImagePullPolicy| string |false|IfNotPresent| Terraform code generator image policy|
|spec.tfExecutorImagePullPolicy| string |false|IfNotPresent| Terraform code generator image policy|
|spec.ansibleGeneratorImage| string |false|dstoffel/ansible| Ansible code generator image path|
|spec.ansibleExecutorImage| string |false|dstoffel/ansible-gen| Ansible executor image path|
|spec.ansibleGeneratorImagePullPolicy| string |false|IfNotPresent| erraform code generator image policy|
|spec.ansibleExecutorImagePullPolicy| string |false|IfNotPresent| Terraform code generator image policy|
|spec.ansibleExecutorImagePullPolicy| string |false|IfNotPresent| Terraform code generator image policy|

# Installation / Upgrade <a name="install"></a>

A helm charts is provided to install the automation toolbox.

```bash
git clone https://github.com/dstoffel/automation-toolbox.git
cd automation-toolbox
git checkout <tag>
kubectl create ns automation-toolbox
helm install automation-toolbox  automation-toolbox-chart/  --namespace automation-toolbox
```
To perform an upgrade: 

```bash
git pull
git checkout <newtag>
helm upgrade  automation-toolbox  automation-toolbox-chart/  --namespace automation-toolbox
```

All existing states will not be updated automatically to allow you to manually tests all plan correctly.
You can update the state image* path to match the new tag.

