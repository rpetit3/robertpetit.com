---
title: illumina-cleanup
summary: A simple pipeline for pre-processing Illumina FASTQ files.
abstract: "A simple pipeline for pre-processing Illumina FASTQ files."
date: "2020-02-25T00:00:00Z"
publishdate: ""
external_link: ""
image:
  caption: '[Photo by Samuel Zeller on Unsplash](https://unsplash.com/photos/FvNp_SY4kF0)'
  focal_point: 'center'
links:
- icon: github
  icon_pack: fab
  name: code
  url: https://github.com/rpetit3/illumina-cleanup

categories:
- nexflow
tags:
- nextflow
- python
- conda

url_code: ""
url_pdf: ""
url_slides: ""
url_video: ""
---
illumina-cleanup is a simple Nextflow pipeline to remove Illumina adapters, PhiX contaminants, 
quality filter, base-error correction, and reduced sequence coverage Illumina samples. This is 
accomplished by making use of FastQC, BBTools (BBDuk, Reformat), Lighter and fastq-scan.
