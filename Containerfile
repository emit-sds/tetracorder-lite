# Davinci only offers AMD support, no ARM
# Newer versions of ubuntu do not have some older packages like libcfitsio9 (davinci dep)
FROM --platform=linux/amd64 ubuntu:22.04

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

# Install tetracorder
RUN cd tetracorder &&\
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
