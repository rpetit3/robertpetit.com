#! /bin/bash
set -euo pipefail
# Get Conda downloads and GitHub Stargazer counts for each repo

declare -a tools=( 
    "assembly-scan" 
    "bactopia"
    "call_variants"
    "dragonflye"
    "ena-dl"
    "fastq-dl"
    "fastq-scan"
    "goblin"
    "illumina-cleanup"
    "illumina-simulation"
    "pasty"
    "pbptyper"
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
        count=$(curl -s "https://api.anaconda.org/package/bioconda/${tool}/files" | jq '[.[].ndownloads] | add // 0' 2>/dev/null || true)
    fi

    star=0
    if [[ "bactopia" == "${tool}" ]]; then
        star=$(curl -s https://api.github.com/repos/bactopia/${tool} | jq .stargazers_count || true)
    elif [[ "staphopia" == "${tool}" ]]; then
        star=$(curl -s https://api.github.com/repos/staphopia/${tool}-ap | jq .stargazers_count || true)
    else
        star=$(curl -s https://api.github.com/repos/rpetit3/${tool} | jq .stargazers_count || true)
    fi

    if [[ "${count}" == "" ]]; then
        count=0
    fi

    if [[ "${star}" == "null" || "${star}" == "" ]]; then
        star=0
    fi

    printf "%s:\n" "${fixed_name}"
    printf "  - downloads: %s\n" "${count}"
    printf "    stars: %s\n\n" "${star}"
    sleep 0.5
done
