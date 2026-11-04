# ubuntu:22.04 is pinned: newer releases dropped packages DaVinci needs
# (libcfitsio9). Do not add --platform -- it would publish one architecture's
# binaries under both manifest entries.

# Stage 1: DaVinci, built from vendor/davinci/src. Separate stage so the
# compilers and source stay out of the final image. See vendor/davinci/VENDOR.md.
FROM ubuntu:22.04 AS davinci-build

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update &&\
    apt-get install -y --no-install-suggests --no-install-recommends \
      build-essential \
      autotools-dev \
      pkg-config \
      libreadline-dev \
      libpng-dev \
      libjpeg-dev \
      zlib1g-dev \
      libcurl4-nss-dev \
      libcfitsio-dev \
      libhdf5-dev \
      dpkg-dev \
      &&\
    rm -rf /var/lib/apt/lists/*

COPY vendor/davinci/src /davinci
WORKDIR /davinci

# The vendored config.guess/config.sub predate aarch64. Replace all six of each
# (libltdl and iomedley bundle their own); missing one fails later as
# "./configure failed for libltdl". Patched here so the vendored tree stays a
# faithful export.
RUN find . \( -name config.guess -o -name config.sub \) | \
      while read -r f; do cp "/usr/share/misc/$(basename "$f")" "$f"; done

# Every flag here is load-bearing; VENDOR.md gives the error each one prevents.
# Briefly: never negate a --with flag (configure.ac does not guard withval="no"
# and injects a literal -Lno/lib); it is --with-gplot, not --with-gnuplot; -fPIC
# must be in CFLAGS or the iomedley sub-configure drops it and the arm64 link
# fails; HDF5 goes via CFLAGS because Ubuntu's layout does not fit --with-hdf5.
# make is serial: Makefile.am uses -ldavinci, so automake orders nothing.
RUN ./configure --prefix=/usr/local \
      --without-x \
      --without-library \
      --without-examples \
      --disable-libisis \
      --with-gplot=/usr/bin/gnuplot \
      CFLAGS="-g -O2 -fPIC -I/usr/include/hdf5/serial" \
      LDFLAGS="-L/usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)/hdf5/serial" &&\
    make &&\
    make install DESTDIR=/davinci-install

# Stage 2: the image itself.
FROM ubuntu:22.04

USER root
RUN apt-get update &&\
    apt-get install -y --no-install-suggests --no-install-recommends \
      #~ davinci
      wget \
      gnuplot \
      gdal-bin \
      libgdal-dev \
      libcfitsio9 \
      libcurl4-nss-dev \
      # DaVinci links these. The .deb used to pull them in as package
      # dependencies; a source build has no package metadata, so they are named
      # here. libhdf5-103-1 is the serial runtime that matches libhdf5-dev.
      libhdf5-103-1 \
      libreadline8 \
      libpng16-16 \
      libjpeg-turbo8 \
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
      #~~ extras installed by the install script (do not appear to be needed, just noted here for future reference)
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
      ca-certificates \
      curl \
      git \
      &&\
    rm -rf /var/lib/apt/lists/*

WORKDIR /root

# specpr build environment. LD_LIBRARY_PATH names both multiarch triplets
# because ENV cannot run dpkg-architecture; the loader ignores the absent one.
ENV LD_LIBRARY_PATH="/usr/local/lib:/usr/lib/x86_64-linux-gnu:/usr/lib/aarch64-linux-gnu" \
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

# DaVinci from stage 1. Lands on /usr/local, already on PATH and
# LD_LIBRARY_PATH, so the colour scripts' `env -S davinci -f` shebang resolves.
COPY --from=davinci-build /davinci-install/ /
# Assert the configuration, not just that it starts: HDF5 and the plotting
# program have each been silently wrong once. Note -V (summary), not -v (level).
RUN ldconfig &&\
    davinci -V 2>&1 | sed 's/\\n/\n/g' > /tmp/dv-config &&\
    cat /tmp/dv-config &&\
    grep -q "Version #3" /tmp/dv-config &&\
    grep -qE "^ *HDF5: *Yes" /tmp/dv-config &&\
    grep -qE "^ *Readline: *Yes" /tmp/dv-config &&\
    grep -qE "^ *Module Support: *Yes" /tmp/dv-config &&\
    grep -qE "^Plotting program: */usr/bin/gnuplot" /tmp/dv-config &&\
    rm /tmp/dv-config

# Initialize tetracorder
COPY . .
RUN sed -i "s/rclark/root/g" tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh &&\
    sed -i "s/home/root/g" tetracorder/AAA.INSTALL.spectroscopy-os-setup-linux.sh &&\
    ln -s tetracorder local &&\
    ln -s tetracorder/sl1 sl1 &&\
    mkdir t1 && ln -s /root/tetracorder/tetracorder.cmds t1/tetracorder.cmds

# Make available Davinci-Tetracorder commands
ENV PATH="/root/tetracorder/tetracorder.cmds/tetracorder6.00a.cmds/davinci-cmds.for.usr.local.bin/:$PATH"

# Install specpr
RUN cd tetracorder/specpr &&\
    mkdir -p lib obj &&\
    # src.specpr errors about ratfor (??), manually making seems to fix it
    cd src.specpr/common && make && cd - &&\
    # psplotdaemon does not compile due to unresolved errors, skip it
    sed -i "234,245 s/^/#/" AAA.INSTALL.specpr+support-progs-linux-upgrade.1.7.sh &&\
    yes "" | bash AAA.INSTALL.specpr+support-progs-linux-upgrade.1.7.sh install

# Install tetracorder.
#
# The makefile hardcodes -mcmodel=medium, which is x86-64 only; aarch64 gfortran
# rejects it. Dropping it there is safe -- aarch64's default model addresses
# 4 GB against x86-64's 2 GB, so it has more headroom than x86-64 has with the
# flag. If it is ever outgrown the linker says "relocation truncated to fit"
# rather than miscompiling.
RUN cd tetracorder &&\
    if [ "$(uname -m)" != x86_64 ]; then \
      sed -i "s/^mcmodelflags=.*/mcmodelflags=/" tetracorder/makefile; \
      echo "dropped -mcmodel=medium (not an option on $(uname -m))"; \
    fi &&\
    # Comment out the chown/chmod section (causes an error on some systems using network mounted filesystems)
    sed -i "398,416 s/^/#/" AAA.INSTALL.spectroscopy-os-setup-linux.sh &&\
    # Comment out forced installs
    sed -i "231,254 s/^/#/" AAA.INSTALL.spectroscopy-os-setup-linux.sh &&\
    yes "y" | bash AAA.INSTALL.spectroscopy-os-setup-linux.sh install &&\
    # Build tetracorder
    cd tetracorder &&\
    ## Build cube spectrum mode
    make install &&\
    ## Build single spectrum mode
    ### Disable block A, enable block B parameter settings
    sed -i "137,140 s/^/#/" multmap.h &&\
    sed -i "144,147 s/^#//" multmap.h &&\
    make installsingle

# Setup the python environment
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"
RUN uv sync --all-extras
ENV PATH="/root/.venv/bin/:$PATH"

CMD ["tetrapy"]
