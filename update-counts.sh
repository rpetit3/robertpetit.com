#! /bin/bash
# Get Conda downloads and GitHub Stargazer counts for each repo

declare -a tools=( 
    "assembly-scan" 
    "bactopia"
    "call_variants"
    "dragonflye"
    "ena-dl"
    "fastq-dl"
    "fastq-scan"
    "illumina-cleanup"
    "illumina-simulation"
    "pasty"
    "pmga"
    "shovill-se"
    "staphopia"
    "staphopia-sccmec"
    "tbl2asn-forever"
    "vcf-annotator"
)

for tool in "${tools[@]}"; do
    count=0
    fixed_name=${tool//-/_}
    if [[ "staphopia" != "${tool}" ]]; then
        count=$(curl -s  https://anaconda.org/bioconda/${tool} | grep "total downloads" | sed -r 's=.*<span>([0-9]+)</span>.*=\1=')
    fi

    star=0
    if [[ "bactopia" == "${tool}" ]]; then
        star=$(curl -s https://api.github.com/repos/bactopia/${tool} | jq .stargazers_count)
    elif [[ "staphopia" == "${tool}" ]]; then
        star=$(curl -s https://api.github.com/repos/staphopia/${tool}-ap | jq .stargazers_count)
    else
        star=$(curl -s https://api.github.com/repos/rpetit3/${tool} | jq .stargazers_count)
    fi

    if [[ "${count}" == "" ]]; then
        count=0
    fi

    if [[ "${star}" == "null" ]]; then
        star=0
    fi

    printf "%s:\n" "${fixed_name}"
    printf "  - downloads: %s\n" "${count}"
    printf "    stars: %s\n\n" "${star}"
    sleep 0.5
done
