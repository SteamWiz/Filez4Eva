# Designed to be sourced. We wrap ZSHRC tricks around this.
VIRTUAL_ENV_DISABLE_PROMPT=1 source .venv/bin/activate

alias play="python -m filez4eva --config sandbox/filez4eva.yml"
alias test="echo | make | cat"