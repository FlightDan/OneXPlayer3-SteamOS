#!/bin/bash
set -euo pipefail
export LC_ALL=C.UTF-8
cd /build
printf '\nHDR_TOOLCHAIN_BEGIN\n'
gcc --version | head -1
ld --version | head -1
cmake --version | head -1
pkg-config --modversion Qt6Widgets Qt6Quick wayland-client vulkan
printf '\nHDR_TOOLCHAIN_END\n'
if [ ! -f source/kwin-6.7.3/.hdr-source-patched ]; then
 mkdir -p inputs source
 tar -xf source-inputs.tar -C inputs
 tar -xf inputs/research/display-source/kwin-6.7.3-1.6.src.tar.gz -C source
 tar -xf source/kwin/kwin-6.7.3.tar.xz -C source
 for patch in 0001-Handle-WM_TAKE_FOCUS-more-gracefully.patch 0002-Load-current-brightness-from-device.patch 0006-inputmethod-Skip-input-events-from-fake-input.patch 0011-Eis-Support-1.6-additions.patch 0013-filter-bad-modes.patch; do
  patch -p1 -d source/kwin-6.7.3 -i "/build/source/kwin/$patch"
 done
 python3 inputs/research/desktop-hdr/patch-kwin.py source/kwin-6.7.3
 touch source/kwin-6.7.3/.hdr-source-patched
fi
hdr=/build/inputs/research/desktop-hdr
prefix=/opt/oxp3-desktop-gamma22/6.7.3-1.6
mkdir -p tests
c++ -std=c++23 -Wall -Wextra -Werror -O2 "$hdr/test-policy.cpp" -o tests/test-policy
./tests/test-policy
c++ -std=c++23 -Wall -Wextra -Werror -O2 "$hdr/test-presentation-proof.cpp" -o tests/test-presentation-proof
./tests/test-presentation-proof
cmake -G Ninja -S source/kwin-6.7.3 -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_INSTALL_LIBDIR=lib -DKDE_INSTALL_LIBDIR=lib -DCMAKE_INSTALL_LIBEXECDIR=lib
cmake --build build -j"${BUILD_JOBS:-2}"
DESTDIR=/build/stage cmake --install build
c++ -std=c++23 -O2 -fPIC "$hdr/mapped-hdr-control.cpp" $(pkg-config --cflags --libs Qt6Widgets) -o "/build/stage$prefix/bin/oxp3-mapped-hdr-control"
wayland-scanner client-header /usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml tests/xdg-shell-client-protocol.h
wayland-scanner private-code /usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml tests/xdg-shell-protocol.c
cc -O2 -c tests/xdg-shell-protocol.c $(pkg-config --cflags wayland-client) -o tests/xdg-shell-protocol.o
c++ -std=c++23 -O2 -I tests "$hdr/pattern-wayland.cpp" tests/xdg-shell-protocol.o $(pkg-config --cflags --libs wayland-client vulkan) -o "/build/stage$prefix/bin/oxp3-hdr-pattern"
install -m755 "$hdr/launch-stable.sh" "/build/stage$prefix/bin/oxp3-kwin-launch"
install -m644 "$hdr/disable-hdr.py" "/build/stage$prefix/disable-hdr.py"
install -m644 "$hdr/compatible-packages.txt" "/build/stage$prefix/compatible-packages.txt"
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH="/build/stage$prefix/lib" "/build/stage$prefix/bin/kwin_wayland" --version
LD_LIBRARY_PATH="/build/stage$prefix/lib" ldd "/build/stage$prefix/bin/kwin_wayland" | tee tests/ldd.txt
! grep -q 'not found' tests/ldd.txt
# Artifact validation is performed on the host after this exact emitted tar is closed.
tar --owner=0 --group=0 -C "/build/stage$prefix" -cf /build/final-runtime.tar .
test -x "/build/stage$prefix/bin/kwin_wayland_wrapper"
test -x "/build/stage$prefix/bin/oxp3-mapped-hdr-control"
test -x "/build/stage$prefix/bin/oxp3-hdr-pattern"
PYTHONPATH=/build/inputs/windows-installer/scripts python3 -c 'from desktop_hdr_policy import validate_desktop_hdr_runtime; validate_desktop_hdr_runtime("/build/final-runtime.tar")'
sha256sum /build/final-runtime.tar
printf '\nHDR_BUILD_COMPLETE\n'
printf 'Portable native artifact: /build/final-runtime.tar\n'
sync
