#!/bin/bash

usage() {
	print "$0 <namespace>\n"
}

if [ $# -ne 1 ] ; then
	usage
fi


namespace="$1"

if [ -z "$TOOLBOX_VERSION" ] ; then
	TOOLBOX_VERSION="v0.0.2"
fi

image="autotbx/terraform-gen:$TOOLBOX_VERSION"
if [ -n "$TOOLBOX_REGISTRY" ] ; then
	image="$TOOLBOX_REGISTRY/$image"
fi
	

kubectl -n "$namespace" run -it --rm --image="$image" --overrides='{ "apiVersion": "v1", "spec": { "serviceAccountName": "automation-toolbox" }}' --env="K8S_NAMESPACE=$namespace" --env="STATE=$namespace" test-gen /bin/bash


