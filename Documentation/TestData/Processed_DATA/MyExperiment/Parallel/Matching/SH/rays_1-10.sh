#!/bin/bash
#$ -S /bin/bash
#$ -N rays_1-10
#$ -q piv_debian*
#$ -P PIV
#$ -cwd
#$ -V
cd ${SGE_O_WORKDIR}
/home/eberna07/Stage_EB_2020/4d-ptv/Documentation/TestData/Processed_DATA/MyExperiment/MyExperiment.o /home/eberna07/Stage_EB_2020/4d-ptv/Documentation/TestData/Processed_DATA/MyExperiment/Parallel/Rays/rays_1-10.dat 10 2 0.200000 400 400 250 2 > /home/eberna07/Stage_EB_2020/4d-ptv/Documentation/TestData/Processed_DATA/MyExperiment/Parallel/LOG/rays_1-10.log
