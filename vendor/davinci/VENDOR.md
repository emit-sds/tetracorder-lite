# Vendored DaVinci source

DaVinci is the ASU image-analysis language that Tetracorder's colour products are
written in: every script under `tetracorder.cmds/tetracorder6.00a.cmds/` with a
`#!/usr/bin/env -S davinci -f` shebang runs on it. Without DaVinci there are no
`color.results/` maps, no browse images and no ENVI headers derived from VICAR.

| | |
|---|---|
| Upstream | `https://oss.mars.asu.edu/svn/davinci/davinci/trunk` |
| Revision | **r19810** (last changed r19810, 2026-02-24) |
| Version | 3.02 (`version.h`) |
| Licence | GPL-2.0-or-later (`src/LICENSE` is the GPL-2 text; the or-later grant is upstream's, in `src/contrib/debian/copyright`) |
| Exported | 2026-09-11 via `./refresh.sh` |

## Why vendored rather than fetched at build time

The image used to install ASU's prebuilt `davinci_3.0.1-1_amd64_ubuntu22_04.deb`.
That is the reason the image was amd64-only: ASU publishes no arm64 binary. Going
to source is what makes an arm64 image possible at all.

Having decided to build from source, the source has to come from somewhere, and
every alternative to vendoring is worse:

* **There is no release tarball.** ASU publishes the `.deb` and nothing else.
  Subversion is the only route to the code.
* **There is no revision to pin to that matches the binary.** The newest SVN tag
  is `dv-2_07`; trunk is 3.02; the `.deb` is 3.0.1. Pinning a revision ourselves
  is the only way to get a reproducible build.
* **`svn export` at build time is a network dependency on a university server**,
  in the middle of a container build, for every build on every machine. The
  server's TLS chain is not in the usual trust stores, so it also needs
  `--trust-server-cert-failures` -- a flag that disables certificate checking,
  which is not something to run in CI on every build.

Vendoring is also what this repository already does: `tetracorder/` is 164 MB of
vendored GPL source under the same reasoning.

## What licence this is actually under, and why it took looking

`src/LICENSE` is the plain GPL-2 text, `src/COPYING` and `src/AUTHORS` are both
empty files, and of the 645 `.c`/`.h` files in the tree only seven carry a
licence header at all -- and those seven are borrowed code (`avl.c`/`avl.h`, `printf.c`,
`libcsv.c`, the bison-generated `parser.c`, `libltdl/ltdl.c`/`ltdl.h`), not DaVinci's own.
Read only that far and the conservative answer is GPL-2.0-**only**, because
nothing grants the version choice.

The grant is there, in `src/contrib/debian/copyright`, which upstream ships in
the tree and which applies `License: GPL-2+` to `Files: *` with the full "or (at
your option) any later version" wording. That file is the copyright holder's own
statement and it covers the whole export, so **GPL-2.0-or-later** is correct.

This matters more now than it did with the `.deb`. The earlier claim rested on
the `debian/copyright` inside ASU's binary package -- something we installed but
never redistributed. Vendoring moves the same statement into a file we ship, so
the licence claim is now supported by the repository itself.

Practically it also removes the one real compatibility question. tetrapy is
Apache-2.0 and Tetracorder is GPL-3.0, neither of which combines with GPL-2.0-only.
Under GPL-2-or-later DaVinci can be taken as GPL-3, and in any case the three run
as separate programs in an image rather than linked into one work -- see the
"Container images" section of `NOTICE`.

## What was pruned, and why

`refresh.sh` exports upstream's top-level files and these directories:

    config contrib docs lib libltdl moddvmagick modules tests vicar

Two upstream directories are deliberately left out:

* **`dv_tests/` (612 MB)** -- test imagery, HDF opacity libraries and Mars maps.
  Not referenced by the autotools build.
* **`win32/` (5.9 MB)** -- a Visual Studio project we will never build.

### iomedley is an svn:external, and the build cannot do without it

`trunk` carries three `svn:externals`, which a plain `svn export` of the
directories above does **not** fetch:

    iomedley     https://oss.mars.asu.edu/svn/davinci/iomedley/trunk
    library      https://oss.mars.asu.edu/svn/davinci/davinci_library/trunk
    iomod_isis3  https://oss.mars.asu.edu/svn/davinci/iomod_isis3/trunk

