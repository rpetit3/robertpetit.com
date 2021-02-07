+++
draft = false
pin = false
type = "publication"
summary = "We developed a model to differentiate Bacillus anthracis, the etiologic agent of anthrax, from the closely related (>99% average nucleotide identity) Bacillus cereus group members in metagenome sequences."
cover = ""

abstract = "**Background**: It is possible to detect bacterial species in shotgun metagenome datasets through the presence of only a few sequence reads. However, false positive results can arise, as was the case in the initial findings of a recent New York City subway metagenome project. False positives are especially likely when two closely related are present in the same sample. *Bacillus anthracis*, the etiologic agent of anthrax, is a high-consequence pathogen that shares >99% average nucleotide identity with *Bacillus cereus* group (BCerG) genomes. Our goal was to create an analysis tool that used k-mers to detect *B. anthracis*, incorporating information about the coverage of BCerG in the metagenome sample. \\\n\\\n**Methods**: Using public complete genome sequence datasets, we identified a set of 31-mer signatures that differentiated *B. anthracis* from other members of the *B. cereus* group (BCerG), and another set which differentiated BCerG genomes (including *B. anthracis*) from other Bacillus strains. We also created a set of 31-mers for detecting the lethal factor gene, the key genetic diagnostic of the presence of anthrax-causing bacteria. We created synthetic sequence datasets based on existing genomes to test the accuracy of a k-mer based detection model. \\\n\\\n**Results**: We found 239,503 *B. anthracis*-specific 31-mers (the Ba31 set), 10,183 BCerG 31-mers (the BCerG31 set), and 2,617 lethal factor k-mers (the lef31 set). We showed that false positive *B. anthracis* k-mers-which arise from random sequencing errors-are observable at high genome coverages of *B. cereus*. We also showed that there is a *gray zone* below 0.184$times$ coverage of the *B. anthracis* genome sequence, in which we cannot expect with high probability to identify lethal factor k-mers. We created a linear regression model to differentiate the presence of *B. anthracis*-like chromosomes from sequencing errors given the BCerG background coverage. We showed that while shotgun datasets from the New York City subway metagenome project had no matches to lef31 k-mers and hence were negative for *B. anthracis*, some samples showed evidence of strains very closely related to the pathogen. \\\n\\\n**Discussion**: This work shows how extensive libraries of complete genomes can be used to create organism-specific signatures to help interpret metagenomes. We contrast *specialist* approaches to metagenome analysis such as this work to *generalist* software that seeks to classify all organisms present in the sample and note the more general utility of a k-mer filter approach when taxonomic boundaries lack clarity or high levels of precision are required."

authors = ["***Robert A. Petit III***", "James M. Hogan", "Matthew N. Ezewudo", "Sandeep J. Joseph", "Timothy D. Read"]
date = "2018-08-01"
journal = "*PeerJ*"
title = "Fine-scale differentiation between *Bacillus anthracis* and *Bacillus cereus* group signatures in metagenome shotgun data"
pdf = "/pdf/2018-bacillus-anthracis.pdf"
tags = ["anthrax", "bacillus", "metagenomic", "typing"]

doi = "10.7717/peerj.5515"
citation = "Petit, R. A., III, Hogan, J. M., Ezewudo, M. N., Joseph, S. J. & Read, T. D. Fine-scale differentiation between *Bacillus anthracis* and *Bacillus cereus* group signatures in metagenome shotgun data. *PeerJ* 6, e5515 (2018)"
+++
