#!/bin/bash

cd /opt/nexus_api_tools
. venv/bin/activate

./nexus_copy.py --file /opt/nexus_api_tools/sync-external-public.yaml
./nexus_copy.py --file /opt/nexus_api_tools/sync-public-external.yaml

if [ -d public-external -o -d external-public ]
then
	archive="sync-archive/sync-$(date +%s)"
	mkdir -p "${archive}"
	mv public-external "${archive}"
	mv external-public "${archive}"
fi
