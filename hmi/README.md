# HMI kit — single source of truth

The authoritative HMI kit lives at `custom_components/nspanel_core/hmi_kit/`
(the integration copies it into a temp dir and compiles with the vendored
nxwright toolchain at every dashboard Send).

This directory used to hold a second, diverging copy (`nspanel-core-native/`)
— removed in P361 after the repo audit found the two trees drifting. The
branding picture generator is `branding/make_kit_pictures.py`.
