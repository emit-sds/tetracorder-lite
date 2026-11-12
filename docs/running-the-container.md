# Running the container

Most people run the whole pipeline in one `docker run` (or `podman run`) call
and never install `tetrapy` themselves. This page covers the container:
Docker vs Podman, Windows, how a container call is put together, building the
image, and the volume contract. The rest of the site documents `tetrapy`
itself.

<!-- The sections below are included from README.md, which stays the single
     source. Edit them there, between the "container" and "volumes" snippet
     markers. -->

--8<-- "README.md:container"

--8<-- "README.md:volumes"