Only `iomedley` is required. It is DaVinci's image-IO layer -- `io_png.c`,
`io_vicar.c`, `io_pnm.c`, `io_gif.c` -- and `configure.ac` puts it in `SUBDIRS`
unconditionally unless `--disable-iomedley`. Leaving it out does not fail at
configure time; it fails several minutes into `make` with

    /bin/bash: line 18: cd: iomedley: No such file or directory

`refresh.sh` therefore exports it explicitly, and `.github/workflows/container.yml`
asserts the directory exists before starting a build. It is 22 MB and bundles its
own libtiff 4.0.3, giflib 4.1.4, libpng 1.2.3 and libjpeg, which the build
compiles rather than using the system copies -- upstream's choice, and the same
one ASU's `.deb` was built with. Its `autom4te.cache/` (1.7 MB) is stripped.

`library` is the ~320 MB Mars data tree, excluded by `--without-library` and not
a build subdirectory. `iomod_isis3` is reached only through ISIS3 support, which
`--disable-libisis` turns off.

The result is ~30 MB. Nothing is modified: the tree under `src/` is exactly what
upstream serves at r19810, so `refresh.sh` at the same revision reproduces it.

## Building it: five traps, four of them arm64-only

None of these are visible from reading the tree; each was found by hitting it.
The Containerfile carries the same notes inline, next to the flag or command
each one constrains.

### 1. `config.guess` predates aarch64 -- and there are six copies

The shipped `config/config.guess` and `config/config.sub` are dated
**2003-06-17**. On arm64 `configure` stops immediately:

    configure: error: cannot guess build type; you must specify one

`libltdl` and `iomedley` bundle their own copies, so replacing the top-level
pair is not enough -- the next one surfaces later as
`configure: error: ./configure failed for libltdl`. The Containerfile replaces
**every** copy in the tree (six of each) with Debian's current ones from the
`autotools-dev` package. They stay unpatched in `src/` so the vendored tree
remains a faithful export.

### 2. Do not pass `--without-motif`

No `AC_ARG_WITH` block in this `configure.ac` guards against `withval="no"`, so
`--without-motif` runs the *same* branch as `--with-motif=/some/path` and appends
a literal `-Lno/lib -Ino/include` to `LDFLAGS`. Configure reports success. The
build then runs for minutes and dies linking `modules/thm`:

    ../../libtool: line 4992: cd: no/lib: No such file or directory

`--without-x` is enough on its own -- with X disabled Motif is never looked for.
The same trap applies to `--without-cfitsio`, `--without-qmv` and
`--without-readline` (`configure.ac` lines 113, 222, 271, 405): omit them rather
than negate them.

### 3. HDF5 is mandatory, and Ubuntu puts it where `--with-hdf5` cannot reach

`ff_load.c` uses `dv_h5_dim_handling` unguarded, so without HDF5 headers the
build stops with `unknown type name`. It is not really optional despite the flag.
ASU's binary links `libhdf5_serial`, so this matches them.

`--with-hdf5=<prefix>` only ever forms `<prefix>/include` and `<prefix>/lib`, and
Ubuntu ships headers under `/usr/include/hdf5/serial` with libraries under
`/usr/lib/<triplet>/hdf5/serial`. Neither fits, so the paths go in as `CFLAGS`
and `LDFLAGS` instead, with `dpkg-architecture -qDEB_HOST_MULTIARCH` supplying
the triplet so the same line works on both architectures.

### 4. Passing `CFLAGS` strips `-fPIC` from iomedley -- fatal on arm64 only

This is the one failure that is genuinely arm64-specific, and the only reason
"DaVinci has never been built on ARM" was a real risk rather than a formality.

`configure.ac:50` does `export CFLAGS="${CFLAGS} -fPIC"`. But `iomedley` is an
`AC_CONFIG_SUBDIRS` sub-configure, and autoconf re-invokes it with
`$ac_configure_args` -- which contains any `CFLAGS` given on the command line,
overriding the exported value. So merely *passing* `CFLAGS` (which trap 3 forces
us to do) silently removes `-fPIC` from iomedley.

