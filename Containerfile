# Davinci only offers AMD support, no ARM
# Newer versions of ubuntu do not have some older packages like libcfitsio9 (davinci dep)
FROM --platform=linux/amd64 ubuntu:22.04 AS base
# COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

USER root
RUN apt-get -o APT::Sandbox::User=root update &&\
    apt-get -o APT::Sandbox::User=root install -y --no-install-suggests --no-install-recommends \
      #~ davinci
      wget \
      gnuplot \
      gdal-bin \
      libgdal-dev \
      libcfitsio9 \
      libcurl4-nss-dev \
      #~ specpr
      libx11-dev \
      #~ tetracorder
      gfortran \
      make \
      gcc \
      g++ \
      ratfor \
      tcsh \
      csh \
      gnuplot-x11 \
      imagemagick \
      tgif \
      #~~ aplay
      alsa-utils \
      #~~ javac
      default-jdk \
      #~~ (extras the install script may reference are pulled transitively; none needed explicitly)
      #~ utilities
      curl \
      git \
      &&\
    rm -rf /var/lib/apt/lists/*

WORKDIR /root

# Environment variables required for compiling specpr
ENV LD_LIBRARY_PATH="/usr/local/lib:/usr/lib/x86_64-linux-gnu" \
    SSPPFLAGS="LINUX -INTEL -XWIN " \
    SPECPR="/root/tetracorder/specpr" \
    RANDRET="32767" \
    SP_LOCAL="/usr/local" \
    SP_BIN="securebin" \
    SP_LDFLAGS=" " \
    SP_LDLIBS="-lX11" \
    SPSDIR="syslinux" \
    RANLIB="ranlib" \
    SSPP="sspp" \
    F77="gfortran" \
    CC="cc" \
    AR="ar" \
    RF="ratfor" \
    YACC="yacc" \
    LEX="flex" \
    SP_FFLAGS="-C -O" \
    SP_FFLAGS1="-C" \
    SP_FFLAGS2="-C" \
    SPKLUDGE="LINUX" \
    BSLASH="-fno-backslash" \
    SP_FOPT="-O" \
    SP_FOPT1="-O" \
    SP_FOPT2="-O" \
    SP_RFLAGS="<" \
    SP_CFLAGS="-O -fcommon" \
    SP_ARFLAGS="rv" \
    SP_GFLAGS="-s" \
    SP_LFLAGS=" " \
    SP_YFLAGS=" " \
    LD_RUN_PATH="/usr/local/lib"

# Derived environment variables that depend on other variables
ENV SP_DBG="${SPECPR}/debug" \
    SP_TMP="${SPECPR}/tmp" \
    SP_OBJ="${SPECPR}/obj" \
    SP_LIB="${SPECPR}/lib" \
    SPSYSOBJ="${SPECPR}/obj/syslinux.o"

# Install ASU Davinci
RUN wget -O davinci.deb --progress=bar:force:noscroll "https://software.mars.asu.edu/davinci/davinci_3.0.1-1_amd64_ubuntu22_04.deb" &&\
    dpkg -i davinci.deb && rm davinci.deb

# Engine sources + python CLI (NOT the big libraries/recipes/config — those come
# in the libdata stage so they cache independently)
COPY tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh
COPY tetracorder/specpr tetracorder/specpr
COPY tetracorder/tetracorder tetracorder/tetracorder
COPY tetracorder/tetracorder.cmds tetracorder/tetracorder.cmds
COPY tetrapy tetrapy
COPY pyproject.toml uv.lock README.md ./
RUN sed -i "s/rclark/root/g" tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh &&\
    sed -i "s/home/root/g" tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh &&\
    # The install script's directory loop does `mkdir /root/sl1` unless [ -d ] is
    # true. The sl1 masters are baked in the libdata stage (not here, so the base
    # layer stays cacheable), so create the real sl1 tree now — otherwise the
    # `ln -s tetracorder/sl1 sl1` below would be a dangling symlink ([ -d ] false)
    # and the install would try (and fail) to mkdir over it.
    mkdir -p tetracorder/sl1/usgs/library06.conv tetracorder/sl1/usgs/rlib06 &&\
    ln -s tetracorder local &&\
    ln -s tetracorder/sl1 sl1 &&\
    mkdir t1 && ln -s /root/tetracorder/tetracorder.cmds t1/tetracorder.cmds

# Install specpr
RUN cd tetracorder/specpr &&\
    mkdir -p lib obj &&\
    # src.specpr errors about ratfor (??), manually making seems to fix it
    cd src.specpr/common && make && cd - &&\
    # psplotdaemon does not compile (unresolved errors); skip its build block.
    # Content-anchored (not line-numbered) so it survives engine line-number shifts:
    # from the "$SPECPR/src.psplotdaemon" section marker through the blank line that
    # ends the block (covers the make/make-install pair AND both `if [ $? ] exit 1`
    # guards, so no guard runs against a stale $? after `make install` is masked).
    sed -i '/src\.psplotdaemon/,/^$/ s/^/#/' AAA.INSTALL.specpr+support-progs-linux-upgrade.1.7.sh &&\
    yes "" | ./AAA.INSTALL.specpr+support-progs-linux-upgrade.1.7.sh install

# Install tetracorder
RUN cd tetracorder &&\
    # Comment out the chown/chmod ownership loop (fails on network-mounted FS).
    # Anchored to the ownership loop's `for i in $t1 $sl1` header through its `done`.
    sed -i '/^for i in[[:space:]]*\$t1[[:space:]]*\$sl1/,/^done/ s/^/#/' AAA.INSTALL.spectroscopy-os-setup-linux.sh &&\
    # Comment out the forced system-package install loop ($aget of libx11-dev etc.,
    # which fails in-container). Anchored to the loop's unique `for j in libx11-dev`
    # header through its `done`; the enclosing `if [ "$doinstall" = "1" ]; then ... fi`
    # stays intact (now just two harmless echoes), so the script remains valid shell.
    sed -i '/^\tfor j in libx11-dev/,/^\tdone/ s/^/#/' AAA.INSTALL.spectroscopy-os-setup-linux.sh &&\
    yes "y" | ./AAA.INSTALL.spectroscopy-os-setup-linux.sh install &&\
    # Build tetracorder
    cd tetracorder &&\
    ## Build cube spectrum mode
    make install &&\
    ## Build single spectrum mode
    ### Disable block A (image-cube params), enable block B (single-spectrum params).
    ### Anchored to the `# A` / `# B` marker comments and each block's `maxpi4=` line so
    ### the toggle survives engine line-number shifts. Only the `parameter` lines in each
    ### range are touched. NOTE: block B's marker is matched as `# B ` (trailing space) to
    ### avoid also matching the `# B2` block that follows.
    sed -i '/^# A$/,/maxpi4=131060/ { /parameter/ s/^/#/ }' multmap.h &&\
    sed -i '/^# B /,/maxpi4=16000/ { /parameter/ s/^#// }' multmap.h &&\
    make installsingle

# Prepare the python CLI
ENV PIXI_HOME="/pixi"
ENV PATH="/pixi/bin:$PATH"
RUN curl -fsSL https://pixi.sh/install.sh | sh &&\
    git clone https://github.com/emit-sds/emit-sds-l2b.git &&\
    pixi run tetrapy --help
ENV PATH="/root/.pixi/envs/default/bin/:$PATH"

# ---------------------------------------------------------------------------
# libdata: reference data in independently-cacheable layers (big -> volatile)
# ---------------------------------------------------------------------------
FROM base AS libdata
# Layer A: FINISHED convolved libraries (the USGS delivery) at their real paths.
# Baked directly because cmd.lib.setup.t6.00a5 addresses spectra by ABSOLUTE specpr
# record number (research refs up to 1338, standard up to 8208): the library the
# runtime restart opens MUST contain those records as valid data-starts. The
# delivered r06emitc (1512 recs) / s06emitc (8220 recs) satisfy that. (Re-convolving
# from a stale recipe produced a 1104-rec lib where record 1116 was out of range and
# tetracorder silently emitted zero mineral IDs — see docs/build.md.)
COPY tetracorder/sl1/usgs/rlib06/r06emitc         /root/tetracorder/sl1/usgs/rlib06/r06emitc
COPY tetracorder/sl1/usgs/library06.conv/s06emitc /root/tetracorder/sl1/usgs/library06.conv/s06emitc
# Layer B: masters + convolution recipes — only needed for the opt-in RECONVOLVE
# path (a genuinely new grid/sensor). Unused when the finished libs above are baked.
COPY tetracorder/sl1/usgs/library06.conv/splib06b /root/tetracorder/sl1/usgs/library06.conv/splib06b
COPY tetracorder/sl1/usgs/rlib06/sprlb06b         /root/tetracorder/sl1/usgs/rlib06/sprlb06b
COPY tetracorder/sl1/usgs/library06.conv/conv.s06emitc.cmds /root/tetracorder/sl1/usgs/library06.conv/conv.s06emitc.cmds
COPY tetracorder/sl1/usgs/library06.conv/conv.r06emitc.cmds /root/tetracorder/sl1/usgs/library06.conv/conv.r06emitc.cmds
# Layer C: sensor-keyed config templates are already inside tetracorder.cmds
#          (copied in base): DATASETS/emit_c, restart_files/r1-emitc,
#          DELETED.channels/delete_emit_c — committed, expert-curated, fixed.

# ---------------------------------------------------------------------------
# epoch: per-instrument/per-epoch convolution + config gate + baked setup
# ---------------------------------------------------------------------------
FROM libdata AS epoch
ARG SENSOR=emit_c
ARG EPOCH_TAG=unset
ARG NCHANS
ARG GRID_UNITS=nanometers
ARG WL_FILE
ARG FWHM_FILE
# RECONVOLVE=1 opts into re-convolving the libraries from the masters + recipes for
# a genuinely new grid/sensor. Default (unset/0) bakes the finished delivered libs
# from the libdata stage — the config-aligned, acceptance path for emit_c.
ARG RECONVOLVE=0

# Calibration grid deliverable (tiny text files) supplied via build context.
# For the baked path these are PROVENANCE ONLY (the delivered lib is already
# convolved for this grid); they drive the convolution only when RECONVOLVE=1.
COPY ${WL_FILE}  /epoch/emit_wl.txt
COPY ${FWHM_FILE} /epoch/emit_fwhm.txt

# 1) Library provisioning.
#    Default: the finished libraries are already baked (libdata stage) — nothing to
#    convolve. Opt-in (RECONVOLVE=1): re-convolve both libraries from the masters
#    into the paths the restart references (for a new grid/sensor). Either way,
#    step 2 syncs the restart protection and gates record alignment, so a
#    misaligned library fails the build instead of silently yielding zero IDs.
RUN if [ "${RECONVOLVE}" = "1" ]; then \
      echo "RECONVOLVE=1: re-convolving libraries from masters" && \
      tetrapy convolve-epoch \
        --sensor "${SENSOR}" \
        --wl /epoch/emit_wl.txt --fwhm /epoch/emit_fwhm.txt --units "${GRID_UNITS}" \
        --spectral-lib /root/tetracorder/sl1/usgs \
        --recipe-dir  /root/tetracorder/sl1/usgs/library06.conv \
        --cmds-dir    /root/tetracorder/tetracorder.cmds/tetracorder6.00a.cmds ; \
    else \
      echo "baking finished delivered libraries (no convolution)" ; \
    fi

# 2) Sync the runtime restart's device-protection numbers to the libraries that
#    are actually present (iprtw/iprty = -(records-1)); without this specpr prompts
#    on a protection mismatch and the container silently produces zero mineral IDs.
RUN tetrapy sync-restart \
      --cmds-dir /root/tetracorder/tetracorder.cmds/tetracorder6.00a.cmds \
      --sensor "${SENSOR}" \
      --std-lib /root/tetracorder/sl1/usgs/library06.conv/s06emitc \
      --res-lib /root/tetracorder/sl1/usgs/rlib06/r06emitc

# 3) Validate the sensor-keyed config against the epoch channel count, assert the
#    restart protection matches the libraries, AND assert every [sprlb06]/[splib06]
#    record number referenced in cmd.lib.setup is a valid data-start in the baked
#    libraries (fail-closed record-alignment gate — catches the zero-ID class of bug
#    at build time).
RUN tetrapy verify-config \
      --cmds-dir /root/tetracorder/tetracorder.cmds/tetracorder6.00a.cmds \
      --sensor "${SENSOR}" --nchans "${NCHANS}" \
      --std-lib /root/tetracorder/sl1/usgs/library06.conv/s06emitc \
      --res-lib /root/tetracorder/sl1/usgs/rlib06/r06emitc

# Note: setup (cmd-setup-tetrun) is NOT baked here. It requires the actual scene
# to build its run tree, so it runs at container start against the mounted /data
# (the `run` command does setup+runtet by default). The epoch image bakes the
# convolved library + validated config — the scene-independent, per-epoch state —
# which is what the image tag captures.

# Bake the sensor so `tetrapy run` uses the matching DATASET/restart at container
# start (cmd-setup-tetrun is sensor-keyed). Keeps the runtime consistent with the
# baked config instead of defaulting to emit_c regardless of the SENSOR build-arg.
ENV TETRA_SENSOR="${SENSOR}"
LABEL emit.sensor="${SENSOR}" emit.epoch="${EPOCH_TAG}" emit.nchans="${NCHANS}"
ENTRYPOINT ["tetrapy"]
CMD ["run"]
