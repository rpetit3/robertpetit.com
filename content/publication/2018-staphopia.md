+++
draft = false
pin = true
type = "publication"

abstract = "Low-cost Illumina sequencing of clinically-important bacterial pathogens has generated thousands of publicly available genomic datasets. Analyzing these genomes and extracting relevant information for each pathogen and the associated clinical phenotypes requires not only resources and bioinformatic skills but organism-specific knowledge. In light of these issues, we created Staphopia, an analysis pipeline, database and application programming interface, focused on *Staphylococcus aureus*, a common colonizer of humans and a major antibiotic-resistant pathogen responsible for a wide spectrum of hospital and community-associated infections. Written in Python, Staphopia's analysis pipeline consists of submodules running open-source tools. It accepts raw FASTQ reads as an input, which undergo quality control filtration, error correction and reduction to a maximum of approximately 100-times chromosome coverage. This reduction significantly reduces total runtime without detrimentally affecting the results. The pipeline performs de novo assembly-based and mapping-based analysis. Automated gene calling and annotation is performed on the assembled contigs. Read-mapping is used to call variants (single nucleotide polymorphisms and insertion/deletions) against a reference *S. aureus* chromosome (N315, ST5). We ran the analysis pipeline on more than 43,000 *S. aureus* shotgun Illumina genome projects in the public European Nucleotide Archive database in November 2017. We found that only a quarter of known multi-locus sequence types (STs) were represented but the top 10 STs made up 70% of all genomes. methicillin-resistant *S. aureus* (MRSA) were 64% of all genomes. Using the Staphopia database we selected 380 high quality genomes deposited with good metadata, each from a different multi-locus ST, as a non-redundant diversity set for studying *S. aureus* evolution. In addition to answering basic science questions, Staphopia could serve as a potential platform for rapid clinical diagnostics of *S. aureus* isolates in the future. The system could also be adapted as a template for other organism-specific databases."

authors = ["***Robert A. Petit III***", "Timothy D. Read"]
date = "2018-07-01"
journal = "*PeerJ*"
title = "*Staphylococcus aureus* viewed from the perspective of 40,000+ genomes"
pdf = "/pdf/2018-staphopia.pdf"
tags = ["resistance", "nextflow", "staphylococcus", "staphopia"]
doi = "10.7717/peerj.5261"
citation = "Petit, R. A., III & Read, T. D. *Staphylococcus aureus* viewed from the perspective of 40,000+ genomes. *PeerJ* 6, e5261 (2018)"
+++
