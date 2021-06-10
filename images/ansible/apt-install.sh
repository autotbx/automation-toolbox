#!/bin/bash

set -eu

apt-get update
xargs -a <(awk '! /^ *(#|$)/' "deblist.txt") -r -- apt-get install