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
      gnuplot \
      gnuplot-x11 \
      imagemagick \
      tgif \
      #~~ aplay
      alsa-utils \
      #~~ javac
      default-jdk \
      #~~ extras installed by the install script
      # glibc-doc \
      # glibc-doc-reference \
      # libxpm-dev \
      # libxt-dev \
      # libpng-dev \
      # libjbig-dev:amd64 \
      # libjbig0:amd64 \
      # libjbig0:i386 \
      # libjbig2dec0 \
      # libjbig2dec0-dev \
      # jbig2dec \
      # jbigkit-bin \
      # libjpeg8-dev \
      # zlib1g \
      # zlib1g-dev \
      # zlib1g:i386 \
      # inotify-tools \
      # vim \
      # vim-common \
      # vim-runtime \
      # vim-tiny \
      # imagemagick \
      # imagemagick-common \
      # imagemagick-doc \
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
    # psplotdaemon does not compile due to unresolved errors, skip it
    sed -i "234,245 s/^/#/" AAA.INSTALL.specpr+support-progs-linux-upgrade.1.7.sh &&\
    yes "" | ./AAA.INSTALL.specpr+support-progs-linux-upgrade.1.7.sh install

# Install tetracorder
RUN cd tetracorder &&\
    # Comment out the chown/chmod section (causes an error on some systems using network mounted filesystems)
    sed -i "398,416 s/^/#/" AAA.INSTALL.spectroscopy-os-setup-linux.sh &&\
    # Comment out forced installs
    sed -i "231,254 s/^/#/" AAA.INSTALL.spectroscopy-os-setup-linux.sh &&\
    yes "y" | ./AAA.INSTALL.spectroscopy-os-setup-linux.sh install &&\
    # Build tetracorder
    cd tetracorder &&\
    ## Build cube spectrum mode
    make install &&\
    ## Build single spectrum mode
    ### Disable block A, enable block B parameter settings
    sed -i "137,140 s/^/#/" multmap.h &&\
    sed -i "144,147 s/^#//" multmap.h &&\
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
# Layer A: masters (~24 MB, change rarely) at their real delivery paths
COPY tetracorder/sl1/usgs/library06.conv/splib06b /root/tetracorder/sl1/usgs/library06.conv/splib06b
COPY tetracorder/sl1/usgs/rlib06/sprlb06b        /root/tetracorder/sl1/usgs/rlib06/sprlb06b
# Layer B: convolution recipes (small, change occasionally)
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

# Calibration grid deliverable (tiny text files) supplied via build context
COPY ${WL_FILE}  /epoch/emit_wl.txt
COPY ${FWHM_FILE} /epoch/emit_fwhm.txt

# 1) Convolve both libraries from the baked b-masters into the paths the
#    restart file references.
RUN tetrapy convolve-epoch \
      --sensor "${SENSOR}" \
      --wl /epoch/emit_wl.txt --fwhm /epoch/emit_fwhm.txt --units "${GRID_UNITS}" \
      --spectral-lib /root/tetracorder/sl1/usgs \
      --recipe-dir  /root/tetracorder/sl1/usgs/library06.conv

# 2) Validate the sensor-keyed config against the epoch channel count + outputs.
RUN tetrapy verify-config \
      --cmds-dir /root/tetracorder/tetracorder.cmds/tetracorder6.00a.cmds \
      --sensor "${SENSOR}" --nchans "${NCHANS}"

# 3) Bake the prepared Tetracorder run tree (setup happens once, at build time).
RUN rm -rf /root/tetbake && \
    tetrapy setup -v 6.00a -s "${SENSOR}" -m cube -o /root/tetbake -f /data/PLACEHOLDER || true

LABEL emit.sensor="${SENSOR}" emit.epoch="${EPOCH_TAG}" emit.nchans="${NCHANS}"
ENTRYPOINT ["tetrapy"]
CMD ["run"]