libtool still compiles a PIC object into `.libs/`, but `libiomedley.a` is a plain
static archive of the **non-PIC** ones, and linking that into the shared
`libdavinci.so` fails on aarch64 with hundreds of:

    relocation R_AARCH64_ADR_PREL_PG_HI21 against symbol `_TIFFNoStripEncode'
    which may bind externally can not be used when making a shared object

x86-64 tolerates the same archive, so this never shows up on amd64. The fix is to
put `-fPIC` in the `CFLAGS` we pass.

### 5. `make` must be serial

`Makefile.am:125` reads

    davinci_LDADD = -ldavinci $(MY_MODULES_LIB) $(MY_LIBLTDLC_LDADD)

A bare `-l` flag rather than `libdavinci.la`. Automake derives dependency edges
from `.la` entries, so this creates none, and under `-j` the `davinci` binary is
linked before the library it links against:

    /usr/bin/ld: cannot find -ldavinci: No such file or directory

Serial `make` happens to order them correctly. Fixing it properly means editing
`Makefile.am` and re-running automake, which is more than this build needs.

### And one documentation bug: the flag is `--with-gplot`

`configure --help` advertises `--with-gnuplot=<path>`, but the help string sits on
`AC_ARG_WITH(gplot, ...)` (`configure.ac:498`). `--with-gnuplot` is therefore not
a registered option and is silently ignored, leaving `Plotting program:` empty in
`davinci -V`. Pass `--with-gplot=/usr/bin/gnuplot`.

## How it is configured

    ./configure --prefix=/usr/local \
      --without-x --without-library --without-examples --disable-libisis \
      --with-gplot=/usr/bin/gnuplot \
      CFLAGS="-g -O2 -fPIC -I/usr/include/hdf5/serial" \
      LDFLAGS="-L/usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)/hdf5/serial"

`--without-library` is the one that saves the space. ASU's `.deb` installs
**336 MB**, of which ~320 MB is `/usr/share/davinci/library/script_files/` -- Mars
opacity libraries, CRISM spectral libraries and THEMIS albedo maps. Tetracorder
uses none of it. The one function that looked like a library dependency,
`read_an_image` (1,144 calls across the colour scripts), turns out to be defined
by Tetracorder itself in `cmds.color.support/`; the scripts otherwise use only
builtins. Our install tree is **19 MB**.

X11 goes because the container has no display. `libisis` goes because ASU's own
binary was built without it. Loadable modules stay enabled, matching the `.deb`.

## Verifying a build matches ASU's

`davinci -V` prints a configuration summary. Ours should differ from ASU's
`3.0.1-1` `.deb` on exactly two lines -- the version, and `Davinci library`,
which we deliberately drop:

| | ASU `.deb` (amd64) | this build (amd64 + arm64) |
|---|---|---|
| Version | 3.01 | 3.02 |
| Readline | Yes | Yes |
| X11/Xt | No | No |
| Motif | No | No |
| HDF5 | Yes | Yes |
| GUI/Vicar Module | No | No |
| libisis | No | No |
| FITS | Yes | Yes |
| QMV / Qt4 / libxml2 | No | No |
| Module Support | Yes | Yes |
| Plotting program | /usr/bin/gnuplot | /usr/bin/gnuplot |
| **Davinci library** | **Yes** | **No** (the 320 MB) |
| Davinci examples | No | No |

Anything else differing means a flag or a dependency moved, and the colour
products are the thing to re-check -- see the note on version drift below.

## Version drift, and what the output actually did

Trunk r19810 is 3.02; ASU's `.deb` is 3.01. DaVinci produces the colour products
and the ENVI-header-from-VICAR conversion, so a source build needs the *output*
re-validated, not just "it compiles".

That was done. The demo pipeline was run twice on the same 300x150 window of
EMIT granule `emit20240626t165035` -- once with the published amd64 image built
on ASU's `.deb` 3.01, once with an arm64 image built from this source at 3.02:

* **Mineralogy is identical to the pixel.** Group 1: 97.4%, 24 materials,
  43,825 px. Group 2: 95.7%, 78 materials, 43,080 px. Same in both.
* **All 46 colour products are byte-for-byte identical** -- 21 in
  `color.results/`, 22 in `color.results+labels/`, 3 in `base-image/`. Not
  "visually equivalent": the same SHA-256.

Byte-identical PNGs across both a different architecture and a different DaVinci
version is a stronger result than it sounds, and it holds because the bundled
libpng-1.2.3 inside iomedley is compiled from the same vendored source in both
cases, so the encoder is the same one.

To repeat the comparison, run the demo against each image and diff
`output/demo/tetracorder/color.results/` plus the `groups` block of
`site/results.json`.

Incidentally, the arm64 run took **198 s** where the amd64 image under Rosetta on
the same machine took 460-820 s. Native beats emulated by a wide margin, which is
most of the point of publishing both.
