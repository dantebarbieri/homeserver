# Derives internetarchive-homeserver.yml from Prowlarr's internetarchive.yml.
# Internet Archive stalls searches that carry Prowlarr's own User-Agent, so
# send a browser one; everything else stays upstream. See docs/PROWLARR.md.
/User-Agent:/ { agents++ }
/^  headers:/ { headers++ }
/^id: internetarchive$/ {
    print "id: internetarchive-homeserver"
    ids++
    next
}
/^name: Internet Archive$/ {
    print "name: Internet Archive (homeserver)"
    names++
    next
}
/^search:$/ {
    print
    print "  headers:"
    print "    User-Agent: [\"Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0\"]"
    searches++
    next
}
{ print }
END {
    if (agents || headers) {
        print "Upstream Internet Archive now sets request headers; review whether the User-Agent workaround is still needed" > "/dev/stderr"
        exit 1
    }
    if (ids != 1 || names != 1 || searches != 1) {
        print "Unexpected Internet Archive definition structure" > "/dev/stderr"
        exit 1
    }
}
