FROM ghcr.io/c4illin/convertx:latest

# Upstream installs its tools with --no-install-recommends, which drops optional
# packages that many of ConvertX's advertised conversions depend on:
#   libmagickcore-*-extra  ImageMagick's SVG/WMF/... coders. Without it every SVG
#                          conversion fails with "no decode delegate for this
#                          image format `SVG'" (C4illin/ConvertX#323).
#   libheif-plugins-all    HEIC/AVIF encoders. Without them vips fails and
#                          ImageMagick silently writes PNG data into .heic/.avif.
#   texlive-plain-generic  soul/ulem, used by pandoc's LaTeX template for
#                          underline/strikeout; PDF output fails without them.
#   fonts-crosextra-*      Calibri/Cambria metric clones so Word documents keep
#                          their layout when converted to PDF.
#   fonts-dejavu-core      Broad Unicode fallback font.
# The libmagickcore package name embeds its ABI version, so derive it from the
# base image instead of hardcoding it.
RUN set -eu; \
    core="$(dpkg-query -W -f='${Package}\n' 'libmagickcore-7.q16-[0-9]*' | grep -v -- '-extra$' | head -n1)"; \
    [ -n "$core" ]; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      "${core}-extra" \
      fonts-crosextra-caladea \
      fonts-crosextra-carlito \
      fonts-dejavu-core \
      libheif-plugins-all \
      texlive-plain-generic; \
    rm -rf /var/lib/apt/lists/*

# ConvertX converts every file in a job concurrently, but LibreOffice instances
# sharing one user profile collide and some conversions fail silently. The
# wrapper gives each invocation a throwaway profile.
COPY --chmod=0755 soffice.sh /usr/local/bin/soffice
COPY --chmod=0755 soffice.sh /usr/local/bin/libreoffice

# ImageMagick:
# - Debian's build has no JPEG XL coder, so it silently writes PNG data into
#   .jxl files. Route JXL through libjxl's cjxl/djxl delegates instead.
# - The default pixel cache limits (1GiB memory, 2GiB disk) make multi-page
#   PDFs, which ConvertX renders at 300 DPI, fail with "cache resources
#   exhausted".
COPY imagemagick-delegates.xml /tmp/imagemagick-delegates.xml
RUN set -eu; \
    cfg=/etc/ImageMagick-7; \
    sed -i -e '\|</delegatemap>|{r /tmp/imagemagick-delegates.xml' -e 'd}' "$cfg/delegates.xml"; \
    rm /tmp/imagemagick-delegates.xml; \
    sed -i -E \
      -e 's|<policy domain="resource" name="memory" value="[^"]*"/>|<policy domain="resource" name="memory" value="4GiB"/>|' \
      -e 's|<policy domain="resource" name="map" value="[^"]*"/>|<policy domain="resource" name="map" value="8GiB"/>|' \
      -e 's|<policy domain="resource" name="disk" value="[^"]*"/>|<policy domain="resource" name="disk" value="32GiB"/>|' \
      "$cfg/policy.xml"

# Fail the build if any of the above stops taking effect.
RUN set -eu; \
    formats="$(magick -list format)"; \
    echo "$formats" | grep -Eq '^ *SVG +SVG +rw'; \
    echo "$formats" | grep -Eq '^ *HEIC +HEIC +rw'; \
    echo "$formats" | grep -Eq '^ *AVIF +HEIC +rw'; \
    magick -list delegate | grep -Eq '^ *png<= jxl '; \
    magick -list delegate | grep -Eq '^ *jxl => '; \
    magick -list resource | grep -Eq 'Disk: 32GiB'; \
    kpsewhich soul.sty >/dev/null; \
    fc-match Calibri | grep -q Carlito; \
    [ "$(command -v soffice)" = /usr/local/bin/soffice ]
