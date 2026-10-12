# Source from recipes before printing. Honour NO_COLOR (even empty) and pipes.
if [ -n "${NO_COLOR+x}" ] || [ ! -t 1 ]; then
  printf() {
    if [ "${1:-}" = '%b\n' ]; then
      command printf "$@" | sed $'s/\033\\[[0-9;]*m//g'
    else
      command printf "$@"
    fi
  }
fi
