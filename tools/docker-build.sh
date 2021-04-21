#!/bin/bash


prefix="harbor.pks.lab.platform-essential.com/library/"

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

cd "$DIR/.." || exit 1

for image in ./images/* ; do
	name="$(basename ${image})"
	
	echo "Working on $name"
	image_iso_date=$( docker inspect -f '{{ .Created }}'  "$prefix$name" )
	if [ -z "$image_iso_date" ] ; then
		build="true"
	else
		image_date=$( date -d "$image_iso_date" +%s )
		dockerfile_date=$( date -d $( ls -l --time-style=full-iso "$image"/Dockerfile  | awk '{ print $6"T"$7$8 }' ) +%s )

		if [ "$dockerfile_date" -gt "$image_date" ] ; then
			build="true"
		fi
	fi
	if [ -n "$build" ] ; then
		docker build -t "$prefix$name" "$image"
	fi
	docker push "$prefix$name"
	echo "Done"
done


