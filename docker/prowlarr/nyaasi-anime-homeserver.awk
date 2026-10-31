# Derives nyaasi-anime-homeserver.yml from Prowlarr's nyaasi.yml. Keeps
# upstream parsing and search variants and narrows only the advertised scope
# to anime, so music, book and live-action requests stop spending Nyaa's
# daily query allowance. See docs/PROWLARR.md.
/^id: nyaasi$/ {
    print "id: nyaasi-anime-homeserver"
    ids++
    next
}
/^name: Nyaa.si$/ {
    print "name: Nyaa.si (anime homeserver)"
    names++
    next
}
/^    - \{id:/ {
    if ($0 ~ /id: 1_[0-4], cat: TV\/Anime,/) {
        tv++
    } else if ($0 ~ /id: 1_[0-4], cat: Movies\/Other,/) {
        movies++
    } else {
        removed++
        next
    }
}
/^    (music-search|book-search):/ {
    modes++
    next
}
/^  - name:/ { category = ($0 == "  - name: cat-id") }
category && /^    default:/ {
    print "    default: 1_0"
    defaults++
    next
}
category && /^      [0-9]_[0-9]:/ {
    if ($0 !~ /^      1_[0-4]:/) {
        next
    }
    options++
}
{ print }
END {
    if (ids != 1 || names != 1 || tv != 5 || movies != 5 ||
        removed == 0 || modes != 2 || defaults != 1 || options != 5) {
        print "Unexpected Nyaa definition structure" > "/dev/stderr"
        exit 1
    }
}
