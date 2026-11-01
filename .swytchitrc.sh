# Designed to be sourced. We wrap ZSHRC tricks around this.
VIRTUAL_ENV_DISABLE_PROMPT=1 source .venv/bin/activate

# Run from the repository root. Single quotes, so $PWD is expanded when the
# alias runs: the intake and target must be absolute paths.
alias play='FILEZ4EVA_INTAKE="$PWD/sandbox/test-intake" FILEZ4EVA_TARGET="$PWD/sandbox/test-target" python -m filez4eva --config sandbox/filez4eva.yml'
alias test="echo | make | cat"