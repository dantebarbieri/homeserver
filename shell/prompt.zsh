# Prompt shared by the server and the Studio: Zim's asciiship, reworded.
#
#   user on host in ~/dir on branch via venv took 3s
#
# user and host only show over SSH (or as root). The host takes its colour from
# the Ghibli character it is named after. Needs Zim's duration-info and
# git-info modules; it replaces the asciiship module, which says "in" twice.
# Plain ASCII only, so it works without a Nerd Font.

_ghibli_vimode() {
  case ${KEYMAP} in
    vicmd) print -n '%S%#%s' ;;
    *) print -n '%#' ;;
  esac
}

_ghibli_keymap_select() {
  zle reset-prompt
  zle -R
}
autoload -Uz add-zle-hook-widget
add-zle-hook-widget -Uz keymap-select _ghibli_keymap_select

typeset -g VIRTUAL_ENV_DISABLE_PROMPT=1

setopt nopromptbang prompt{cr,percent,sp,subst}

autoload -Uz add-zsh-hook
if (( ${+functions[duration-info-preexec]} && \
    ${+functions[duration-info-precmd]} )); then
  zstyle ':zim:duration-info' format ' took %B%F{yellow}%d%f%b'
  add-zsh-hook preexec duration-info-preexec
  add-zsh-hook precmd duration-info-precmd
fi

typeset -gA git_info
if (( ${+functions[git-info]} )); then
  zstyle ':zim:git-info:branch' format '%b'
  zstyle ':zim:git-info:commit' format 'HEAD %F{green}(%c)'
  zstyle ':zim:git-info:action' format ' %F{yellow}(${(U):-%s})'
  zstyle ':zim:git-info:stashed' format '\\\$'
  zstyle ':zim:git-info:unindexed' format '!'
  zstyle ':zim:git-info:indexed' format '+'
  zstyle ':zim:git-info:ahead' format '>'
  zstyle ':zim:git-info:behind' format '<'
  zstyle ':zim:git-info:keys' format \
      'status' '%S%I%i%A%B' \
      'prompt' ' on %%B%F{magenta}%b%c%s${(e)git_info[status]:+" %F{red}[${(e)git_info[status]}]"}%f%%b'
  add-zsh-hook precmd git-info
fi

# xterm-256 colours: calcifer orange, no-face violet, totoro grey-blue,
# laputa sky blue, jiji green (his eyes), susuwatari soot grey.
typeset -A _ghibli_host_colors=(
  calcifer 208  no-face 98  totoro 110  laputa 117  jiji 70  susuwatari 244
)
_ghibli_host_color=${_ghibli_host_colors[${${HOST%%.*}:l}]:-green}

# Fixed when the shell starts: SSH_TTY and EUID never change within one shell.
if [[ -n ${SSH_TTY} ]]; then
  _ghibli_who="%B%F{$(( EUID == 0 ? 1 : 3 ))}%n%f%b on %B%F{${_ghibli_host_color}}%m%f%b in "
elif (( EUID == 0 )); then
  _ghibli_who='%B%F{red}%n%f%b in '
else
  _ghibli_who=''
fi

PS1='
%(2L.%B%F{yellow}(%L)%f%b .)'${_ghibli_who}'%B%F{cyan}%~%f%b${(e)git_info[prompt]}${VIRTUAL_ENV:+" via %B%F{yellow}${VIRTUAL_ENV:t}%f%b"}${duration_info}
%B%(1j.%F{blue}*%f .)%(?.%F{green}.%F{red}%? )$(_ghibli_vimode)%f%b '
unset RPS1
