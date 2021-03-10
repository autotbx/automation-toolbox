# terraform-operator

This is the reposity for the terraform-operator.

Terraform-operator is an operator for Kubernetes.

The goal of this operator is to provide Kubernetes CRDs to manage the plan, execution and the state of a terraform project based on external terraform module.

The idea is to have a simple way to consume a terraform module without advanced terraform understanding.

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
* ModuleTemplate
* ClusterProvider
* Provider

The state defined the **working environment**. This allow to avoid to create multiple resources with only a few differents settings that depend on the environment.

Example with a ClusterModuleTemplate with environment support enabled :

```
apiVersion: terraform.dst.io/v1
kind: ClusterModuleTemplate
metadata:
  name: svvm
spec:
  requiredAttributes:
  - vmnames
  - num_cpus
  - memory
  defaultAttributes:
    network_name : vm_network
    dns_servers:
    - 172.19.36.2
    domain: vm.lab.platform-essential.com
    folder_path: dst
    datacenter_name: Datacenter
    cluster_name: VxRail
    datastore_name: VSAN
    template_name: ubuntu-1804-tpl-davy
    source: "git::http://toolbox.vm.lab.platform-essential.com/toolbox-repos/terraform-module-svvm.git"
  environments:
  - name: dev
    defaultAttributes:
      folder_path: 'dst-dev'
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
Kind: Provider
metadata:
  name: vcsa
spec:
  type: vsphere
  autoPlanRequest: true
  defaultAttributes:
    user: "administrator@vsphere.local"
    password: "VMware123!"
    vsphere_server: "https://vcsa.local"
    allow_unverified_ssl: true
```

will generated the corresponding terraform file :

```
provider "vsphere" {
	user     = "administrator@vsphere.local"
	password = "VMware123!"
	vsphere_server   = "https://vcsa.local""
	allow_unverified_ssl = true
}

```

The same behaviour happens the previous listed objets, except for the Modules that support attributes heritance from the referenced template.
State is automatically managed by the operator.

You can use the commands ``` kubectl logs POD-ID -c tfgen``` to have the generated output.

# Objects definitions
## ClusterProviders / Providers

These objects represent a terraform provider at the cluster or namespace level. Cluster level is used to shared a Providers with multiple namespace.

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the provider|
|spec.type |string|true      |         |Type of the provider (terraform name)|
|spec.autoPlanRequest|boolean|true||Create auto PlanRequest if modified|
|spec.defaultAttributes| object   |true|         | attributes to use for terraform|
|spec.environments | array[object] |false|| Overwrite defaultAttribute for defined env|


```
apiVersion: terraform.dst.io/v1
kind: Provider
metadata:
  name: vcsa
spec:
  type: vsphere
  autoPlanRequest: true
  defaultAttributes:
    user: "yyyy"
    password: "xxxx"
    vsphere_server: "zzzz"
    allow_unverified_ssl: true
  environments:
  - name: dev
    defaultAttributes:
      user: 'abc'
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
### ClusterModuleTemplates/ModuleTemplates

ModuleTemplates can be consumed by a Module to provides default configuration with the possibilities to overwrite specific parameters

| variable | type | required | default | Description |
|----------|----------|----------|---------|-------|
|metadata.name | string |true |         |Name of the PlanRequest|
|spec.requiredAttributes|array[string]|true      |         |Required attributes for module that consume this template|
|spec.defaultAttributes|object|true      |         |Default attributes for module that consume this template|
|spec.environments|array[object]|false      |         |Default attributes for module that consume this template in the specify environment|

```
apiVersion: terraform.dst.io/v1
kind: ClusterModuleTemplate
metadata:
  name: svvm
spec:
  requiredAttributes:
  - vmnames
  - num_cpus
  - memory
  defaultAttributes:
    network_name : vm_network
    dns_servers:
    - 172.19.36.2
    domain: vm.lab.platform-essential.com
    folder_path: dst
    datacenter_name: Datacenter
    cluster_name: VxRail
    datastore_name: VSAN
    template_name: ubuntu-1804-tpl-davy
    source: "git::http://toolbox.vm.lab.platform-essential.com/toolbox-repos/terraform-module-svvm.git"
  environments:
  - name: dev
    defaultAttributes:
      folder_path: 'dst-dev'
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




