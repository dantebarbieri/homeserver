FROM ghcr.io/hotio/bazarr:nightly

# Bazarr's Whisper provider saves error responses as subtitles. Patch it to
# reject non-2xx responses and redirects, then exercise the patched methods.
# Any upstream change that breaks either step fails this build, so the update
# keeps the previous Bazarr container and reports the failure.
COPY patch_whisperai.py check_whisperai.py /tmp/bazarr-whisper/
RUN provider="${APP_DIR:?}/bin/custom_libs/subliminal_patch/providers/whisperai.py" && \
    python3 /tmp/bazarr-whisper/patch_whisperai.py "$provider" && \
    python3 /tmp/bazarr-whisper/check_whisperai.py "$provider" && \
    rm -rf /tmp/bazarr-whisper
