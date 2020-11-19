---
title: fastq-dl
summary: A tool for downloading FASTQ files from the European Nucleotide Archive or the Sequence Read Archive.
abstract: "A tool for downloading FASTQ files from the European Nucleotide Archive or the Sequence Read Archive."
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
  url: https://github.com/rpetit3/fastq-dl

categories:
- software
tags:
- python
- conda
- software

url_code: ""
url_pdf: ""
url_slides: ""
url_video: ""
---

fastq-dl is a tool for downloading FASTQ files from the European Nucleotide Archive or the Sequence Read Archive.

fastq-dl takes an ENA/SRA accession (Study, Experiment, or Run) and queries ENA (via Data Warehouse API) to determine the associated metadata. It then downloads FASTQ files for each Run. For Samples or Experiments with multiple Runs, users can optionally merge the runs.
