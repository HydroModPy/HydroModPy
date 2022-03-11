#!/bin/bash

#OAR -p virt='YES'
#OAR -l {mem_core > 6*1024}/core=5,walltime=28:00:0
#OAR --array-param-file /srv/tempdd/jbenvegn/modflops/scripts/params_remaining_bis.txt
#OAR -O /srv/tempdd/jbenvegn/oar_output/job.%jobid%.output
#OAR -E /srv/tempdd/jbenvegn/oar_output/job.%jobid%.error
#OAR --notify mail:june.benvegnu-sallou@irisa.fr


. /etc/profile.d/modules.sh

set -x
module load spack/gvirt

VM_NAME=vm-${OAR_JOBID}

gvirt start ${VM_NAME} --image /srv/soft/gvirt-images/alpine-3.11.3-docker-x86_64.qcow2

SITE=$1
CHR=$2
APPROX=$3
RATE=$4
REF=$5
PERM=$6
STEADY=$7
TOPO=$9

cd /srv/tempdd/jbenvegn/modflops;
echo $PWD


VM_CMD="/mnt/srv/tempdd/jbenvegn/modflops/run_H_ind.sh $SITE $CHR $APPROX $RATE $REF $PERM $STEADY $TOPO"

gvirt exec $VM_NAME -- "$VM_CMD"
