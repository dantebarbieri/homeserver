# Plex playback

## LAN bandwidth classification

Set **Settings > Network > Show Advanced > LAN Networks** to
`192.168.50.0/24`. Plex stores this as `LanNetworksBandwidth` in
`${DATA}/plex/config/Library/Application Support/Plex Media Server/Preferences.xml`,
so it survives container recreation. Use Plex's settings UI or authenticated
`PUT /:/prefs?LanNetworksBandwidth=192.168.50.0%2F24` API rather than editing the
XML while Plex is running.

The `plexinc/pms-docker` image does **not** implement `LAN_NETWORKS`. Setting that
environment variable does not update the preference. Do not substitute
`ALLOWED_NETWORKS`: that configures authentication bypass, not bandwidth.

LAN clients connect directly to the server's published port 32400. Do not add
the Docker proxy subnet to LAN Networks: NPM connections share the proxy's
source address, so that would exempt remote streams from upload limits.
Likewise, an SSH tunnel to `127.0.0.1:32400` can reach Plex through Docker's
bridge address and be subject to remote limits. For LAN playback diagnostics,
forward to `192.168.50.100:32400` and verify the source classification in Plex's
log.

## Apple TV, Dolby Vision and quality limits

An error saying both "no direct play video profile" and "no conversion audio
and video encoders" is not proof that the NVIDIA encoders are broken. Check the
movie's streams, the client's augmented tvOS profile, and the complete
`Streaming Resource` decision in `Plex Media Server.log`. Hardware availability
can be checked independently:

```bash
bash /srv/homeserver/docker/scripts/check-plex-hwaccel.sh
```

Dolby Vision **Profile 5** has no HDR10-compatible base layer. Do not strip its
metadata or treat it as ordinary HDR10; that can produce incorrect colors.
The native Apple TV playback path may reject MKV while accepting a correctly
signaled Dolby Vision MP4. A lossless remux must preserve the Dolby Vision
configuration and RPU data, the original audio, and valid HEVC parameter sets.
For Profile 5, verify the resulting `dvh1` MP4 still reports
`DOVIProfile=5`/`dv_profile=5`; a plain `hvc1` remux can lose Dolby Vision
container signaling with the bundled FFmpeg.

Some MKVs contain HEVC parameter sets only inside the video packets, leaving
an empty configuration record. With such a source,
`-bsf:v hevc_mp4toannexb,extract_extradata` reconstructs the configuration for
MP4 without re-encoding. Probe and decode the result before publishing it;
changing the extension or container tag alone is not sufficient.

A lossless remux does **not** reduce bandwidth. Plex can estimate required
bandwidth substantially above the file's average bitrate, and a client-supplied
20 Mbps quality limit still applies on the LAN. If that limit requires video
conversion, a Profile 5 source can still fail even when its direct-play
decision says OK.

For clients that need a lower-bitrate version, retain the original and create
a separate SDR compatibility copy using a Dolby-Vision-aware tone mapper.
The existing Jellyfin FFmpeg supports
`tonemap_cuda=tonemap=bt2390:format=yuv420p:apply_dovi=1`; follow it with
`scale_cuda=1920:1080:format=yuv420p` for a 1080p H.264 MP4 fallback. Tag the
output as BT.709, retain supported audio and subtitles, and constrain bitrate
to fit the client's actual limit. Do not label this copy as Dolby Vision.

When converting subtitles to MP4 `mov_text`, long gaps between forced cues can
overflow the muxer's microsecond timestamps. Rescale both timestamps and
durations, not just the declared timebase:

```text
-bsf:s 'setts=pts=PTS*TB/TB_OUT:dts=DTS*TB/TB_OUT:duration=DURATION*TB/TB_OUT:time_base=1/1000'
```

The bundled FFmpeg ignores `-enc_time_base` for subtitles. Compare extracted
forced cues with the original, including their timing, before publishing.

Write conversions outside the library, verify their duration, color metadata,
audio and seekability, and publish only completed files. Rescan just the movie
folder. Keep the original and compatible copies grouped under the same Plex
movie so watch history is retained and Plex can automatically choose a playable
version.

Validate the **general** playback decision, not just `directPlayDecisionCode`,
using the client's profile, subtitle selection and quality limit. Confirm both
automatic version selection and seeking around the resume point; an
unrestricted-quality test alone does not cover a capped Apple TV.
